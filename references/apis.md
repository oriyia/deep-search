Когда читать: этап 3 — нужны данные из API: документация, ПО и хостинги кода, пакеты, чужой код, обсуждения, справочные факты, наука, нормативные акты. Читать «Общее» и раздел своей области, не весь файл.

# API по областям

Содержание: Общее · Документация библиотек · ПО: GitHub · ПО: другие хостинги ·
ПО: пакеты и поддержка · Чужой код · Обсуждения и опыт · Справочные факты · Наука ·
Нормативные акты.

Специализированный источник прежде общего веба (`references/sources.md`, раздел «Инструменты»).
Примеры выполнены 2026-10-05 и 2026-10-09; где не так — сказано почему. `OWNER/REPO`, `DOI`,
`QUERY` — подставить.

## Общее

- Ответы — JSON: отбирать `jq`, а не читать целиком. В журнале — `method: api`.
- **User-Agent.** Часть API отвечает 403 без своего User-Agent (Wikidata, Repology) или на
  браузерный (Software Heritage): `-A 'deep-search (+<ссылка на скилл или адрес владельца>)'`.
- **Сжатие.** Stack Exchange всегда отдаёт gzip — `curl --compressed`.
- **Лимиты** — у каждого API ниже; 429 или 403 «rate limit» — пауза, затем другой источник.
- Запрос уходит внешнему сервису — сверить с `disclosure_constraints`.

## Документация библиотек

**context7.** Есть MCP context7 — сначала `resolve-library-id`, затем `query-docs` с id и темой. Без
MCP — HTTP, без ключа:

```sh
curl -sS "https://context7.com/api/v1/search?query=fastapi" | jq -r '.results[:3][]|"\(.id) \(.title)"'
curl -sS "https://context7.com/api/v1/websites/fastapi_tiangolo?tokens=2000&topic=dependencies"
```

Фрагменты context7 — указатель; цитата для A — по странице из строки `Source:` фрагмента.

## ПО: GitHub

Без токена — 60 запросов в час, поиск — 10 в минуту (при общем IP исчерпывается быстро, ответ 403
«rate limit»). Есть токен — `-H "Authorization: Bearer $GITHUB_TOKEN"`.

```sh
curl -sS https://api.github.com/repos/OWNER/REPO | jq -c '{license:.license.spdx_id,pushed_at,archived}'
curl -sS https://api.github.com/repos/OWNER/REPO/releases/latest | jq -c '{tag_name,published_at}'
curl -sS "https://api.github.com/search/repositories?q=topic:log-management&sort=stars&per_page=5" \
  | jq -r '.items[]|"\(.full_name) \(.stargazers_count)"'
curl -sS https://raw.githubusercontent.com/OWNER/REPO/HEAD/LICENSE   # имя файла бывает LICENSE.txt, COPYING
gh api repos/OWNER/REPO/releases --jq '.[0].tag_name'                # не проверено
```

`license.spdx_id` = `NOASSERTION` — лицензия нестандартная: читать сам файл.

## ПО: другие хостинги

Проект не на GitHub — его хостинг первоисточник так же.

```sh
# GitLab: путь проекта URL-кодирован (/ → %2F); без токена — 60 в час по документации
curl -sS "https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab-runner" | jq -c '{star_count,last_activity_at}'
curl -sS "https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab-runner/releases?per_page=2" | jq -c '.[]|{tag_name,released_at}'
# Codeberg и любой Forgejo или Gitea — тот же API; заголовок лимита — 2000 за 600 с
curl -sS https://codeberg.org/api/v1/repos/forgejo/forgejo | jq -c '{stars_count,updated_at,archived}'
# Gitee: поля как у GitHub; без токена — 60 запросов
curl -sS https://gitee.com/api/v5/repos/openharmony/docs | jq -c '{stargazers_count,pushed_at}'
```

GitFlic отвечает только с токеном — без него сайт проекта и веб-поиск.

## ПО: пакеты и поддержка

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
# Repology: в каких дистрибутивах есть пакет и какой версии; не чаще 1 запроса в секунду
curl -sS -A 'deep-search (+<ссылка>)' https://repology.org/api/v1/project/ripgrep \
  | jq -c '[.[]|{repo,version,status}][:5]'
```

«Нет в базе уязвимостей» не значит «уязвимостей нет»: базы обогащаются с задержкой. Имя проекта в
Repology бывает не равно имени пакета.

## Чужой код

Кто и как использует библиотеку или API — по коду публичных репозиториев.

```sh
# GitHub code search — только с токеном (без него 401)
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/search/code?q=QUERY+language:python" \
  | jq -r '.items[:5][]|"\(.repository.full_name) \(.path)"'
