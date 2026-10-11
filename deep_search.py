#!/usr/bin/env python3
"""deep-search: проверки скилла, брифа, прогона и хранилища; новое из лент (watch); сводка
о репозитории или пакете (facts).

Один файл, Python stdlib ≥3.10, без внешних зависимостей (спецификация, 8.1).

Коды выхода: 0 — нарушений нет (предупреждения допустимы), 1 — есть нарушения, 2 — ошибка
вызова или команда не реализована. Строка нарушения — `<путь>: <правило>: <подробность>`,
предупреждение — та же строка с префиксом `warn: `. Имя правила — kebab-case, по нему
проверяют тесты, поэтому его не меняют без правки тестов и документации.
"""

from __future__ import annotations

import argparse
import email.utils
import fnmatch
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import socket
import ssl
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

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
# хранилище читаются вместе с другими подфайлами в одном этапе — им предел строже. Сценарий
# «что нового» держит рядом с собой найденное запуском watch (спецификация мониторинга, 9).
REF_MAX_LINES = 200
REF_MAX_CHARS = 12_000
REF_CHAR_BUDGETS = {"verify-merge.md": 8_000, "store.md": 8_000, "watch.md": 8_000}

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
# Дайджест не длиннее 150 строк (спецификация мониторинга, 9): шаблон — его скелет, а не текст.
DIGEST_TEMPLATE = "templates/digest.md"
DIGEST_TEMPLATE_MAX_CHARS = 2_000
TEMPLATE_BUDGETS = {
    BRIEF_TEMPLATE: (BRIEF_TEMPLATE_MAX_CHARS, "brief-template-chars"),
    DIGEST_TEMPLATE: (DIGEST_TEMPLATE_MAX_CHARS, "digest-template-chars"),
}

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
    # Допустимые пресеты берутся из presets/<имя>.md скилла (preset_names); этот список —
    # запасной, для скрипта, скопированного без папки пресетов.
    "preset": ("technology", "ai", "none"),
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
# читает в свой контекст: 5 000 символов ≈ 1,5 тыс. токенов на ветку. Задание — до 2 500:
# субагент получает его целиком вместе с поручением; в 2 000 задание ветки с перечнем
# известного и пояснениями к бюджету ужималось в несколько проходов.
RETURN_KEYS = ("task_id", "status", "stop_reason", "answer", "findings", "rejected", "conflicts",
               "gaps", "leads", "signals", "log_summary", "evidence_path")
RETURN_STATUSES = ("done", "partial", "not_found", "budget_exhausted", "blocked")
RETURN_MAX_CHARS = 5_000
TASK_MAX_CHARS = 2_500

# Журнал ветки (спецификация, 5.7): `capture` — только у ключевых страниц, поэтому не обязателен.
LOG_KEYS = ("ts", "branch", "method", "source", "query", "filters", "shown", "screened", "kept",
            "dupes", "note")
LOG_METHODS = ("query", "browse", "citation", "api", "batch")
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
# Любой из них — признак готового хранилища: init его не трогает, кроме watch/ — в нём
# досоздаётся недостающее (спецификация мониторинга, 8): библиотеки старше мониторинга иначе
# пришлось бы дополнять руками.
STORE_MARKERS = ("INDEX.md", "log.md", "sources.md", "topics", "claims")
# Заготовка watch/feeds.json (спецификация мониторинга, 2.3): набор скилла без добавок.
WATCH_FEEDS_STUB = {"version": 1, "add": [], "disable": [], "override": {}, "interests": {}}
# new/ и state.json пишет watch, digests/ — агент по сценарию «что нового».
WATCH_SUBDIRS = ("new", "digests")

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

# --- watch: новое из лент (спецификация мониторинга, 2–3) ---------------------------------

# Набор лент скилла и папка библиотеки (спецификация мониторинга, 2.1). Набор приходит со
# скиллом; добавки, отключения, состояние и найденное — в библиотеке, общей для всех проектов.
WATCH_FEEDS = "presets/ai-feeds.json"
WATCH_DIR = "watch"
WATCH_VERSION = 1

# Типы лент — в коде, по разборщику на тип (спецификация мониторинга, 3.2); сами ленты — данными.
# Перечень полный: тип, которого здесь нет, — ошибка вызова.
FEED_TYPES = ("rss", "sitemap", "github_releases", "hf_trending", "hf_papers", "openrouter",
              "hn", "telegram", "page")
# Порядок групп — порядок вывода: первоисточники раньше пересказов. У первоисточников склейка
# дублей берёт ссылку и дату.
FEED_GROUPS = ("labs", "releases", "aggregators", "newsletters", "telegram")
PRIMARY_GROUPS = ("labs", "releases")
FEED_LANGS = ("en", "ru")
FEED_FILTERS = ("always", "interests")
INTERESTS = ("models", "agents", "providers", "research", "apps")
# Обязательные поля ленты (спецификация мониторинга, 2.2); ещё нужен `url` или `params`.
FEED_REQUIRED = ("id", "type", "group", "lang", "filter")
# `match` сужает ленту: префиксы пути ссылки, префиксы заголовка (`[AINews]`) и подстроки
# ссылки или заголовка, которые выбрасывают запись.
FEED_MATCH_KEYS = ("path", "title", "exclude")

# Строка `new/<дата>.jsonl` — только эти поля: содержимое лент — данные, а не инструкции, и в
# файл попадает лишь то, что нужно агенту для отбора (спецификация мониторинга, 3.6).
RECORD_FIELDS = ("key", "title", "url", "date", "date_kind", "group", "feeds", "first_feed",
                 "interests", "topics", "excerpt", "trial")
# `topics` — темы библиотеки, чьё имя объекта или другое название встретилось в новости
# целым словом. Имя короче трёх символов («Go», «R») ловит чужие слова и не сверяется.
TOPIC_NAME_MIN_CHARS = 3

# Окно: первый запуск — неделя; дальше — от прошлого удачного опроса с перекрытием в сутки,
# чтобы запись с задержкой публикации не выпала (повтор отсекает `seen`). Дата дальше суток в
# будущем — опечатка ленты или дедлайн, а не публикация: как нет даты.
WATCH_FIRST_DAYS = 7
WATCH_OVERLAP = timedelta(days=1)
FUTURE_SLACK = timedelta(days=1)
# Провалов подряд до пометки «проверить или отключить»: один-два — сбой сети, три — лента
# сломалась или переехала.
FEED_FAILS_MARK = 3
# Виденное ленты ограничено, чтобы state.json не рос без конца; старые ключи вытесняются, а
# старые записи и так отсекает окно.
SEEN_MAX = 500
EXCERPT_MAX_CHARS = 300
TITLE_MAX_CHARS = 300
# Опрос: одновременно — не больше 8 хостов; к одному хосту — по очереди. Таймаут и предел тела
# — на ленту: полная история OpenAI или Hugging Face — несколько мегабайт.
FEED_WORKERS = 8
FEED_TIMEOUT = 20.0
FEED_BODY_MAX = 4 * 1024 * 1024
# Индекс карт сайта читается на один уровень; подкарт больше этого — лента слишком широка, её
# адрес лучше направить на нужную подкарту.
SITEMAP_CHILDREN_MAX = 50
# Описательный User-Agent: по нему владелец сайта видит, кто и зачем читает ленту. Браузерный
# (`ua: browser`) — только где описательный режут; Reddit, наоборот, режет браузерный
# (research/2026-10-09-sources-check/02-aggregators-telegram.md).
WATCH_UA = "deep-search-watch/1 (feed reader, manual runs)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
FEED_UA = ("browser",)
# Пауза между запросами к хосту (`min_interval`) — не больше этого: дольше таймаута ленты
# ждать нет смысла, а опечатка в наборе не должна вешать запуск.
MIN_INTERVAL_MAX = 120
# Лента «на пробу» после стольких удачных запусков без своей новости — кандидат на отключение.
TRIAL_RUNS_MARK = 8

# Типы, у которых адрес строится из `params` (спецификация мониторинга, 2.2): хост, на который
# идут запросы, обязательные и необязательные параметры. У остальных типов адрес — `url`.
PARAM_FEEDS = {
    "github_releases": ("api.github.com", ("repo",), ()),
    "hf_trending": ("huggingface.co", (), ("limit",)),
    "hf_papers": ("huggingface.co", (), ("min_upvotes",)),
    "openrouter": ("openrouter.ai", (), ()),
    "hn": ("hn.algolia.com", ("query",), ("min_points",)),
    "telegram": ("t.me", ("channel",), ()),
}
# Числовые параметры: целые не меньше нуля.
PARAM_COUNTS = ("limit", "min_upvotes", "min_points")
GITHUB_API_HOST = "api.github.com"
GITHUB_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TELEGRAM_CHANNEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,31}")
# Выпусков с одного запроса к API: окно в неделю у самых частых репозиториев — до двух десятков
# выпусков; releases.atom держит только 10 (01-labs.md).
GITHUB_RELEASES_PER_PAGE = 30
# Модели в тренде Hugging Face: сколько верхних смотреть; новое среди них — созданные за окно.
HF_TRENDING_LIMIT = 50
HF_TRENDING_LIMIT_MAX = 100
# Статьи недели Hugging Face: недель окна — не больше этого (длинный --since берёт последние).
HF_PAPERS_WEEKS_MAX = 4
HN_HITS_PER_PAGE = 50
# Telegram: страниц `?before=` на канал — не больше; у частых каналов 3–4 дня — 2–4 страницы.
TELEGRAM_PAGES_MAX = 4
TELEGRAM_TITLE_CHARS = 120
# page: строка короче — счётчик, кнопка или дата, а не содержание; снимок — хеши строк, не
# больше PAGE_LINES_MAX, чтобы state.json не рос от большой страницы.
PAGE_LINE_MIN_CHARS = 10
PAGE_LINES_MAX = 3_000
# Склейка по заголовку — только у содержательных заголовков: «Release notes» или «v1.2.0» у
# разных лент — разные новости.
TITLE_MERGE_MIN_WORDS = 3
TITLE_MERGE_MIN_CHARS = 16
# В строке сводки заголовок обрезается: полный — в файле найденного.
WATCH_TITLE_CHARS = 60
# Список «не ответили» — одной строкой ограниченной длины: при сбое сети он перечислял бы
# весь набор.
WATCH_FAILED_CHARS = 1_500

# --- facts: сводка о репозитории или пакете (спецификация мониторинга, 5) ----------------------

FACTS_TIMEOUT = 15.0
FACTS_BODY_MAX = 4 * 1024 * 1024
FACTS_MAX_CHARS = 2_000
FACTS_UA = "deep-search-facts/1 (package and repository facts, manual runs)"
# Значение — из чужого ответа: длинное обрезается, список уязвимостей — короче, с хвостом
# «… ещё N»: иначе сводка о репозитории не влезает в предел.
FACT_VALUE_CHARS = 200
FACT_LIST_CHARS = 120
FACTS_FAILED_CHARS = 400
# Циклов endoflife.date в строке, когда версия цели не задана или не нашлась.
EOL_CYCLES = 3
# Поля в порядке вывода: ключ (он же `field` в --json) и подпись в тексте.
FACT_FIELDS = {
    "repository": "репозиторий",
    "license": "лицензия",
    "archived": "архивирован",
    "stars": "звёзды",
    "last_commit": "последний коммит",
    "last_release": "последний выпуск",
    "package": "пакет",
    "versions": "версии",
    "version": "лицензии, уязвимости версии",
    "vulns": "уязвимости (OSV)",
    "eol": "конец поддержки",
    "usage": "загрузки, зависимые",
    "scorecard": "оценка сопровождения",
    "distros": "в дистрибутивах",
}
# Тип purl → экосистема OSV, реестр ecosyste.ms, префикс проекта Repology.
PURL_SYSTEMS = {"pypi": ("PyPI", "pypi.org", "python"), "npm": ("npm", "npmjs.org", "node")}
# Хостинги по имени хоста; другой хост с «gitlab» в имени — GitLab, остальные — Forgejo/Gitea.
FORGE_HOSTS = {"github.com": "github", "gitlab.com": "gitlab", "gitee.com": "gitee",
               "codeberg.org": "gitea"}
# Хостинги, о проектах которых знает deps.dev.
DEPSDEV_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
# deps.dev отдаёт пакеты проекта (:packageversions) не больше 1 500 записей и без следующей
# страницы: у репозитория с частыми коммитами их все занимают псевдоверсии модуля Go.
DEPSDEV_LIST_CAP = 1_500
FACTS_EXAMPLES = ("https://github.com/psf/requests", "psf/requests",
                  "https://gitlab.com/gitlab-org/gitlab-runner",
                  "https://codeberg.org/forgejo/forgejo", "https://gitee.com/openharmony/docs",
                  "pkg:pypi/requests", "pkg:npm/react@18.3.1")

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
# Сценарий «что нового» (references/watch.md, «Шаги») читает вывод watch — он ограничен
# OUTPUT_MAX_CHARS — и выборки jq из new/<дата>.jsonl: по группам labs и releases, ×N, интересам и
# рейтингу HN. Строка выборки ≈160 символов (дата, число лент, заголовок до 80, ссылка); ориентир —
# ≈55 строк, столько же, сколько строк записей в выводе watch. Страницы первоисточников при
# проверке отобранного не считаются, как у quick.
WATCH_JQ_CHARS = 9_000
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
# id утверждения в тексте карточки: slug жадный, но отдаёт номер — C-log-search-001 целиком.
CLAIM_REF_RE = re.compile(rf"(?<![\w-])C-{SLUG}-\d{{3}}(?!\d)")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
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
    reserve = len(TAIL.format(len(ordered))) + len(summary) + 2 + (len(head) + 1 if head else 0)
    fitted, omitted = fit_lines([i.line() for i in ordered], OUTPUT_MAX_CHARS - reserve)
    shown: list[str] = [head] if head else []
    shown += fitted
    if omitted:
        shown.append(TAIL.format(omitted))
    shown.append(summary)
    return "\n".join(shown)


TAIL = "… ещё {}"


def fit_lines(lines: list[str], budget: int) -> tuple[list[str], int]:
    """Строки по порядку, пока влезают в budget символов с переводами строк, и число невлезших.

    Длинная строка обрезается до LINE_MAX_CHARS. После первой невлезшей отбрасываются и
    остальные: выборка из середины списка вводила бы в заблуждение.
    """
    shown: list[str] = []
    size = 0
    for line in lines:
        line = shorten(line, LINE_MAX_CHARS)
        if size + len(line) + 1 > budget:
            break
        shown.append(line)
        size += len(line) + 1
    return shown, len(lines) - len(shown)


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    for rel, (limit, rule) in TEMPLATE_BUDGETS.items():
        path = skill / rel
        if path.is_file():
            size = len(read(path))
            if size > limit:
                issues.append(Issue(rel, rule, f"{num(size)} символов при пределе {num(limit)}"))
    issues += check_feed_sets(skill)
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
        if name == "preset":
            allowed = preset_names(SKILL_DIR)
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


def preset_names(skill: Path) -> tuple[str, ...]:
    """Пресеты для поля `preset` брифа: presets/<имя>.md скилла и `none`.

    Новый пресет становится допустимым, как только появился его файл. Без папки пресетов
    (скрипт скопирован отдельно) — запасной список BRIEF_ENUMS.
    """
    names = sorted(p.stem for p in (skill / "presets").glob("*.md") if p.is_file())
    return (*names, "none") if names else BRIEF_ENUMS["preset"]


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
    if entry.get("method") == "batch" and not journal_count(entry):
        problems.append("у batch нет count — числа запросов пакета")
    return problems


