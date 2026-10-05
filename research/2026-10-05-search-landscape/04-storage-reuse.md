# Хранение и переиспользование результатов поиска

Для скилла поиска с ветвлением, часть «Сохранение». 2026-10-05. [n] — «Источники»; [?] — не проверено по первоисточнику.

## Коротко

- Продукты deep research держат результат внутри одного прогона или блокнота. Накопление дают LLM Wiki Карпатого и файловая память агентов: неизменные свидетельства, переписываемый синтез, `index.md`, `log.md`, lint.
- Единица хранения — тема, а не прогон. Отчёт прогона — снимок. Знание из него переносится в карточку темы, реестр источников и реестр утверждений.
- Утверждение хранится вместе с источником, дословной цитатой, уровнем источника, оценкой, датой сверки и сроком годности. Синтез источником не становится.
- Против свалки: канонический ключ источника и upsert по нему, статусы, сроки годности, бюджеты размеров, lint-скрипт.
- Контекст: на старте ничего не грузится. Переиспользование стоит ≈3–9k токенов, чтение старых отчётов — 11–34k. 1 КБ Markdown ≈ 250–290 токенов (мой замер).
- Рекомендую вариант Б: библиотека в отдельном git-репозитории. Отчёт для конкретного проекта по-прежнему ложится в проект.

## 1. Продукты deep research

- **STORM** пишет папку прогона: `conversation_log.json`, `raw_search_results.json`, два outline, `url_to_info.json` (по сути реестр источников), `storm_gen_article(_polished).txt`, `llm_call_history.jsonl` [1].
- **open_deep_research** держит всё в состоянии графа: `research_brief`, `notes`, `raw_notes`, `final_report`. Ветка возвращает `compressed_research`. Межпрогонного хранилища в `state.py` нет [2].
- **GPT Researcher** отдаёт отчёт и `get_source_urls()` / `get_research_sources()` / `get_research_context()` [3].
- **NotebookLM** (в справке 2026 — Gemini Notebook): блокнот = источники + заметки (до 1000 заметок, 50–600 источников по тарифу); «Save to Note» сохраняет ответ без права правки; заметку можно превратить в источник [4][5].
- **Perplexity Spaces** — файлы, инструкции и треды одной темы [?]. Сайт отдал 403.

Знание не копится ни в одном продукте. Карпатый о NotebookLM и RAG: «rediscovering knowledge from scratch on every question. There's no accumulation» [6]. «Convert to source» — ловушка: синтез модели превращается в источник. Выводы ИИ — это материал вендора.

## 2. LLM Wiki — ближайший образец

Gist Карпатого, 2026-04-04 [6]:
- **Слои:** raw sources «immutable»; wiki — Markdown, который ведёт LLM; schema — CLAUDE.md или AGENTS.md.
- **Операции:** ingest (один источник правит 10–15 страниц); query — «good answers can be filed back into the wiki as new pages»; lint — «contradictions… stale claims… orphan pages… missing cross-references».
- **`index.md`** — строка и метаданные на страницу. Работает «at moderate scale (~100 sources, ~hundreds of pages)» без RAG, дальше нужен поиск (qmd: BM25 + векторы).
- **`log.md`** — append-only, записи `## [2026-04-02] ingest | Title` разбираются grep-ом.
- **Человек** смотрит в Obsidian: «Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase».

Отличие от нас: источники приносит поиск. Поэтому слой raw заменяют реестры с цитатами, а полные копии хранятся только по исключению.

## 3. Личные базы знаний

- **Ahrens:** literature notes — коротко, своими словами, при ссылке; permanent notes «never be thrown away» и понятны без контекста [7] → цитата в реестре и карточка темы.
- **Zettelkasten:** обязательный уникальный ID, structure notes — «fast tracks» по сети [8] → ID `S-…`, `C-…`, slug.
- **Evergreen notes:** «accumulate over time, across projects», атомарны, про понятие [9] → карточка на тему, не на проект.
- **Progressive summarization:** «opportunistic compression» слоями [10] → выжимка сверху.
- **PARA:** archives — «no longer active» [11] → статус `archived`. **MOC** [12] → растущий INDEX делится на карты областей.
- **Obsidian Bases:** «database-like views» по YAML-properties, данные в Markdown [13] → виды «просрочено», «противоречия» без отдельной БД.

