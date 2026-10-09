# Проверка источников: ленты ИИ, агрегаторы, API общего назначения

Дата: 2026-10-09. Статус: **заморожено**. Решения — в
[спецификации](../../docs/specs/2026-10-05-deep-search-design.md) и в
[README](../../README.md), раздел «История решений»; если отчёт расходится с ними, действуют они.

Вопрос: какие источники работают без ключа, без входа и без браузера — для мониторинга новинок ИИ и
для пробелов набора источников, найденных при описании раздела 5.5
[руководства](../../docs/guide.md).

Метод: четыре субагента, у каждого свой список кандидатов. «Работает» — только по настоящему ответу
`curl` в день проверки; лимиты — по официальной странице со ссылкой или по заголовкам ответа (так и
помечено). Выборочно перепроверено вручную: OpenRouter, Hacker News, Telegram, Codeberg, статьи дня
Hugging Face, карта сайта Anthropic, Semantic Scholar.

| Файл | Тема |
|---|---|
| `01-labs.md` | первоисточники 19 компаний ИИ: RSS и Atom, карты сайта, выпуски GitHub, организации Hugging Face, журналы изменений |
| `02-aggregators-telegram.md` | агрегаторы по всей отрасли (OpenRouter, Hugging Face, arXiv, Hacker News, LMArena, Epoch AI, рассылки, Reddit, реестр MCP) и Telegram-каналы |
| `03-general.md` | хостинги кода кроме GitHub, Repology, Software Heritage, Stack Exchange, Unpaywall, Semantic Scholar, поиск по коду, Wikidata, архивы, КиберЛенинка, pravo.gov.ru |
| `04-telegram-lateral.md` | боковое чтение 17 Telegram-каналов: кто автор, независимые упоминания, признаки против; имена авторов опущены |

## Коротко

- Машинный канал без ключа есть у всех 19 компаний (хотя бы Hugging Face или GitHub); своя лента
  или карта сайта с датами — у 13. Без своей ленты — xAI, Meta, Qwen, MiniMax, DeepSeek.
- Агрегаторы без ключа: OpenRouter, Hugging Face (тренды, статьи дня), Hacker News, arXiv, данные
  LMArena, каталоги Epoch AI, рассылки с RSS. Telegram читается без входа через `t.me/s/<канал>`.
- Общего назначения без ключа: Codeberg и Forgejo, Repology, Wikidata, Europe PMC, API
  опубликования pravo.gov.ru; с оговорками — GitLab, Gitee, Stack Exchange, Unpaywall, Software
  Heritage, Sourcegraph, grep.app, Wayback CDX.
- Не годны без ключа: Semantic Scholar, Artificial Analysis, GitHub code search, GitFlic, Save Page
  Now; не годны совсем: Papers with Code, публичный RSSHub, archive.today.
- Ловушки для кода: код 200 не значит лента — проверять корневой тег; gzip без запроса; Cloudflare
  и капчи; даты записей ненадёжны (дата правки, будущие даты, без года); у `releases.atom` только 10
  записей; часть API требует описательный User-Agent и отвечает 403 на браузерный.
