#!/usr/bin/env python3
"""deep-search: проверки скилла, брифа, прогона и хранилища.

Один файл, Python stdlib ≥3.10, без внешних зависимостей (спецификация, 8.1).

Коды выхода: 0 — нарушений нет (предупреждения допустимы), 1 — есть нарушения, 2 — ошибка
вызова или команда не реализована. Строка нарушения — `<путь>: <правило>: <подробность>`,
предупреждение — та же строка с префиксом `warn: `. Имя правила — kebab-case, по нему
проверяют тесты, поэтому его не меняют без правки тестов и документации.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import socket
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SKILL_DIR = Path(__file__).resolve().parent

# --- Бюджеты размеров: спецификация, 7.2 ---------------------------------------------------

# Описание грузится в контекст каждой сессии вместе с описаниями всех скиллов: длинное
# описание платится всегда и размывает выбор скилла по триггерам.
DESCRIPTION_MAX_CHARS = 500

# Ядро — маршрутизатор: читается целиком при каждом вызове скилла. Строки считают плохо
# (строка-абзац проходит как одна), поэтому предел и в символах: 5 500 ≈ 1,8 тыс. токенов.
CORE_MAX_LINES = 85
CORE_MAX_CHARS = 5_500

# После сжатия контекста восстанавливается только начало тела скилла (спецификация, 2.2):
# правила «Всегда» и таблица «Этапы» должны уместиться в него целиком.
CORE_TOP_LINES = 60
CORE_TOP_HEADINGS = ("Всегда", "Этапы")

# Заголовки ядра неизменны (спецификация, 2.2): на них ссылаются подфайлы и эта проверка.
CORE_HEADINGS = ("Всегда", "Этапы", "Эпизодически", "Где что лежит")

# Таблицы-маршруты ядра: в них названы файлы, которые агент читает на каждом этапе.
ROUTE_HEADINGS = ("Этапы", "Эпизодически")
ROUTE_RE = re.compile(r"(?<![\w./-])((?:references|presets|templates)/[^\s`|,;()«»\"']+)")
# Часть пути в угловых скобках — подстановка (`presets/<preset>.md`): путь — шаблон glob.
ROUTE_SLOT_RE = re.compile(r"<[^>]*>")

# Подфайл читается целиком на своём этапе, поэтому ограничен. Проверка и сведение, а также
# хранилище читаются вместе с другими подфайлами в одном этапе — им предел строже.
REF_MAX_LINES = 200
REF_MAX_CHARS = 12_000
REF_CHAR_BUDGETS = {"verify-merge.md": 8_000, "store.md": 8_000}

# Первая строка подфайла говорит, на каком этапе его читать: агент решает по ней, не
# читая файл дальше.
WHEN_TO_READ = "Когда читать:"

# Длинный подфайл агент часто читает частично; оглавление в начале показывает, что в нём
# есть. Оглавление — строка с маркером в первых строках файла и после неё имена всех
# разделов `## ` (ссылками или текстом).
REF_TOC_MIN_LINES = 100
TOC_WITHIN_LINES = 20
TOC_MARKER = "Содержание"

# Пресет читается ветками вместе с sources.md; шаблон брифа — на этапе брифа вместе с
# references/brief.md.
PRESET_MAX_CHARS = 12_000
BRIEF_TEMPLATE = "templates/brief.md"
BRIEF_TEMPLATE_MAX_CHARS = 4_000

# Вывод скрипта читает агент, и вывод занимает его контекст. Главное — в первых 2 000
# символах: нарушения идут раньше предупреждений, строка обрезается до LINE_MAX_CHARS, так
# что первые нарушения всегда видны; не влезшее считается в хвосте «… ещё N».
OUTPUT_MAX_CHARS = 9_000
OUTPUT_HEAD_CHARS = 2_000
LINE_MAX_CHARS = 400

# Оценка токенов по символам (спецификация, 7.3): кириллица делится на токены мельче
# латиницы. Коэффициенты от 2026-10-05, ещё не откалиброваны по счётчику контекста агента
# (`/context`, спецификация, 7.5). После калибровки обновить их и дату.
TOKENS_PER_CYR_CHAR = 1 / 2.7
TOKENS_PER_OTHER_CHAR = 1 / 4.0
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# --- Бриф, прогон, хранилище: форматы из плана («Общие решения») и references/ -------------

# Перечисления — дословно: по ним агент и человек ищут grep'ом, синоним сломал бы поиск.
QUESTION_TYPES = ("fact", "validation", "comparison", "options", "exhaustive_list",
                  "replacement", "compliance")
BUDGET_TIERS = ("S", "M", "L", "XL")
BRIEF_ENUMS = {
    "question_type": QUESTION_TYPES,
    "mode": ("one_off", "update"),
    "stakes": ("low", "normal", "high"),
    "coverage_goal": ("first_sufficient", "representative", "exhaustive"),
    "budget_tier": BUDGET_TIERS,
    "store": ("library", "project", "none"),
    "preset": ("technology", "none"),
}
# У `coverage_goal` после значения идёт ориентир числа («representative, ~20»): значение —
# первое слово. Остальные перечисления — значение целиком.
BRIEF_ENUM_HEAD = ("coverage_goal",)

# Обязательные поля брифа (спецификация, 3.2–3.3; references/brief.md, «Поля»). На S бриф
# облегчённый: уровень S — быстрый вопрос, полный бриф стоил бы дороже ответа.
BRIEF_S_FIELDS = ("id", "question", "question_type", "done_criteria", "budget_tier", "store")
BRIEF_M_FIELDS = BRIEF_S_FIELDS + (
    "decision_context", "mode", "stakes", "coverage_goal", "concept", "exclusion_criteria",
    "keywords", "sources_plan", "prior_work", "budget", "stop_rule", "min_confirmation",
    "store_topic")
# Сверх «О» по типу вопроса — начиная с M. `baseline` у comparison — «если есть», поэтому не
# проверяется; `subject` и `disclosure_constraints` зависят от смысла, коду не видны.
BRIEF_TYPE_FIELDS = {
    "validation": ("hypotheses",),
    "comparison": ("comparison_criteria",),
    "options": ("inclusion_criteria", "baseline", "type_data"),
    "exhaustive_list": ("inclusion_criteria", "known_items"),
    "replacement": ("inclusion_criteria", "baseline", "type_data"),
    "compliance": ("type_data",),
}
# Без двух известных объектов полноту перечня не проверить: хороший поиск находит их сам.
KNOWN_ITEMS_MIN = 2
# Начиная с M — полный бриф и plan.md: ведущий не держит дерево в голове, состояние — в
# plan.md (спецификация, 2.4).
FROM_M_TIERS = ("M", "L", "XL")

# Контракт ветки (спецификация, 4.5; templates/branch-return.yaml). Ответы всех веток ведущий
# читает в свой контекст: 5 000 символов ≈ 1,5 тыс. токенов на ветку. Задание — до 2 000:
# субагент получает его целиком вместе с поручением.
RETURN_KEYS = ("task_id", "status", "stop_reason", "answer", "findings", "rejected", "conflicts",
               "gaps", "leads", "signals", "log_summary", "evidence_path")
RETURN_STATUSES = ("done", "partial", "not_found", "budget_exhausted", "blocked")
RETURN_MAX_CHARS = 5_000
TASK_MAX_CHARS = 2_000

# Журнал ветки (спецификация, 5.7): `capture` — только у ключевых страниц, поэтому не обязателен.
LOG_KEYS = ("ts", "branch", "method", "source", "query", "filters", "shown", "screened", "kept",
            "dupes", "note")
LOG_METHODS = ("query", "browse", "citation", "api")
LOG_COUNTS = ("shown", "screened", "dupes")

# Хранилище (спецификация, 6.2–6.6; references/store.md). Бюджеты — против свалки: INDEX
# читается grep'ом на этапе 0 и должен оставаться оглавлением, карточка — читаемым синтезом,
# реестр темы — обозримым. Превышение — сигнал делить, а не ошибка: предупреждение.
INDEX_MAX_LINES = 100
CARD_MAX_LINES = 300
CLAIMS_MAX_ROWS = 200
# `tldr` попадает в строку INDEX: длинный превращает оглавление в текст.
TLDR_MAX_CHARS = 100
# Цитата — улика, а не пересказ; длинная цитата — уже копия источника.
QUOTE_MAX_WORDS = 25

CARD_FIELDS = ("topic", "title", "tldr", "aliases", "keywords", "status", "checked", "expires",
               "runs")
# `aliases` бывает пустым: не у каждой темы есть другие имена.
CARD_REQUIRED = ("topic", "title", "tldr", "keywords", "status", "checked", "expires", "runs")
CARD_LISTS = ("aliases", "keywords", "runs")
CARD_STATUSES = ("live", "stale", "archived")

INDEX_HEADER = ("slug", "TL;DR", "keywords", "статус", "проверено", "годен до")
CLAIMS_HEADER = ("id", "код", "утверждение", "предмет", "источники", "цитата", "проверено",
                 "свежесть", "статус")
SOURCES_HEADER = ("id", "тип", "заголовок", "владелец", "опубликовано", "обращение", "URL",
                  "архив", "надёжен для")
LOG_KINDS = ("search", "update", "verify", "archive")
# Под заголовком записи log.md — до двух строк: журнал событий, а не второй отчёт.
LOG_TEXT_MAX_LINES = 2
NO_VALUE = "—"

# Раскладка init (спецификация, 6.2). raw/ — полные копии страниц: большие и не для
# публикации, поэтому вне git. archive/ скрыт через .ignore: rg и поиск агента его не видят,
# и этап 0 не находит ушедшие в архив темы.
STORE_DIRS = ("topics", "claims", "runs", "raw", "archive")
STORE_IGNORES = {".gitignore": "raw/", ".ignore": "archive/"}
# Любой из них — признак готового хранилища: init его не трогает.
STORE_MARKERS = ("INDEX.md", "log.md", "sources.md", "topics", "claims")

# --- doctor: проба среды (спецификация, 8.1; references/environment.md) -------------------

# Команды: имя в отчёте и имена бинаря. Chromium в дистрибутивах называется по-разному.
DOCTOR_COMMANDS = (
    ("curl", ("curl",)),
    ("pandoc", ("pandoc",)),
    ("pdftotext", ("pdftotext",)),
    ("chromium", ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")),
    ("jq", ("jq",)),
    ("rg", ("rg",)),
    ("lychee", ("lychee",)),
    ("docker", ("docker",)),
    ("gh", ("gh",)),
)
# Основной путь к тексту страницы и PDF (environment.md, «Текст страницы», «PDF»): без этих
# команд число и цитату взять не из чего, поэтому их нехватка — предупреждение с запасным путём.
# Остальные команды удобны, но у каждой есть замена, и отчёт только отмечает их отсутствие.
DOCTOR_ESSENTIAL = {
    "curl": "текст страницы остаётся только у WebFetch, а он годится лишь для сортировки",
    "pandoc": "HTML → Markdown — Jina Reader, если позволяют disclosure_constraints",
    "pdftotext": "PDF — Jina Reader, если позволяют disclosure_constraints",
}

# Бесплатные API из спецификации, 8.1: (ключ в JSON, имя, метод, адрес, тело). Запрос — самый
# лёгкий у сервиса; доступность — любой HTTP-ответ, даже 4xx: сервис достижим. У Wayback HEAD
# корня: поиск снимков CDX отвечает за десяток секунд и для пробы слишком медленный.
DOCTOR_APIS = (
    ("github", "GitHub", "GET", "https://api.github.com/rate_limit", None),
    ("openalex", "OpenAlex", "GET", "https://api.openalex.org/works?per-page=1&select=id", None),
    ("crossref", "Crossref", "GET", "https://api.crossref.org/works?rows=0", None),
    ("endoflife", "endoflife.date", "GET", "https://endoflife.date/api/v1/products/python/",
     None),
    ("osv", "OSV", "POST", "https://api.osv.dev/v1/query",
     b'{"package":{"name":"jinja2","ecosystem":"PyPI"},"version":"3.1.6"}'),
    ("wayback", "Wayback", "HEAD", "https://web.archive.org/", None),
)
# doctor запускается в начале каждого прогона: ждать дольше нескольких секунд нельзя, а API,
# который отвечает дольше, ветке всё равно не помощник. Запросы идут параллельно, так что вся
# проба укладывается примерно в один таймаут.
DOCTOR_TIMEOUT = 6.0
# GitHub без токена — 60 запросов в час на IP (references/apis.md, «ПО: GitHub»); при общем IP
# лимит съедают соседи, и ветки получат 403 посреди поиска.
GITHUB_LOW_REMAINING = 10

# Самостоятельный SearXNG (environment.md, «Другие агенты»): адрес — из SEARXNG_URL. Пробуется
# поиск с format=json: 403 значит, что сервис жив, но JSON-вывод выключен в его настройках.
SEARXNG_URL_VAR = "SEARXNG_URL"
SEARXNG_DEFAULT_URL = "http://localhost:8080"

# Прокси (environment.md, «Claude Code»): при заданном прокси запрос к локальному сервису уходит
# в прокси и падает по таймауту, если localhost и 127.0.0.1 не перечислены в NO_PROXY.
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
NO_PROXY_VAR = "NO_PROXY"
LOCAL_HOSTS = ("localhost", "127.0.0.1")

# Ключи поисковых API: отчёт называет только переменную и есть ли она. Значение не читается в
# вывод никогда: вывод doctor --json ложится в manifest.json прогона, а тот — в хранилище.
KEY_VARS = ("GITHUB_TOKEN", "GH_TOKEN", "TAVILY_API_KEY", "EXA_API_KEY", "BRAVE_API_KEY",
            "FIRECRAWL_API_KEY", "SERPAPI_API_KEY", "JINA_API_KEY")
LIBRARY_VAR = "DEEP_SEARCH_LIBRARY"

# --- cost: цена сценариев (спецификация, 7.3 и 7.5) ----------------------------------------

# Стадия — то, что ведущий (или субагент ветки) держит в контексте за один этап. Больше 40 000
# символов (≈13 тыс. токенов) одна стадия вытесняет рабочее место под поиск и рассуждение; весь
# прогон в одной сессии — до 80 000, иначе он не доживёт до сохранения без сжатия контекста.
STAGE_MAX_CHARS = 40_000
FULL_MAX_CHARS = 80_000
# Ветки по умолчанию — середина уровня M (2–4, references/branching.md, «Бюджет»); при трёх
# ответах по 5 000 символов сведение M и стоит ≈9 тыс. токенов, как в спецификации, 7.3.
COST_BRANCHES = 3
# plan.md прогона — до 4 000 символов (спецификация, 7.2): вместе с ядром весь контекст
# возобновления.
PLAN_MAX_CHARS = 4_000
# Содержимое хранилища — не файлы скилла, его размер известен только по бюджетам. Этап 0 читает
# grep INDEX обоих хранилищ, до двух карточек частями (frontmatter, «Ответ», «Отклонено») и grep
# утверждений: вместе 10–30 тыс. символов по спецификации, 7.3, здесь — середина. Сохранение
# пишет карточку (до 300 строк, синтез — около трети) и строки реестров: текст остаётся в
# контексте ведущего.
INDEX_GREP_CHARS = 2_000
CARD_READ_CHARS = 4_000
REUSE_CARDS = 2
CLAIMS_GREP_CHARS = 4_000
SAVE_WRITE_CHARS = 8_000
# Ветка читает references/apis.md не целиком, а «Общее» и раздел своей области. Самая дорогая
# частая ветка — поиск технологий: GitHub, пакеты и поддержка, обсуждения для запроса-опровержения.
BRANCH_API_SECTIONS = ("Общее", "ПО: GitHub", "ПО: пакеты и поддержка", "Обсуждения и опыт")

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
DATE = r"\d{4}-\d{2}-\d{2}"
SLUG_RE = re.compile(SLUG)
RUN_ID_RE = re.compile(rf"({DATE})-({SLUG})")
TASK_ID_RE = re.compile(r"B\d+(?:\.\d+)*")
CODE_RE = re.compile(r"[A-F][1-6]!?")
SOURCE_ID_RE = re.compile(r"S-[0-9a-f]{8}")
SOURCE_REF_RE = re.compile(r"(S-[0-9a-f]{8})(?:\s+§\s*\S.*)?")
FRESH_RE = re.compile(rf"V0|V[1-3]→({DATE})")
CLAIM_STATUS_RE = re.compile(rf"live|stale|retracted|superseded→(C-{SLUG}-\d{{3}})")
LOG_HEAD_RE = re.compile(
    rf"## \[({DATE})\] ({'|'.join(LOG_KINDS)}) \| ({SLUG}) \| ({DATE}-{SLUG}|{NO_VALUE})")


@dataclass
class Issue:
    path: str
    rule: str
    detail: str
    warn: bool = False

    def line(self) -> str:
        prefix = "warn: " if self.warn else ""
        return f"{prefix}{self.path}: {self.rule}: {self.detail}"


# --- Общие помощники ------------------------------------------------------------------------


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def num(n: int) -> str:
    """Число с пробелом между разрядами, как в спецификации: 5 500."""
    return f"{n:,}".replace(",", " ")


def estimate_tokens(text: str) -> int:
    cyr = len(CYRILLIC_RE.findall(text))
    return round(cyr * TOKENS_PER_CYR_CHAR + (len(text) - cyr) * TOKENS_PER_OTHER_CHAR)


def h2_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """Разделы `## `: (заголовок, индекс строки заголовка, индекс конца раздела).

    `## ` внутри блока кода — пример, а не заголовок. Раздел кончается на следующем `## `
    или `# `.
    """
    heads: list[tuple[str, int]] = []
    ends: list[int] = []
    fenced = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            heads.append((line[3:].strip(), i))
        elif not fenced and line.startswith("# "):
            ends.append(i)
    sections = []
    for n, (title, start) in enumerate(heads):
        stop = heads[n + 1][1] if n + 1 < len(heads) else len(lines)
        stop = min([stop, *[e for e in ends if e > start]])
        sections.append((title, start, stop))
    return sections


def section(lines: list[str], title: str) -> tuple[int, int] | None:
    """Границы первого раздела с таким заголовком или None."""
    for head, start, stop in h2_sections(lines):
        if head == title:
            return start, stop
    return None


def frontmatter(text: str) -> dict[str, str] | None:
    """Ключи верхнего уровня frontmatter; None, если frontmatter нет.

    Полный разбор YAML не нужен (спецификация, 8.1): значение — строка; блочные скаляры
    `>` и `|` склеиваются, кавычки снимаются.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    return yaml_fields(lines[1:end])