## 4. Файловая память агентов

| Система | Всегда в контексте | По требованию | Против разрастания |
|---|---|---|---|
| Claude Code auto memory | `MEMORY.md`, «first 200 lines… or the first 25KB» | topic-файлы [14] | «keep one line per entry… merge or drop stale entries» |
| Anthropic memory tool | Инструкция «ALWAYS VIEW YOUR MEMORY DIRECTORY» | `/memories`, `view` режет >16 000 символов [15] | «Periodically delete memory files that haven't been accessed» |
| Letta Context Repositories | Папка `system/` | Остальное — по frontmatter-описаниям | Git-версия каждой правки; дефрагментация до «15–25 focused files»; субагенты пишут в своих worktree [16] |
| Serena | Список имён | По имени, ссылки `mem:имя` | Глобальная и проектная память; ignored-паттерны для архива; `memories check`; «Prefer references to search», «Prefer deliberate reads to triggers» [17] |
| Copilot Memory | — | Факт с citations; их сверяют с веткой, «Only validated facts are used» | Удаление через 28 дней без использования, при подтверждении таймер сбрасывается [18] |

Basic Memory: `- [category] факт #tag`, `- relation [[Entity]]` поверх SQLite [19]. A-MEM: заметка {content, timestamp, keywords, tags, context, embedding, links}; новая заметка «эволюционирует» старые, переписывая атрибуты [20].

**Выводы:** (1) свидетельства неизменны, синтез переписывается — эволюция по A-MEM стёрла бы прошлое, поэтому старое утверждение получает `superseded`; (2) описание в одну строку во frontmatter, индекс — из описаний; (3) сверка перед использованием, как у Copilot; (4) архив скрыт от агента.

## 5. Карточка источника и архивирование

- **Поля** — из CSL-JSON [21]: `type`, `title`, `author`, `container-title`, `issued` (публикация), `accessed` (обращение), `URL`, `DOI` и `custom` — «custom key-value pairs». Поля для URL снимка в схеме нет. В `custom` кладутся уровень 1–5 по шкале типов источников, `vendor`, `archive_url`, `sha256` и темы, где используется источник.
- **Robust link** — оригинальный URL, URL снимка и дата (`data-originalurl`, `data-versionurl`, `data-versiondate`). Защищает от link rot и content drift [22]. Для кода — permalink на коммит.
- **Сохранять всегда:** URL, снимок через Wayback Save Page Now (одна страница по запросу [23]), цитаты под утверждениями, дату обращения.
- **Полная копия — по исключению.** Berkeley Protocol: для «internal work product» хватает скриншота или PDF, для доказательств нужен хэш. Протокол велит оценить риск удаления и сохранить «most reliable known version» [24]. Инструменты: SingleFile [25], ArchiveBox (HTML, PDF, WARC, текст, `index.json`) [26].
- **Не сохранять:** выдачу и сниппеты (вывод делается только по открытой странице), документацию с версионными ссылками.
- **Право.** Ст. 1274 ГК РФ разрешает цитирование «в объеме, оправданном целью цитирования», с указанием автора и источника [27]. Полная копия — воспроизведение: только для внутреннего пользования, вне git. Это не юридическая оценка [?].

## 6. Реестр утверждений

- **ClaimReview.** `claimReviewed` «less than 75 characters», текстовый вердикт `alternateName`, у Claim — `author`, `datePublished`, `appearance`, `firstAppearance`. Google сворачивает показ в Поиске, но формат годен [28].
- **Cochrane.** Форма извлечения пилотируется. Источник записывается «including where it was found», для суждений — «quote directly from the source document». Принцип «Collate multiple reports of the same study»: единица — исследование [29].
- **FM 2-22.3, прил. B.** Две оси: надёжность источника A–F и достоверность сведения 1–6. F и 6 — «нельзя оценить», а не «плохо» [30].

Одна строка таблицы — одно утверждение, grep отдаёт её целиком:

