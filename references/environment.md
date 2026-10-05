Когда читать: нет субагентов или работает другой агент; нужно выбрать инструмент, достать текст страницы, PDF, JS-страницу или архивную копию.

# Среда и инструменты

Содержание: Текст страницы · PDF · JS-страницы · Архив и мёртвые ссылки · API по областям ·
Claude Code · Другие агенты.

Порядок ступеней — `references/sources.md`, раздел «Инструменты»; здесь — как ими пользоваться.
Примеры выполнены 2026-10-05; где не так — сказано почему. `OWNER/REPO`, `URL`, `DOI` — подставить.
Всё, что уходит во внешний сервис, сверять с `disclosure_constraints`.

## Текст страницы

Число и цитата — только по тексту страницы. Основной путь — curl + pandoc:

```sh
curl -sSL --max-time 30 "URL" | pandoc -f html -t gfm-raw_html --wrap=none -o page.md
grep -n -i "incremental" page.md          # место для §; цитата — из этой строки
sha256sum page.md                         # хеш для capture ключевой страницы
```

- Сначала статус и конечный адрес после редиректов:
  `curl -sSL -o /dev/null -w '%{http_code} %{url_effective}\n' "URL"`.
- Сайт отвечает 403 на curl — добавить `-A 'Mozilla/5.0'`; не помогло — Jina Reader или Chromium.
- Простой текст без разметки — `-t plain`; меню и подвалы отсекать grep по месту, а не читать всё.
- Текст почти пустой или «enable JavaScript» — страница на JS, раздел «JS-страницы».

**Jina Reader** — URL → Markdown, рендерит JS и PDF, без ключа (с ограничением частоты):

```sh
curl -sS --max-time 40 "https://r.jina.ai/URL"
```

Адрес страницы уходит стороннему сервису — только если `disclosure_constraints` это позволяют.

## PDF

```sh
curl -sSL --max-time 60 -o doc.pdf "URL"
pdfinfo doc.pdf | grep -E 'Pages|CreationDate'
pdftotext -layout -f 3 -l 5 doc.pdf -      # страницы 3–5 в stdout
pdftotext doc.pdf - | grep -n "Transformer"
```

- § улики из PDF — номер страницы: искать по диапазонам `-f`/`-l`, а не по всему файлу.
- `-layout` держит колонки и таблицы; для сплошного текста цитаты — без него.
- Скан без текстового слоя `pdftotext` не читает — нужен OCR; без него утверждение получает «6».
- Запасной путь — Jina Reader, с той же оговоркой.

## JS-страницы

Не проверено. Команда по документации Chromium:

```sh
chromium --headless --disable-gpu --virtual-time-budget=10000 --dump-dom "URL" \
  | pandoc -f html -t gfm-raw_html --wrap=none
```

- `--virtual-time-budget` даёт скриптам время дорисовать страницу; мало — увеличить.
- Имя бинаря бывает `chromium`, `chromium-browser`, `google-chrome`.
- Подключён Playwright MCP — снимок страницы через него; Chromium нет совсем — Jina Reader.

## Архив и мёртвые ссылки

Мёртвая ссылка проверяется в Wayback: страница была и устарела или ссылка выдумана.

```sh
# снимки адреса: время, исходный URL, код ответа
curl -sS "https://web.archive.org/cdx/search/cdx?url=example.com/&output=json&limit=3&fl=timestamp,original,statuscode"
# ближайший снимок к году, без обвязки Wayback (суффикс id_)
curl -sSL "https://web.archive.org/web/2015id_/http://example.com/"
# сохранить ключевую страницу; адрес снимка — в заголовке Location, он идёт в capture
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' "https://web.archive.org/save/URL"
```

- Снимков нет и адрес не встречается в других источниках — ссылка, вероятно, выдумана: не
  использовать, в журнал — «не найдено».
- `https://archive.org/wayback/available?url=…` при проверке отвечал 429 — брать CDX.
- Пакетная проверка ссылок отчёта: `lychee --no-progress --format compact report.md`; домены
  example.* lychee пропускает.

## API по областям

Специализированный источник прежде общего веба. Ответы — JSON, отбирать `jq`, а не читать целиком.

**Документация библиотек — context7.** Есть MCP context7 — сначала `resolve-library-id`, затем
`query-docs` с id и темой. Без MCP — HTTP, без ключа:

```sh
curl -sS "https://context7.com/api/v1/search?query=fastapi" | jq -r '.results[:3][]|"\(.id) \(.title)"'
curl -sS "https://context7.com/api/v1/websites/fastapi_tiangolo?tokens=2000&topic=dependencies"
```

Фрагменты context7 — указатель; цитата для A — по странице из строки `Source:` фрагмента.

**ПО — GitHub.** Без токена — 60 запросов в час, поиск — 10 в минуту (при общем IP исчерпывается
быстро, ответ 403 «rate limit»). Есть токен — `-H "Authorization: Bearer $GITHUB_TOKEN"`.

```sh
curl -sS https://api.github.com/repos/OWNER/REPO | jq -c '{license:.license.spdx_id,pushed_at,archived}'
curl -sS https://api.github.com/repos/OWNER/REPO/releases/latest | jq -c '{tag_name,published_at}'
curl -sS "https://api.github.com/search/repositories?q=topic:log-management&sort=stars&per_page=5" \
  | jq -r '.items[]|"\(.full_name) \(.stargazers_count)"'
curl -sS https://raw.githubusercontent.com/OWNER/REPO/HEAD/LICENSE   # имя файла бывает LICENSE.txt, COPYING
gh api repos/OWNER/REPO/releases --jq '.[0].tag_name'                # не проверено
```

