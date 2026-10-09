# Машинные каналы новостей ИИ-компаний — проверка curl

**Проверено: 2026-10-09.** Метод: `curl -sSL --max-time 30 -A 'Mozilla/5.0'`, тело разобрано скриптом
(тип: rss/atom/sitemap/json/html; число записей; дата **последней записи** — по `<item>/<entry>`, без
`lastBuildDate`/`<updated>` канала, которые часто равны «сегодня»). Сырые ответы не сохранялись.

Вердикт: **годен** — лента/JSON с датой у каждой записи; **с оговорками** — работает, но есть ловушка
(нет дат, дата не про публикацию, HTML-снимок, мусор не по теме); **не годен** — 403/404/JS/капча/устарело.

## Таблица

| Компания | Канал (тип) | Точный URL | HTTP | Формат | Даты у записей | Последняя запись | Вердикт | Заметка |
|---|---|---|---|---|---|---|---|---|
| Anthropic | RSS новостей | https://www.anthropic.com/rss.xml (и /news/rss.xml, /feed.xml) | 404 | — | — | — | не годен | RSS у anthropic.com нет |
| Anthropic | sitemap (новости+research+engineering) | https://www.anthropic.com/sitemap.xml (из robots.txt) | 200 | sitemap, 552 URL | да, `<lastmod>` у 522 | 2026-10-09 (/research/), 2026-10-08 (/news/) | годен (с оговоркой) | Фильтр по префиксу /news/, /research/, /engineering/. lastmod = дата правки, а не публикации: старый building-effective-agents имеет lastmod 2026-08-10 → новизну считать по появлению нового URL, lastmod — вторичный сигнал |
| Anthropic | HTML новостей | https://www.anthropic.com/news | 200 | HTML (SSR) | да, «Oct 7, 2026» | 2026-10-07 | с оговорками | Отдаётся без JS, даты в тексте; запасной вариант |
| Anthropic | HTML engineering | https://www.anthropic.com/engineering | 200 | HTML (SSR) | да | 2026-04-23 | с оговорками | Без JS, даты есть |
| Anthropic | Release notes платформы | https://docs.claude.com/en/release-notes/overview → https://platform.claude.com/docs/en/release-notes/overview | 200 | HTML (SSR) | да, «October 8, 2026» | 2026-10-08 | с оговорками | Редирект на platform.claude.com; RSS (`…/overview/rss.xml`) отдаёт HTML-заглушку, не ленту |
| Anthropic | GitHub releases Claude Code | https://github.com/anthropics/claude-code/releases.atom | 200 | Atom, 10 | да | 2026-10-08 | годен | Только 10 последних — при опросе раз в несколько дней релизы могут «выпасть» (выходят почти ежедневно) |
| Anthropic | Коммиты CHANGELOG.md | https://github.com/anthropics/claude-code/commits/main/CHANGELOG.md.atom | 200 | Atom, 20 | да | 2026-10-08 | годен | |
| Anthropic | raw CHANGELOG | https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md | 200 | Markdown, ~970 КБ | нет (только `## 2.1.295`) | — | с оговорками | Дат у версий нет; сравнивать верхний заголовок версии. Файл большой |
| Anthropic | Статус | https://status.anthropic.com/history.rss → https://status.claude.com/history.rss (также history.atom) | 200 | RSS, 25 | да | 2026-10-07 | годен | Atlassian Statuspage; редирект на status.claude.com |
| Anthropic | SDK Python releases | https://github.com/anthropics/anthropic-sdk-python/releases.atom | 200 | Atom, 10 | да | 2026-10-08 | годен | |
| OpenAI | RSS новостей | https://openai.com/news/rss.xml (/blog/rss.xml → редирект сюда) | 200 | RSS, 1259 | да | 2026-10-09 | годен | Вся история с 2015 (~большой файл); `<category>` есть: Research, Product, Safety, Company… — research фильтровать по ней |
| OpenAI | RSS research | https://openai.com/research/index/rss.xml | 403 | — | — | — | не годен | Отдельной ленты research нет; брать из news/rss.xml по category=Research |
| OpenAI | sitemap | https://openai.com/sitemap.xml | 200 | sitemapindex, 42 подкарты | нет lastmod в индексе | — | с оговорками | Не нужен при наличии RSS |
| OpenAI | Changelog API | https://platform.openai.com/docs/changelog → https://developers.openai.com/api/docs/changelog | 200 | HTML (SSR) | да, «October 5, 2026» | 2026-10-05 | с оговорками | Редирект на developers.openai.com; в тексте есть и будущие даты (дедлайны deprecation) — брать дату заголовка записи |
| OpenAI | Страница моделей | https://platform.openai.com/docs/models → https://developers.openai.com/api/docs/models | 200 | HTML (SSR) | почти нет (3 даты) | — | с оговорками | Только сравнение снимков списка моделей |
| OpenAI | Статус | https://status.openai.com/history.rss | 200 | RSS, 111 | да | 2026-10-08 | годен | |
| OpenAI | GitHub releases | https://github.com/openai/openai-python/releases.atom ; https://github.com/openai/codex/releases.atom | 200 | Atom, 10 | да | 2026-10-08 / 2026-10-09 | годен | Codex — несколько релизов в день, 10 записей ≈ 2 дня |
| Google DeepMind | RSS блога | https://deepmind.google/blog/rss.xml | 200 | RSS, 100 | да | 2026-10-06 | годен (ловушка) | **curl без `--compressed` получает gzip-тело** (Content-Encoding: gzip без запроса); urllib в проверке получил plain XML. В скрипте: если тело начинается с `\x1f\x8b` — `gzip.decompress` |
| Google DeepMind | blog.google, раздел DeepMind | https://blog.google/technology/google-deepmind/rss/ → https://blog.google/innovation-and-ai/models-and-research/google-deepmind/rss/ | 200 | RSS, 20 | да | 2026-10-07 | годен | Старый адрес редиректит; urllib редиректы проходит |
| Google | blog.google AI | https://blog.google/technology/ai/rss/ → …/innovation-and-ai/technology/ai/rss/ | 200 | RSS, 20 | да | 2026-10-07 | годен | |
| Google | Developers Blog | https://developers.googleblog.com/feeds/posts/default | 200 | RSS, 20 | **нет** (в item только title/link/description/guid) | — | с оговорками | Новизну — только по guid; дата лишь в lastBuildDate канала |
| Google Gemini API | Changelog | https://ai.google.dev/gemini-api/docs/changelog | 200 | HTML (SSR) | да, «October 8, 2026» | 2026-10-08 | с оговорками | Ленты нет (feeds/…xml → 404); в тексте есть будущие даты (отключения моделей) |
| Google Gemini API | GitHub releases | https://github.com/googleapis/python-genai/releases.atom ; https://github.com/google-gemini/gemini-cli/releases.atom | 200 | Atom, 10 | да | 2026-10-07 / 2026-10-08 | годен | |
| Meta AI | HTML блога | https://ai.meta.com/blog/ | 200 | HTML | да, «Jul 27, 2026» | 2026-07-27 (видимая) | с оговорками | Ссылки на посты (~10) и даты в тексте есть; RSS /blog/rss/ → 404 |
| Meta AI | sitemap | https://ai.meta.com/sitemap/ai_meta_com_sitemap.xml.gz (из robots.txt) | 403 | — | — | — | не годен | robots.txt: «сбор автоматическими средствами запрещён» |
| Meta | Engineering blog | https://engineering.fb.com/feed/ | 200 | RSS, 9 | да | 2026-10-06 | с оговорками | Не только ИИ — нужен фильтр по категории/словам |
| Meta | Hugging Face | https://huggingface.co/api/models?author=facebook&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да, createdAt | 2026-09-30 | годен | `author=meta-llama` тоже работает, но последняя модель 2025-04-28 |
| Meta | GitHub | https://github.com/meta-llama/llama-models/releases.atom | 200 | Atom, 10 | да | 2025-04-05 | с оговорками | Работает, но репозиторий затих с 2025 |
| Mistral AI | RSS новостей | https://mistral.ai/rss.xml → https://mistral.ai/news/rss | 200 | RSS, 89 | да | 2026-10-06 | годен | |
| Mistral AI | Changelog документации | https://docs.mistral.ai/getting-started/changelog → https://docs.mistral.ai/resources/changelogs | 200 | HTML (SSR) | да, но мало (4 даты) | 2026-09-30 | с оговорками | RSS-варианта нет (404) |
| Mistral AI | Hugging Face | https://huggingface.co/api/models?author=mistralai&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-07-16 | годен | |
| Mistral AI | GitHub | https://github.com/mistralai/client-python/releases.atom | 200 | Atom, 10 | да | 2026-10-09 | годен | |
| xAI | Новости | https://x.ai/news ; https://x.ai/sitemap.xml | 403 | Cloudflare «Attention Required» | — | — | не годен | robots.txt (200) указывает sitemap, но сам sitemap тоже 403 |
| xAI | Release notes | https://docs.x.ai/docs/release-notes → https://docs.x.ai/developers/release-notes | 200 | HTML (SSR) | частично: «October 2» под заголовком месяца, **без года** | ~2026-10-02 | с оговорками | Год выводить из контекста; RSS (…/rss.xml) → 404. Бренд на странице — «SpaceXAI» |
| xAI | Hugging Face | https://huggingface.co/api/models?author=xai-org&sort=createdAt&direction=-1&limit=5 | 200 | JSON, 2 | да | 2025-08-22 | с оговорками | Работает, но почти пусто |
| xAI | GitHub | https://github.com/xai-org/xai-sdk-python/releases.atom | 200 | Atom, 10 | да | 2026-09-24 | годен | Только SDK |
| DeepSeek | Hugging Face | https://huggingface.co/api/models?author=deepseek-ai&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-09-10 | годен | Главный сигнал о новых моделях |
| DeepSeek | GitHub org (API) | https://api.github.com/orgs/deepseek-ai/repos?sort=created&direction=desc&per_page=5 | 200 | JSON | да, created_at/pushed_at | 2026-09-30 | годен | Лимит API без токена — 60 запросов/час на IP |
| DeepSeek | Новости API-доков | https://api-docs.deepseek.com/updates | 200 | HTML (SSR, Docusaurus) | да, «2026-09-10» | 2026-09-10 | с оговорками | RSS нет: /news/rss.xml отдаёт HTML-заглушку SPA с кодом 200 (ловушка: 200 ≠ лента) |
| DeepSeek | sitemap доков | https://api-docs.deepseek.com/sitemap.xml | 200 | sitemap, 52 URL | **нет lastmod** | — | с оговорками | Новые /news/newsMMDD видны как новые URL (год в URL отсутствует); robots.txt отдаёт HTML-заглушку |
| DeepSeek | Коммиты репо | https://github.com/deepseek-ai/DeepSeek-V3/commits/main.atom | 200 | Atom, 20 | да | 2025-08-28 | с оговорками | Работает, но репо затих; лучше org API |
| Alibaba Qwen | Старый блог (Hugo) | https://qwenlm.github.io/blog/index.xml | 200 | RSS, 44 | да | 2025-09-23 | не годен | Лента жива, но **заброшена** — блог переехал на qwen.ai |
| Alibaba Qwen | Новый блог | https://qwen.ai/research | 200 | HTML-оболочка SPA (6 символов текста) | — | — | не годен | JS-only; robots.txt и sitemap.xml редиректят на главную |
| Alibaba Qwen | Hugging Face | https://huggingface.co/api/models?author=Qwen&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-09-20 | годен | |
| Alibaba Qwen | GitHub org (API) | https://api.github.com/orgs/QwenLM/repos?sort=created&direction=desc&per_page=5 | 200 | JSON | да | 2026-09-29 | годен | |
| Alibaba Qwen | GitHub releases | https://github.com/QwenLM/qwen-code/releases.atom | 200 | Atom, 10 | да | 2026-10-09 | годен | `QwenLM/Qwen3/releases.atom` — 200, но **0 записей** (релизов нет) |
| Moonshot / Kimi | Changelog платформы (Mintlify RSS) | https://platform.kimi.ai/docs/platform-changelog/rss.xml | 200 | RSS, 15 | формально да, но **одна дата на все** (2026-09-16) | записи помесячные («September 2026») | с оговорками | Item = месяц; pubDate не информативен → сравнивать хеш description. Также .md: https://platform.kimi.ai/docs/platform-changelog.md (найден через /docs/llms.txt) |
| Moonshot / Kimi | Блог | https://www.kimi.com/blog → https://www.kimi.ai/blog/ | 200 | HTML | да, «2026-07-16» | 2026-07-16 | с оговорками | rss.xml/feed.xml редиректят на HTML |
| Moonshot / Kimi | Hugging Face | https://huggingface.co/api/models?author=moonshotai&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-06-13 | годен | |
| Moonshot / Kimi | GitHub | https://api.github.com/orgs/MoonshotAI/repos?sort=created&direction=desc&per_page=5 ; https://github.com/MoonshotAI/kimi-cli/releases.atom | 200 | JSON / Atom | да | 2026-07-27 (репо) / 2026-09-22 | годен | |
| Zhipu / Z.ai | Release notes (Mintlify RSS) | https://docs.z.ai/release-notes/new-released/rss.xml | 200 | RSS, 15 | да | 2026-08-26 | годен | lastBuildDate = сегодня, не путать с датой записи. HTML: https://docs.z.ai/release-notes/new-released |
| Zhipu / Z.ai | Блог | https://z.ai/blog | 404 | — | — | — | не годен | |
| Zhipu / Z.ai | Hugging Face | https://huggingface.co/api/models?author=zai-org&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-08-25 | годен | Организация zai-org (бывш. THUDM) |
| Zhipu / Z.ai | GitHub org (API) | https://api.github.com/orgs/zai-org/repos?sort=created&direction=desc&per_page=5 | 200 | JSON | да | 2026-09-20 | годен | |
| MiniMax | Новости | https://www.minimax.io/news | 200 | HTML-оболочка (≈600 символов) | — | — | не годен | JS; /news/rss.xml → 404; sitemap.xml (200) — только 9 разделов, без статей |
| MiniMax | Release notes моделей | https://platform.minimax.io/docs/release-notes/models | 200 | HTML (SSR) | да, «Jul. 31, 2026» | 2026-07-31 | с оговорками | RSS-варианта нет (404) |
| MiniMax | Hugging Face | https://huggingface.co/api/models?author=MiniMaxAI&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-08-07 | годен | |
| MiniMax | GitHub org (API) | https://api.github.com/orgs/MiniMax-AI/repos?sort=created&direction=desc&per_page=5 | 200 | JSON | да | 2026-10-02 | годен | |
| Cohere | Changelog (Fern RSS) | https://docs.cohere.com/v2/changelog.rss | 200 | RSS, 65 | да | 2026-09-30 | годен | `/changelog/rss.xml` → 404; правильный суффикс `.rss` |
| Cohere | sitemap (блог) | https://cohere.com/sitemap.xml | 200 | sitemap, 820 URL | да, lastmod у всех | 2026-10-06 (/blog/) | годен (с оговоркой) | 420 URL /blog/ включая локали /fr/, /ja/… — отфильтровать; /blog/rss.xml редиректит на HTML |
| Cohere | Hugging Face | https://huggingface.co/api/models?author=CohereLabs&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-09-08 | годен | |
| Cohere | GitHub | https://github.com/cohere-ai/cohere-python/releases.atom | 200 | Atom, 10 | да | 2026-09-28 | годен | |
| Microsoft AI | Новости microsoft.ai | https://microsoft.ai/news/ ; https://microsoft.ai/feed/ | 403 | Cloudflare | — | — | не годен | Страницы и WP-ленты закрыты |
| Microsoft AI | sitemap новостей (WP/Yoast) | https://microsoft.ai/new-sitemap.xml (индекс https://microsoft.ai/sitemap_index.xml) | 200 | sitemap, 34 URL | да | 2026-10-08 | годен | **Страницы 403, а sitemap отдаётся.** Модели: https://microsoft.ai/model-sitemap.xml (7 URL, 2026-10-08). Имя подкарты «new-», не «news-» (news-sitemap.xml → 404) |
| Microsoft | Research feed | https://www.microsoft.com/en-us/research/feed/ | 403 | — | — | — | не годен | Также news.microsoft.com/source/feed/ → 403 |
| Microsoft | Azure blog | https://azure.microsoft.com/en-us/blog/feed/ | 200 | RSS, 10 | да | 2026-10-07 | с оговорками | Не только ИИ |
| Microsoft | Foundry devblog | https://devblogs.microsoft.com/foundry/feed/ | 200 | RSS, 10 | да | 2026-10-07 | годен | |
| Microsoft (Phi) | Hugging Face | https://huggingface.co/api/models?author=microsoft&search=Phi&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-05-07 | годен | Без search: 2026-09-21 |
| Amazon (Nova) | Сайт Nova | https://nova.amazon.com/ | 200 | HTML-оболочка (60 символов) | — | — | не годен | JS-only |
| Amazon | AWS What's New | https://aws.amazon.com/about-aws/whats-new/recent/feed/ | 200 | RSS, 100 | да | 2026-10-08 | с оговорками | ~100 записей за ~10 дней по всему AWS — фильтровать по «Nova»/«Bedrock» |
| Amazon | AWS ML blog / News blog | https://aws.amazon.com/blogs/machine-learning/feed/ ; https://aws.amazon.com/blogs/aws/feed/ | 200 | RSS, 20 | да | 2026-10-08 / 2026-10-06 | с оговорками | Нужен фильтр по Nova |
| Amazon | Amazon Science | https://www.amazon.science/index.rss | 200 | RSS, 25 | да | 2026-10-01 | годен | |
| Amazon | Hugging Face | https://huggingface.co/api/models?author=amazon&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-10-02 | годен | |
| NVIDIA | Hugging Face (Nemotron) | https://huggingface.co/api/models?author=nvidia&search=Nemotron&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-09-04 | годен | Без search: 2026-10-09 (очень много моделей) |
| NVIDIA | Developer blog | https://developer.nvidia.com/blog/feed | 200 | Atom, 100 | да | 2026-10-09 | годен | |
| NVIDIA | Корп. блог | https://blogs.nvidia.com/feed/ | 200 | RSS, 18 | да | 2026-10-08 | годен | |
| NVIDIA | Research | https://research.nvidia.com/rss.xml | 200 | RSS, 10 | да | 2026-10-05 | годен | |
| Hugging Face | Блог | https://huggingface.co/blog/feed.xml | 200 | RSS, 876 | да | 2026-10-08 | годен | Полная история с 2020 (большой файл) |
| Hugging Face | GitHub transformers | https://github.com/huggingface/transformers/releases.atom | 200 | Atom, 10 | да | 2026-10-06 | годен | |
| Яндекс | Блог на Хабре | https://habr.com/ru/rss/companies/yandex/articles/ (старый /rss/company/yandex/blog/ редиректит) | 200 | RSS, 40 | да | 2026-10-07 | годен | Не только ИИ — фильтр по YandexGPT/Алиса/нейросеть |
| Яндекс | Новости компании | https://yandex.ru/company/news | 200 | HTML | дата в URL `/company/news/DD-MM-YYYY-NN` | 2026-10-09 | с оговорками | RSS не найден; парсить ссылки (9 на странице) |
| Яндекс | Release notes AI Studio / Cloud | https://yandex.cloud/ru/docs/foundation-models/release-notes ; https://aistudio.yandex.ru/docs/ru/ai-studio/release-notes/ ; https://yandex.cloud/ru/blog | 200 после редиректа на капчу | HTML «Are you not a robot?» | — | — | не годен | **SmartCaptcha** на curl |
| Яндекс | Hugging Face | https://huggingface.co/api/models?author=yandex&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-09-12 | годен | `search=YandexGPT` → последняя 2025-03-28 |
| Сбер (GigaChat) | Changelog API | https://developers.sber.ru/docs/ru/gigachat/changelog | 200 | HTML (SSR) | да, «06.10.2026» | 2026-10-06 | с оговорками | Найден через docs/sitemap.xml; также https://developers.sber.ru/docs/ru/gigachat/models/updates (даты «24 июля 2026»/дд.мм.гггг) |
| Сбер | sitemap доков | https://developers.sber.ru/docs/sitemap.xml | 200 | sitemap, 2090 URL | нет lastmod | — | не годен для новизны | Только для поиска адресов |
| Сбер | Блоги на Хабре | https://habr.com/ru/rss/companies/sberdevices/articles/ ; https://habr.com/ru/rss/companies/sberbank/articles/ | 200 | RSS, 40 | да | 2026-10-01 / 2026-10-08 | годен | Нужен фильтр по GigaChat |
| Сбер | Hugging Face | https://huggingface.co/api/models?author=ai-sage&sort=createdAt&direction=-1&limit=5 | 200 | JSON | да | 2026-09-07 | годен | |
| Сбер | GitHub | https://github.com/ai-forever/gigachat/releases.atom ; https://api.github.com/orgs/ai-forever/repos?sort=created&direction=desc&per_page=5 | 200 | Atom / JSON | да | 2026-07-31 (releases) | годен | |