| id | утверждение | предмет | источник | цитата, место | ур. | оценка | проверено | годность | статус |
|---|---|---|---|---|---|---|---|---|---|
| C-<тема>-014 | <X делает Y> | <X> | S-3f2a91c0 | «…» (раздел) | 1 | подтверждено ×2 | 2026-10-05 | fast | live |

- **Оценка** — текстом: подтверждено (уровень 1 или ≥2 независимых), один источник, только вендор, противоречие (с обоими id), не найдено.
- **Статус:** `live`, `stale`, `superseded→C-…`, `retracted`.
- Без цитаты утверждение не записывается.

## 7. Правила против свалки

1. **Единица — тема или сущность.** Прогон — неизменный снимок [29][6].
2. **Факт живёт в одном месте.** Отчёты и карточки ссылаются на id (правило project-memory).
3. **Ключ источника** — первый доступный: DOI → канонический URL (`rel="canonical"` [31], нормализация RFC 3986 §6 [32], без фрагмента и `utm_*`) → sha256 текста. Сохранение — upsert.
4. **Годность по классам** (суждение): fast (версии, активность, цены) — 90 дней, medium (лицензия, поддержка) — 180, slow (стандарты) — 730. Для сравнения: Copilot — 28 дней [18], project-memory — 60. `expires` карточки — минимум по её live-утверждениям.
5. **«Проверено»** меняется только при сверке с источником, а не при правке текста.
6. **Бюджеты:** INDEX ≤100 строк (≈7k токенов), иначе делится по областям; карточка ≤300 строк; утверждения темы ≤200.
7. **Не пишутся** черновики веток, сниппеты, расшифровки субагентов.
8. **Lint** — скриптом при каждом сохранении: битые id, дубли ключей, сироты, истёкшие сроки, размеры. Противоречия ищет LLM-lint отдельным субагентом.
9. **Консолидация** при превышении бюджета: делить или сливать (Letta держит 15–25 файлов [16]). «Отклонено» с «Пересмотреть, если» не удаляется.
10. **Архив** — `archived`, папка `archive/` скрыта от агента, как ignored-паттерны у Serena [17]; для grep — через `.ignore`. Копии архивных тем удаляются через год (суждение).
11. **Синтез — не источник.** Утверждения ссылаются только на внешние `S-…`.

## 8. Как найти нужное, не читая лишнего

- **Опыт Claude Code.** Cherny, 2026-02-01: «Early versions of Claude Code used RAG + a local vector db, but we found pretty quickly that agentic search generally works better… simpler and doesn't have the same issues around security, privacy, staleness, and reliability» [33].
- **Позиция Anthropic** [34]: grep и glob «just-in-time, effectively bypassing the issues of stale indexing»; в контексте — «lightweight identifiers (file paths, stored queries, web links)»; субагент отдаёт «condensed, distilled summary… (often 1,000-2,000 tokens)»; «context rot».
- **Замер Letta.** Агент на файлах набрал 74,0% на LoCoMo против 68,5% у графового Mem0: «memory is more about how agents manage context than the exact retrieval mechanism» [35].
- **Не грузить заранее.** По Gloaguen et al., файлы контекста в среднем не повышают успех задач и удорожают работу более чем на 20% [36]. Индекс библиотеки не кладётся в CLAUDE.md или auto memory.
- **Порядок поиска в хранилище:** grep по INDEX (ключевые слова RU и EN, по основам слов) → шапки 1–2 карточек → grep по утверждениям → источник по id. Больше трёх файлов — значит, чинить INDEX.
- **Когда нужен индекс.** Когда INDEX перерос ~100 строк или grep пропускает синонимы — SQLite FTS5: BM25, токенизатор trigram. Стемминг porter только английский [37], поэтому для русского — trigram и keywords. Эмбеддинги нужны при сотнях тем; их цена — инфраструктура и устаревание [33].

## 9. Где хранить

| Где | Плюсы | Минусы |
|---|---|---|
| В проекте | Как в обычном отчёте о поиске; права не нужны | Знание заперто в проекте |
| Папка пользователя | Переиспользование между проектами | Одна машина [14]; проекты смешиваются |
| Отдельный git-репозиторий | История, диффы, Obsidian, команда; подключается через `--add-dir` / `additionalDirectories` [38] | Нужна дисциплина; риск вынести данные проекта |