def journal_count(entry: dict) -> int:
    """Обращений наружу в строке: у пакета скрипта — его `count`, у остальных — одно."""
    if entry.get("method") != "batch":
        return 1
    count = entry.get("count")
    return count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 0


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
    for path in sorted(branches.glob("*.return.yaml")):
        issues += check_log_summary(path, branches, label(path))
    return issues


LOG_SUMMARY_RE = re.compile(r"^log_summary:.*?\bqueries:\s*(\d+).*?\bsources_viewed:\s*(\d+)", re.M)


def check_log_summary(path: Path, branches: Path, label: str) -> list[Issue]:
    """Ответ ветки насчитал больше обращений, чем записано в журнале.

    Бюджет ведущий считает по журналу; ветка, которая пишет журнал не на каждое обращение,
    занижает расход, и прогон незаметно выходит за бюджет.
    """
    m = LOG_SUMMARY_RE.search(read(path))
    journal = branches / (path.name[: -len(".return.yaml")] + ".jsonl")
    if m is None or not journal.is_file():
        return []
    entries = []
    for line in read(journal).splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    queries = sum(1 for e in entries if e.get("method") == "query")
    calls = sum(journal_count(e) for e in entries)
    said_queries, said_viewed = int(m.group(1)), int(m.group(2))
    gaps = []
    if said_queries > queries:
        gaps.append(f"запросов {said_queries}, а строк query {queries}")
    if said_queries + said_viewed > calls:
        gaps.append(f"запросов и источников {said_queries + said_viewed}, а обращений в журнале "
                    f"{calls}")
    if not gaps:
        return []
    return [Issue(label, "log-undercount",
                  "в log_summary " + "; ".join(gaps) + " — журнал пишется на каждое обращение "
                  "(references/sources.md, «Журнал и улики»)", warn=True)]


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
    subject: str = ""
    checked: date | None = None

    @property
    def key(self) -> str:
        """`предмет` для сверки между утверждениями и темами: без учёта регистра и пробелов."""
        key = " ".join(self.subject.split()).casefold()
        return "" if key == NO_VALUE else key


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


def check_card(card: Card, claims: list[Claim] | None, today: date) -> list[Issue]:
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

    # Живых непросроченных утверждений нет — status: stale (references/store.md, «Запись»).
    # Нет живых совсем — ошибка; все просрочены — предупреждение: это наступает со временем,
    # а не от правки.
    if claims and all(c.parsed for c in claims) and status in ("live", "stale"):
        fresh = [c for c in live if c.fresh is None or c.fresh >= today]
        if status == "live" and not live:
            issues.append(Issue(rel, "card-status",
                                "status: live, а живых утверждений нет — status: stale"))
        elif status == "live" and not fresh:
            issues.append(Issue(rel, "card-status",
                                "status: live, а все живые утверждения просрочены — перепроверить "
                                "или status: stale", warn=True))
        elif status == "stale" and fresh:
            issues.append(Issue(rel, "card-status",
                                f"status: stale, а живых непросроченных {len(fresh)} — после "
                                "перепроверки вернуть status: live", warn=True))
    return issues


def card_lines(text: str) -> list[str]:
    """Строки карточки без frontmatter и комментариев `<!-- -->`; номера строк сохраняются."""
    text = HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        lines[:end + 1] = [""] * (end + 1)
    return lines


def answer_blocks(lines: list[str], start: int, stop: int) -> list[tuple[int, str]]:
    """Выводы раздела «Ответ на …»: пункт списка или абзац с продолжением — (строка, текст)."""
    blocks: list[tuple[int, list[str]]] = []
    for i in range(start + 1, stop):
        line = lines[i]
        if not line.strip() or line.startswith(("|", "#")):
            blocks.append((i, []))
            continue
        item = re.match(r"\s*(?:[-*+]|\d+[.)])\s", line) is not None
        if item or not blocks or not blocks[-1][1]:
            blocks.append((i, [line]))
        else:
            blocks[-1][1].append(line)
    return [(i + 1, " ".join(b)) for i, b in blocks if b]


def check_card_refs(card: Card, claims: dict[str, Claim], archived: set[str]) -> list[Issue]:
    """Ссылки карточки на утверждения и выводы без них (references/store.md, «Запись», шаг 3).

    Карточка — что известно сейчас: ссылка на заменённое или опровергнутое значит, что вывод
    не переписали после обновления утверждений.
    """
    rel = f"topics/{card.path.name}"
    lines = card_lines(read(card.path))
    issues: list[Issue] = []
    for n, line in enumerate(lines, 1):
        for cid in dict.fromkeys(CLAIM_REF_RE.findall(line)):
            claim = claims.get(cid)
            if claim is None:
                where = ("в архиве — агент туда не смотрит" if cid in archived
                         else "такого утверждения нет")
                issues.append(Issue(rel, "card-claim-ref", f"строка {n}: {cid} — {where}"))
            elif claim.status.startswith("superseded→"):
                target = claim.status.partition("→")[2]
                issues.append(Issue(rel, "card-claim-ref",
                                    f"строка {n}: {cid} заменено на {target} — переписать вывод "
                                    f"по {target}"))
            elif claim.status == "retracted":
                issues.append(Issue(rel, "card-claim-ref",
                                    f"строка {n}: {cid} опровергнуто — вывод пересмотреть"))
    for head, start, stop in h2_sections(lines):
        if not head.startswith("Ответ на"):
            continue
        bare = [n for n, text in answer_blocks(lines, start, stop)
                if not CLAIM_REF_RE.search(text)]
        if bare:
            issues.append(Issue(rel, "card-answer-ref",
                                f"«{head}», строки {lines_list(bare)}: вывод без ссылки на C-… — "
                                "сослаться на утверждение или перенести в «Открытые вопросы»",
                                warn=True))
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
                            fresh_date, status, subject=subject, checked=valid_date(checked)))
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
    by_id = {c.id: c for rows in claims.values() for c in rows}
    archived = {cid for path in sorted((store / "archive" / "claims").glob("*.md"))
                for cid in re.findall(rf"(?m)^\| (C-{SLUG}-\d{{3}})", read(path))}
    for card in cards:
        issues += check_card(card, claims.get(card.path.stem), today)
        issues += check_card_refs(card, by_id, archived)

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
    issues += check_watch(store)
    return issues


def load_claims(store: Path, today: date) -> dict[str, list[Claim]]:
    """Утверждения хранилища по темам; ошибки формата здесь не нужны — их даёт check_store."""
    return {p.stem: check_claims(p, p.name, p.stem, today)[1]
            for p in sorted((store / "claims").glob("*.md"))}


def run_topic(run: Path) -> tuple[str, date] | None:
    """Тема и дата прогона из брифа: store_topic (или slug из id) и дата из id."""
    path = run / "brief.md"
    fields = frontmatter(read(path)) if path.is_file() else None
    values = {k: scalar(v) for k, v in (fields or {}).items()}
    m = RUN_ID_RE.fullmatch(values.get("id", ""))
    day = valid_date(m.group(1)) if m else None
    if m is None or day is None:
        return None
    return values.get("store_topic") or m.group(2), day


def claim_dates(claims: list[Claim]) -> str:
    shown = ", ".join(f"{c.id} ({c.checked or '?'})" for c in claims[:5])
    return shown + (f" … (всего {len(claims)})" if len(claims) > 5 else "")


def check_subjects(run: Path, store: Path, also: list[Path], today: date | None = None
                   ) -> list[Issue]:
    """Сверка того, что обновил прогон, с прежними живыми утверждениями (references/store.md,
    «Запись», шаг 4).

    Прогон тронул предмет, если у живого утверждения его темы `проверено` не раньше даты
    прогона. Прежние живые утверждения о том же предмете — в своей теме, в других темах
    хранилища и в хранилищах `also` — могли устареть или разойтись с новым. Сверка привязана к
    прогону: без него новое не отличить от перепроверенного, и предупреждение висело бы вечно.
    """
    today = today or date.today()
    found = run_topic(run)
    if found is None:
        return []
    topic, day = found
    claims = load_claims(store, today)
    touched: dict[str, list[Claim]] = {}
    for c in claims.get(topic, []):
        if c.status == "live" and c.key and c.checked is not None and c.checked >= day:
            touched.setdefault(c.key, []).append(c)
    issues: list[Issue] = []

    def compare(where: str, slug: str, rows: list[Claim]) -> None:
        old: dict[str, list[Claim]] = {}
        for c in rows:
            if (c.status == "live" and c.key in touched
                    and (c.checked is None or c.checked < day)):
                old.setdefault(c.key, []).append(c)
        for key, stale in old.items():
            new = ", ".join(c.id for c in touched[key][:5])
            if slug == topic and where == "":
                issues.append(Issue(f"claims/{slug}.md", "claim-subject",
                                    f"«{stale[0].subject}»: {claim_dates(stale)} — прогон обновил "
                                    f"предмет ({new}): заменить (superseded→…), перепроверить "
                                    "или оставить как независимое", warn=True))
            else:
                issues.append(Issue(f"{where}claims/{slug}.md", "claim-subject-shared",
                                    f"«{stale[0].subject}»: {claim_dates(stale)} — предмет обновлён "
                                    f"в теме {topic} ({new}): сверить; расходится — перепроверить "
                                    "или пометить stale", warn=True))

    for slug, rows in claims.items():
        compare("", slug, rows)
    for other in also:
        where = other.as_posix().rstrip("/") + "/"
        twin = other / "topics" / f"{topic}.md"
        if twin.is_file() and not Card(twin, frontmatter(read(twin))).archived:
            issues.append(Issue(f"{where}topics/{topic}.md", "topic-twin",
                                "та же тема в другом хранилище — сверить выводы и даты "
                                "проверки; расхождение разрешить или вынести в открытые "
                                "вопросы", warn=True))
        for slug, rows in load_claims(other, today).items():
            compare(where, slug, rows)
    return issues


def run_lint(run: Path | None, store: Path | None, also: list[Path] | None = None) -> int:
    # Имя папки прогона сверяется с id брифа: у «.» имени нет, поэтому путь — абсолютный.
    run = run.resolve() if run is not None else None
    store = store.resolve() if store is not None else None
    also = [path.resolve() for path in also or []]
    if run is None and store is None:
        print("lint: нужен --run <папка прогона> и/или --store <хранилище>", file=sys.stderr)
        return 2
    if also and (run is None or store is None):
        print("lint: --also сверяет тему прогона — нужны и --run, и --store", file=sys.stderr)
        return 2
    if run is not None and not run.is_dir():
        print(f"lint: папки прогона нет: {run}", file=sys.stderr)
        return 2
    for path in ([store] if store is not None else []) + also:
        if not (path / "INDEX.md").is_file():
            print(f"lint: хранилища нет (нет INDEX.md): {path} — deep_search.py init <путь>",
                  file=sys.stderr)
            return 2
    issues: list[Issue] = []
    if run is not None:
        issues += check_run(run)
    if store is not None:
        issues += check_store(store)
    if run is not None and store is not None:
        issues += check_subjects(run, store, also)
    errors = sum(not i.warn for i in issues)
    summary = f"lint: нарушений {errors}, предупреждений {len(issues) - errors}"
    print(bounded_report(issues, summary))
    return 1 if errors else 0


# --- init, index ----------------------------------------------------------------------------