def yaml_fields(lines: list[str]) -> dict[str, str]:
    """Ключи верхнего уровня YAML: значение — строка, вложенное склеено в неё.

    Строка-комментарий `#` в начале строки пропускается; комментарий в конце значения
    остаётся в значении — его снимает `scalar`.
    """
    fields: dict[str, str] = {}
    key: str | None = None
    style: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if key is None:
            return
        if style == "|":
            value = "\n".join(buf).strip()
        else:
            value = " ".join(x for x in buf if x)
        if style is None and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote = value[0]
            value = value[1:-1]
            value = value.replace("''", "'") if quote == "'" else value.replace('\\"', '"')
        fields[key] = value

    for line in lines:
        m = re.match(r"^([A-Za-z_][\w-]*):(?:[ \t]+(.*))?$", line)
        if m:
            flush()
            key, value = m.group(1), (m.group(2) or "").strip()
            if re.fullmatch(r"[>|][+-]?", value):
                style, buf = value[0], []
            else:
                style, buf = None, [value] if value else []
        elif key is not None and (line[:1] in (" ", "\t") or not line.strip()):
            buf.append(line.strip())
    flush()
    return fields


def bounded_report(issues: list[Issue], summary: str, head: str = "") -> str:
    """Отчёт не длиннее OUTPUT_MAX_CHARS: шапка, нарушения, затем предупреждения, затем итог.

    Шапка — короткая сводка постоянного размера (таблица cost, обзор doctor); она входит в
    предел. Пункты идут по порядку, и после первого невлезшего остальные тоже отбрасываются:
    выборка из середины списка вводила бы в заблуждение. Отброшенное считается в хвосте.
    """
    ordered = [i for i in issues if not i.warn] + [i for i in issues if i.warn]
    tail = "… ещё {}"
    reserve = len(tail.format(len(ordered))) + len(summary) + 2 + (len(head) + 1 if head else 0)
    budget = OUTPUT_MAX_CHARS - reserve
    shown: list[str] = [head] if head else []
    size = 0
    fitted = 0
    for issue in ordered:
        line = issue.line()
        if len(line) > LINE_MAX_CHARS:
            line = line[: LINE_MAX_CHARS - 1] + "…"
        if size + len(line) + 1 > budget:
            break
        shown.append(line)
        size += len(line) + 1
        fitted += 1
    omitted = len(ordered) - fitted
    if omitted:
        shown.append(tail.format(omitted))
    shown.append(summary)
    return "\n".join(shown)