`license.spdx_id` = `NOASSERTION` — лицензия нестандартная: читать сам файл.

**ПО — пакеты, сроки поддержки, уязвимости, здоровье проекта.**

```sh
# deps.dev: версии, лицензии, уязвимости пакета (npm, pypi, go, maven, cargo, nuget)
curl -sS https://api.deps.dev/v3/systems/pypi/packages/requests/versions/2.32.3 | jq -c '{licenses,advisoryKeys}'
# endoflife.date: циклы выпуска и конец поддержки
curl -sS https://endoflife.date/api/v1/products/postgresql/ | jq -c '.result.releases[:3][]|{name,eolFrom,latest:.latest.name}'
# OSV: уязвимости версии пакета
curl -sS -X POST https://api.osv.dev/v1/query \
  -d '{"package":{"name":"jinja2","ecosystem":"PyPI"},"version":"2.4.1"}' | jq -r '.vulns[]?.id'
# ecosyste.ms: загрузки и зависимые
curl -sS https://packages.ecosyste.ms/api/v1/registries/npmjs.org/packages/react \
  | jq -c '{latest_release_number,downloads,dependent_repos_count}'
# OpenSSF Scorecard: сопровождение, ревью кода
curl -sS https://api.securityscorecards.dev/projects/github.com/OWNER/REPO | jq -c '{date,score}'
```

«Нет в базе уязвимостей» не значит «уязвимостей нет»: базы обогащаются с задержкой.

**Наука — OpenAlex, arXiv, Crossref.**

```sh
# OpenAlex: фильтр по заглавию точнее, чем search= (тот при проверке подмешал чужую тему)
curl -sS "https://api.openalex.org/works?filter=title.search:retrieval%20augmented%20generation,from_publication_date:2024-01-01&sort=cited_by_count:desc&per-page=5&select=doi,display_name,publication_year,cited_by_count" | jq -c '.results[]'
# arXiv: Atom XML; не чаще одного запроса в 3 секунды
curl -sS "https://export.arxiv.org/api/query?search_query=ti:%22retrieval%20augmented%22&sortBy=submittedDate&max_results=5"
# Crossref: метаданные DOI; mailto — адрес того, кто запускает
curl -sS "https://api.crossref.org/works/DOI?mailto=you@example.org" | jq -c '.message|{title:.title[0],type}'
# отозвана ли статья: уведомления, которые обновляют этот DOI
curl -sS "https://api.crossref.org/works?filter=updates:DOI&mailto=you@example.org" \
  | jq -c '.message.items[]|{DOI,type:.["update-to"][0].type}'
```

Тип `retraction` в ответе — статья отозвана, не использовать.

## Claude Code

- **WebSearch и WebFetch** бывают отложенными: схемы нет, вызов падает. Загрузить через ToolSearch
  с запросом `select:WebSearch,WebFetch`.
- **WebSearch** — заголовки и URL; фильтр — `allowed_domains` или `blocked_domains`, не оба вместе.
  К выдаче приложена сводка модели — не источник. Не больше 200 вызовов на сессию вместе с
  субагентами: счёт вести по журналу.
- **Ловушки WebFetch:** отвечает малая модель на `prompt`, а не отдаёт страницу; «не упоминает X»
  может значить, что prompt об X не спрашивал; большие страницы обрезаются; кэш 15 минут; HTTP
  поднимается до HTTPS; редирект на другой хост не выполняется — вызвать снова с новым адресом;
  localhost, имена без точки и закрытые страницы не открывает — curl.
- **Субагенты** — у каждого своё окно; ведущий получает только последнее сообщение; истории
  разговора у субагента нет. Запускаются фоном, о завершении приходит уведомление — ждать, а не
  опрашивать. Вложенность ограничена (до 3 уровней). Как поручать — `references/branching.md`,
  раздел «Поручение субагенту».
- **Прокси.** Заданы `HTTP_PROXY`/`HTTPS_PROXY` — curl к локальному сервису (SearXNG, MCP по HTTP)
  уходит в прокси и падает по таймауту. Обход — `curl --noproxy localhost,127.0.0.1 …` или
  `localhost,127.0.0.1` в `NO_PROXY`.

## Другие агенты

Нет субагентов — ветки последовательно, `references/branching.md`, раздел «Без субагентов». Любой
встроенный «fetch», который отдаёт пересказ, — как WebFetch: только сортировка; текст — curl.

- **Codex CLI.** По умолчанию поиск идёт по кэшу индекса, без выхода в сеть; живой — флаг
  `--search`: `codex --search exec "…"`. Флаг принимается; ответ зависит от модели, доступной
  учётной записи.
- **Gemini CLI.** `google_web_search` и `web_fetch` отдают сводку с источниками, а не текст — цифры
  и цитаты брать curl. Не проверено.
- **Нет встроенного поиска.** Обнаружение — через API раздела «API по областям» и самостоятельный
  метапоиск SearXNG: `curl -sS "http://localhost:8080/search?q=QUERY&format=json"` (JSON-вывод
  включается в его настройках). Не проверено.