## Нет машинного канала для собственных новостей

Ни одна из 19 компаний не осталась совсем без машинного канала: у каждой работает хотя бы Hugging Face
API или GitHub. Но **собственные новости/блог** у этих компаний доступны только как HTML или не доступны вовсе:

- **xAI** — x.ai/news и sitemap: 403 Cloudflare. Есть только HTML release notes на docs.x.ai (без года у записей), GitHub SDK и почти пустой HF.
- **Meta AI** — блог только HTML (ai.meta.com/blog/), RSS 404, sitemap 403. Модели видны через HF `facebook`.
- **Alibaba Qwen** — qwen.ai — JS-оболочка SPA, старый RSS заброшен с 2025-09-23. Остаются HF и GitHub.
- **MiniMax** — новости на JS, release notes только HTML. Остаются HF и GitHub.
- **DeepSeek** — новости только HTML (`/updates`), sitemap без lastmod. Остаются HF и GitHub.
- **Moonshot / Kimi** — блог только HTML. Changelog есть как RSS, но записи помесячные и без собственных дат.
- **Google Gemini API** — changelog только HTML (блоги Google при этом с RSS).
- **Amazon Nova** — nova.amazon.com на JS. Новости Nova приходят только через общие ленты AWS с фильтром.
- **Яндекс** — RSS новостей компании нет (только HTML со ссылками, в которых есть дата). Документация Cloud/AI Studio закрыта капчей. Из лент остаётся Хабр.
- **Сбер GigaChat** — changelog только HTML, из лент остаётся Хабр.
- **Anthropic** (частично) — RSS нет, но sitemap с lastmod покрывает news/research/engineering. Release notes платформы только HTML.