def init_watch(store: Path) -> list[str]:
    """Недостающее в watch/: заготовка feeds.json, new/, digests/. Что уже есть — не трогается.

    Возвращает созданное, пути от watch/.
    """
    folder = store / WATCH_DIR
    created: list[str] = []
    folder.mkdir(exist_ok=True)
    feeds = folder / "feeds.json"
    if not feeds.exists():
        feeds.write_text(json.dumps(WATCH_FEEDS_STUB, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        created.append("feeds.json")
    for name in WATCH_SUBDIRS:
        if not (folder / name).is_dir():
            (folder / name).mkdir()
            created.append(f"{name}/")
    return created


def run_init(store: Path) -> int:
    if store.exists() and not store.is_dir():
        print(f"init: это файл, а не папка: {store}", file=sys.stderr)
        return 2
    watch_dir = store / WATCH_DIR
    clash = [p for p in (watch_dir, *(watch_dir / n for n in WATCH_SUBDIRS))
             if p.exists() and not p.is_dir()]
    if clash:
        print(f"init: это файл, а не папка: {clash[0]} — ничего не изменено", file=sys.stderr)
        return 2
    present = [m for m in STORE_MARKERS if (store / m).exists()]
    if present:
        created = init_watch(store)
        if not created:
            print(f"init: хранилище уже есть ({', '.join(present)}) и {WATCH_DIR}/ на месте: "
                  f"{store} — ничего не изменено", file=sys.stderr)
            return 2
        print(f"init: хранилище уже есть ({', '.join(present)}): {store} — не тронуто; "
              f"в {WATCH_DIR}/ досоздано: " + ", ".join(created))
        return 0
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
    init_watch(store)
    print(f"init: хранилище создано: {store}\n"
          "INDEX.md, log.md, sources.md, " + ", ".join(f"{d}/" for d in STORE_DIRS)
          + f", {WATCH_DIR}/ (feeds.json, " + ", ".join(f"{d}/" for d in WATCH_SUBDIRS)
          + "); raw/ — в .gitignore, archive/ — в .ignore")
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
    """Ответ на запрос: HTTP-код и тело (если просили) или причина отказа.

    url — адрес после редиректов; truncated — тело длиннее предела и обрезано.
    """
    status: int | None = None
    body: bytes = b""
    error: str = ""
    url: str = ""
    truncated: bool = False


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


def http_request(method: str, url: str, data: bytes | None = None,
                 headers: Mapping[str, str] | None = None, *, proxy: bool = True,
                 timeout: float = DOCTOR_TIMEOUT, limit: int = 0) -> Probe:
    """Один запрос: тело — до limit байт (0 — тело не читается). proxy=False — мимо прокси,
    как `curl --noproxy`.

    gzip распаковывается по сигнатуре тела, а не по заголовку: часть серверов сжимает ответ,
    даже когда сжатия не просили (research/2026-10-09-sources-check/01-labs.md, DeepMind).
    Тело длиннее предела обрезается с пометкой truncated: решает вызывающий. Authorization не
    идёт за редиректом: токен — только тому хосту, которому его дали.
    """
    opener = urllib.request.build_opener(*([] if proxy else [urllib.request.ProxyHandler({})]))
    headers = dict(headers or {})
    auth = headers.pop("Authorization", "")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    if auth:
        request.add_unredirected_header("Authorization", auth)
    try:
        with opener.open(request, timeout=timeout) as resp:
            status, final = resp.status, resp.geturl()
            body = resp.read(limit + 1) if limit else b""
    except urllib.error.HTTPError as exc:
        exc.close()
        return Probe(exc.code)
    except Exception as exc:  # noqa: BLE001  любой отказ — строка отчёта, а не падение пробы
        return Probe(error=fetch_error(exc))
    if body[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as packed:
                body = packed.read(limit + 1)
        except (OSError, EOFError, zlib.error):
            # Обрезанное сжатое тело не распаковать до конца: это превышение предела, а не порча.
            return Probe(status, url=final, truncated=True) if len(body) > limit \
                else Probe(status, error="битый gzip", url=final)
    return Probe(status, body[:limit], url=final, truncated=len(body) > limit)


def http_fetch(method: str, url: str, data: bytes | None, proxy: bool, want_body: bool,
               token: str = "") -> Probe:
    """Пробный запрос doctor с DOCTOR_TIMEOUT; тело — до 64 КБ, если просили.

    token — Bearer-токен: с ним /rate_limit GitHub показывает лимит токена, а не IP.
    """
    headers = {"User-Agent": "deep-search-doctor"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    return http_request(method, url, data, headers, proxy=proxy, timeout=DOCTOR_TIMEOUT,
                        limit=65_536 if want_body else 0)


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
    token = github_token(environ)
    jobs = [(key, method, url, data, True, key == "github", token if key == "github" else "")
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


# --- watch: новое из лент -------------------------------------------------------------------


class WatchError(Exception):
    """Ошибка вызова watch: код 2 и текст для человека."""


class FeedError(Exception):
    """Лента не ответила или прислала не то: причина — короткая строка «не ответили»."""


# fetch(адрес, заголовки) — запрос ленты; подменяется в тестах, как Fetch у doctor.
FeedFetch = Callable[[str, Mapping[str, str]], Probe]


def feed_fetch(url: str, headers: Mapping[str, str]) -> Probe:
    return http_request("GET", url, None, headers, timeout=FEED_TIMEOUT, limit=FEED_BODY_MAX)


@dataclass
class Entry:
    """Запись ленты после разбора: ключ, заголовок и выдержка — уже простой текст.

    when — дата записи или None (даты нет, она без года или дальше суток в будущем); links —
    внешние ссылки поста, по ним склеиваются пересказы с первоисточником.
    """
    key: str
    title: str
    url: str
    when: datetime | None
    date_kind: str
    excerpt: str = ""
    links: tuple[str, ...] = ()
    feed: str = ""
    # Заголовок выведен из адреса (карта сайта): по нему ленты не склеиваются.
    title_from_url: bool = False


@dataclass
class FeedPoll:
    """Всё, что нужно разборщику ленты: сама лента, запрос с её заголовками, начало окна,
    время запуска и её состояние (разборщик может хранить в нём своё)."""
    feed: dict
    get: Callable[[str], Probe]
    since: datetime
    now: datetime
    state: dict


@dataclass
class FeedOutcome:
    entries: list[Entry] | None = None
    error: str = ""


@dataclass
class FeedSet:
    feeds: list[dict]
    interests: dict[str, list[str]]
    notes: list[str]


@dataclass
class WatchRun:
    day: str
    records: list[dict]
    feeds: int
    failed: list[tuple[str, str]]
    notes: list[str]
    # Файл найденного; None — --dry-run, ничего не записано.
    path: Path | None
    # Ленты «на пробу», не давшие своего за TRIAL_RUNS_MARK запусков.
    idle_trials: list[str] = field(default_factory=list)


# --- watch: набор лент и состояние ----------------------------------------------------------


def feed_problems(feed: object) -> list[tuple[str, str]]:
    """Нарушения одной ленты: (правило, подробность). Правила — как у self и lint."""
    if not isinstance(feed, dict):
        return [("feeds-json", "лента — не объект JSON")]
    problems: list[tuple[str, str]] = []
    fid = feed.get("id")
    if not isinstance(fid, str) or not SLUG_RE.fullmatch(fid):
        problems.append(("feeds-id", f"id {json.dumps(fid, ensure_ascii=False)} — нужен slug "
                                     "из латиницы, цифр и дефисов"))
    missing = [k for k in FEED_REQUIRED if k not in feed]
    if "url" not in feed and "params" not in feed:
        missing.append("url или params")
    if missing:
        problems.append(("feeds-json", "нет полей: " + ", ".join(missing)))
    kind = feed.get("type")
    if "type" in feed and kind not in FEED_TYPES:
        problems.append(("feeds-type", f"неизвестный тип «{kind}» — известны: "
                                       + ", ".join(FEED_TYPES)))
    for key, allowed in (("group", FEED_GROUPS), ("lang", FEED_LANGS),
                         ("filter", FEED_FILTERS)):
        if key in feed and feed[key] not in allowed:
            problems.append(("feeds-json", f"{key} «{feed[key]}» — допустимо: "
                                           + ", ".join(allowed)))
    if "url" in feed and not (isinstance(feed["url"], str)
                              and urlsplit(feed["url"]).scheme in ("http", "https")):
        problems.append(("feeds-json", "url — не адрес http(s)"))
    problems += param_problems(feed)
    if "ua" in feed and feed["ua"] not in FEED_UA:
        problems.append(("feeds-json", f"ua «{feed['ua']}» — допустимо: " + ", ".join(FEED_UA)))
    interval = feed.get("min_interval", 0)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) \
            or not 0 <= interval <= MIN_INTERVAL_MAX:
        problems.append(("feeds-json", f"min_interval — секунды от 0 до {MIN_INTERVAL_MAX}"))
    if not isinstance(feed.get("trial", False), bool):
        problems.append(("feeds-json", "trial — true или false"))
    match = feed.get("match", {})
    if not isinstance(match, dict) or any(
            k not in FEED_MATCH_KEYS or not all(isinstance(x, str) for x in as_list(v))
            for k, v in match.items()):
        problems.append(("feeds-json", "match — объект с ключами " + ", ".join(FEED_MATCH_KEYS)
                                       + " и строками или списками строк"))
    return problems


def param_problems(feed: dict) -> list[tuple[str, str]]:
    """Адрес ленты: у типов из PARAM_FEEDS — `params` с известными ключами и без `url`, у
    остальных — `url`. Опечатка в имени параметра — нарушение: иначе порог молча не работал бы."""
    kind = feed.get("type")
    if not isinstance(kind, str) or kind not in PARAM_FEEDS:
        if kind in FEED_TYPES and "url" not in feed and "params" in feed:
            return [("feeds-json", f"у типа {kind} адрес — url, а не params")]
        return []
    problems: list[tuple[str, str]] = []
    if "url" in feed:
        problems.append(("feeds-json", f"у типа {kind} адрес строится из params — url не нужен"))
    params = feed.get("params", {})
    if not isinstance(params, dict):
        return problems + [("feeds-json", "params — объект")]
    _, required, optional = PARAM_FEEDS[kind]
    missing = [k for k in required if k not in params]
    if missing and "params" in feed:
        problems.append(("feeds-json", "нет params." + ", params.".join(missing)))
    extra = [k for k in params if k not in required + optional]
    if extra:
        problems.append(("feeds-json", f"params у типа {kind} — только "
                                       + (", ".join(required + optional) or "пустой объект")
                                       + "; лишние: " + ", ".join(extra)))
    if "repo" in params and not (isinstance(params["repo"], str)
                                 and GITHUB_REPO_RE.fullmatch(params["repo"])):
        problems.append(("feeds-json", "params.repo — OWNER/REPO"))
    if "channel" in params and not (isinstance(params["channel"], str)
                                    and TELEGRAM_CHANNEL_RE.fullmatch(params["channel"])):
        problems.append(("feeds-json", "params.channel — имя канала без t.me/ и @"))
    if "query" in params:
        queries = as_list(params["query"])
        if not queries or not all(isinstance(q, str) and q.strip() for q in queries):
            problems.append(("feeds-json", "params.query — строка или список непустых строк"))
    for key in PARAM_COUNTS:
        value = params.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(("feeds-json", f"params.{key} — целое не меньше 0"))
    return problems


def as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    return [value]


def load_watch_json(path: Path, rel: str) -> dict:
    data, problems = feeds_document(path)
    if data is None:
        raise WatchError(f"{rel}: {problems[0][1]}")
    return data


def interest_words(value: object, rel: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise WatchError(f"{rel}: interests — объект «группа → список слов»")
    words: dict[str, list[str]] = {}
    for group, items in value.items():
        if group not in INTERESTS:
            raise WatchError(f"{rel}: интерес «{group}» — известны: " + ", ".join(INTERESTS))
        if not isinstance(items, list) or not all(isinstance(w, str) and w for w in items):
            raise WatchError(f"{rel}: interests.{group} — список непустых строк")
        words[group] = items
    return words


def load_feed_set(skill: Path, library: Path) -> FeedSet:
    """Набор = ленты скилла − disable + add, затем override (спецификация мониторинга, 2.3)."""
    notes: list[str] = []
    skill_path = skill / WATCH_FEEDS
    base: dict = {}
    if skill_path.is_file():
        base = load_watch_json(skill_path, WATCH_FEEDS)
    else:
        notes.append(f"в скилле нет {WATCH_FEEDS} — только ленты библиотеки")
    lib_rel = f"{WATCH_DIR}/feeds.json"
    lib_path = library / lib_rel
    extra = load_watch_json(lib_path, lib_rel) if lib_path.is_file() else {}

    skill_feeds = base.get("feeds", [])
    add = extra.get("add", [])
    disable = extra.get("disable", [])
    override = extra.get("override", {})
    if not isinstance(skill_feeds, list):
        raise WatchError(f"{WATCH_FEEDS}: feeds — список лент")
    if not isinstance(add, list):
        raise WatchError(f"{lib_rel}: add — список лент")
    if not isinstance(disable, list) or not all(isinstance(x, str) for x in disable):
        raise WatchError(f"{lib_rel}: disable — список id")
    if not isinstance(override, dict) or not all(isinstance(v, dict) for v in override.values()):
        raise WatchError(f"{lib_rel}: override — объект «id → поля»")

    feeds: list[dict] = []
    origin: dict[str, str] = {}
    for rel, items in ((WATCH_FEEDS, skill_feeds), (lib_rel, add)):
        for item in items:
            fid = item.get("id") if isinstance(item, dict) else None
            if rel == WATCH_FEEDS and fid in disable:
                continue
            if isinstance(fid, str) and fid in origin:
                where = "в том же файле" if origin[fid] == rel else f"— уже есть в {origin[fid]}"
                raise WatchError(f"{rel}: лента {fid}: повтор id {where}")
            if isinstance(fid, str):
                origin[fid] = rel
            feeds.append(dict(item) if isinstance(item, dict) else item)
    skill_ids = {f.get("id") for f in skill_feeds if isinstance(f, dict)}
    stale = [x for x in disable if x not in skill_ids]
    if stale:
        notes.append(f"{lib_rel}: disable — в наборе скилла нет: " + ", ".join(stale))

    by_id = {f["id"]: f for f in feeds if isinstance(f, dict) and isinstance(f.get("id"), str)}
    missing = []
    for fid, fields in override.items():
        if fid not in by_id:
            missing.append(fid)
            continue
        if fields.get("id", fid) != fid:
            raise WatchError(f"{lib_rel}: override {fid}: id не меняется")
        by_id[fid].update(fields)
    if missing:
        notes.append(f"{lib_rel}: override — таких лент в наборе нет: " + ", ".join(missing))

    for n, feed in enumerate(feeds):
        problems = feed_problems(feed)
        if problems:
            fid = feed.get("id") if isinstance(feed, dict) else None
            name = f"лента {fid}" if isinstance(fid, str) else f"лента №{n + 1}"
            rel = origin.get(fid, WATCH_FEEDS) if isinstance(fid, str) else WATCH_FEEDS
            raise WatchError(f"{rel}: {name}: " + "; ".join(p for _, p in problems))

    interests = interest_words(base.get("interests", {}), WATCH_FEEDS)
    interests.update(interest_words(extra.get("interests", {}), lib_rel))
    if not feeds:
        raise WatchError(f"лент нет: ни в {WATCH_FEEDS} скилла, ни в add библиотеки")
    return FeedSet(feeds, interests, notes)


def select_feeds(feeds: list[dict], only: str | None) -> list[dict]:
    if only is None:
        return feeds
    if only in FEED_GROUPS:
        chosen = [f for f in feeds if f["group"] == only]
    else:
        chosen = [f for f in feeds if f["id"] == only]
    if not chosen:
        raise WatchError(f"--only {only}: нет ни такой группы с лентами, ни включённой ленты — "
                         "группы: " + ", ".join(FEED_GROUPS))
    return chosen


def new_feed_state() -> dict:
    return {"last_ok": "", "fails": 0, "last_error": "", "seen": [], "runs": 0, "new": 0,
            "first": 0, "unique": 0}


def feed_state(raw: dict) -> dict:
    """Состояние ленты с полями нужных типов; чужие поля сохраняются."""
    state = dict(raw)
    for key, default in new_feed_state().items():
        value = raw.get(key)
        if type(value) is not type(default):
            state[key] = default
    state["seen"] = [k for k in state["seen"] if isinstance(k, str)][:SEEN_MAX]
    return state


def load_state(path: Path) -> tuple[dict[str, dict], bool]:
    """Состояние лент и признак «файл битый»."""
    if not path.is_file():
        return {}, False
    try:
        data = json.loads(read(path))
    except json.JSONDecodeError:
        return {}, True
    if (not isinstance(data, dict) or data.get("version") != WATCH_VERSION
            or not isinstance(data.get("feeds"), dict)):
        return {}, True
    return {fid: feed_state(v) for fid, v in data["feeds"].items() if isinstance(v, dict)}, False


def write_json_atomic(path: Path, data: dict) -> None:
    """Временный файл рядом и замена: прерванный запуск не оставляет полузаписанный JSON."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=1)
            out.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- self и lint: файлы мониторинга ---------------------------------------------------------
#
# Те же правила, что у watch, но списком нарушений, а не первой ошибкой вызова: человек правит
# всё за один заход. Проверка только читает — битый state.json переименовывает сам watch.


Problems = list[tuple[str, str]]


def feeds_document(path: Path) -> tuple[dict | None, Problems]:
    """Файл набора или добавок: объект JSON с version 1. Не он — None и нарушение."""
    try:
        data = json.loads(read(path))
    except json.JSONDecodeError as exc:
        return None, [("feeds-json", f"битый JSON — {exc.msg}, строка {exc.lineno}")]
    if not isinstance(data, dict):
        return None, [("feeds-json", "нужен объект JSON")]
    if data.get("version", WATCH_VERSION) != WATCH_VERSION:
        return None, [("feeds-json", f"version {data.get('version')} — известна только "
                                     f"{WATCH_VERSION}")]
    return data, []


def feed_list_problems(feeds: list) -> Problems:
    """Нарушения каждой ленты списка и повторы id; у подробности — имя ленты."""
    problems: Problems = []
    seen: set[str] = set()
    for n, feed in enumerate(feeds):
        fid = feed.get("id") if isinstance(feed, dict) else None
        name = f"лента {fid}" if isinstance(fid, str) else f"лента №{n + 1}"
        problems += [(rule, f"{name}: {text}") for rule, text in feed_problems(feed)]
        if isinstance(fid, str):
            if fid in seen:
                problems.append(("feeds-id", f"{name}: повтор id"))
            seen.add(fid)
    return problems


def interests_problems(value: object, rel: str) -> Problems:
    try:
        interest_words(value, rel)
    except WatchError as exc:
        return [("feeds-json", str(exc).removeprefix(f"{rel}: "))]
    return []


def check_feed_sets(skill: Path) -> list[Issue]:
    """self: наборы лент скилла presets/*-feeds.json (спецификация мониторинга, 2.2)."""
    issues: list[Issue] = []
    for path in sorted(skill.glob("presets/*-feeds.json")):
        rel = path.relative_to(skill).as_posix()
        data, problems = feeds_document(path)
        if data is not None:
            feeds = data.get("feeds")
            if isinstance(feeds, list) and feeds:
                problems += feed_list_problems(feeds)
            else:
                problems.append(("feeds-json", "feeds — непустой список лент"))
            problems += interests_problems(data.get("interests", {}), rel)
        issues += [Issue(rel, rule, text) for rule, text in problems]
    return issues


def skill_feeds(skill: Path) -> list[dict]:
    """Ленты набора скилла для сверки с добавками; набор не читается — пусто (это дело self)."""
    path = skill / WATCH_FEEDS
    data = feeds_document(path)[0] if path.is_file() else None
    feeds = data.get("feeds") if data is not None else None
    return [f for f in feeds if isinstance(f, dict)] if isinstance(feeds, list) else []


def library_feeds_problems(path: Path, rel: str, skill: Path) -> Problems:
    """watch/feeds.json библиотеки: форма 2.3 и набор, который из неё соберёт watch."""
    data, problems = feeds_document(path)
    if data is None:
        return problems
    add = data.get("add", [])
    disable = data.get("disable", [])
    override = data.get("override", {})
    if not isinstance(add, list):
        problems.append(("feeds-json", "add — список лент"))
        add = []
    if not isinstance(disable, list) or not all(isinstance(x, str) for x in disable):
        problems.append(("feeds-json", "disable — список id"))
        disable = []
    if not isinstance(override, dict) or not all(isinstance(v, dict) for v in override.values()):
        problems.append(("feeds-json", "override — объект «id → поля»"))
        override = {}
    problems += interests_problems(data.get("interests", {}), rel)

    # Своя лента проверяется с override, как её увидит watch; id override не меняет.
    for fid, fields in override.items():
        if fields.get("id", fid) != fid:
            problems.append(("feeds-id", f"override {fid}: id не меняется"))
    merged = []
    for item in add:
        fid = item.get("id") if isinstance(item, dict) else None
        if isinstance(fid, str) and fid in override:
            item = {**item, **{k: v for k, v in override[fid].items() if k != "id"}}
        merged.append(item)
    problems += feed_list_problems(merged)

    own = {f.get("id") for f in add if isinstance(f, dict)}
    base = {f["id"]: f for f in skill_feeds(skill)
            if isinstance(f.get("id"), str) and f["id"] not in disable}
    for fid in sorted(x for x in own if isinstance(x, str) and x in base):
        problems.append(("feeds-id", f"лента {fid}: уже есть в {WATCH_FEEDS} скилла — "
                                     "изменить её — override, заменить — disable и add"))
    for fid, fields in override.items():
        if fid in own or fid not in base:
            continue
        before = feed_problems(base[fid])
        after = feed_problems({**base[fid], **{k: v for k, v in fields.items() if k != "id"}})
        problems += [(rule, f"override {fid}: {text}") for rule, text in after
                     if (rule, text) not in before]
    return problems


def check_watch(store: Path, skill: Path = SKILL_DIR) -> list[Issue]:
    """lint --store: watch/ библиотеки. Нет папки — не нарушение: хранилище старше мониторинга."""
    folder = store / WATCH_DIR
    if not folder.is_dir():
        return []
    issues: list[Issue] = []
    rel = f"{WATCH_DIR}/feeds.json"
    if (folder / "feeds.json").is_file():
        issues += [Issue(rel, rule, text)
                   for rule, text in library_feeds_problems(folder / "feeds.json", rel, skill)]
    state = folder / "state.json"
    if state.is_file() and load_state(state)[1]:
        issues.append(Issue(f"{WATCH_DIR}/state.json", "watch-state",
                            f"не JSON формы {{\"version\": {WATCH_VERSION}, \"feeds\": {{…}}}} — "
                            "следующий watch переименует его в state.json.bad-<дата> и начнёт "
                            "как первый запуск"))
    return issues


# --- watch: текст, даты, ключи --------------------------------------------------------------


class _TextParser(HTMLParser):
    """Текст из HTML: без тегов, скриптов и стилей; сущности раскрыты. Блочный тег — граница
    слов, строчный (`<b>`, `<a>`) — нет."""

    HIDDEN = ("script", "style", "template", "noscript")
    INLINE = ("a", "abbr", "b", "code", "em", "i", "mark", "s", "small", "span", "strong", "sub",
              "sup", "u")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.HIDDEN:
            self.hidden += 1
        if tag not in self.INLINE:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.HIDDEN and self.hidden:
            self.hidden -= 1
        if tag not in self.INLINE:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


# Управляющие символы и невидимые знаки направления: в выдержке они прячут текст от человека.
INVISIBLE = {"​", "‌", "‍", "‎", "‏", "⁠", "﻿",
             *map(chr, range(0x202a, 0x202f)), *map(chr, range(0x2066, 0x206a))}


MARKUP_RE = re.compile(r"<[A-Za-z/!]|&(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z]+);")


def plain_text(text: str, limit: int) -> str:
    """Простой текст из заголовка или описания ленты: разметка снята, пробелы схлопнуты.

    Второй проход — для дважды экранированного HTML (`&amp;lt;b&amp;gt;`): ленты так делают,
    и после одного прохода в тексте остались бы теги.
    """
    for _ in range(2):
        if not MARKUP_RE.search(text):
            break
        parser = _TextParser()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    text = "".join(" " if unicodedata.category(ch) == "Cc" or ch in INVISIBLE else ch
                   for ch in text)
    return shorten(" ".join(text.split()), limit)


ISO_DATE_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?"
    r"\s*(Z|[+-]\d{2}(?::?\d{2})?)?", re.IGNORECASE)


def parse_date(text: str) -> datetime | None:
    """Дата RFC 822 (RSS) или ISO 8601 (Atom, карты сайта); без пояса — UTC; иначе None."""
    text = text.strip()
    if not text:
        return None
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        when = None
    if when is None:
        m = ISO_DATE_RE.fullmatch(text)
        if m is None:
            return None
        year, month, day, hour, minute, second, zone = m.groups()
        tz = timezone.utc
        if zone and zone.upper() != "Z":
            digits = zone[1:].replace(":", "")
            offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:] or 0))
            tz = timezone(offset if zone[0] == "+" else -offset)
        try:
            when = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                            int(second or 0), tzinfo=tz)
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def entry_date(text: str, now: datetime) -> datetime | None:
    when = parse_date(text)
    if when is None or when > now + FUTURE_SLACK:
        return None
    return when


def entry_key(link: str, guid: str, feed_id: str) -> str | None:
    """Ключ записи — ссылка как source_key; нет ссылки — id записи ленты."""
    if link:
        return source_key(link)
    if guid:
        return source_key(guid) if re.match(r"(?i)https?://", guid) else f"{feed_id}:{guid}"
    return None


def match_key(key: str) -> str:
    """Ключ для сравнения: без схемы, `www.` и косой черты в конце — одна страница в разных
    лентах пишется то с ними, то без."""
    m = re.match(r"(?i)https?://(?:www\.)?(.*)", key)
    return m.group(1).rstrip("/") if m else key


def title_norm(title: str) -> str:
    return " ".join(re.findall(r"\w+", title.casefold()))


# --- watch: разборщики лент -----------------------------------------------------------------


def local_name(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if local_name(c.tag) == name]


def child_text(el: ET.Element, *names: str) -> str:
    """Текст первого непустого потомка с одним из имён, по порядку имён; вложенная разметка
    (Atom `type="xhtml"`) — текстом."""
    for name in names:
        for c in children(el, name):
            text = "".join(c.itertext()).strip()
            if text:
                return text
    return ""


def probe_body(probe: Probe) -> bytes:
    if probe.error:
        raise FeedError(probe.error)
    if probe.status is None or not 200 <= probe.status < 300:
        raise FeedError(f"HTTP {probe.status}")
    if probe.truncated:
        raise FeedError(f"ответ больше {FEED_BODY_MAX // 2**20} МБ")
    return probe.body


def feed_body(poll: FeedPoll, url: str) -> bytes:
    return probe_body(poll.get(url))


def looks_html(body: bytes) -> bool:
    head = body[:2048].lower()
    return b"<!doctype html" in head or b"<html" in head


def feed_xml(body: bytes, expected: str) -> ET.Element:
    """Корень XML-ленты. Код 200 с HTML — частая ловушка: заглушка SPA или страница вместо
    ленты (research/2026-10-09-sources-check/01-labs.md, DeepSeek, Anthropic)."""
    body = body.lstrip(b"\xef\xbb\xbf \t\r\n")
    # Объявления сущностей ленте не нужны, а раздувание сущностями — известная атака на разбор XML.
    if b"<!ENTITY" in body:
        raise FeedError("не разобралась: XML с объявлением сущностей")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        if looks_html(body):
            raise FeedError(f"не та лента: HTML вместо {expected}") from None
        raise FeedError("не разобралась: не XML") from None
    if local_name(root.tag).lower() == "html":
        raise FeedError(f"не та лента: HTML вместо {expected}")
    return root


def atom_link(entry: ET.Element) -> str:
    links = children(entry, "link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href", "").strip()
    return next((x.get("href", "").strip() for x in links if x.get("href")), "")


def read_rss(poll: FeedPoll) -> list[Entry]:
    """RSS 2.0, RSS 1.0 и Atom. Дата — только у записи: `lastBuildDate` и `updated` канала
    часто равны «сегодня» и новизны не значат."""
    root = feed_xml(feed_body(poll, poll.feed["url"]), "RSS или Atom")
    kind = local_name(root.tag)
    fid = poll.feed["id"]
    entries: list[Entry] = []
    if kind == "feed":
        for item in children(root, "entry"):
            published = child_text(item, "published")
            stamp = published or child_text(item, "updated")
            excerpt = child_text(item, "summary", "content")
            entries.append(make_entry(
                fid, text_title(child_text(item, "title"), excerpt), atom_link(item),
                child_text(item, "id"), entry_date(stamp, poll.now),
                "published" if published else "modified", excerpt))
        return [e for e in entries if e.key]
    if kind == "rss":
        channel = next(iter(children(root, "channel")), None)
        items = children(channel, "item") if channel is not None else []
    elif kind == "RDF":
        items = children(root, "item")
    else:
        raise FeedError(f"не та лента: корень <{kind}>, а не RSS или Atom")
    for item in items:
        # У RSS ссылка — текст <link>; atom:link внутри item — атрибутом.
        link = next((c.text.strip() for c in item if c.tag == "link" and c.text), "") \
            or next((c.text.strip() for c in children(item, "link") if c.text), "")
        guid_el = next(iter(children(item, "guid")), None)
        guid = (guid_el.text or "").strip() if guid_el is not None else ""
        if not link and guid and guid_el is not None \
                and guid_el.get("isPermaLink", "true") != "false":
            link = guid if re.match(r"(?i)https?://", guid) else ""
        excerpt = child_text(item, "description", "encoded")
        entries.append(make_entry(
            fid, text_title(child_text(item, "title"), excerpt), link, guid,
            entry_date(child_text(item, "pubDate", "date"), poll.now), "published", excerpt))
    return [e for e in entries if e.key]


def text_title(title: str, excerpt: str) -> str:
    """Заголовок записи; без него — первая строка текста, как у поста Telegram.

    У RSS профиля Bluesky `<title>` нет вовсе: без заголовка запись не проходит ни фильтр
    интересов, ни склейку дублей по заголовку.
    """
    if plain_text(title, TITLE_MAX_CHARS):
        return title
    line = next((line for line in excerpt.splitlines() if line.strip()), "")
    return plain_text(line, TELEGRAM_TITLE_CHARS)


def make_entry(fid: str, title: str, link: str, guid: str, when: datetime | None, kind: str,
               excerpt: str, title_from_url: bool = False) -> Entry:
    return Entry(key=entry_key(link, guid, fid) or "", title=plain_text(title, TITLE_MAX_CHARS),
                 url=link, when=when, date_kind=kind,
                 excerpt=plain_text(excerpt, EXCERPT_MAX_CHARS), feed=fid,
                 title_from_url=title_from_url)


def title_from_url(url: str) -> str:
    """Заголовок из последней части пути: у карты сайта заголовков нет."""
    segment = next((s for s in reversed(urlsplit(url).path.split("/")) if s), "")
    return re.sub(r"[-_]+", " ", re.sub(r"\.\w{2,5}$", "", segment)).strip() or url


def sitemap_urls(root: ET.Element, poll: FeedPoll) -> list[Entry]:
    """Записи `<urlset>`. `lastmod` — дата правки, а не публикации (`date_kind: modified`);
    у карт Google News есть дата публикации и заголовок — они точнее."""
    entries = []
    for node in children(root, "url"):
        loc = child_text(node, "loc")
        if not loc:
            continue
        news = next(iter(children(node, "news")), None)
        news_date = child_text(news, "publication_date") if news is not None else ""
        news_title = child_text(news, "title") if news is not None else ""
        when = entry_date(news_date or child_text(node, "lastmod"), poll.now)
        entries.append(make_entry(poll.feed["id"], news_title or title_from_url(loc), loc, "",
                                  when, "published" if news_date else "modified", "",
                                  title_from_url=not news_title))
    return entries


def read_sitemap(poll: FeedPoll) -> list[Entry]:
    """Карта сайта или индекс карт. Индекс читается на один уровень: подкарта-индекс не
    раскрывается; подкарта, не менявшаяся с начала окна, не запрашивается."""
    root = feed_xml(feed_body(poll, poll.feed["url"]), "карты сайта")
    kind = local_name(root.tag)
    if kind == "urlset":
        return sitemap_urls(root, poll)
    if kind != "sitemapindex":
        raise FeedError(f"не та лента: корень <{kind}>, а не карта сайта")
    maps = []
    for node in children(root, "sitemap"):
        loc = child_text(node, "loc")
        changed = parse_date(child_text(node, "lastmod"))
        if loc and (changed is None or changed >= poll.since):
            maps.append(loc)
    entries: list[Entry] = []
    for loc in maps[:SITEMAP_CHILDREN_MAX]:
        child = feed_xml(feed_body(poll, loc), "карты сайта")
        if local_name(child.tag) == "urlset":
            entries += sitemap_urls(child, poll)
    return entries


def json_data(body: bytes) -> object:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if looks_html(body):
            raise FeedError("не та лента: HTML вместо JSON") from None
        raise FeedError("не разобралась: не JSON") from None


def json_items(data: object, key: str = "") -> list[dict]:
    """Объекты списка ответа (или списка под ключом key); не объекты пропускаются."""
    items = data.get(key) if key and isinstance(data, dict) else data
    if not isinstance(items, list):
        raise FeedError("не та лента: в JSON нет списка" + (f" {key}" if key else ""))
    return [x for x in items if isinstance(x, dict)]


def text_of(obj: dict, *keys: str) -> str:
    """Первое непустое строковое поле из keys."""
    return next((v.strip() for k in keys if isinstance(v := obj.get(k), str) and v.strip()), "")


def count_of(obj: dict, key: str) -> int:
    value = obj.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def unix_date(value: object, now: datetime) -> datetime | None:
    """Дата из секунд Unix (OpenRouter, HN); дальше суток в будущем — как нет даты."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        when = datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return None if when > now + FUTURE_SLACK else when


def markdown_text(text: str) -> str:
    """Markdown описания выпуска — текстом: ссылки и картинки — их подписью, без маркеров
    заголовков, списков, цитат, жирного и кода."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^[ \t]{0,3}(?:#{1,6}|[*+-]|>)[ \t]+", "", text)
    return re.sub(r"\*\*|__|`", "", text)


def read_github_releases(poll: FeedPoll) -> list[Entry]:
    """Выпуски репозитория через API: releases.atom держит только 10 записей (01-labs.md).
    Черновики пропускаются. Без токена — 60 запросов в час на IP, с GITHUB_TOKEN — 5 000."""
    repo = poll.feed["params"]["repo"]
    probe = poll.get(f"https://{GITHUB_API_HOST}/repos/{repo}/releases"
                     f"?per_page={GITHUB_RELEASES_PER_PAGE}")
    if probe.status in (403, 429):
        raise FeedError(f"HTTP {probe.status} — похоже на лимит API GitHub; GITHUB_TOKEN "
                        "поднимает его")
    short = repo.split("/")[1].casefold()
    entries = []
    for rel in json_items(json_data(probe_body(probe))):
        if rel.get("draft") is True:
            continue
        name = text_of(rel, "name", "tag_name")
        tag = text_of(rel, "tag_name") or name
        # Имя выпуска часто — голая версия: без имени репозитория она в сводке ничего не значит.
        title = name if short in name.casefold() else f"{repo} {name}"
        excerpt = ("пре-релиз. " if rel.get("prerelease") is True else "") \
            + markdown_text(text_of(rel, "body"))
        entries.append(make_entry(
            poll.feed["id"], title, text_of(rel, "html_url"), f"{repo}@{tag}",
            entry_date(text_of(rel, "published_at", "created_at"), poll.now), "published",
            excerpt))
    return [e for e in entries if e.key]


def read_hf_trending(poll: FeedPoll) -> list[Entry]:
    """Модели в тренде Hugging Face, созданные за окно. Только sort=trendingScore: createdAt —
    поток тестовых репозиториев, likes — лидеры за всё время (02-aggregators-telegram.md).
    Модель без даты создания пропускается: по ней не понять, новая ли она."""
    limit = poll.feed.get("params", {}).get("limit") or HF_TRENDING_LIMIT
    query = urlencode({"sort": "trendingScore", "direction": "-1",
                       "limit": min(limit, HF_TRENDING_LIMIT_MAX)})
    body = feed_body(poll, f"https://huggingface.co/api/models?{query}")
    entries = []
    for model in json_items(json_data(body)):
        mid = text_of(model, "id", "modelId")
        when = entry_date(text_of(model, "createdAt"), poll.now)
        if not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", mid) or when is None:
            continue
        about = [text_of(model, "pipeline_tag"), f"лайков {count_of(model, 'likes')}"]
        entries.append(make_entry(poll.feed["id"], mid, f"https://huggingface.co/{mid}", "",
                                  when, "published", " · ".join(x for x in about if x)))
    return entries


def iso_weeks(since: datetime, now: datetime) -> list[str]:
    """Недели ISO окна (`2026-W41`), последние HF_PAPERS_WEEKS_MAX."""
    day = since.astimezone(timezone.utc).date()
    end = now.astimezone(timezone.utc).date()
    day -= timedelta(days=day.weekday())
    weeks = []
    while day <= end:
        year, week, _ = day.isocalendar()
        weeks.append(f"{year}-W{week:02d}")
        day += timedelta(days=7)
    if not weeks:
        year, week, _ = end.isocalendar()
        weeks.append(f"{year}-W{week:02d}")
    return weeks[-HF_PAPERS_WEEKS_MAX:]


def read_hf_papers(poll: FeedPoll) -> list[Entry]:
    """Статьи недели Hugging Face (`?week=ГГГГ-Wнн`) с порогом голосов `params.min_upvotes`.
    `sort=trending` отдаёт статьи прошлых лет, день без параметров с утра — статьи с 1–2
    голосами (02-aggregators-telegram.md). Дата — когда статью принесли в Daily Papers: старая
    статья arXiv, попавшая туда на этой неделе, — новость недели. Ссылка arXiv — для склейки."""
    min_upvotes = poll.feed.get("params", {}).get("min_upvotes", 0)
    entries: list[Entry] = []
    taken: set[str] = set()
    for week in iso_weeks(poll.since, poll.now):
        for item in json_items(json_data(feed_body(
                poll, f"https://huggingface.co/api/daily_papers?week={week}"))):
            paper = item.get("paper") if isinstance(item.get("paper"), dict) else item
            pid = text_of(paper, "id")
            upvotes = count_of(paper, "upvotes")
            if not re.fullmatch(r"[\w.-]+", pid) or pid in taken or upvotes < min_upvotes:
                continue
            taken.add(pid)
            stamp = text_of(paper, "submittedOnDailyAt") or text_of(item, "publishedAt") \
                or text_of(paper, "publishedAt")
            entry = make_entry(poll.feed["id"], text_of(item, "title") or text_of(paper, "title"),
                               f"https://huggingface.co/papers/{pid}", "",
                               entry_date(stamp, poll.now), "published",
                               f"голосов {upvotes}. " + text_of(paper, "summary"))
            if re.fullmatch(r"\d{4}\.\d{4,5}", pid):
                entry.links = (f"https://arxiv.org/abs/{pid}",)
            entries.append(entry)
    return entries


def per_million(price: object) -> str:
    """Цена за токен строкой (`"0.000003"`) — долларами за миллион; нет или отрицательная — ''."""
    try:
        value = float(price) * 1_000_000
    except (TypeError, ValueError):
        return ""
    return f"${value:g}/M" if value >= 0 else ""


def read_openrouter(poll: FeedPoll) -> list[Entry]:
    """Каталог моделей OpenRouter; новое — по `created`, времени появления в каталоге, а не
    выпуска модели. Варианты `:free` и `:batch` — одна модель: склеиваются по `canonical_slug`,
    дата — самого раннего варианта. Модель без `created` пропускается: дата есть всегда."""
    groups: dict[str, list[dict]] = {}
    for model in json_items(json_data(feed_body(poll, "https://openrouter.ai/api/v1/models")),
                            "data"):
        mid = text_of(model, "id")
        if re.fullmatch(r"[\w.-]+/[\w.:-]+", mid):
            groups.setdefault(text_of(model, "canonical_slug") or mid.partition(":")[0],
                              []).append(model)
    entries = []
    for slug, variants in groups.items():
        dates = [d for m in variants if (d := unix_date(m.get("created"), poll.now))]
        if not dates:
            continue
        base = next((m for m in variants if ":" not in m["id"]), variants[0])
        base_id = base["id"].partition(":")[0]
        pricing = base.get("pricing") if isinstance(base.get("pricing"), dict) else {}
        about = []
        if count_of(base, "context_length"):
            about.append(f"контекст {count_of(base, 'context_length')}")
        for label, key in (("вход", "prompt"), ("выход", "completion")):
            if price := per_million(pricing.get(key)):
                about.append(f"{label} {price}")
        tags = sorted({":" + m["id"].partition(":")[2] for m in variants if ":" in m["id"]})
        if tags:
            about.append("варианты " + ", ".join(tags))
        about.append(text_of(base, "description"))
        entries.append(make_entry(poll.feed["id"], text_of(base, "name") or base_id,
                                  f"https://openrouter.ai/{base_id}", slug, min(dates),
                                  "published", ". ".join(x for x in about if x)))
    return entries


def read_hn(poll: FeedPoll) -> list[Entry]:
    """Истории Hacker News через Algolia — по запросу на каждую строку `params.query`, одна
    лента. numericFilters кодируются (urlencode): с голыми `>` и `,` Algolia отвечает 400
    (02-aggregators-telegram.md). Запрос ищет не только по заголовку — ленте нужен фильтр
    интересов. Ключ — внешняя ссылка истории, обсуждение — в выдержке."""
    params = poll.feed["params"]
    min_points = params.get("min_points", 0)
    filters = [f"created_at_i>{int(poll.since.timestamp())}"]
    if min_points:
        filters.insert(0, f"points>={min_points}")
    entries: list[Entry] = []
    taken: set[str] = set()
    for query in as_list(params["query"]):
        url = "https://hn.algolia.com/api/v1/search_by_date?" + urlencode(
            {"query": query, "tags": "story", "numericFilters": ",".join(filters),
             "hitsPerPage": HN_HITS_PER_PAGE})
        for hit in json_items(json_data(feed_body(poll, url)), "hits"):
            oid = str(hit.get("objectID") or "")
            points = count_of(hit, "points")
            if not oid.isdigit() or oid in taken or points < min_points:
                continue
            taken.add(oid)
            thread = f"https://news.ycombinator.com/item?id={oid}"
            link = text_of(hit, "url")
            when = unix_date(hit.get("created_at_i"), poll.now) \
                or entry_date(text_of(hit, "created_at"), poll.now)
            excerpt = (f"HN: очков {points}, комментариев {count_of(hit, 'num_comments')} — "
                       f"{thread}. " + text_of(hit, "story_text"))
            entries.append(make_entry(
                poll.feed["id"], text_of(hit, "title"),
                link if urlsplit(link).scheme in ("http", "https") else thread, "", when,
                "published", excerpt))
    return entries


class _TelegramParser(HTMLParser):
    """Посты веб-превью канала (`t.me/s/<канал>`): `data-post`, текст, внешние ссылки текста и
    `<time datetime>`. Глубина `div` считается: в тексте поста бывают вложенные `div`, и
    обрезка по первому `</div>` теряет текст (02-aggregators-telegram.md, gonzo_ML). Текст
    цитаты из ответа (`js-message_reply_text`) — не текст поста."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict] = []
        self.depth = 0
        self.post_depth = 0
        self.text_depth = 0
        self.post: dict | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr = {k: v or "" for k, v in attrs}
        classes = attr.get("class", "").split()
        if tag == "div":
            self.depth += 1
            if "tgme_widget_message" in classes and attr.get("data-post"):
                self.post = {"post": attr["data-post"], "text": [], "links": [], "time": ""}
                self.posts.append(self.post)
                self.post_depth, self.text_depth = self.depth, 0
            elif (self.post is not None and not self.text_depth
                  and "tgme_widget_message_text" in classes
                  and "js-message_reply_text" not in classes):
                self.text_depth = self.depth
            elif self.text_depth:
                self.post["text"].append("\n")
        if self.post is None:
            return
        if self.text_depth and tag == "br":
            self.post["text"].append("\n")
        if self.text_depth and tag == "a" and attr.get("href"):
            self.post["links"].append(attr["href"])
        if tag == "time" and attr.get("datetime") and not self.post["time"]:
            self.post["time"] = attr["datetime"]

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        if self.text_depth and self.depth == self.text_depth:
            self.text_depth = 0
        elif self.text_depth:
            self.post["text"].append("\n")
        if self.post is not None and self.depth == self.post_depth:
            self.post = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.post is not None and self.text_depth:
            self.post["text"].append(data)


TELEGRAM_HOSTS = ("t.me", "telegram.me", "telegram.org")


def telegram_entry(post: dict, fid: str, now: datetime) -> Entry | None:
    """Запись поста; пост без текста (альбом, медиа) — None."""
    lines = [" ".join(line.split()) for line in "".join(post["text"]).split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        return None
    links = []
    for href in post["links"]:
        parts = urlsplit(href)
        host = (parts.hostname or "").removeprefix("www.")
        if parts.scheme in ("http", "https") and host not in TELEGRAM_HOSTS:
            links.append(href)
    url = f"https://t.me/{post['post']}"
    return Entry(key=source_key(url) or url, title=plain_text(lines[0], TELEGRAM_TITLE_CHARS),
                 url=url, when=entry_date(post["time"], now), date_kind="published",
                 excerpt=plain_text(" ".join(lines), EXCERPT_MAX_CHARS),
                 links=tuple(dict.fromkeys(links)), feed=fid)


def read_telegram(poll: FeedPoll) -> list[Entry]:
    """Канал через веб-превью `t.me/s/<канал>`: листает `?before=<меньший id>`, пока не дойдёт
    до начала окна (прошлый опрос минус сутки), не больше TELEGRAM_PAGES_MAX страниц. Редирект
    на `t.me/<канал>` — у канала нет превью или его нет совсем."""
    channel = poll.feed["params"]["channel"]
    base = f"https://t.me/s/{channel}"
    url = base
    entries: list[Entry] = []
    taken: set[str] = set()
    for _ in range(TELEGRAM_PAGES_MAX):
        probe = poll.get(url)
        if probe.url and not urlsplit(probe.url).path.startswith("/s/"):
            raise FeedError("нет превью: t.me/s/ ведёт на страницу канала")
        parser = _TelegramParser()
        parser.feed(probe_body(probe).decode("utf-8", "replace"))
        parser.close()
        ids, dates = [], []
        for post in parser.posts:
            number = post["post"].rpartition("/")[2]
            if not number.isdigit() or post["post"] in taken:
                continue
            taken.add(post["post"])
            ids.append(int(number))
            if (when := parse_date(post["time"])) is not None:
                dates.append(when)
            if (entry := telegram_entry(post, poll.feed["id"], poll.now)) is not None:
                entries.append(entry)
        if not ids or not dates or min(dates) < poll.since:
            break
        url = f"{base}?before={min(ids)}"
    return entries


class _LinesParser(HTMLParser):
    """Строки текста страницы: блочный тег — граница строки; скрипты, стили, меню, подвал и
    боковые панели — мимо (их смена — не новость)."""

    SKIP = _TextParser.HIDDEN + ("nav", "footer", "aside", "svg", "button", "select")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.hidden += 1
        if tag not in _TextParser.INLINE:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.hidden:
            self.hidden -= 1
        if tag not in _TextParser.INLINE:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def page_lines(body: bytes) -> list[str]:
    """Содержательные строки страницы по порядку, не больше PAGE_LINES_MAX."""
    parser = _LinesParser()
    parser.feed(body.decode("utf-8", "replace"))
    parser.close()
    lines = (plain_text(line, LINE_MAX_CHARS) for line in "".join(parser.parts).split("\n"))
    return [line for line in lines if len(line) >= PAGE_LINE_MIN_CHARS][:PAGE_LINES_MAX]


def line_hash(line: str) -> str:
    return hashlib.blake2b(line.encode("utf-8"), digest_size=8).hexdigest()


def read_page(poll: FeedPoll) -> list[Entry]:
    """Страница без ленты: новое — строки, которых не было в прошлом снимке; подряд идущие
    новые строки — одна запись (первая — заголовок). Снимок — хеши строк в состоянии ленты
    (`page_lines`): сам текст раздувал бы state.json. Первый опрос только запоминает снимок.
    Даты у строки нет — запись получает время опроса (`date_kind: polled`)."""
    url = poll.feed["url"]
    lines = page_lines(feed_body(poll, url))
    if not lines:
        raise FeedError("не та лента: на странице нет текста (нужен JavaScript?)")
    hashes = [line_hash(line) for line in lines]
    before = poll.state.get("page_lines")
    poll.state["page_lines"] = list(dict.fromkeys(hashes))
    if not isinstance(before, list):
        return []
    old = set(before)
    blocks: list[list[str]] = []
    fresh = False
    for line, digest in zip(lines, hashes):
        if digest in old:
            fresh = False
            continue
        if fresh:
            blocks[-1].append(line)
        else:
            blocks.append([line])
        fresh = True
    page = source_key(url) or url
    return [Entry(key=f"{page}#{line_hash(block[0])}", title=shorten(block[0], TITLE_MAX_CHARS),
                  url=url, when=None, date_kind="polled",
                  excerpt=shorten(" ".join(block[1:]), EXCERPT_MAX_CHARS), feed=poll.feed["id"])
            for block in blocks]


# Разборщик на тип: новый тип — функция и строка здесь (спецификация мониторинга, 3.2); тест
# сверяет, что у каждого типа FEED_TYPES разборщик есть.
FEED_READERS: dict[str, Callable[[FeedPoll], list[Entry]]] = {
    "rss": read_rss,
    "sitemap": read_sitemap,
    "github_releases": read_github_releases,
    "hf_trending": read_hf_trending,
    "hf_papers": read_hf_papers,
    "openrouter": read_openrouter,
    "hn": read_hn,
    "telegram": read_telegram,
    "page": read_page,
}


# --- watch: опрос, отбор, склейка -----------------------------------------------------------


def feed_headers(feed: dict) -> dict[str, str]:
    return {"User-Agent": BROWSER_UA if feed.get("ua") == "browser" else WATCH_UA}


def request_headers(headers: Mapping[str, str], url: str, token: str) -> dict[str, str]:
    """Заголовки одного запроса. Токен GitHub — только к api.github.com по https: ни другому
    хосту, ни по открытому каналу он не уходит."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != GITHUB_API_HOST:
        return dict(headers)
    extra = {"Accept": "application/vnd.github+json"}
    if token:
        extra["Authorization"] = f"Bearer {token}"
    return {**headers, **extra}


def github_token(environ: Mapping[str, str]) -> str:
    return (environ.get("GITHUB_TOKEN") or environ.get("GH_TOKEN") or "").strip()


def feed_host(feed: dict) -> str:
    if feed["type"] in PARAM_FEEDS:
        return PARAM_FEEDS[feed["type"]][0]
    return urlsplit(feed.get("url", "")).hostname or feed["type"]


class HostPace:
    """Пауза между запросами к одному хосту: от конца прошлого запроса до начала следующего —
    не меньше interval секунд. sleep подменяется в тестах."""

    def __init__(self, interval: float, sleep: Callable[[float], None]) -> None:
        self.interval = interval
        self.sleep = sleep
        self.last: float | None = None

    def call(self, request: Callable[[], Probe]) -> Probe:
        if self.interval and self.last is not None:
            left = self.last + self.interval - time.monotonic()
            if left > 0:
                self.sleep(left)
        try:
            return request()
        finally:
            self.last = time.monotonic()


def feed_since(state: dict, since: datetime | None, now: datetime) -> datetime:
    if since is not None:
        return since
    last = parse_date(state.get("last_ok", ""))
    if last is not None:
        return last - WATCH_OVERLAP
    return now - timedelta(days=WATCH_FIRST_DAYS)


def poll_feed(feed: dict, fetch: FeedFetch, since: datetime, now: datetime,
              state: dict, token: str = "") -> FeedOutcome:
    reader = FEED_READERS[feed["type"]]
    headers = feed_headers(feed)
    poll = FeedPoll(feed, lambda url: fetch(url, request_headers(headers, url, token)), since,
                    now, state)
    try:
        return FeedOutcome(reader(poll))
    except FeedError as exc:
        return FeedOutcome(error=str(exc))
    except Exception as exc:  # noqa: BLE001  сбой разбора одной ленты не ломает запуск
        return FeedOutcome(error=f"не разобралась: {type(exc).__name__}")


def poll_feeds(feeds: list[dict], fetch: FeedFetch, windows: dict[str, datetime],
               now: datetime, states: dict[str, dict], token: str = "",
               sleep: Callable[[float], None] = time.sleep) -> dict[str, FeedOutcome]:
    """Опрос параллельно по хостам: ленты одного хоста — по очереди, чтобы не бить сайт
    одновременными запросами, а между запросами к хосту — пауза `min_interval` (наибольшая у
    его лент: arXiv просит 3 с, Reddit — минуту)."""
    by_host: dict[str, list[dict]] = {}
    for feed in feeds:
        by_host.setdefault(feed_host(feed), []).append(feed)

    def run_host(group: list[dict]) -> list[tuple[str, FeedOutcome]]:
        pace = HostPace(max(f.get("min_interval", 0) for f in group), sleep)

        def paced(url: str, headers: Mapping[str, str]) -> Probe:
            return pace.call(lambda: fetch(url, headers))

        return [(f["id"], poll_feed(f, paced, windows[f["id"]], now,
                                    states.get(f["id"]) or new_feed_state(), token))
                for f in group]

    outcomes: dict[str, FeedOutcome] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(FEED_WORKERS, len(by_host)))) as pool:
        for pairs in pool.map(run_host, by_host.values()):
            outcomes.update(pairs)
    return outcomes


def match_entry(feed: dict, entry: Entry) -> bool:
    match = feed.get("match", {})
    paths = as_list(match.get("path", []))
    if paths and not any(urlsplit(entry.url).path.startswith(p) for p in paths):
        return False
    titles = [t.casefold() for t in as_list(match.get("title", []))]
    if titles and not any(entry.title.casefold().startswith(t) for t in titles):
        return False
    text = f"{entry.url} {entry.title}".casefold()
    return not any(x.casefold() in text for x in as_list(match.get("exclude", [])))


def fresh_entries(feed: dict, entries: list[Entry], since: datetime, seen: set[str],
                  first_run: bool) -> tuple[list[Entry], list[str]]:
    """Новое ленты и ключи для её `seen`.

    Отбрасывается: не прошедшее `match`, старше окна, повтор внутри ленты, виденное любой
    лентой. Запись без даты при первом опросе ленты только запоминается: иначе лента без дат
    выдала бы всю свою историю как новое.
    """
    fresh: list[Entry] = []
    keys: list[str] = []
    taken: set[str] = set()
    for entry in entries:
        if not match_entry(feed, entry):
            continue
        if entry.when is not None and entry.when < since:
            continue
        mk = match_key(entry.key)
        if mk in taken:
            continue
        taken.add(mk)
        keys.append(entry.key)
        if mk in seen or (entry.when is None and first_run):
            continue
        fresh.append(entry)
    return fresh, keys


def merge_groups(entries: list[Entry]) -> list[list[Entry]]:
    """Дубли между лентами: один ключ; внешняя ссылка поста — ключ другой записи; один
    содержательный заголовок у разных лент."""
    parent = list(range(len(entries)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    by_key: dict[str, int] = {}
    by_title: dict[str, dict[str, int]] = {}
    for i, entry in enumerate(entries):
        mk = match_key(entry.key)
        if mk in by_key:
            union(i, by_key[mk])
        else:
            by_key[mk] = i
        norm = title_norm(entry.title)
        if (not entry.title_from_url and len(norm.split()) >= TITLE_MERGE_MIN_WORDS
                and len(norm) >= TITLE_MERGE_MIN_CHARS):
            per_feed = by_title.setdefault(norm, {})
            if entry.feed not in per_feed:
                for j in per_feed.values():
                    union(i, j)
                per_feed[entry.feed] = i
    for i, entry in enumerate(entries):
        for link in entry.links:
            j = by_key.get(match_key(source_key(link) or link))
            if j is not None:
                union(i, j)
    groups: dict[int, list[Entry]] = {}
    for i, entry in enumerate(entries):
        groups.setdefault(find(i), []).append(entry)
    return list(groups.values())


def topic_names(library: Path) -> dict[str, list[re.Pattern]]:
    """Имена тем библиотеки для пометки новостей: `aliases` карточки и имена из «Объекты».

    Архивные темы не берутся: агент в архив не смотрит. Имя ищется целым словом без учёта
    регистра.
    """
    names: dict[str, list[re.Pattern]] = {}
    for card in load_cards(library):
        if card.fields is None or card.archived:
            continue
        found = flat_list(card.fields.get("aliases", ""))
        lines = card_lines(read(card.path))
        span = section(lines, "Объекты")
        if span is not None:
            for line in lines[span[0] + 1:span[1]]:
                cells = table_cells(line)
                if cells and not is_separator(cells) and cells[0] != "имя":
                    found.append(cells[0])
        words = {w.strip().casefold() for w in found}
        names[card.slug] = [re.compile(rf"(?<!\w){re.escape(w)}(?!\w)") for w in sorted(words)
                            if len(w) >= TOPIC_NAME_MIN_CHARS]
    return {slug: pats for slug, pats in names.items() if pats}


def make_record(group: list[Entry], feeds: dict[str, dict], order: dict[str, int],
                interests: dict[str, list[str]], now: datetime,
                topics: dict[str, list[re.Pattern]] | None = None) -> dict | None:
    """Запись склейки или None, если ни интересы, ни темы библиотеки её не пропустили.

    Ссылка и дата — у самой ранней записи первоисточника (`labs`, `releases`), иначе у самой
    ранней вообще; `first_feed` — лента самой ранней записи. Запись без даты — как опрошенная
    сейчас. Новость о предмете темы проходит фильтр и без слов интересов: она может сделать
    тему устаревшей.
    """
    group = sorted(group, key=lambda e: (e.when or now, order[e.feed]))
    primary = [e for e in group if feeds[e.feed]["group"] in PRIMARY_GROUPS]
    rep = (primary or group)[0]
    ids = list(dict.fromkeys(e.feed for e in group))
    text = " ".join(f"{e.title} {e.excerpt}" for e in group).casefold()
    matched = [g for g, words in interests.items() if any(w.casefold() in text for w in words)]
    hit = [slug for slug, pats in (topics or {}).items() if any(p.search(text) for p in pats)]
    if not matched and not hit and all(feeds[f]["filter"] != "always" for f in ids):
        return None
    when = (rep.when or now).astimezone(now.tzinfo)
    record = {
        "key": rep.key,
        "title": rep.title,
        "url": rep.url,
        "date": when.date().isoformat(),
        "date_kind": rep.date_kind if rep.when is not None else "polled",
        "group": feeds[rep.feed]["group"],
        "feeds": ids,
        "first_feed": group[0].feed,
        "interests": matched,
        "topics": hit,
        "excerpt": rep.excerpt or next((e.excerpt for e in group if e.excerpt), ""),
        "trial": all(feeds[f].get("trial") is True for f in ids),
    }
    return record


def sort_records(records: list[dict]) -> None:
    """labs и releases, затем по числу лент, затем новее раньше (сортировка устойчивая)."""
    records.sort(key=lambda r: r["title"])
    records.sort(key=lambda r: r["date"], reverse=True)
    records.sort(key=lambda r: (PRIMARY_GROUPS.index(r["group"]) if r["group"] in PRIMARY_GROUPS
                                else len(PRIMARY_GROUPS), -len(r["feeds"])))


def watch(skill: Path, library: Path, fetch: FeedFetch = feed_fetch, now: datetime | None = None,
          only: str | None = None, since: date | None = None, dry_run: bool = False,
          environ: Mapping[str, str] | None = None,
          sleep: Callable[[float], None] = time.sleep) -> WatchRun:
    """Запуск watch (спецификация мониторинга, 3.3). Ошибка вызова — WatchError.

    environ — откуда взять GITHUB_TOKEN (как у doctor); sleep — пауза min_interval.
    """
    now = now or datetime.now().astimezone()
    if not library.is_dir():
        raise WatchError(f"папки библиотеки нет: {library}")
    feed_set = load_feed_set(skill, library)
    feeds = select_feeds(feed_set.feeds, only)
    notes = list(feed_set.notes)
    day = now.date().isoformat()
    folder = library / WATCH_DIR
    state_path = folder / "state.json"
    states, broken = load_state(state_path)
    if broken:
        if dry_run:
            notes.append("state.json битый — запуск как первый; без --dry-run файл будет "
                         f"переименован в state.json.bad-{day}")
        else:
            os.replace(state_path, folder / f"state.json.bad-{day}")
            notes.append(f"state.json битый — переименован в state.json.bad-{day}, запуск как "
                         "первый")

    start = datetime.combine(since, datetime.min.time(), now.tzinfo) if since else None
    windows = {f["id"]: feed_since(states.get(f["id"], {}), start, now) for f in feeds}
    seen = {match_key(k) for state in states.values() for k in state["seen"]}
    first_run = {f["id"]: not states.get(f["id"], {}).get("last_ok") for f in feeds}
    # Состояние заводится до опроса: разборщик может хранить в нём своё.
    for feed in feeds:
        states.setdefault(feed["id"], new_feed_state())
    outcomes = poll_feeds(feeds, fetch, windows, now, states, github_token(environ or {}),
                          sleep)

    fresh: list[Entry] = []
    seen_keys: dict[str, list[str]] = {}
    for feed in feeds:
        outcome = outcomes[feed["id"]]
        if outcome.entries is None:
            continue
        found, keys = fresh_entries(feed, outcome.entries, windows[feed["id"]], seen,
                                    first_run[feed["id"]])
        fresh += found
        seen_keys[feed["id"]] = keys

    by_id = {f["id"]: f for f in feeds}
    order = {f["id"]: n for n, f in enumerate(feeds)}
    topics = topic_names(library)
    records = [r for g in merge_groups(fresh)
               if (r := make_record(g, by_id, order, feed_set.interests, now, topics))
               is not None]
    sort_records(records)

    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    failed: list[tuple[str, str]] = []
    for feed in feeds:
        fid = feed["id"]
        outcome = outcomes[fid]
        state = states[fid]
        if outcome.error:
            state["fails"] += 1
            state["last_error"] = outcome.error
            mark = (f" ×{state['fails']} подряд — проверить или отключить"
                    if state["fails"] >= FEED_FAILS_MARK else "")
            failed.append((fid, outcome.error + mark))
            continue
        keys = seen_keys[fid]
        taken = {match_key(k) for k in keys}
        state.update(last_ok=stamp, fails=0, last_error="",
                     seen=(keys + [k for k in state["seen"] if match_key(k) not in taken])
                     [:SEEN_MAX])
        state["runs"] += 1
    for record in records:
        for fid in record["feeds"]:
            states[fid]["new"] += 1
        states[record["first_feed"]]["first"] += 1
        if len(record["feeds"]) == 1:
            states[record["feeds"][0]]["unique"] += 1
    idle = [f["id"] for f in feeds if f.get("trial") is True
            and states[f["id"]]["runs"] >= TRIAL_RUNS_MARK and states[f["id"]]["unique"] == 0]

    path = None
    if not dry_run:
        path = folder / "new" / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Пустой файл тоже пишется: он значит, что запуск сегодня был (сценарий «что нового»).
        with path.open("a", encoding="utf-8") as out:
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
        write_json_atomic(state_path, {"version": WATCH_VERSION, "feeds": states})
    return WatchRun(day, records, len(feeds), failed, notes, path, idle)


# --- watch: вывод ---------------------------------------------------------------------------


def capped_join(prefix: str, items: list[str], limit: int) -> str:
    """Список через запятую не длиннее limit; не влезшее — «… ещё N»."""
    if len(prefix + ", ".join(items)) <= limit:
        return prefix + ", ".join(items)
    shown: list[str] = []
    for item in items:
        rest = TAIL.format(len(items) - len(shown) - 1)
        if len(prefix + ", ".join([*shown, item, rest])) > limit:
            break
        shown.append(item)
    return prefix + ", ".join([*shown, TAIL.format(len(items) - len(shown))])


def record_line(record: dict) -> str:
    title = shorten(record["title"], WATCH_TITLE_CHARS)
    line = f"{record['date']}  {record['group']:<11} {title:<{WATCH_TITLE_CHARS}} " \
           f"{record['url'] or record['key']}"
    if len(record["feeds"]) > 1:
        line += f"  ×{len(record['feeds'])}"
    if record["interests"]:
        line += "  " + ",".join(record["interests"])
    if record["topics"]:
        line += "  тема: " + ",".join(record["topics"])
    if record["trial"]:
        line += "  на пробу"
    return line


def watch_summary(run: WatchRun) -> tuple[str, list[str]]:
    """Шапка и подвал сводки: что найдено по группам, кто не ответил, где файл."""
    counts = Counter(r["group"] for r in run.records)
    groups = ", ".join(f"{g} {counts[g]}" for g in FEED_GROUPS if counts[g])
    head = (f"watch: {run.day} — новых {len(run.records)}" + (f" ({groups})" if groups else "")
            + f"; лент {run.feeds}, не ответили {len(run.failed)}")
    foot = []
    if run.failed:
        foot.append(capped_join("не ответили: ", [f"{fid} ({why})" for fid, why in run.failed],
                                WATCH_FAILED_CHARS))
    if run.idle_trials:
        suffix = " — предложить отключить"
        foot.append(capped_join(f"на пробу без своего за {TRIAL_RUNS_MARK} запусков: ",
                                run.idle_trials, WATCH_FAILED_CHARS - len(suffix)) + suffix)
    foot += [shorten(n, LINE_MAX_CHARS) for n in run.notes]
    foot.append(f"найденное: {run.path}" if run.path is not None
                else "найденное не записано: --dry-run")
    return head, foot


def watch_text(run: WatchRun) -> str:
    """Сводка не длиннее OUTPUT_MAX_CHARS: шапка, записи по порядку, хвост, подвал."""
    head, foot = watch_summary(run)
    more = TAIL + " — полный список в файле найденного"
    reserve = len(head) + sum(len(x) + 1 for x in foot) + len(more.format(len(run.records))) + 1
    lines, omitted = fit_lines([record_line(r) for r in run.records], OUTPUT_MAX_CHARS - reserve)
    if omitted:
        lines.append(more.format(omitted))
    return "\n".join([head, *lines, *foot])


def watch_json(run: WatchRun) -> str:
    """Найденное строками JSON в пределах OUTPUT_MAX_CHARS. Не влезшее — последней строкой
    `{"omitted": N}`: так вывод остаётся JSONL, а полный список — в файле."""
    lines = [json.dumps(r, ensure_ascii=False) for r in run.records]
    tail = json.dumps({"omitted": len(lines)})
    shown: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > OUTPUT_MAX_CHARS - len(tail) - 1:
            break
        shown.append(line)
        size += len(line) + 1
    if len(shown) < len(lines):
        shown.append(json.dumps({"omitted": len(lines) - len(shown)}))
    return "\n".join(shown)


def run_watch(skill: Path, library: Path | None, only: str | None, since_text: str | None,
              dry_run: bool, as_json: bool) -> int:
    """Код 0, даже если часть лент не ответила; 2 — ошибка вызова."""
    if library is None and os.environ.get(LIBRARY_VAR):
        library = Path(os.environ[LIBRARY_VAR])
    if library is None:
        print(f"watch: библиотеки нет — --library <путь> или {LIBRARY_VAR}", file=sys.stderr)
        return 2
    since = None
    if since_text is not None:
        since = valid_date(since_text)
        if since is None:
            print(f"watch: --since {since_text} — нужна дата ГГГГ-ММ-ДД", file=sys.stderr)
            return 2
    try:
        run = watch(skill, library.expanduser(), only=only, since=since, dry_run=dry_run,
                    environ=os.environ)
    except WatchError as exc:
        print(f"watch: {exc}", file=sys.stderr)
        return 2
    if as_json:
        head, foot = watch_summary(run)
        if run.records:
            print(watch_json(run))
        print("\n".join([head, *foot]), file=sys.stderr)
    else:
        print(watch_text(run))
    return 0


# --- facts: сводка о репозитории или пакете -------------------------------------------------


class FactsError(Exception):
    """Ошибка вызова facts: код 2 и текст для человека."""


class SourceError(Exception):
    """Источник не ответил или прислал не то: причина — для строки «не ответили»."""


# fetch(метод, адрес, тело, заголовки) — запрос facts; подменяется в тестах, как Fetch у doctor.
FactsFetch = Callable[[str, str, bytes | None, Mapping[str, str]], Probe]


def facts_fetch(method: str, url: str, data: bytes | None, headers: Mapping[str, str]) -> Probe:
    return http_request(method, url, data, headers, timeout=FACTS_TIMEOUT, limit=FACTS_BODY_MAX)


@dataclass
class Target:
    """Цель facts: репозиторий (хостинг, хост, путь) или пакет (система, имя, версия)."""
    kind: str
    forge: str = ""
    host: str = ""
    path: str = ""
    system: str = ""
    name: str = ""
    version: str = ""

    def label(self) -> str:
        if self.kind == "repo":
            return f"{self.host}/{self.path}"
        return f"pkg:{self.system}/{self.name}" + (f"@{self.version}" if self.version else "")

    def short(self) -> str:
        """Имя без владельца и области: по нему ищут endoflife.date и Repology."""
        if self.kind == "repo":
            return self.path.rsplit("/", 1)[-1].lower()
        return self.name.lower().lstrip("@").replace("/", "-")


@dataclass
class Fact:
    """Строка сводки. value None — поле пустое: источник ответил, что такого нет."""
    field: str
    value: str | None
    source: str
    path: str


@dataclass
class FactsRun:
    target: str
    day: str
    facts: list[Fact]
    failed: list[tuple[str, str]]


SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]+")
PYPI_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
NPM_NAME_RE = re.compile(r"(?:@[A-Za-z0-9~][\w.~-]*/)?[A-Za-z0-9~][\w.~-]*")
VERSION_RE = re.compile(r"[A-Za-z0-9][\w.+!-]*")
FORGE_TITLES = {"github": "GitHub", "gitlab": "GitLab", "gitea": "Forgejo/Gitea", "gitee": "Gitee"}


def unknown_target(text: str) -> FactsError:
    return FactsError(f"цель не распознана: «{shorten(text, 100)}» — примеры: "
                      + ", ".join(FACTS_EXAMPLES))


def parse_purl(text: str) -> Target:
    """purl пакета: `pkg:pypi/requests`, `pkg:npm/%40types/node@20.1.0`; квалификаторы и
    подпуть отбрасываются."""
    body = re.split(r"[?#]", text[4:], maxsplit=1)[0]
    kind, _, rest = body.partition("/")
    kind = kind.lower()
    if kind not in PURL_SYSTEMS:
        raise FactsError(f"purl типа «{shorten(kind, 30)}» не поддержан — только "
                         + ", ".join(f"pkg:{k}/…" for k in PURL_SYSTEMS)
                         + "; примеры: " + ", ".join(FACTS_EXAMPLES))
    # Версия — после последней «@», если та стоит после «/»: ведущая «@» — область npm.
    at = rest.rfind("@")
    has_version = at > 0 and at > rest.rfind("/")
    name = unquote(rest[:at] if has_version else rest)
    version = unquote(rest[at + 1:]) if has_version else ""
    pattern = PYPI_NAME_RE if kind == "pypi" else NPM_NAME_RE
    if not pattern.fullmatch(name) or (has_version and not VERSION_RE.fullmatch(version)):
        raise unknown_target(text)
    if kind == "pypi":
        # Имя PyPI по PEP 503: так его знают deps.dev, OSV и ecosyste.ms.
        name = re.sub(r"[-_.]+", "-", name).lower()
    return Target("package", system=kind, name=name, version=version)


def parse_repo_url(text: str) -> Target | None:
    """Ссылка на репозиторий, со схемой или без; лишнее после пути проекта отбрасывается."""
    parts = urlsplit(text if "://" in text else f"https://{text}")
    try:
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    hostname = parts.hostname.lower().removeprefix("www.")
    host = hostname + (f":{port}" if port else "")
    forge = FORGE_HOSTS.get(hostname) or ("gitlab" if "gitlab" in hostname else "gitea")
    segments = [s for s in parts.path.split("/") if s]
    if "-" in segments:
        # GitLab: /-/tree/…, /-/issues — служебная часть после пути проекта.
        segments = segments[:segments.index("-")]
    if forge != "gitlab":
        # У GitLab путь — группы и подгруппы; у остальных — владелец и имя.
        segments = segments[:2]
    if segments:
        segments[-1] = segments[-1].removesuffix(".git")
    if len(segments) < 2 or not all(SEGMENT_RE.fullmatch(s) for s in segments):
        return None
    return Target("repo", forge=forge, host=host, path="/".join(segments))


def parse_target(text: str) -> Target:
    """Цель facts. Нераспознанная — FactsError с примерами."""
    text = text.strip()
    if text.lower().startswith("pkg:"):
        return parse_purl(text)
    first = text.split("/", 1)[0]
    target = None
    if "://" in text or ("." in first and text.count("/") >= 2):
        target = parse_repo_url(text)
    elif GITHUB_REPO_RE.fullmatch(text) and "." not in first:
        target = Target("repo", forge="github", host="github.com",
                        path=text.removesuffix(".git"))
    if target is None:
        raise unknown_target(text)
    return target


@dataclass
class FactsQuery:
    """Запросы источников. Токен GitHub — только к его API (request_headers)."""
    fetch: FactsFetch
    token: str

    def json(self, url: str, payload: dict | None = None) -> object | None:
        """Ответ JSON; None — 404: такого объекта нет, поле пустое, а не ошибка."""
        headers = {"User-Agent": FACTS_UA}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        probe = self.fetch("GET" if data is None else "POST", url, data,
                           request_headers(headers, url, self.token))
        if probe.error:
            raise SourceError(probe.error)
        if probe.status == 404:
            return None
        if probe.status in (403, 429) and urlsplit(url).hostname == GITHUB_API_HOST:
            raise SourceError(f"HTTP {probe.status} — похоже на лимит API GitHub; GITHUB_TOKEN "
                              "поднимает его")
        if probe.status is None or not 200 <= probe.status < 300:
            raise SourceError(f"HTTP {probe.status}")
        if probe.truncated:
            raise SourceError(f"ответ больше {FACTS_BODY_MAX // 2**20} МБ")
        try:
            return json.loads(probe.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SourceError("не JSON") from None


# Источник дописывает строки в out по мере ответов: упал второй запрос — первые строки остаются.
FactsJob = tuple[str, Callable[[FactsQuery, list[Fact]], None]]

PATH_TOKEN_RE = re.compile(r"\[(\d+)\]|([^.\[\]]+)")


def dig(data: object, path: str) -> object:
    """Значение по пути вида `[0].commit.committer.date`; нет — None."""
    for index, key in PATH_TOKEN_RE.findall(path):
        if index:
            data = data[int(index)] if isinstance(data, list) and len(data) > int(index) else None
        else:
            data = data.get(key) if isinstance(data, dict) else None
    return data


def present(value: object) -> str | None:
    """Значение поля строкой: да/нет, список через запятую; пустое — None."""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if isinstance(v, (str, int, float)))
    if value is None or isinstance(value, dict):
        return None
    return str(value).strip() or None


def iso_day(value: object) -> str:
    return value[:10] if isinstance(value, str) and re.match(DATE, value) else ""


def fact(field: str, value: object, source: str, path: str) -> Fact:
    """Строка сводки. Значение — из чужого ответа: это данные, поэтому — простой строкой без
    «|», которая разорвала бы столбцы."""
    text = present(value)
    if text is not None:
        text = plain_text(text, FACT_VALUE_CHARS).replace("|", "/")
    return Fact(field, text, source, path)


def dict_items(data: object, key: str = "") -> list[dict]:
    items = data.get(key) if key and isinstance(data, dict) else data
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def forge_api(t: Target) -> str:
    if t.forge == "github":
        return f"https://{GITHUB_API_HOST}/repos/{t.path}"
    if t.forge == "gitlab":
        return f"https://{t.host}/api/v4/projects/{quote(t.path, safe='')}"
    if t.forge == "gitee":
        return f"https://{t.host}/api/v5/repos/{t.path}"
    return f"https://{t.host}/api/v1/repos/{t.path}"


# Пути полей в ответе о репозитории: лицензия и звёзды у хостингов называются по-разному.
FORGE_FIELDS = {
    "github": ("license.spdx_id", "stargazers_count"),
    "gitee": ("license", "stargazers_count"),
    "gitlab": ("license.key", "star_count"),
    "gitea": ("licenses", "stars_count"),
}


def hosting_repo(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    url = forge_api(t) + ("?license=true" if t.forge == "gitlab" else "")
    data = q.json(url)
    if data is None:
        out.append(fact("license", None, url, "HTTP 404"))
        return
    if not isinstance(data, dict):
        raise SourceError("не тот ответ: нет объекта репозитория")
    license_path, stars_path = FORGE_FIELDS[t.forge]
    license_name = present(dig(data, license_path))
    if license_name == "NOASSERTION":
        license_name += " — нестандартная, читать сам файл"
    for key, value, path in (("license", license_name, license_path),
                             ("archived", dig(data, "archived"), "archived"),
                             ("stars", dig(data, stars_path), stars_path)):
        # Поле, которого хостинг не отдаёт (archived у Gitee), не выводится.
        if present(value) is not None:
            out.append(fact(key, value, url, path))


def hosting_release(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    if t.forge == "gitlab":
        url, prefix = forge_api(t) + "/releases?per_page=1", "[0]."
    else:
        url, prefix = forge_api(t) + "/releases/latest", ""
    when = {"gitlab": "released_at", "gitee": "created_at"}.get(t.forge, "published_at")
    data = q.json(url)
    tag = present(dig(data, prefix + "tag_name"))
    if tag is None:
        out.append(fact("last_release", None, url, "HTTP 404" if data is None else "нет выпусков"))
        return
    day = iso_day(dig(data, prefix + when))
    out.append(fact("last_release", f"{tag} ({day})" if day else tag, url,
                    f"{prefix}tag_name, {prefix}{when}"))


def hosting_commit(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    if t.forge == "gitlab":
        url, path = forge_api(t) + "/repository/commits?per_page=1", "[0].committed_date"
    elif t.forge == "gitea":
        url = forge_api(t) + "/commits?limit=1&stat=false&verification=false&files=false"
        path = "[0].commit.committer.date"
    else:
        url, path = forge_api(t) + "/commits?per_page=1", "[0].commit.committer.date"
    data = q.json(url)
    day = iso_day(dig(data, path))
    if not day:
        path = "HTTP 404" if data is None else "нет коммитов"
    out.append(fact("last_commit", day or None, url, path))


def scorecard(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    url = f"https://api.securityscorecards.dev/projects/github.com/{t.path}"
    data = q.json(url)
    score = present(dig(data, "score"))
    if score is None:
        out.append(fact("scorecard", None, url, "HTTP 404" if data is None else "нет оценки"))
        return
    maintained = next((present(c.get("score")) for c in dict_items(data, "checks")
                       if c.get("name") == "Maintained"), None)
    value = f"{score} из 10 ({iso_day(dig(data, 'date'))})"
    out.append(fact("scorecard", value + (f"; Maintained {maintained} из 10" if maintained else ""),
                    url, "score, date, checks[Maintained].score"))


def depsdev_link(t: Target, linked: list[Target], q: FactsQuery, out: list[Fact]) -> None:
    """Пакет репозитория по deps.dev. Кандидатов бывает много — среди них пакеты-подделки со
    ссылкой на чужой репозиторий: выше подтверждённая связь, затем имя как у репозитория,
    затем число версий."""
    key = f"{t.host}/{t.path}".lower()
    url = f"https://api.deps.dev/v3/projects/{quote(key, safe='')}:packageversions"
    data = q.json(url)
    path = "versions[].versionKey, relationProvenance"
    if data is None:
        out.append(fact("package", None, url, "HTTP 404"))
        return
    found: dict[tuple[str, str], list] = {}
    for item in dict_items(data, "versions"):
        system = str(dig(item, "versionKey.system") or "").lower()
        name = dig(item, "versionKey.name")
        if system not in PURL_SYSTEMS or not isinstance(name, str):
            continue
        entry = found.setdefault((system, name), [False, 0])
        entry[0] |= item.get("relationProvenance") not in (None, "", "UNVERIFIED_METADATA")
        entry[1] += 1
    short = t.short()
    if not found:
        if depsdev_by_name(t, key, linked, q, out):
            return
        clipped = len(dict_items(data, "versions")) >= DEPSDEV_LIST_CAP
        out.append(fact("package", None, url, path + " — пакет " + ", ".join(PURL_SYSTEMS)
                        + " не найден" + (f"; список обрезан на {DEPSDEV_LIST_CAP}" if clipped
                                          else "")))
        return
    (system, name), (verified, _) = max(
        found.items(), key=lambda kv: (kv[1][0], kv[0][1].lower() == short, kv[1][1]))
    value = f"pkg:{system}/{name}" + ("" if verified else ", связь не подтверждена") \
        + (f", других кандидатов {len(found) - 1}" if len(found) > 1 else "")
    out.append(fact("package", value, url, path))
    linked.append(Target("package", system=system, name=name))


def depsdev_by_name(t: Target, key: str, linked: list[Target], q: FactsQuery,
                    out: list[Fact]) -> bool:
    """Обратный путь: пакет с именем репозитория, чья версия по умолчанию ссылается на этот же
    репозиторий. Одно имя без ссылки — не связь: пакет `uv` в npm — чужой проект."""
    for system in PURL_SYSTEMS:
        name = re.sub(r"[-_.]+", "-", t.short()) if system == "pypi" else t.short()
        base = f"https://api.deps.dev/v3/systems/{system}/packages/{quote(name, safe='')}"
        default = next((v for v in dict_items(q.json(base), "versions")
                        if v.get("isDefault") is True), None)
        version = present(dig(default, "versionKey.version"))
        if version is None:
            continue
        url = f"{base}/versions/{quote(version, safe='')}"
        repo = next((p for p in dict_items(q.json(url), "relatedProjects")
                     if p.get("relationType") == "SOURCE_REPO"
                     and str(dig(p, "projectKey.id") or "").lower() == key), None)
        if repo is None:
            continue
        unverified = repo.get("relationProvenance") in (None, "", "UNVERIFIED_METADATA")
        out.append(fact("package", f"pkg:{system}/{name}"
                        + (", связь не подтверждена" if unverified else ""), url,
                        "relatedProjects[SOURCE_REPO].projectKey.id"))
        linked.append(Target("package", system=system, name=name))
        return True
    return False


def depsdev_package(t: Target, with_repo: bool, q: FactsQuery, out: list[Fact]) -> None:
    """Версии пакета, затем лицензии и уязвимости версии цели или версии по умолчанию."""
    base = f"https://api.deps.dev/v3/systems/{t.system}/packages/{quote(t.name, safe='')}"
    data = q.json(base)
    if data is None:
        out.append(fact("versions", None, base, "HTTP 404"))
        return
    versions = dict_items(data, "versions")
    default = next((v for v in versions if v.get("isDefault") is True), None)
    version = t.version
    if default is not None:
        name = present(dig(default, "versionKey.version"))
        day = iso_day(default.get("publishedAt"))
        out.append(fact("versions", f"по умолчанию {name} ({day}), всего {len(versions)}", base,
                        "versions[isDefault].versionKey.version, publishedAt"))
        version = version or name or ""
    if not version:
        return
    url = f"{base}/versions/{quote(version, safe='')}"
    data = q.json(url)
    if data is None:
        out.append(fact("version", None, url, "HTTP 404 — версии нет"))
        return
    licenses = present(dig(data, "licenses")) or "не указаны"
    ids = [a["id"] for a in dict_items(data, "advisoryKeys") if isinstance(a.get("id"), str)]
    head = f"{version}: лицензии {licenses}; уязвимостей "
    value = capped_join(f"{head}{len(ids)} — ", ids, FACT_LIST_CHARS) if ids \
        else head + "в базе нет"
    out.append(fact("version", value, url, "licenses, advisoryKeys[].id"))
    if with_repo:
        repo = next((p for p in dict_items(data, "relatedProjects")
                     if p.get("relationType") == "SOURCE_REPO"), None)
        if repo is not None and present(dig(repo, "projectKey.id")):
            unverified = repo.get("relationProvenance") == "UNVERIFIED_METADATA"
            out.append(fact("repository", f"{dig(repo, 'projectKey.id')}"
                            + (", связь не подтверждена" if unverified else ""), url,
                            "relatedProjects[SOURCE_REPO].projectKey.id"))


def osv(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    """Уязвимости версии. Запрос — POST: источником пишется он целиком, чтобы его повторить."""
    url = "https://api.osv.dev/v1/query"
    payload = {"package": {"name": t.name, "ecosystem": PURL_SYSTEMS[t.system][0]},
               "version": t.version}
    data = q.json(url, payload)
    ids = [v["id"] for v in dict_items(data, "vulns") if isinstance(v.get("id"), str)]
    value = (capped_join(f"{t.version}: {len(ids)} — ", ids, FACT_LIST_CHARS) if ids
             else f"{t.version}: в базе нет")
    out.append(fact("vulns", value, f"POST {url} {json.dumps(payload, separators=(',', ':'))}",
                    "vulns[].id"))


def eol_cycle(release: dict) -> str:
    name = present(release.get("name")) or "?"
    when = iso_day(release.get("eolFrom"))
    if release.get("isEol") is True:
        return f"{name} — снят с поддержки" + (f" {when}" if when else "")
    return f"{name} — поддержка до {when}" if when else f"{name} — поддерживается"


def endoflife(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    """Циклы выпуска по имени продукта. 404 — продукта нет: поле пустое, не ошибка."""
    url = f"https://endoflife.date/api/v1/products/{quote(t.short(), safe='')}/"
    data = q.json(url)
    if data is None:
        out.append(fact("eol", None, url, "HTTP 404"))
        return
    releases = dict_items(dig(data, "result"), "releases")
    version = t.version
    match = [r for r in releases if isinstance(r.get("name"), str) and version
             and (version == r["name"] or version.startswith(r["name"] + "."))]
    shown = match[:1] or releases[:EOL_CYCLES]
    out.append(fact("eol", "; ".join(eol_cycle(r) for r in shown) or None, url,
                    "result.releases[].name, isEol, eolFrom"))


def ecosystems(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    registry = PURL_SYSTEMS[t.system][1]
    url = (f"https://packages.ecosyste.ms/api/v1/registries/{registry}/packages/"
           f"{quote(t.name, safe='')}")
    data = q.json(url)
    if data is None:
        out.append(fact("usage", None, url, "HTTP 404"))
        return
    if not isinstance(data, dict):
        raise SourceError("не тот ответ: нет объекта пакета")
    downloads, period = data.get("downloads"), present(data.get("downloads_period"))
    parts = [f"{downloads}" + (f" за {period}" if period else "")] \
        if isinstance(downloads, int) else ["загрузок нет в ответе"]
    # Одна строка на ответ: сводка о репозитории иначе не влезает в предел.
    parts.append("зависимых пакетов " + (present(data.get("dependent_packages_count")) or "?")
                 + ", репозиториев " + (present(data.get("dependent_repos_count")) or "?"))
    out.append(fact("usage", "; ".join(parts), url,
                    "downloads, downloads_period, dependent_packages_count, dependent_repos_count"))


def repology(t: Target, q: FactsQuery, out: list[Fact]) -> None:
    """Пакет в дистрибутивах — по имени проекта Repology. Оно бывает не равно имени пакета:
    это сказано в значении, чтобы совпадение не приняли за проверенное."""
    name = f"{PURL_SYSTEMS[t.system][2]}:{t.short()}" if t.kind == "package" else t.short()
    url = f"https://repology.org/api/v1/project/{quote(name, safe=':')}"
    items = dict_items(q.json(url))
    if not items:
        out.append(fact("distros", f"проекта «{name}» нет — имя в Repology может быть другим",
                        url, "[]"))
        return
    repos = {i["repo"] for i in items if isinstance(i.get("repo"), str)}
    newest = next((present(i.get("version")) for i in items if i.get("status") == "newest"), None)
    value = f"репозиториев {len(repos)}" + (f", новейшая {newest}" if newest else "") \
        + f"; найдено по имени «{name}»"
    out.append(fact("distros", value, url, "[].repo, [status=newest].version"))


def bind(call: Callable, *args: object) -> Callable[[FactsQuery, list[Fact]], None]:
    return lambda q, out: call(*args, q, out)


def target_jobs(t: Target, linked: list[Target]) -> list[FactsJob]:
    """Источники цели (спецификация мониторинга, таблица 5.2)."""
    if t.kind == "repo":
        forge = FORGE_TITLES[t.forge]
        jobs: list[FactsJob] = [(forge, bind(hosting_repo, t)), (forge, bind(hosting_release, t)),
                                (forge, bind(hosting_commit, t))]
        if t.forge == "github":
            jobs.append(("Scorecard", bind(scorecard, t)))
        if t.host in DEPSDEV_HOSTS:
            jobs.append(("deps.dev", bind(depsdev_link, t, linked)))
    else:
        jobs = [("deps.dev", bind(depsdev_package, t, True)), ("ecosyste.ms", bind(ecosystems, t))]
        if t.version:
            jobs.append(("OSV", bind(osv, t)))
    return jobs + [("endoflife.date", bind(endoflife, t)), ("Repology", bind(repology, t))]


def run_jobs(q: FactsQuery, jobs: list[FactsJob]) -> tuple[list[Fact], list[tuple[str, str]]]:
    """Источники параллельно; упавший — пара (источник, причина), остальным он не мешает."""
    def run(job: FactsJob) -> tuple[list[Fact], str]:
        out: list[Fact] = []
        try:
            job[1](q, out)
        except SourceError as exc:
            return out, str(exc)
        except Exception as exc:  # noqa: BLE001  чужой ответ не той формы не ломает сводку
            return out, f"не разобрался: {type(exc).__name__}"
        return out, ""

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(run, jobs))
    rows: list[Fact] = []
    failed: list[tuple[str, str]] = []
    for (name, _), (out, error) in zip(jobs, results):
        rows += out
        if error and (name, error) not in failed:
            failed.append((name, error))
    return rows, failed


def facts(text: str, fetch: FactsFetch = facts_fetch, environ: Mapping[str, str] | None = None,
          today: date | None = None) -> FactsRun:
    """Сводка о цели (спецификация мониторинга, 5). Ошибка вызова — FactsError.

    Пакет репозитория узнаётся у deps.dev, поэтому его источники — вторым кругом.
    """
    target = parse_target(text)
    query = FactsQuery(fetch, github_token(environ or {}))
    linked: list[Target] = []
    rows, failed = run_jobs(query, target_jobs(target, linked))
    if linked:
        more, more_failed = run_jobs(query, [
            ("deps.dev", bind(depsdev_package, linked[0], False)),
            ("ecosyste.ms", bind(ecosystems, linked[0]))])
        rows += more
        failed += [f for f in more_failed if f not in failed]
    order = list(FACT_FIELDS)
    rows.sort(key=lambda f: order.index(f.field))
    return FactsRun(target.label(), (today or date.today()).isoformat(), rows, failed)


def fact_line(row: Fact, day: str) -> str:
    value = NO_VALUE if row.value is None else row.value
    return f"{FACT_FIELDS[row.field]} | {value} | {row.source} §{row.path} | {day}"


def facts_text(run: FactsRun) -> str:
    """Сводка не длиннее FACTS_MAX_CHARS: шапка, строки полей, хвост, кто не ответил."""
    head = (f"facts: {shorten(run.target, 200)} — полей {len(run.facts)}, "
            f"не ответили {len(run.failed)}")
    foot = [capped_join("не ответили: ", [f"{s} ({why})" for s, why in run.failed],
                        FACTS_FAILED_CHARS)] if run.failed else []
    reserve = len(head) + sum(len(x) + 1 for x in foot) + len(TAIL.format(len(run.facts))) + 2
    lines, omitted = fit_lines([fact_line(f, run.day) for f in run.facts],
                               FACTS_MAX_CHARS - reserve)
    if omitted:
        lines.append(TAIL.format(omitted))
    return "\n".join([head, *lines, *foot])


FACTS_COLUMNS = ("field", "value", "source", "path")


def facts_json(run: FactsRun) -> str:
    """То же объектом не длиннее FACTS_MAX_CHARS. Строка поля — массив по `columns`, как
    столбцы текста (дата — одна на всех, `date`): объект на поле повторял бы ключи и не
    влезал в предел. Не влезшие поля — числом в `omitted`."""
    rows = [[f.field, f.value, f.source, f.path] for f in run.facts]
    obj: dict = {"target": shorten(run.target, 200), "date": run.day,
                 "columns": list(FACTS_COLUMNS), "facts": rows,
                 "failed": [{"source": s, "error": e} for s, e in run.failed]}
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    keep = len(rows)
    while len(text) > FACTS_MAX_CHARS and keep > 0:
        keep -= 1
        obj["facts"], obj["omitted"] = rows[:keep], len(rows) - keep
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return text


def run_facts(target: str, as_json: bool) -> int:
    """Код 0, даже если часть источников не ответила; 2 — цель не распознана."""
    try:
        run = facts(target, environ=os.environ)
    except FactsError as exc:
        print(f"facts: {exc}", file=sys.stderr)
        return 2
    print(facts_json(run) if as_json else facts_text(run))
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
    watch_digest = parts(core, fs.file("references/watch.md"),
                         fs.estimate("вывод watch", OUTPUT_MAX_CHARS),
                         fs.estimate("выборки jq из new/", WATCH_JQ_CHARS),
                         fs.file(DIGEST_TEMPLATE))
    scenarios = [
        Scenario("quick", parts(core), "страницы ведущий читает сам — не считаются"),
        Scenario("reuse", reuse),
        Scenario("brief", brief),
        Scenario("fan-out", fan_out),
        Scenario("branch", branch, "контекст субагента, в ведущего не попадает"),
        Scenario("merge", merge),
        Scenario("save", save),
        Scenario("resume", parts(core, fs.estimate("plan.md", PLAN_MAX_CHARS))),
        Scenario("watch-digest", watch_digest, "страницы первоисточников не считаются"),
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
        description="Проверки скилла deep-search, брифа, прогона и хранилища; новое из лент; "
                    "сводка о репозитории или пакете.",
    )
    sub = parser.add_subparsers(dest="command", metavar="{doctor,init,lint,index,cost,self,watch,facts}")

    p = sub.add_parser("doctor", help="проба среды: утилиты, API, прокси")
    p.add_argument("--json", action="store_true", help="вывод в JSON (для manifest.json)")

    p = sub.add_parser("init", help="каркас хранилища")
    p.add_argument("path", metavar="путь", type=Path)

    p = sub.add_parser("lint", help="бриф, прогон, хранилище")
    p.add_argument("--run", metavar="папка", type=Path, help="папка прогона")
    p.add_argument("--store", metavar="путь", type=Path, help="хранилище")
    p.add_argument("--also", metavar="путь", type=Path, action="append", default=[],
                   help="другое хранилище: сверить с ним тему прогона (нужны --run и --store)")

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

    p = sub.add_parser("watch", help="новое из лент отрасли ИИ: найденное — в watch/ библиотеки")
    p.add_argument("--library", metavar="путь", type=Path,
                   help=f"библиотека (по умолчанию — {LIBRARY_VAR})")
    p.add_argument("--only", metavar="ГРУППА|ID", help="одна группа или лента")
    p.add_argument("--since", metavar="ДАТА",
                   help="окно с этой даты (ГГГГ-ММ-ДД) вместо расчётного")
    p.add_argument("--dry-run", action="store_true", help="не записывать new/ и state.json")
    p.add_argument("--json", action="store_true",
                   help="найденное в stdout строками JSON, сводка — в stderr")
    p.add_argument("--skill-dir", metavar="путь", type=Path, default=SKILL_DIR,
                   help="папка скилла (по умолчанию — папка скрипта)")

    p = sub.add_parser("facts", help="сводка о репозитории или пакете: поле, значение, источник")
    p.add_argument("target", metavar="цель",
                   help="ссылка на репозиторий, OWNER/REPO (GitHub) или purl: pkg:pypi/requests, "
                        "pkg:npm/react@18.3.1")
    p.add_argument("--json", action="store_true", help="вывод объектом JSON")
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
        return run_lint(args.run, args.store, args.also)
    if args.command == "doctor":
        return run_doctor(args.json)
    if args.command == "watch":
        return run_watch(args.skill_dir.resolve(), args.library, args.only, args.since,
                         args.dry_run, args.json)
    if args.command == "facts":
        return run_facts(args.target, args.json)
    return run_cost(args.skill_dir.resolve(), args.branches, args.return_chars)


if __name__ == "__main__":
    sys.exit(main())