# --- self: форма скилла ---------------------------------------------------------------------


def check_description(text: str) -> list[Issue]:
    fields = frontmatter(text)
    desc = (fields or {}).get("description", "")
    if not desc:
        return [Issue("SKILL.md", "description-chars",
                      "нет description во frontmatter — нужно «что + когда» с триггерами, "
                      f"до {DESCRIPTION_MAX_CHARS} символов")]
    if len(desc) > DESCRIPTION_MAX_CHARS:
        return [Issue("SKILL.md", "description-chars",
                      f"description — {num(len(desc))} символов при пределе "
                      f"{DESCRIPTION_MAX_CHARS}: оно грузится в каждую сессию")]
    return []


def check_core(text: str) -> list[Issue]:
    issues = check_description(text)
    lines = text.splitlines()
    if len(lines) > CORE_MAX_LINES:
        issues.append(Issue("SKILL.md", "core-lines",
                            f"{len(lines)} строк при пределе {CORE_MAX_LINES} — ядро только "
                            "маршрутизирует, подробности — в references/"))
    if len(text) > CORE_MAX_CHARS:
        issues.append(Issue("SKILL.md", "core-chars",
                            f"{num(len(text))} символов (≈{num(estimate_tokens(text))} токенов) "
                            f"при пределе {num(CORE_MAX_CHARS)} — подробности — в references/"))
    titles = [head for head, _, _ in h2_sections(lines)]
    for title in CORE_HEADINGS:
        if title not in titles:
            issues.append(Issue("SKILL.md", "core-headings",
                                f"нет заголовка «## {title}» — заголовки ядра неизменны"))
    for title in CORE_TOP_HEADINGS:
        bounds = section(lines, title)
        if bounds is None:
            continue
        start, stop = bounds
        last = max((i for i in range(start, stop) if lines[i].strip()), default=start)
        if last + 1 > CORE_TOP_LINES:
            issues.append(Issue("SKILL.md", "core-top",
                                f"раздел «{title}» кончается на строке {last + 1}, а должен "
                                f"уместиться в первые {CORE_TOP_LINES} — после сжатия контекста "
                                "восстанавливается только начало ядра"))
    return issues


def route_paths(lines: list[str]) -> list[tuple[str, str]]:
    """Пути внутри скилла из строк таблиц «Этапы» и «Эпизодически»: (путь, таблица).

    Пути прогона (`runs/…`) и прочее вне references/, presets/, templates/ не берутся.
    """
    found: list[tuple[str, str]] = []
    for title in ROUTE_HEADINGS:
        bounds = section(lines, title)
        if bounds is None:
            continue
        for line in lines[bounds[0]:bounds[1]]:
            if not line.lstrip().startswith("|"):
                continue
            for m in ROUTE_RE.finditer(line):
                path = m.group(1).rstrip(".:")
                if all(path != p for p, _ in found):
                    found.append((path, title))
    return found


def route_glob(path: str) -> str:
    return ROUTE_SLOT_RE.sub("*", path)


def check_routes(skill: Path, text: str) -> list[Issue]:
    issues: list[Issue] = []
    routes = route_paths(text.splitlines())
    for path, table in routes:
        if ROUTE_SLOT_RE.search(path):
            if not any(p.is_file() for p in skill.glob(route_glob(path))):
                issues.append(Issue("SKILL.md", "route-missing",
                                    f"`{path}` из таблицы «{table}»: по шаблону не нашлось ни "
                                    "одного файла"))
        elif not (skill / path).is_file():
            issues.append(Issue("SKILL.md", "route-missing",
                                f"`{path}` из таблицы «{table}» не существует"))

    # Подфайл и пресет, которых нет в таблицах, агент не найдёт: ядро — единственный маршрут.
    # Шаблоны сюда не входят: часть из них ядро не называет, на них ведут подфайлы.
    exact = {p for p, _ in routes if not ROUTE_SLOT_RE.search(p)}
    patterns = [route_glob(p) for p, _ in routes if ROUTE_SLOT_RE.search(p)]
    candidates = sorted(skill.glob("references/*.md")) + sorted(skill.glob("presets/*.md"))
    for file in candidates:
        rel = file.relative_to(skill).as_posix()
        if rel in exact or any(fnmatch.fnmatchcase(rel, pat) for pat in patterns):
            continue
        issues.append(Issue(rel, "route-unlisted",
                            "не упомянут в таблицах «Этапы» и «Эпизодически» ядра — агент его "
                            "не найдёт"))
    return issues


def check_reference(skill: Path, file: Path) -> list[Issue]:
    rel = file.relative_to(skill).as_posix()
    text = read(file)
    lines = text.splitlines()
    issues: list[Issue] = []
    first = lines[0] if lines else ""
    if not first.startswith(WHEN_TO_READ) or not first[len(WHEN_TO_READ):].strip():
        issues.append(Issue(rel, "when-to-read",
                            f"первая строка не «{WHEN_TO_READ} …» — по ней агент решает, читать ли "
                            "файл"))
    if len(lines) > REF_MAX_LINES:
        issues.append(Issue(rel, "ref-lines",
                            f"{len(lines)} строк при пределе {REF_MAX_LINES} — разделить или сжать"))
    limit = REF_CHAR_BUDGETS.get(file.name, REF_MAX_CHARS)
    if len(text) > limit:
        issues.append(Issue(rel, "ref-chars",
                            f"{num(len(text))} символов (≈{num(estimate_tokens(text))} токенов) "
                            f"при пределе {num(limit)}"))
    if len(lines) > REF_TOC_MIN_LINES:
        issues += check_toc(rel, lines)
    return issues


def check_toc(rel: str, lines: list[str]) -> list[Issue]:
    head = lines[:TOC_WITHIN_LINES]
    marker = next((i for i, line in enumerate(head) if TOC_MARKER in line), None)
    if marker is None:
        return [Issue(rel, "ref-toc",
                      f"длиннее {REF_TOC_MIN_LINES} строк, а «{TOC_MARKER}» в первых "
                      f"{TOC_WITHIN_LINES} строках нет — оглавление с именами всех разделов ##")]
    toc = "\n".join(head[marker:])
    missing = [h for h, _, _ in h2_sections(lines) if h != TOC_MARKER and h not in toc]
    if missing:
        return [Issue(rel, "ref-toc",
                      f"в оглавлении «{TOC_MARKER}» (первые {TOC_WITHIN_LINES} строк) нет "
                      "разделов: " + "; ".join(missing))]
    return []


def check_skill(skill: Path) -> list[Issue]:
    issues: list[Issue] = []
    core = skill / "SKILL.md"
    if core.is_file():
        text = read(core)
        issues += check_core(text)
        issues += check_routes(skill, text)
    else:
        # Без ядра маршрутов нет: нарушения route-* были бы шумом.
        issues.append(Issue("SKILL.md", "core-missing",
                            "файла нет — ядро-маршрутизатор скилла (спецификация, 2.2)"))
    for file in sorted(skill.glob("references/*.md")):
        issues += check_reference(skill, file)
    for file in sorted(skill.glob("presets/*.md")):
        size = len(read(file))
        if size > PRESET_MAX_CHARS:
            issues.append(Issue(file.relative_to(skill).as_posix(), "preset-chars",
                                f"{num(size)} символов при пределе {num(PRESET_MAX_CHARS)}"))
    brief = skill / BRIEF_TEMPLATE
    if brief.is_file():
        size = len(read(brief))
        if size > BRIEF_TEMPLATE_MAX_CHARS:
            issues.append(Issue(BRIEF_TEMPLATE, "brief-template-chars",
                                f"{num(size)} символов при пределе "
                                f"{num(BRIEF_TEMPLATE_MAX_CHARS)}"))
    return issues


def run_self(skill: Path) -> int:
    if not skill.is_dir():
        print(f"self: папки скилла нет: {skill}", file=sys.stderr)
        return 2
    issues = check_skill(skill)
    errors = sum(not i.warn for i in issues)
    summary = f"self: нарушений {errors}, предупреждений {len(issues) - errors}"
    print(bounded_report(issues, summary))
    return 1 if errors else 0


# --- Помощники форматов --------------------------------------------------------------------