## 10. Варианты архитектуры

### А. В проекте

**Состав:** `research/` (или `memory/research/`) с `INDEX.md`, `log.md`, `topics/<slug>.md`, `sources.md`, `claims/<slug>.md` и `runs/<дата>-<slug>/` (бриф, журнал, отчёт, ветки).

**Цикл:** прогон пишет `runs/`, затем upsert в `sources.md`, строки в `claims/`, перезапись карточки, строки в INDEX и log. Переиспользование — grep по INDEX проекта; обновление — новый прогон с `since`; архив — вместе с проектом.

**Плюс:** просто. **Минус:** каждый проект начинает с нуля.

### Б. Библиотека пользователя — рекомендую

```
~/research-library/          # git-репо и хранилище Obsidian
  INDEX.md                   # скрипт собирает из frontmatter карточек
  log.md                     # ## [дата] search|update|lint|archive | slug
  topics/<slug>.md           # карточка темы, ≤300 строк
  sources.md                 # строка на источник, ключ S-<хэш>
  claims/<slug>.md           # утверждения темы
  runs/2026/<дата>-<slug>/   # снимки прогонов (brief, log, report, branches/), вне INDEX
  raw/                       # полные копии, .gitignore, sha256
  archive/                   # .ignore для агента
  tools/lint.py
```

**Карточка.** Frontmatter: `topic`, `title`, `aliases` (RU/EN), `keywords`, `status`, `checked`, `expires`, `runs`, `confidentiality`. Тело: TL;DR; «Ответ» на дату `checked`; «Кандидаты» (имя, класс, C-…, статус); «Отклонено» с «Пересмотреть, если»; «Что уже искали» → `runs/…/log.md`; «Открытые вопросы».

**Цикл:**
- **Создание.** Ветки пишут в `branches/`, один агент сводит их в реестры и карточку. Отчёт для конкретного проекта идёт в проект, копия — в `runs/`.
- **Переиспользование.** grep по INDEX на подготовке. Карточка даёт брифу `prior_work`, `known_exclusions` и `since`. Поиск идёт по дельте, просроченные утверждения перепроверяются.
- **Обновление.** Разделы карточки перезаписываются, утверждения версионируются, `checked` и `expires` пересчитываются.
- **Архив.** `archived`, файл — в `archive/`, строка из INDEX убирается.

**Плюсы:** переиспользование между проектами, один источник правды, просмотр в Obsidian Bases, ревью диффом. **Минус:** нужен доступ вне проекта; при `confidentiality: project-only` — вариант А.

### В. Компилируемая вики

**Состав:** Б плюс страницы сущностей, обязательный lint, FTS5 с trigram (позже эмбеддинги), MOC по областям.

**Плюс:** держит сотни тем. **Минусы:** ingest правит 10–15 страниц — дорого и трудно проверить; индекс устаревает; синтез может тихо переписать факты.

### Рекомендация

Начать с Б в минимальном составе: INDEX, log, topics, sources, claims, runs, lint. Перейти на В, когда INDEX перерастёт 100–150 строк. Вариант А — для конфиденциальных поисков. Коммиты — по правилам репозитория библиотеки.

## 11. Рост контекста

**Замер на этой модели** (по счётчику токенов сессии): `references/writing.md` из project-memory (26 549 байт, 16 110 символов русского Markdown) — ≈7,5k токенов, то есть ≈3,5 байта или ≈2,1 символа на токен; выдержка из табличного документа (15 КБ) — 3,9–4,3 байта на токен; точность ±15%. Для английского, по данным Anthropic, ≈3,5 символа на токен [39].

**Правило:** 1 КБ ≈ 250–290 токенов на любом языке; на символ русский дороже английского в ~1,7 раза.