# grep.app — через MCP-адрес; обычный API закрыт защитой от роботов
curl -sS -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"searchGitHub","arguments":{"query":"tokio::select!","language":["Rust"]}}}' \
  https://mcp.grep.app
# Sourcegraph: поток событий, находки — строки data: у event: matches
curl -sS -H 'Accept: text/event-stream' \
  "https://sourcegraph.com/.api/search/stream?q=repo:%5Egithub%5C.com/BurntSushi/ripgrep%24%20fn%20main%20count:3&v=V3"
```

Анонимный доступ Sourcegraph не задокументирован и может закрыться — тогда grep.app или GitHub.

## Обсуждения и опыт

Опыт эксплуатации, проблемы, «почему отказались» — уровень C; запрос-опровержение — здесь.

```sh
# Hacker News через Algolia: по релевантности или по дате; фильтр — points>N (знаки URL-кодировать)
curl -sS "https://hn.algolia.com/api/v1/search?query=QUERY&tags=story&numericFilters=points%3E50" \
  | jq -r '.hits[:5][]|"\(.created_at[:10]) \(.points) \(.title) https://news.ycombinator.com/item?id=\(.objectID)"'
curl -sS "https://hn.algolia.com/api/v1/search_by_date?query=QUERY&tags=story&numericFilters=created_at_i%3E1759276800"
# Stack Exchange: без ключа 300 запросов в сутки на IP
curl -sS --compressed "https://api.stackexchange.com/2.3/search/advanced?site=stackoverflow&q=QUERY&pagesize=5&sort=relevance" \
  | jq -r '.items[]|"\(.score) \(.is_answered) \(.title) \(.link)"'
```

Ссылка обсуждения HN — на сам тред, а не только на статью: опыт — в комментариях. Reddit без входа —
только RSS, с описательным User-Agent и не чаще раза в минуту; `.json` закрыт.

## Справочные факты

**Wikidata** — лицензия, версии с датами, разработчик, сайт: сверка с другими источниками, не
первоисточник (D). Без User-Agent — 403; не больше 5 запросов параллельно.

```sh
# идентификатор по названию
curl -sS -A 'deep-search (+<ссылка>)' \
  "https://www.wikidata.org/w/api.php?action=wbsearchentities&search=PostgreSQL&language=en&format=json&limit=2" \
  | jq -c '.search[]|{id,description}'
# лицензия и предпочтительная версия с датой (Q28865 — Python)
curl -sS -G -A 'deep-search (+<ссылка>)' -H 'Accept: application/sparql-results+json' \
  --data-urlencode 'query=SELECT ?licenseLabel ?ver ?date WHERE { wd:Q28865 wdt:P275 ?license . OPTIONAL { wd:Q28865 p:P348 ?st . ?st ps:P348 ?ver ; pq:P577 ?date ; wikibase:rank wikibase:PreferredRank } SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }' \
  https://query.wikidata.org/sparql | jq -c '.results.bindings[]'
```

## Наука

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
# Unpaywall: легальная открытая копия по DOI; email — настоящий адрес того, кто запускает
curl -sS "https://api.unpaywall.org/v2/DOI?email=<адрес>" | jq -c '{is_oa,oa_status,url:.best_oa_location.url}'
# Europe PMC: биомедицина, флаг открытого доступа
curl -sS "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=QUERY&format=json&pageSize=5" \
  | jq -c '.resultList.result[]|{title,pubYear,doi,isOpenAccess}'
```

Тип `retraction` в ответе Crossref — статья отозвана, не использовать. Unpaywall отвергает адреса
вида `test@example.com` (422). Semantic Scholar без ключа не отвечает (429) — OpenAlex.

## Нормативные акты

**pravo.gov.ru — официальное опубликование** (A для текста и даты): поиск по названию, только чтение.
`PageSize` — только 10, 30, 100 или 200, иначе 400.

```sh
curl -sS -G "http://publication.pravo.gov.ru/api/Documents" --data-urlencode "Name=о персональных данных" \
  -d PageSize=10 -d Index=1 | jq -c '.items[:3][]|{eoNumber,complexName,publishDateShort}'
```

Ищет подстроку в полном названии, в том числе региональных актов: уточнять название, отбирать по
`complexName`. Текст действующей редакции — ИПС «Законодательство России» (`pravo.gov.ru/proxy/ips/`): HTML в
windows-1251, `iconv -f cp1251 -t utf-8`; отвечает медленно.