def scalar(value: str) -> str:
    """Значение без комментария YAML в конце (` # …`) и без кавычек вокруг."""
    value = re.sub(r"(?:^|\s)#.*$", "", value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def valid_date(text: str) -> date | None:
    if not re.fullmatch(DATE, text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def flat_list(value: str) -> list[str]:
    """Плоский список frontmatter: строки через `, ` (без `[]`)."""
    return [x.strip() for x in value.split(",") if x.strip()]


def table_cells(line: str) -> list[str] | None:
    """Ячейки строки таблицы Markdown; `\\|` внутри текста — не граница. None — не строка."""
    line = line.strip()
    if len(line) < 2 or not line.startswith("|") or not line.endswith("|"):
        return None
    return [c.strip() for c in re.split(r"(?<!\\)\|", line[1:-1])]


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def table_row(cells: tuple[str, ...] | list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def table_head(header: tuple[str, ...]) -> str:
    return table_row(header) + "\n" + "|" + "---|" * len(header) + "\n"


@dataclass
class Registry:
    """Реестр-таблица: шапка, строки записей (номер строки, ячейки), посторонние строки."""
    header: list[str] | None
    rows: list[tuple[int, list[str]]]
    extra: list[int]


def read_registry(text: str, prefix: str) -> Registry:
    """В реестре только таблица: шапка, разделитель и строки, начинающиеся с `| <prefix>`."""
    header: list[str] | None = None
    rows: list[tuple[int, list[str]]] = []
    extra: list[int] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        cells = table_cells(line)
        if cells is not None and line.lstrip().startswith(f"| {prefix}"):
            rows.append((n, cells))
        elif cells is not None and header is None and not rows:
            header = cells
        elif cells is not None and is_separator(cells):
            continue
        else:
            extra.append(n)
    return Registry(header, rows, extra)


def lines_list(numbers: list[int], limit: int = 5) -> str:
    shown = ", ".join(map(str, numbers[:limit]))
    return shown + (f" … (всего {len(numbers)})" if len(numbers) > limit else "")


# --- lint --run: бриф, план, ветки ----------------------------------------------------------


def check_brief(run: Path, label: str) -> tuple[str | None, list[Issue]]:
    """Бриф прогона: обязательные поля по уровню и типу, перечисления, id. Возвращает уровень."""
    path = run / "brief.md"
    if not path.is_file():
        return None, [Issue(label, "brief-required",
                            "файла нет — бриф прогона по templates/brief.md")]
    fields = frontmatter(read(path))
    if fields is None:
        return None, [Issue(label, "brief-required",
                            "нет frontmatter с полями — форма templates/brief.md")]
    values = {k: scalar(v) for k, v in fields.items()}
    issues: list[Issue] = []
    tier = values.get("budget_tier", "")
    qtype = values.get("question_type", "")

    # Уровень неизвестен — проверяются только поля S: остальное зависит от уровня, а сам
    # уровень уже будет в нарушениях.
    required = BRIEF_S_FIELDS
    context = "уровень S"
    if tier in FROM_M_TIERS:
        required = BRIEF_M_FIELDS + BRIEF_TYPE_FIELDS.get(qtype, ())
        context = f"уровень {tier}" + (f", тип {qtype}" if qtype in BRIEF_TYPE_FIELDS else "")
    elif tier not in BUDGET_TIERS:
        context = "уровень не задан — проверены поля S"
    missing = [f for f in required if not values.get(f)]
    if missing:
        issues.append(Issue(label, "brief-required",
                            f"не заполнены ({context}): " + ", ".join(missing)))
    if (tier in FROM_M_TIERS and qtype == "exhaustive_list" and values.get("known_items")
            and len(flat_list(values["known_items"].replace(";", ","))) < KNOWN_ITEMS_MIN):
        issues.append(Issue(label, "brief-required",
                            f"known_items: для exhaustive_list нужно хотя бы {KNOWN_ITEMS_MIN}–3 "
                            "объекта — тест полноты"))

    for name, allowed in BRIEF_ENUMS.items():
        value = values.get(name, "")
        if not value:
            continue
        if name in BRIEF_ENUM_HEAD:
            m = re.match(r"[A-Za-z_]+", value)
            value = m.group(0) if m else value
        if value not in allowed:
            issues.append(Issue(label, "brief-enum",
                                f"{name}: «{value}» — допустимо: " + " · ".join(allowed)))
    if values.get("store") == "none" and tier in FROM_M_TIERS:
        issues.append(Issue(label, "brief-enum",
                            f"store: none допустим только на уровне S, а уровень {tier}"))

    issues += check_brief_id(run, label, values)
    return (tier if tier in BUDGET_TIERS else None), issues


def check_brief_id(run: Path, label: str, values: dict[str, str]) -> list[Issue]:
    """id брифа — имя папки прогона; его slug — store_topic (references/brief.md, «Поля»)."""
    issues: list[Issue] = []
    run_id = values.get("id", "")
    topic = values.get("store_topic", "")
    if topic and not SLUG_RE.fullmatch(topic):
        issues.append(Issue(label, "brief-id",
                            f"store_topic «{topic}» — не slug: латиница kebab-case"))
    if not run_id:
        return issues
    m = RUN_ID_RE.fullmatch(run_id)
    if m is None or valid_date(m.group(1)) is None:
        issues.append(Issue(label, "brief-id",
                            f"id «{run_id}» — нужно <ГГГГ-ММ-ДД>-<slug>"))
        return issues
    if run_id != run.name:
        issues.append(Issue(label, "brief-id",
                            f"id «{run_id}» не совпадает с папкой прогона «{run.name}»"))
    slug = m.group(2)
    if topic and slug != topic and not re.fullmatch(rf"{re.escape(topic)}-\d+", slug):
        issues.append(Issue(label, "brief-id",
                            f"slug в id «{slug}» не совпадает со store_topic «{topic}»"))
    return issues


def check_return(path: Path, label: str) -> list[Issue]:
    """Ответ ветки: верхний уровень — ключи, status, размер (спецификация, 8.1)."""
    text = read(path)
    issues: list[Issue] = []
    if len(text) > RETURN_MAX_CHARS:
        issues.append(Issue(label, "return-chars",
                            f"{num(len(text))} символов при пределе {num(RETURN_MAX_CHARS)} — "
                            "вернуть ветке на сжатие: подробности — в улики и журнал"))
    fields = yaml_fields(text.splitlines())
    missing = [k for k in RETURN_KEYS if k not in fields]
    unknown = [k for k in fields if k not in RETURN_KEYS]
    if missing:
        issues.append(Issue(label, "return-keys",
                            "нет ключей: " + ", ".join(missing)
                            + " — templates/branch-return.yaml"))
    if unknown:
        issues.append(Issue(label, "return-keys",
                            "лишние ключи: " + ", ".join(unknown)
                            + " — templates/branch-return.yaml"))
    task_id = scalar(fields.get("task_id", ""))
    stem = path.name[: -len(".return.yaml")]
    if "task_id" in fields and task_id != stem:
        issues.append(Issue(label, "return-keys",
                            f"task_id «{task_id}» не совпадает с именем файла «{stem}»"))
    if "status" in fields:
        status = scalar(fields["status"])
        if status not in RETURN_STATUSES:
            issues.append(Issue(label, "return-status",
                                f"status «{status}» — допустимо: " + " · ".join(RETURN_STATUSES)))
    return issues


def journal_problems(entry: dict, branch: str) -> list[str]:
    problems: list[str] = []
    missing = [k for k in LOG_KEYS if k not in entry]
    if missing:
        problems.append("нет ключей " + ", ".join(missing))
    if "method" in entry and entry["method"] not in LOG_METHODS:
        problems.append(f"method «{entry['method']}» — допустимо: " + " · ".join(LOG_METHODS))
    if "branch" in entry and entry["branch"] != branch:
        problems.append(f"branch «{entry['branch']}» не совпадает с файлом «{branch}»")
    bad = [k for k in LOG_COUNTS
           if k in entry and (not isinstance(entry[k], int) or isinstance(entry[k], bool))]
    if bad:
        problems.append("не числа: " + ", ".join(bad))
    if "kept" in entry and not isinstance(entry["kept"], list):
        problems.append("kept — не список")
    return problems


def check_journal(path: Path, label: str) -> list[Issue]:
    """Журнал ветки: JSON-объект на строку и его ключи. По правилу — первая плохая строка."""
    branch = path.name[: -len(".jsonl")]
    found: dict[str, list[tuple[int, str]]] = {"log-json": [], "log-fields": []}
    for n, line in enumerate(read(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            found["log-json"].append((n, f"не JSON: {exc.msg}"))
            continue
        if not isinstance(entry, dict):
            found["log-json"].append((n, "не объект JSON"))
            continue
        problems = journal_problems(entry, branch)
        if problems:
            found["log-fields"].append((n, "; ".join(problems)))
    issues = []
    for rule, bad in found.items():
        if bad:
            n, detail = bad[0]
            more = f" (плохих строк всего {len(bad)})" if len(bad) > 1 else ""
            issues.append(Issue(label, rule, f"строка {n}: {detail}{more}"))
    return issues


def check_run(run: Path) -> list[Issue]:
    def label(path: Path) -> str:
        return f"{run.name}/{path.relative_to(run).as_posix()}"

    tier, issues = check_brief(run, label(run / "brief.md"))
    if tier in FROM_M_TIERS and not (run / "plan.md").is_file():
        issues.append(Issue(label(run / "plan.md"), "plan-missing",
                            f"файла нет, а уровень {tier} — дерево и «Следующий шаг» живут в "
                            "plan.md (references/branching.md, «plan.md прогона»)"))
    branches = run / "branches"
    for path in sorted(branches.glob("*.task.yaml")):
        size = len(read(path))
        if size > TASK_MAX_CHARS:
            issues.append(Issue(label(path), "task-chars",
                                f"{num(size)} символов при пределе {num(TASK_MAX_CHARS)}"))
    for path in sorted(branches.glob("*.return.yaml")):
        issues += check_return(path, label(path))
    for path in sorted(branches.glob("*.jsonl")):
        issues += check_journal(path, label(path))
    return issues


# --- lint --store: хранилище ----------------------------------------------------------------


@dataclass
class Claim:
    id: str
    sources: list[str]
    fresh: date | None
    status: str
    # Строка с неверным числом столбцов: поля не разобраны, и правила, которые на них
    # опираются, её пропускают — иначе одна ошибка формата дала бы каскад нарушений.
    parsed: bool = True


@dataclass
class Card:
    path: Path
    fields: dict[str, str] | None

    @property
    def slug(self) -> str:
        topic = (self.fields or {}).get("topic", "")
        return topic if topic else self.path.stem

    @property
    def archived(self) -> bool:
        return (self.fields or {}).get("status") == "archived"


def load_cards(store: Path) -> list[Card]:
    return [Card(p, frontmatter(read(p))) for p in sorted((store / "topics").glob("*.md"))]


def index_cell(value: str) -> str:
    value = " ".join(value.split())
    return value.replace("|", "\\|") if value else NO_VALUE


def index_text(cards: list[Card]) -> str:
    """INDEX.md из frontmatter карточек: без архивных, по алфавиту slug (references/store.md)."""
    rows = []
    for card in sorted((c for c in cards if c.fields is not None and not c.archived),
                       key=lambda c: c.slug):
        f = card.fields or {}
        words = ", ".join(flat_list(f.get("aliases", "")) + flat_list(f.get("keywords", "")))
        rows.append(table_row([index_cell(card.slug), index_cell(f.get("tldr", "")),
                               index_cell(words), index_cell(f.get("status", "")),
                               index_cell(f.get("checked", "")), index_cell(f.get("expires", ""))]))
    return table_head(INDEX_HEADER) + "".join(r + "\n" for r in rows)


def check_index(store: Path, cards: list[Card]) -> list[Issue]:
    text = read(store / "INDEX.md")
    issues: list[Issue] = []
    lines = len(text.splitlines())
    if lines > INDEX_MAX_LINES:
        issues.append(Issue("INDEX.md", "index-lines",
                            f"{lines} строк при пределе {INDEX_MAX_LINES} — делить хранилище по "
                            "областям, с пользователем", warn=True))
    listed = {}
    for line in text.splitlines():
        cells = table_cells(line)
        if cells and not is_separator(cells) and cells[0] != INDEX_HEADER[0]:
            listed[cells[0]] = line
    live = [c for c in cards if c.fields is not None and not c.archived]
    for card in live:
        if card.slug not in listed:
            issues.append(Issue(f"topics/{card.path.name}", "index-coverage",
                                f"нет строки «{card.slug}» в INDEX.md — deep_search.py index"))
    known = {c.slug for c in live}
    for slug in listed:
        if slug not in known:
            issues.append(Issue("INDEX.md", "index-coverage",
                                f"строка «{slug}» без живой карточки в topics/ — "
                                "deep_search.py index"))
    if not issues or all(i.warn for i in issues):
        if text != index_text(cards):
            issues.append(Issue("INDEX.md", "index-coverage",
                                "расходится с frontmatter карточек — INDEX руками не правится: "
                                "deep_search.py index"))
    return issues


def check_card(card: Card, claims: list[Claim] | None) -> list[Issue]:
    rel = f"topics/{card.path.name}"
    text = read(card.path)
    issues: list[Issue] = []
    lines = len(text.splitlines())
    if lines > CARD_MAX_LINES:
        issues.append(Issue(rel, "card-lines",
                            f"{lines} строк при пределе {CARD_MAX_LINES} — сжать синтез: факты — "
                            "в утверждениях, карточка ссылается на id", warn=True))
    f = card.fields
    if f is None:
        return issues + [Issue(rel, "card-header",
                               "нет frontmatter — шапка по templates/topic.md")]

    def bad(detail: str) -> None:
        issues.append(Issue(rel, "card-header", detail))

    missing = [k for k in CARD_FIELDS if k not in f]
    if missing:
        bad("нет полей: " + ", ".join(missing))
    empty = [k for k in CARD_REQUIRED if k in f and not f[k].strip()]
    if empty:
        bad("пустые поля: " + ", ".join(empty))
    topic = f.get("topic", "")
    if topic and (topic != card.path.stem or not SLUG_RE.fullmatch(topic)):
        bad(f"topic «{topic}» — должен быть slug и совпадать с именем файла")
    status = f.get("status", "")
    if status and status not in CARD_STATUSES:
        bad(f"status «{status}» — допустимо: " + " · ".join(CARD_STATUSES))
    tldr = f.get("tldr", "")
    if len(tldr) > TLDR_MAX_CHARS:
        bad(f"tldr — {len(tldr)} символов при пределе {TLDR_MAX_CHARS}: он идёт в строку INDEX")
    checked = f.get("checked", "")
    if checked and valid_date(checked) is None:
        bad(f"checked «{checked}» — нужна дата ГГГГ-ММ-ДД")
    expires = f.get("expires", "")
    if expires and expires != NO_VALUE and valid_date(expires) is None:
        bad(f"expires «{expires}» — нужна дата ГГГГ-ММ-ДД или «{NO_VALUE}»")
    for name in CARD_LISTS:
        if f.get(name, "").lstrip().startswith("["):
            bad(f"{name} — плоская строка через «, », без []")
    wrong = [r for r in flat_list(f.get("runs", "")) if not RUN_ID_RE.fullmatch(r.strip("[]"))]
    if wrong:
        bad("runs — не id прогонов <ГГГГ-ММ-ДД>-<slug>: " + ", ".join(wrong))

    # expires — минимум дат свежести живых утверждений; все V0 — «—» (references/store.md).
    live = [c for c in claims or [] if c.status == "live"]
    if live and expires and all(c.parsed for c in claims or []):
        dates = [c.fresh for c in live if c.fresh is not None]
        expected = min(dates).isoformat() if dates else NO_VALUE
        if expires != expected:
            bad(f"expires «{expires}», а по живым утверждениям — «{expected}»")
    return issues


def check_claims(path: Path, rel: str, slug: str, today: date) -> tuple[list[Issue], list[Claim]]:
    reg = read_registry(read(path), "C-")
    issues: list[Issue] = []
    claims: list[Claim] = []
    if reg.header is None or tuple(reg.header) != CLAIMS_HEADER:
        issues.append(Issue(rel, "claim-format",
                            "шапка таблицы не та: " + table_row(CLAIMS_HEADER)))
    if reg.extra:
        issues.append(Issue(rel, "claim-format",
                            "в реестре только таблица; посторонние строки: "
                            + lines_list(reg.extra)))
    if len(reg.rows) > CLAIMS_MAX_ROWS:
        issues.append(Issue(rel, "claims-lines",
                            f"утверждений {len(reg.rows)} при пределе {CLAIMS_MAX_ROWS} — делить "
                            "тему на подтемы со своими slug", warn=True))
    id_re = re.compile(rf"C-{re.escape(slug)}-(\d{{3}})")
    seen: set[str] = set()
    last = 0
    for n, cells in reg.rows:
        where = f"строка {n}"
        cid = cells[0]
        m = id_re.fullmatch(cid)
        if m is None:
            issues.append(Issue(rel, "claim-id", f"{where}: «{cid}» — нужно C-{slug}-<NNN>"))
        elif cid in seen:
            issues.append(Issue(rel, "claim-id", f"{where}: {cid} повторяется"))
        elif int(m.group(1)) <= last:
            issues.append(Issue(rel, "claim-id",
                                f"{where}: {cid} не по порядку — номер после последнего, "
                                "номера не переиспользуются"))
        if m is not None:
            last = max(last, int(m.group(1)))
        seen.add(cid)
        if len(cells) != len(CLAIMS_HEADER):
            issues.append(Issue(rel, "claim-format",
                                f"{where}: {len(cells)} столбцов вместо {len(CLAIMS_HEADER)} — "
                                "`|` в тексте экранируется `\\|`"))
            claims.append(Claim(cid, [], None, "", parsed=False))
            continue
        _, code, text, subject, sources, quote, checked, fresh, status = cells
        problems = []
        if not CODE_RE.fullmatch(code):
            problems.append(f"код «{code}» — нужно ^[A-F][1-6]!?$")
        if not text or not subject:
            problems.append("пустое утверждение или предмет")
        words = len(quote.strip("«»").split())
        if not (quote.startswith("«") and quote.endswith("»")) or words == 0:
            problems.append("нет цитаты в «» — без цитаты утверждение не записывается")
        elif words > QUOTE_MAX_WORDS:
            problems.append(f"цитата — {words} слов при пределе {QUOTE_MAX_WORDS}")
        if valid_date(checked) is None:
            problems.append(f"проверено «{checked}» — нужна дата ГГГГ-ММ-ДД")
        fm = FRESH_RE.fullmatch(fresh)
        fresh_date = valid_date(fm.group(1)) if fm and fm.group(1) else None
        if fm is None or (fm.group(1) and fresh_date is None):
            problems.append(f"свежесть «{fresh}» — нужно V1–V3→ГГГГ-ММ-ДД или V0")
        sm = CLAIM_STATUS_RE.fullmatch(status)
        if sm is None:
            problems.append(f"статус «{status}» — live · stale · superseded→C-… · retracted")
        for problem in problems:
            issues.append(Issue(rel, "claim-format", f"{where} {cid}: {problem}"))
        claims.append(Claim(cid, [s.strip() for s in sources.split(";") if s.strip()],
                            fresh_date, status))
        if status == "live" and fresh_date is not None and fresh_date < today:
            issues.append(Issue(rel, "claim-expired",
                                f"{cid}: свежесть {fresh} прошла — перепроверить или пометить "
                                "stale", warn=True))
    ids = {c.id for c in claims}
    for claim in claims:
        target = claim.status.partition("→")[2]
        if target and target not in ids:
            issues.append(Issue(rel, "claim-format",
                                f"{claim.id}: заменено на {target}, а такой строки нет"))
    return issues, claims


def source_key(url: str) -> str | None:
    """Ключ источника для поиска дублей: DOI в нижнем регистре или URL без фрагмента и utm_*."""
    url = url.strip()
    if not url or url == NO_VALUE:
        return None
    m = re.fullmatch(r"(?i)(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)", url)
    if m:
        return "doi:" + m.group(1).lower()
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def check_sources(store: Path) -> tuple[list[Issue], dict[str, int]]:
    """sources.md: формат и дубли. Возвращает id → номер строки."""
    path = store / "sources.md"
    if not path.is_file():
        return [], {}
    rel = "sources.md"
    reg = read_registry(read(path), "S-")
    issues: list[Issue] = []
    if reg.header is None or tuple(reg.header) != SOURCES_HEADER:
        issues.append(Issue(rel, "source-format",
                            "шапка таблицы не та: " + table_row(SOURCES_HEADER)))
    if reg.extra:
        issues.append(Issue(rel, "source-format",
                            "в реестре только таблица; посторонние строки: "
                            + lines_list(reg.extra)))
    ids: dict[str, int] = {}
    keys: dict[str, str] = {}
    for n, cells in reg.rows:
        sid = cells[0]
        if not SOURCE_ID_RE.fullmatch(sid):
            issues.append(Issue(rel, "source-format",
                                f"строка {n}: «{sid}» — нужно S- и 8 hex sha256 ключа"))
        if len(cells) != len(SOURCES_HEADER):
            issues.append(Issue(rel, "source-format",
                                f"строка {n}: {len(cells)} столбцов вместо {len(SOURCES_HEADER)} — "
                                "`|` в тексте экранируется `\\|`"))
        if sid in ids:
            issues.append(Issue(rel, "source-dup",
                                f"строка {n}: {sid} уже на строке {ids[sid]} — тот же ключ "
                                "заменяет прежнюю строку"))
            continue
        ids[sid] = n
        key = source_key(cells[6]) if len(cells) > 6 else None
        if key is not None:
            if key in keys and keys[key] != sid:
                issues.append(Issue(rel, "source-dup",
                                    f"строка {n}: {sid} и {keys[key]} — один ключ «{key}»"))
            keys.setdefault(key, sid)
    return issues, ids


def check_log(store: Path) -> list[Issue]:
    path = store / "log.md"
    if not path.is_file():
        return []
    issues: list[Issue] = []
    heads = 0
    text_lines = 0
    for n, line in enumerate(read(path).splitlines(), 1):
        if line.startswith("## "):
            m = LOG_HEAD_RE.fullmatch(line.rstrip())
            if m is None or valid_date(m.group(1)) is None:
                issues.append(Issue("log.md", "log-entry",
                                    f"строка {n}: нужно «## [ГГГГ-ММ-ДД] <вид> | <slug> | "
                                    f"<прогон или {NO_VALUE}>», вид — " + " · ".join(LOG_KINDS)))
            heads += 1
            text_lines = 0
        elif line.strip() and not line.startswith("# "):
            if not heads:
                issues.append(Issue("log.md", "log-entry",
                                    f"строка {n}: текст до первой записи"))
                continue
            text_lines += 1
            if text_lines == LOG_TEXT_MAX_LINES + 1:
                issues.append(Issue("log.md", "log-entry",
                                    f"строка {n}: под записью больше {LOG_TEXT_MAX_LINES} строк"))
    return issues


def check_store(store: Path, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []
    cards = load_cards(store)
    issues += check_index(store, cards)

    claims: dict[str, list[Claim]] = {}
    for path in sorted((store / "claims").glob("*.md")):
        found, claims[path.stem] = check_claims(path, f"claims/{path.name}", path.stem, today)
        issues += found
    for card in cards:
        issues += check_card(card, claims.get(card.path.stem))

    found, sources = check_sources(store)
    issues += found
    for slug, rows in claims.items():
        for claim in rows:
            if not claim.parsed:
                continue
            if not claim.sources:
                issues.append(Issue(f"claims/{slug}.md", "claim-source",
                                    f"{claim.id}: нет источников — только внешние S-…"))
            for ref in claim.sources:
                m = SOURCE_REF_RE.fullmatch(ref)
                if m is None:
                    issues.append(Issue(f"claims/{slug}.md", "claim-source",
                                        f"{claim.id}: «{ref}» — не S-…[ §место]: синтез "
                                        "источником не служит"))
                elif m.group(1) not in sources:
                    issues.append(Issue(f"claims/{slug}.md", "claim-source",
                                        f"{claim.id}: {m.group(1)} нет в sources.md"))

    # Архив уносит утверждения в archive/claims/, а источники остаются в sources.md: ссылки
    # из архива тоже держат источник. Ищется по тексту реестров, чтобы строка с ошибкой
    # формата не превращала свои источники в сирот.
    used: set[str] = set()
    for folder in (store / "claims", store / "archive" / "claims"):
        for path in sorted(folder.glob("*.md")):
            used.update(SOURCE_ID_RE.findall(read(path)))
    for sid, n in sources.items():
        if SOURCE_ID_RE.fullmatch(sid) and sid not in used:
            issues.append(Issue("sources.md", "source-orphan",
                                f"строка {n}: на {sid} не ссылается ни одно утверждение — "
                                "в реестре только источники утверждений"))
    issues += check_log(store)
    return issues


def run_lint(run: Path | None, store: Path | None) -> int:
    if run is None and store is None:
        print("lint: нужен --run <папка прогона> и/или --store <хранилище>", file=sys.stderr)
        return 2
    if run is not None and not run.is_dir():
        print(f"lint: папки прогона нет: {run}", file=sys.stderr)
        return 2
    if store is not None and not (store / "INDEX.md").is_file():
        print(f"lint: хранилища нет (нет INDEX.md): {store} — deep_search.py init <путь>",
              file=sys.stderr)
        return 2
    issues: list[Issue] = []
    if run is not None:
        issues += check_run(run)
    if store is not None:
        issues += check_store(store)
    errors = sum(not i.warn for i in issues)
    summary = f"lint: нарушений {errors}, предупреждений {len(issues) - errors}"
    print(bounded_report(issues, summary))
    return 1 if errors else 0


# --- init, index ----------------------------------------------------------------------------


def run_init(store: Path) -> int:
    if store.exists() and not store.is_dir():
        print(f"init: это файл, а не папка: {store}", file=sys.stderr)
        return 2
    present = [m for m in STORE_MARKERS if (store / m).exists()]
    if present:
        print(f"init: хранилище уже есть ({', '.join(present)}): {store} — ничего не изменено",
              file=sys.stderr)
        return 2
    store.mkdir(parents=True, exist_ok=True)
    for name in STORE_DIRS:
        (store / name).mkdir(exist_ok=True)
    (store / "INDEX.md").write_text(index_text([]), encoding="utf-8")
    (store / "log.md").write_text("", encoding="utf-8")
    (store / "sources.md").write_text(table_head(SOURCES_HEADER), encoding="utf-8")
    for name, entry in STORE_IGNORES.items():
        path = store / name
        old = read(path) if path.is_file() else ""
        if entry not in old.splitlines():
            sep = "" if not old or old.endswith("\n") else "\n"
            path.write_text(old + sep + entry + "\n", encoding="utf-8")
    print(f"init: хранилище создано: {store}\n"
          "INDEX.md, log.md, sources.md, " + ", ".join(f"{d}/" for d in STORE_DIRS)
          + "; raw/ — в .gitignore, archive/ — в .ignore")
    return 0


def run_index(store: Path) -> int:
    path = store / "INDEX.md"
    if not path.is_file():
        print(f"index: хранилища нет (нет INDEX.md): {store} — deep_search.py init <путь>",
              file=sys.stderr)
        return 2
    cards = load_cards(store)
    issues = [Issue(f"topics/{c.path.name}", "card-header",
                    "нет frontmatter — строка в INDEX не собрана", warn=True)
              for c in cards if c.fields is None]
    text = index_text(cards)
    # Без изменений файл не переписывается: повторный запуск ничего не трогает.
    changed = read(path) != text
    if changed:
        path.write_text(text, encoding="utf-8")
    live = sum(1 for c in cards if c.fields is not None and not c.archived)
    archived = sum(1 for c in cards if c.archived)
    state = "обновлён" if changed else "без изменений"
    print(bounded_report(issues, f"index: INDEX.md {state} — тем {live}, архивных пропущено "
                                 f"{archived}"))
    return 0


# --- doctor: проба среды --------------------------------------------------------------------


@dataclass
class Probe:
    """Ответ на пробный запрос: HTTP-код и тело (если просили) или причина отказа."""
    status: int | None = None
    body: bytes = b""
    error: str = ""


# fetch(метод, адрес, тело, через прокси ли, нужно ли тело) — подменяется в тестах, чтобы
# проба не ходила в сеть.
Fetch = Callable[[str, str, bytes | None, bool, bool, str], Probe]


def fetch_error(exc: BaseException) -> str:
    """Причина отказа словами — без адресов и сообщений ОС: они длинные и бывают личными."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, TimeoutError):
        return "таймаут"
    if isinstance(reason, ConnectionRefusedError):
        return "соединение отклонено"
    if isinstance(reason, socket.gaierror):
        return "имя не разрешилось (DNS)"
    if isinstance(reason, ssl.SSLError):
        return "ошибка TLS"
    return "нет соединения"


def http_fetch(method: str, url: str, data: bytes | None, proxy: bool, want_body: bool,
               token: str = "") -> Probe:
    """Один запрос с DOCTOR_TIMEOUT. proxy=False — мимо прокси, как `curl --noproxy`.

    token — Bearer-токен: с ним /rate_limit GitHub показывает лимит токена, а не IP.
    """
    opener = urllib.request.build_opener(*([] if proxy else [urllib.request.ProxyHandler({})]))
    headers = {"User-Agent": "deep-search-doctor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener.open(request, timeout=DOCTOR_TIMEOUT) as resp:
            return Probe(resp.status, resp.read(65_536) if want_body else b"")
    except urllib.error.HTTPError as exc:
        exc.close()
        return Probe(exc.code)
    except Exception as exc:  # noqa: BLE001  любой отказ — строка отчёта, а не падение пробы
        return Probe(error=fetch_error(exc))


def env_value(environ: Mapping[str, str], name: str) -> str:
    """Переменная в верхнем или нижнем регистре: curl и urllib читают обе формы."""
    return environ.get(name) or environ.get(name.lower()) or ""


def bare_url(url: str) -> str:
    """Схема, хост и порт — без логина, пароля и пути."""
    parts = urlsplit(url)
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        port = ""
    return f"{parts.scheme}://{parts.hostname or ''}{port}"


def github_rate(body: bytes) -> tuple[int, int] | None:
    """Остаток и предел запросов в час из ответа /rate_limit."""
    try:
        core = json.loads(body.decode("utf-8"))["resources"]["core"]
        return int(core["remaining"]), int(core["limit"])
    except (ValueError, KeyError, TypeError):
        return None


def probe_env(environ: Mapping[str, str], fetch: Fetch, today: date) -> tuple[dict, str]:
    """Объект среды для ключа `env` в manifest.json и адрес SearXNG для отчёта.

    В объекте только флаги и коды ответов — ни путей, ни значений переменных: он ложится в
    хранилище, а оно может уйти в git.
    """
    path = environ.get("PATH", "")
    commands = {name: any(shutil.which(b, path=path) for b in binaries)
                for name, binaries in DOCTOR_COMMANDS}

    searx = (environ.get(SEARXNG_URL_VAR) or SEARXNG_DEFAULT_URL).rstrip("/")
    github_token = environ.get("GITHUB_TOKEN") or environ.get("GH_TOKEN") or ""
    jobs = [(key, method, url, data, True, key == "github",
             github_token if key == "github" else "")
            for key, _, method, url, data in DOCTOR_APIS]
    # Локальный сервис — мимо прокси: так его и надо вызывать (environment.md, «Claude Code»).
    jobs.append(("searxng", "GET", f"{searx}/search?q=deep-search&format=json", None, False,
                 False, ""))
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        probes = dict(zip((j[0] for j in jobs), pool.map(lambda j: fetch(*j[1:]), jobs)))

    api: dict[str, dict] = {}
    for key, _, _, _, _ in DOCTOR_APIS:
        probe = probes[key]
        entry: dict = {"ok": probe.status is not None and probe.status < 400,
                       "status": probe.status}
        if probe.error:
            entry["error"] = probe.error
        if key == "github" and probe.status == 200:
            rate = github_rate(probe.body)
            if rate is not None:
                entry["remaining"], entry["limit"] = rate
        api[key] = entry
    searx_probe = probes["searxng"]

    no_proxy = {h.strip().lower() for h in env_value(environ, NO_PROXY_VAR).split(",") if h.strip()}
    proxy: dict[str, bool] = {name: bool(env_value(environ, name)) for name in PROXY_VARS}
    proxy[NO_PROXY_VAR] = bool(no_proxy)
    proxy["local_bypass"] = "*" in no_proxy or all(h in no_proxy for h in LOCAL_HOSTS)

    library = environ.get(LIBRARY_VAR, "")
    env = {
        "checked": today.isoformat(),
        "commands": commands,
        "network": any(probes[key].status is not None for key, *_ in DOCTOR_APIS),
        "api": api,
        "searxng": {"ok": searx_probe.status is not None, "status": searx_probe.status,
                    "json": searx_probe.status == 200},
        "proxy": proxy,
        "keys": {name: bool(environ.get(name)) for name in KEY_VARS},
        "library": {"set": bool(library),
                    "store": bool(library)
                    and (Path(library).expanduser() / "INDEX.md").is_file()},
    }
    return env, bare_url(searx)


def doctor_issues(env: dict) -> list[Issue]:
    issues: list[Issue] = []
    for name, fallback in DOCTOR_ESSENTIAL.items():
        if not env["commands"].get(name):
            issues.append(Issue(name, "doctor-command",
                                f"нет в PATH — {fallback} (references/environment.md)", warn=True))
    proxied = any(env["proxy"][name] for name in PROXY_VARS)
    names = {key: title for key, title, *_ in DOCTOR_APIS}
    if not env["network"]:
        via = " — запросы шли через прокси: проверить его" if proxied else ""
        issues.append(Issue("api", "doctor-network",
                            f"нет сети: ни один API не ответил за {DOCTOR_TIMEOUT:g} с{via}; "
                            "поиск — только встроенными средствами агента", warn=True))
    else:
        for key, entry in env["api"].items():
            if entry["status"] is None:
                issues.append(Issue(names[key], "doctor-api",
                                    f"не отвечает: {entry.get('error', 'нет соединения')}",
                                    warn=True))
    github = env["api"].get("github", {})
    if "remaining" in github and github["remaining"] < GITHUB_LOW_REMAINING:
        issues.append(Issue("GitHub", "doctor-api",
                            f"осталось {github['remaining']} из {github['limit']} запросов в час — "
                            "без токена лимит общий на IP; токен — GITHUB_TOKEN", warn=True))
    if proxied and not env["proxy"]["local_bypass"]:
        issues.append(Issue(NO_PROXY_VAR, "doctor-proxy",
                            "прокси задан, а localhost и 127.0.0.1 не в NO_PROXY — запросы к "
                            "локальным сервисам (SearXNG, MCP по HTTP) уйдут в прокси и упадут по "
                            "таймауту: добавить их в NO_PROXY или curl --noproxy "
                            "localhost,127.0.0.1", warn=True))
    return issues


def split_names(flags: dict[str, bool]) -> str:
    have = [name for name, ok in flags.items() if ok]
    miss = [name for name, ok in flags.items() if not ok]
    return f"есть — {', '.join(have) or '—'}; нет — {', '.join(miss) or '—'}"


def doctor_text(env: dict, searx: str) -> str:
    lines = [f"doctor: среда deep-search на {env['checked']}",
             "команды: " + split_names(env["commands"])]
    if env["network"]:
        parts = []
        for key, title, *_ in DOCTOR_APIS:
            entry = env["api"][key]
            if entry["status"] is None:
                parts.append(f"{title} — {entry.get('error', 'нет соединения')}")
                continue
            rate = (f", осталось {entry['remaining']} из {entry['limit']} в час"
                    if "remaining" in entry else "")
            parts.append(f"{title} {entry['status']}{rate}")
        lines.append(f"API (таймаут {DOCTOR_TIMEOUT:g} с): " + " · ".join(parts))
    else:
        lines.append(f"API: нет сети — ни один из {len(DOCTOR_APIS)} не ответил за "
                     f"{DOCTOR_TIMEOUT:g} с")
    s = env["searxng"]
    if not s["ok"]:
        state = f"не отвечает — адрес задаёт {SEARXNG_URL_VAR}"
    elif s["json"]:
        state = "отвечает, JSON включён"
    else:
        state = f"отвечает {s['status']}, JSON-вывода нет — включить format json в его настройках"
    lines.append(f"SearXNG ({searx}): {state}")
    proxy = env["proxy"]
    shown = ", ".join(f"{name} {'задан' if proxy[name] else 'нет'}" for name in PROXY_VARS)
    if not proxy[NO_PROXY_VAR]:
        bypass = "нет"
    elif proxy["local_bypass"]:
        bypass = "localhost и 127.0.0.1 — в обход прокси"
    else:
        bypass = "задан, но без localhost и 127.0.0.1"
    lines.append(f"прокси: {shown}; {NO_PROXY_VAR}: {bypass}")
    lines.append("ключи API (только наличие): " + split_names(env["keys"]))
    lib = env["library"]
    if not lib["set"]:
        lib_state = "не задана — хранилище только в проекте"
    elif lib["store"]:
        lib_state = "задана, хранилище есть"
    else:
        lib_state = "задана, а хранилища нет — deep_search.py init <путь>"
    lines.append(f"библиотека: {LIBRARY_VAR} {lib_state}")
    return "\n".join(lines)


def doctor(environ: Mapping[str, str], fetch: Fetch = http_fetch,
           today: date | None = None) -> tuple[dict, list[Issue], str]:
    """Проба среды: объект для manifest.json (с предупреждениями), предупреждения, обзор."""
    env, searx = probe_env(environ, fetch, today or date.today())
    issues = doctor_issues(env)
    env["warnings"] = [f"{i.path}: {i.rule}: {i.detail}" for i in issues]
    return env, issues, doctor_text(env, searx)


def run_doctor(as_json: bool) -> int:
    """Проба, а не проверка: код 0 при любом итоге, нехватка — строки warn."""
    env, issues, text = doctor(os.environ)
    if as_json:
        print(json.dumps(env, ensure_ascii=False, indent=2))
    else:
        print(bounded_report(issues, f"doctor: предупреждений {len(issues)}", head=text))
    return 0


# --- cost: цена сценариев -------------------------------------------------------------------


@dataclass
class Part:
    label: str
    chars: int
    tokens: int


@dataclass
class Scenario:
    name: str
    parts: list[Part]
    note: str = ""
    # Вместо перечня частей — note: у full перечень повторил бы всю таблицу.
    note_only: bool = False
    limit: int = STAGE_MAX_CHARS
    rule: str = "cost-stage"

    @property
    def chars(self) -> int:
        return sum(p.chars for p in self.parts)

    @property
    def tokens(self) -> int:
        return sum(p.tokens for p in self.parts)

    def what(self) -> str:
        if self.note_only:
            return self.note
        listed = " + ".join(p.label for p in self.parts)
        return f"{listed}; {self.note}" if self.note else listed


@dataclass
class SkillFiles:
    """Файлы скилла для cost: размеры частей и предупреждения о недостающих (по одному)."""
    skill: Path
    issues: list[Issue] = field(default_factory=list)
    ratio: float = 0.0
    _seen: dict[str, Part | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        texts = [read(p) for p in self.all_files()]
        total = sum(len(t) for t in texts)
        # Оценки (задания, ответы, карточка) пишутся тем же языком, что и файлы скилла: доля
        # кириллицы у них та же.
        self.ratio = (sum(estimate_tokens(t) for t in texts) / total if total
                      else TOKENS_PER_CYR_CHAR)

    def all_files(self) -> list[Path]:
        files = [self.skill / "SKILL.md"]
        for folder in ("references", "presets", "templates"):
            files += sorted((self.skill / folder).glob("*"))
        return [p for p in files if p.is_file()]

    def missing(self, rel: str, what: str) -> None:
        self.issues.append(Issue(rel, "cost-missing", f"{what} — сценарии посчитаны без него",
                                 warn=True))

    def file(self, rel: str) -> Part | None:
        """Файл скилла; у шаблона glob — самый большой из подходящих, нет ни одного — None."""
        if rel in self._seen:
            return self._seen[rel]
        pattern = any(c in rel for c in "*?[")
        found = [p for p in (sorted(self.skill.glob(rel)) if pattern else [self.skill / rel])
                 if p.is_file()]
        part = None
        if found:
            path = max(found, key=lambda p: len(read(p)))
            text = read(path)
            part = Part(path.relative_to(self.skill).as_posix(), len(text), estimate_tokens(text))
        elif not pattern:
            # Пресета может не быть (preset: none) — его отсутствие не предупреждение.
            self.missing(rel, "файла нет")
        self._seen[rel] = part
        return part

    def section(self, rel: str, heading: str, label: str) -> Part | None:
        path = self.skill / rel
        lines = read(path).splitlines() if path.is_file() else []
        bounds = section(lines, heading)
        if bounds is None:
            if path.is_file():
                self.missing(rel, f"нет раздела «{heading}»")
            return None
        text = "\n".join(lines[bounds[0]:bounds[1]])
        return Part(label, len(text), estimate_tokens(text))

    def estimate(self, label: str, chars: int) -> Part:
        return Part(label, chars, round(chars * self.ratio))


def unique(parts: list[Part]) -> list[Part]:
    seen: set[str] = set()
    out = []
    for part in parts:
        if part.label not in seen:
            seen.add(part.label)
            out.append(part)
    return out


def cost_scenarios(skill: Path, branches: int,
                   return_chars: int) -> tuple[list[Scenario], list[Issue]]:
    """Сценарии спецификации, 7.3, по реальным размерам файлов скилла.

    Состав — по таблице «Этапы» ядра (какой этап что читает) и поручению ветки
    (references/branching.md, «Поручение субагенту»). Чего нет среди файлов скилла — задания,
    ответы веток, plan.md, хранилище — берётся по бюджетам 7.2 и оценкам из констант.
    """
    fs = SkillFiles(skill)

    def parts(*items: Part | None) -> list[Part]:
        return [p for p in items if p is not None]

    core = fs.file("SKILL.md")
    store = fs.file("references/store.md")
    tasks = fs.estimate(f"задания {branches} × {num(TASK_MAX_CHARS)}", branches * TASK_MAX_CHARS)
    returns = fs.estimate(f"ответы {branches} × {num(return_chars)}", branches * return_chars)

    brief = parts(core, fs.file("references/brief.md"), fs.file("templates/brief.md"))
    fan_out = brief + parts(fs.file("references/branching.md"),
                            fs.file("templates/branch-task.yaml"), tasks)
    merge = parts(core, fs.file("references/verify-merge.md"), fs.file("templates/report.md"),
                  returns)
    save = parts(core, store, fs.file("templates/topic.md"),
                 fs.estimate("карточка и строки реестров", SAVE_WRITE_CHARS))
    reuse = parts(core, store, fs.estimate("grep INDEX", INDEX_GREP_CHARS),
                  fs.estimate(f"{REUSE_CARDS} карточки частями", REUSE_CARDS * CARD_READ_CHARS),
                  fs.estimate("grep утверждений", CLAIMS_GREP_CHARS))
    # apis.md ветка читает по разделам своей области; считаются разделы поиска технологий.
    apis = [fs.section("references/apis.md", head, f"apis «{head}»") for head in BRANCH_API_SECTIONS]
    branch = parts(fs.section("references/branching.md", "Поручение субагенту", "поручение"),
                   fs.estimate("задание", TASK_MAX_CHARS), fs.file("references/sources.md"),
                   fs.file("presets/*.md"), fs.file("references/environment.md"), *apis,
                   fs.file("templates/branch-return.yaml"))
    scenarios = [
        Scenario("quick", parts(core), "страницы ведущий читает сам — не считаются"),
        Scenario("reuse", reuse),
        Scenario("brief", brief),
        Scenario("fan-out", fan_out),
        Scenario("branch", branch, "контекст субагента, в ведущего не попадает"),
        Scenario("merge", merge),
        Scenario("save", save),
        Scenario("resume", parts(core, fs.estimate("plan.md", PLAN_MAX_CHARS))),
        Scenario("full", unique(fan_out + merge + save),
                 "brief + fan-out + merge + save без повторов: уровень M, одна сессия",
                 note_only=True, limit=FULL_MAX_CHARS, rule="cost-full"),
    ]
    return scenarios, fs.issues


def cost_issues(scenarios: list[Scenario]) -> list[Issue]:
    issues = []
    for s in scenarios:
        if s.chars <= s.limit:
            continue
        top = sorted(s.parts, key=lambda p: p.chars, reverse=True)[:3]
        issues.append(Issue(s.name, s.rule,
                            f"{num(s.chars)} символов (≈{num(s.tokens)} токенов) при пределе "
                            f"{num(s.limit)} — крупнее всего: "
                            + ", ".join(f"{p.label} {num(p.chars)}" for p in top), warn=True))
    return issues


def cost_text(scenarios: list[Scenario], branches: int, return_chars: int) -> str:
    def ratio(per_char: float) -> str:
        return f"{1 / per_char:.1f}".replace(".", ",")

    rows = [("сценарий", "символы", "≈ токены", "состав")]
    rows += [(s.name, num(s.chars), num(s.tokens), s.what()) for s in scenarios]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    table = [f"{r[0]:<{widths[0]}}  {r[1]:>{widths[1]}}  {r[2]:>{widths[2]}}  {r[3]}"
             for r in rows]
    return "\n".join([
        f"cost: цена сценариев (спецификация, 7.3) — веток {branches}, ответ ветки "
        f"{num(return_chars)} символов; токены ≈ кириллица / {ratio(TOKENS_PER_CYR_CHAR)} + "
        f"прочее / {ratio(TOKENS_PER_OTHER_CHAR)}, без калибровки по /context",
        *table,
        f"пределы: стадия {num(STAGE_MAX_CHARS)}, full {num(FULL_MAX_CHARS)} символов; задания, "
        "ответы и plan.md — по бюджетам, хранилище — оценка",
    ])


def run_cost(skill: Path, branches: int | None, return_chars: int | None) -> int:
    """Отчёт, а не проверка: код 0, превышение предела — строка warn."""
    if not skill.is_dir():
        print(f"cost: папки скилла нет: {skill}", file=sys.stderr)
        return 2
    branches = COST_BRANCHES if branches is None else branches
    return_chars = RETURN_MAX_CHARS if return_chars is None else return_chars
    if branches < 0 or return_chars < 0:
        print("cost: --branches и --return-chars — неотрицательные числа", file=sys.stderr)
        return 2
    scenarios, issues = cost_scenarios(skill, branches, return_chars)
    issues += cost_issues(scenarios)
    print(bounded_report(issues, f"cost: предупреждений {len(issues)}",
                         head=cost_text(scenarios, branches, return_chars)))
    return 0


# --- Вызов ------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deep_search.py",
        description="Проверки скилла deep-search, брифа, прогона и хранилища.",
    )
    sub = parser.add_subparsers(dest="command", metavar="{doctor,init,lint,index,cost,self}")

    p = sub.add_parser("doctor", help="проба среды: утилиты, API, прокси")
    p.add_argument("--json", action="store_true", help="вывод в JSON (для manifest.json)")

    p = sub.add_parser("init", help="каркас хранилища")
    p.add_argument("path", metavar="путь", type=Path)

    p = sub.add_parser("lint", help="бриф, прогон, хранилище")
    p.add_argument("--run", metavar="папка", type=Path, help="папка прогона")
    p.add_argument("--store", metavar="путь", type=Path, help="хранилище")

    p = sub.add_parser("index", help="собрать INDEX.md из карточек")
    p.add_argument("path", metavar="путь", type=Path)

    p = sub.add_parser("cost", help="цена сценариев в токенах")
    p.add_argument("--branches", metavar="N", type=int, help="число веток")
    p.add_argument("--return-chars", metavar="N", type=int, help="размер ответа ветки")
    p.add_argument("--skill-dir", metavar="путь", type=Path, default=SKILL_DIR,
                   help="папка скилла (по умолчанию — папка скрипта)")

    p = sub.add_parser("self", help="форма скилла: размеры, заголовки ядра, маршруты")
    p.add_argument("--skill-dir", metavar="путь", type=Path, default=SKILL_DIR,
                   help="папка скилла (по умолчанию — папка скрипта)")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except ValueError:
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "self":
        return run_self(args.skill_dir.resolve())
    if args.command == "init":
        return run_init(args.path)
    if args.command == "index":
        return run_index(args.path)
    if args.command == "lint":
        return run_lint(args.run, args.store)
    if args.command == "doctor":
        return run_doctor(args.json)
    return run_cost(args.skill_dir.resolve(), args.branches, args.return_chars)


if __name__ == "__main__":
    sys.exit(main())