| Сценарий | Что читается | Объём | Токены |
|---|---|---|---|
| Старт сессии | description скилла | — | ~0,1k |
| Смежный поиск | grep по INDEX, 5–15 строк | 1–4 КБ | 0,3–1,1k |
| | шапки и «Ответ / Отклонено» 1–2 карточек | 4–12 КБ | 1,1–3,4k |
| | grep по утверждениям, 10–30 строк | 3–10 КБ | 0,9–2,9k |
| | grep по журналам прогонов | 1,5–4,5 КБ | 0,4–1,3k |
| | **итого** | 10–30 КБ | **≈3–9k** |
| Без хранилища | 2 прежних отчёта | 40–80 КБ | 11–23k |
| Пример | исследование для project-memory `research/2026-09-25-memory-landscape`, 5 файлов | 121 КБ | ≈34k |
| Сохранение | `storage.md` + карточка + grep по ключам | ≤22 КБ | ≤6k на вход, 3–6k на выход |
| Ветка-субагент | выжимка главному агенту | — | 1–2k [34] |

- **INDEX целиком** (100 строк × 250 байт = 25 КБ) — ≈7k, порядок лимита auto memory [14].
- **С консолидацией** цена переиспользования почти постоянна, потолок — ≈13k (две полные карточки).
- **Без консолидации** она растёт линейно: +6–11k за каждый прежний прогон.
- **`references/storage.md`** грузится только на этапе сохранения — по схеме постепенной подгрузки Skills [40].

## Что взять в скилл

Формат: приём — часть; откуда; основание.

1. Два слоя: свидетельства (`runs/`, `sources.md`, `claims/`) неизменны, синтез (`topics/`, INDEX) переписывается; старое утверждение → `superseded` — сохранение; [6], A-MEM [20] как антипример; твёрдое.
2. Единица знания — карточка темы; отчёт — снимок со ссылками на id — сохранение; [29][9]; твёрдое.
3. Карточка по шаблону раздела 10, ≤300 строк, выжимка сверху — сохранение, контекст; KB project-memory, [10][13]; среднее.
4. Реестр источников: ключ `S-<хэш DOI или канонического URL>`, upsert, поля CSL + `custom` — сохранение; [21][31][32]; твёрдое.
5. Robust link для ключевых утверждений; полные копии — только критичных и исчезающих страниц, вне git; цитаты — в пределах ст. 1274 — сохранение; [22][24][27]; среднее (в закрытом контуре архив недоступен; право [?]).
6. Реестр утверждений с цитатой и местом, двумя осями оценки и явным «не найдено»; без цитаты не пишется — поиск, сохранение; [28][29][30]; поля твёрдые, шкалы средние.
7. Сверка перед использованием: просроченное утверждение — только после повторного открытия источника; удачная сверка продлевает срок — поиск; [18]; твёрдое (перенос из кода).
8. Годность 90/180/730 дней, `expires` карточки = минимум — сохранение; суждение; слабое, откалибровать.
9. Синтез — не источник: утверждения ссылаются только на внешние `S-…` — сохранение; [4] как антипример; твёрдое.
10. INDEX (slug | TL;DR ≤100 символов | keywords RU/EN | статус | проверено | годен до) собирается скриптом, ≤100 строк, дальше MOC; log append-only `## [дата] вид | slug` — контекст; [6][14][12]; твёрдое.
11. Поля брифа: `prior_work`, `known_exclusions`, `since`, `freshness`, `store_topic`, `confidentiality` — подготовка; суждение; среднее.
12. grep по INDEX → ≤2 карточки → grep по утверждениям → источник; больше трёх файлов — чинить INDEX; на старте ничего не грузить — контекст; [34][36][17][40]; твёрдое.
13. Ветка пишет свой файл и отдаёт выжимку на 1–2k; сводит один агент; формат субагенту передаётся явно — поиск, сохранение; [34][16]; твёрдое.
14. Lint-скрипт при каждом сохранении, LLM-lint противоречий — субагентом; архив скрыт от агента; «Отклонено» не удаляется — сохранение; [6][17][11]; твёрдое.
15. grep до ~100–150 тем, дальше FTS5 с trigram, эмбеддинги — при сотнях тем — контекст; [33][35][37]; среднее (пороги ориентировочные).
16. Вариант Б, подключение через `--add-dir`; отчёт — в проект; при `project-only` — А — сохранение; [38]; среднее.
17. 1 КБ ≈ 0,28k токенов; переиспользование ≤9k, INDEX целиком ≤7k — контекст; замер, [39]; среднее (перемерить count_tokens).