## Главные ловушки для скрипта на stdlib

1. **200 ≠ лента.** Некоторые адреса лент отвечают 200, но отдают HTML-заглушку SPA или редиректят на HTML-страницу: api-docs.deepseek.com/news/rss.xml, platform.claude.com/…/rss.xml, cohere.com/blog/rss.xml, kimi.ai/blog/rss.xml, qwen.ai/sitemap.xml. Проверять корневой тег (`<rss`/`<feed`/`<urlset`), а не код ответа.
2. **gzip без запроса.** deepmind.google/blog/rss.xml отдаёт curl'у тело в gzip. Проверять магию `\x1f\x8b` и распаковывать.
3. **Дата канала вместо даты записи.** `lastBuildDate` и `<updated>` фида часто равны «сегодня» (Z.ai, статус-страницы). Дату брать из item/entry.
4. **Нет дат у записей.** Google Developers Blog, raw CHANGELOG Claude Code, sitemaps DeepSeek и Сбера, Kimi changelog (одна дата на все месячные записи). Новизну определять по guid/URL/хешу.
5. **lastmod — дата правки.** Это не дата публикации (Anthropic sitemap).
6. **403 Cloudflare:** x.ai, microsoft.ai (страницы и /feed/), microsoft.com/research/feed, news.microsoft.com. **Капча:** yandex.cloud, aistudio.yandex.ru. **Запрет в robots.txt:** ai.meta.com, у которого sitemap тоже отдаёт 403.
7. **Обход через sitemap.** microsoft.ai: страницы отдают 403, но sitemap отдаётся (new-sitemap.xml, model-sitemap.xml).
8. **Окно в 10 записей у GitHub releases.atom.** Claude Code и Codex выпускают релизы ежедневно, поэтому при опросе раз в 3+ дня часть записей пропадает. Добирать по коммитам CHANGELOG.md.atom. Репозиторий без релизов отдаёт пустую ленту с кодом 200 (QwenLM/Qwen3).
9. **Лимит GitHub REST API без токена — 60 запросов в час.** Atom-ленты под этот лимит не попадают.
10. **Будущие даты в changelog.** На страницах OpenAI, Gemini и xAI это даты отключения моделей, их нельзя брать как дату записи. У xAI в записях нет года.
11. **Ленты общего профиля** (AWS What's New, Azure, Хабр, engineering.fb.com) нужно фильтровать по ключевым словам.