## Источники

Все открыты 2026-10-05; в скобках — дата публикации.

1. STORM, engine.py — https://github.com/stanford-oval/storm
2. open_deep_research, state.py — https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/state.py
3. GPT Researcher — https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package
4. Gemini Notebook Help, заметки — https://support.google.com/notebooklm/answer/16262519
5. Gemini Notebook Help, лимиты — https://support.google.com/notebooklm/answer/16213268
6. Karpathy, LLM Wiki (2026-04-04) — https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
7. Lengyel, zettelkasten.de (2022-02-10) — https://zettelkasten.de/posts/concepts-sohnke-ahrens-explained/
8. Zettelkasten Method, Introduction (2020-10-27) — https://zettelkasten.de/introduction/
9. Matuschak, Evergreen notes — https://notes.andymatuschak.org/Evergreen_notes
10. Forte, Progressive Summarization (2017, обн. 2023-05-16) — https://fortelabs.com/blog/progressive-summarization-a-practical-technique-for-designing-discoverable-notes/
11. Forte, PARA (2023-02-24, обн. 2026-04-15) — https://fortelabs.com/blog/para/
12. Milo, MOCs — https://blog.linkingyourthinking.com/notes/mocs-(defn)
13. Obsidian Help, Bases и Properties — https://obsidian.md/help/bases, https://obsidian.md/help/properties
14. Claude Code Docs, Memory — https://code.claude.com/docs/en/memory
15. Claude Docs, Memory tool — https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
16. Letta, Context Repositories (2026-02-12) — https://www.letta.com/blog/context-repositories/
17. Serena, Memories — https://oraios.github.io/serena/02-usage/045_memories.html
18. GitHub Docs, Copilot Memory — https://docs.github.com/en/copilot/concepts/agents/copilot-memory
19. Basic Memory, README — https://github.com/basicmachines-co/basic-memory
20. Xu et al., A-MEM (2025-02-17) — https://arxiv.org/abs/2502.12110
21. CSL-JSON schema — https://github.com/citation-style-language/schema/blob/master/schemas/input/csl-data.json
22. Robust Links, Spec — https://mementoweb.org/robustlinks/spec/
23. Internet Archive Help, Wayback — https://help.archive.org/help/using-the-wayback-machine/
24. OHCHR, Berkeley Protocol (2022), п. 149–150 — https://www.ohchr.org/sites/default/files/2024-01/OHCHR_BerkeleyProtocol.pdf
25. SingleFile — https://github.com/gildas-lormeau/SingleFile
26. ArchiveBox — https://github.com/ArchiveBox/ArchiveBox
27. ГК РФ, ст. 1274 — https://pravo.ppt.ru/kodeks/gk/st-1274
28. Google, ClaimReview — https://developers.google.com/search/docs/appearance/structured-data/factcheck
29. Cochrane Handbook v6.5, гл. 5 — https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-05
30. FM 2-22.3 (2006), App. B, копия — https://redanalysis.org/wp-content/uploads/2016/09/Appendix-B-reliability-of-information.pdf
31. RFC 6596 (2012) — https://www.rfc-editor.org/rfc/rfc6596
32. RFC 3986 (2005) — https://www.rfc-editor.org/rfc/rfc3986
33. Cherny, X (2026-02-01) — https://x.com/bcherny/status/2017824286489383315
34. Anthropic, Effective context engineering (2025-09-29) — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
35. Letta, Benchmarking AI agent memory (2025-08-12) — https://www.letta.com/blog/benchmarking-ai-agent-memory
36. Gloaguen et al., arXiv:2602.11988 (2026-02-12) — https://arxiv.org/abs/2602.11988
37. SQLite FTS5 — https://www.sqlite.org/fts5.html
38. Claude Code Docs, Permissions — https://code.claude.com/docs/en/permissions
39. Claude Docs, Glossary — https://platform.claude.com/docs/en/about-claude/glossary
40. Anthropic, Agent Skills (2025-10-16) — https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills

Внутренние: project-memory, `references/writing.md`.
