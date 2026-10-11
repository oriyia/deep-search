# Откуда без задержки узнавать о новинках ИИ, которые сначала появляются в X и Discord, и какие авторские каналы дают своё содержание

Прогон `2026-10-11-ai-early-signals` · отчёт 2026-10-11 · уровень L · пресет ai · неисчерпывающий

Копия отчёта прогона. Бриф, план, ответы веток с уликами (`branches/`), протокол проверки
(`verify.md`) — в папке прогона `runs/2026-10-11-ai-early-signals/` библиотеки deep-search;
утверждения — `claims/ai-early-signals.md`, карточка — `topics/ai-early-signals.md` там же.
Ссылки на профили авторов Telegram-каналов в копии опущены. Заморожено, не правится.

## 1. Бриф и отклонения

Ищем, откуда мониторинг watch узнаёт о новинках ИИ так же рано, как X и Discord, и какие авторские
источники дают своё содержание. Два класса со своей меркой: «скорость» — раньше текущих лент,
«содержание» — своё, чего нет в других. Пути с ключом или входом оцениваются вместе с открытыми.
Главная мерка — ретроспектива: 13 выходов за сентябрь — октябрь 2026, отставание 68 текущих лент и
кандидатов от первого сообщения. Ответ — таблица кандидатов; набор не правится без решения
сопровождающего. Бриф — `brief.md`.

Отклонения:
- 2026-10-11 · budget · 120 → 170 · раунд 1 занял 89 (74 %), ретроспективе нужна история лент
- 2026-10-11 · budget · 170 → 185 · после B5 и проверки V1–V3 потрачено 178; выборка B5 (V4)

## 2. Сводка

**Ответ:** на официальных анонсах X почти не опережает ленты, которые watch уже читает: по 13
выходам медиана поста лаборатории в X — +0,3 ч от первого сообщения, первым X был 1 раз из 9, а
Hacker News — 9 раз из 13, OpenRouter — медиана +0,2 ч, Telegram-каналы набора — +0,4 ч без пропусков
`A2` (B5:ev1, B5:ev2, B5:ev3, B5:ev7). X опережает только до анонса — утечками; их открыто пересказывает
TestingCatalog: заранее в 6 из 13 событий, за 6 ч — 9 дней `A2` (B5:ev13), первоисточник утечек — посты
X, содержание — слухи `E` (B1:ev1, проверено частично). Прямой доступ к X без нарушения условий — только
платный X API ($0.005 за прочитанный пост `A1`, B2:ev2); Nitter, xcancel, RSSHub для X и чтение чужих
серверов Discord своим аккаунтом нарушают условия или не работают `A1` (B2:ev5, B2:ev6, B2:ev13,
B2:ev23). Важнее X — дыры самого набора: лента anthropic-site пропустила все 4 выхода моделей
Anthropic (B5:ev12), порог hn 100 очков задерживает самый быстрый источник. Суждение: брать X API
сейчас не нужно — очень вероятно.

- Цель полноты: representative, 5–10 кандидатов на класс · остановка: выполнены done_criteria;
  бюджет 185 исчерпан почти полностью
- Поток: найдено 69 → дубли 0 → просмотрено 61 → оставлено 8 новых лент и 4 правки набора
- Не просмотрено: 8 Telegram-каналов из конфигов агрегаторов (B3 gaps); Discord не измерялся;
  время X — нижняя граница по ссылкам в рассылках, не первый пост

## 3. Ответы по подвопросам

### Открытые источники ранних сигналов — покрытие 1

- Факты: testingcatalog.com/rss — RSS с pubDate без входа, 100 записей за 46 дней — `A1`,
  [TestingCatalog RSS](https://www.testingcatalog.com/rss/), 2026-10-11 (B1:ev3, проверено «да»)
- Факты: зеркала X на Bluesky `*.xmirror.bot` — неофициальные, RSS с pubDate, без title; время поста
  совпадает с X до 2–3 мин; есть для anthropicai, openai, xai — `A2` (B1:ev7, B1:ev8, B5:ev5, B5:ev6)
- Факты: лаборатории на Bluesky и Mastodon почти не пишут (anthropic.com — 0 постов,
  huggingface@mastodon.social — 0) — `A2` (B1:ev6, B1:ev13, проверено «да»)
- Факты: Techmeme, LiteLLM, models.dev, LLMLearner запаздывают; Reddit без фильтра — 160–730
  записей в неделю — `A2` (B1:ev10, B1:ev5, B1:ev14, B1:ev15)
- Суждение: из открытых источников ранний сигнал до анонса даёт только TestingCatalog — вероятно

### Доступ к X и Discord с ключом или входом — покрытие 1

- Факты: X API — pay-per-use, $0.005 за прочитанный пост, свои данные $0.001 — `A1`
  ([docs.x.com](https://docs.x.com/x-api/getting-started/pricing), B2:ev2, проверено «да»)
- Факты: условия X запрещают crawling и scraping без письменного согласия — `A1` (B2:ev5, «да»)
- Факты: xcancel отвечает 451; репозиторий Nitter в архиве после требований X Corp. — `A1`
  (B2:ev6, B2:ev13, «да»); свой Nitter и маршрут twitter в RSSHub требуют данных аккаунта X — `A1`
  (B2:ev15, B2:ev18, «да» и «частично»)
- Факты: Telegram API бесплатен, но нужен аккаунт с телефоном; аккаунты неофициальных клиентов под
  наблюдением — `A1` (B2:ev7, «да»)
- Факты: Discord запрещает автоматизацию пользовательских аккаунтов — `A1` (B2:ev23, «да»); законный
  путь — Follow Announcement Channel в канал своего сервера, нужно MANAGE_WEBHOOKS — `A2` (B2:ev26,
  «частично»: что сервер свой, страница прямо не говорит)
- Допущение: 50 авторов × 10 постов в день ≈ $75 в месяц — арифметика ветки, `E`
- Суждение: из путей с входом приемлем только X API; остальное — риск бана или нарушение условий —
  почти наверняка

### Методы поиска авторских Telegram-каналов и кандидаты — покрытие 1

- Факты: лучший метод — поиск кода GitHub по конфигам чужих агрегаторов (каналы, которые
  перечисляют вместе с каналами набора) — `D3` (B3:ev2–ev5); граф цитирований по t.me/s разрежен;
  страница t.me/addlist показывает только число чатов — `A2` (B3:ev1, B3:ev6, «да»); awesome-списков
  нет, Telemetr закрыт Cloudflare (B3 gaps)
- Факты: авторство подтверждено ссылками на канал в README профилей автора у senior_augur, doomgrad,
  partially_unsupervised, stuffyNLP (команда NLP Яндекса) — `C2` (B3:ev17–ev20, «да»); elkornacio —
  бейдж «Telegram Follow» в README автора — `C3` (B3:ev21, «частично»)
- Факты: авторских каналов о Сбере не найдено (B3 gaps)
- Суждение: elkornacio — быстрый, но в ретроспективе отметил 3 из 11 событий — канал на пробу,
  не опора — вероятно

### Авторские источники вне Telegram — покрытие 1

- Факты: X больше всех пересказывают Zvi (46,3 % ссылок на x.com, ~6,5 выпуска в неделю) и Ben's
  Bites (41 %) — `A2` (B4:ev1, «да»; B4:ev2)
- Факты: The Rundown, The Neuron, TLDR AI — ежедневные редакционные; x.com 4–16 %; реклама; у TLDR
  в RSS нет description — `A2` (B4:ev3, B4:ev8, B4:ev6 «частично»)
- Факты: по ретроспективе рассылки отстают от первого сообщения: TLDR 6,6 ч, Rundown 16,2, Neuron
  16,4, Ben's Bites 43,2, Zvi 47,0, Transformer 70,1; Marcus и Exponential View о выходах не пишут —
  `A2` (B5:ev18, B5:ev20)
- Суждение: рассылкам место только в классе «содержание»; редакционные ежедневные медленнее набора
  и подпадают под исключение «пересказчики» — очень вероятно

### Отставание текущих лент и кандидатов от первоисточника — покрытие 1

- Факты: 13 событий × 28 источников, таблица — `branches/B5.md`, «Таблица событие × источник».
  Медиана отставания, ч: HN 0,0 (первым 9 раз); блог поставщика 0,0 (2 раза, 7 пропусков);
  OpenRouter 0,2; GitHub-выпуски CLI 0,2; X лаборатории 0,3; Telegram набора 0,4 (0 пропусков);
  TestingCatalog 4,5 после анонса, но до анонса в 6 случаях; рассылки набора 11,4 — `A2` (B5:ev1–ev13)
- Факты: anthropic-site берёт из sitemap только `/news/`, `/research/`, `/engineering/` (конфиг
  presets/ai-feeds.json) и пропустил все 4 выхода моделей Anthropic — `A1` (B5:ev12)
- Факты: у openai-news 1195 из 1287 pubDate (93 %) ровно на начале часа (V4) — время только как дата — `A2` (B5:ev11)
- Допущение: время X — по ссылкам в рассылках, это нижняя граница; Discord не измерялся
- Суждение: размер пробела с X на официальных анонсах — меньше часа; пробел есть на утечках и на
  том, что публикуется только в X — почти наверняка

## 4. Объекты

| id | объект | утверждение | код | первичный источник, дата | улики | проверка |
|---|---|---|---|---|---|---|
| F1 | testingcatalog-feed | https://www.testingcatalog.com/rss/ — да: curl 200 text/xml, RSS, pubDate; без входа и ключа; ~15 записей/нед (100 за 46 дней); утечки, кодовые имена, тесты до анонса | A1 | https://www.testingcatalog.com/rss/ | B1:ev3 | да |
| F2 | testingcatalog-early | TestingCatalog 2026-09-21 08:45Z пересказал как слух («Rumor has it») пост из X от 2026-09-20 о тестировании Opus 5.5 под именем claude-wafer-eap; в OpenRouter модель появилась 2026-09-22 16:32Z. Первоисточник — X, TestingCatalog — быстрый пересказ утечек X | E2 | https://www.testingcatalog.com/anthropic-tests-fable-5-2-and-opus-5-5-ahead-of-the-release/ | B1:ev1; B1:ev2; B1:ev3; B1:ev4 | частично |
| F3 | bsky-xmirror | bsky.app/profile/anthropicai.xmirror.bot/rss и openai.xmirror.bot — условно да: 200 application/xml, RSS, pubDate; ~20–27/нед; неофициальные; пост 2026-10-09 22:06Z — одновременно с блогом; есть посты только из X | A2 | https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles | B1:ev7; B1:ev8 | да |
| F4 | bsky-labs-silent | Лаборатории на Bluesky не пишут: anthropic.com — 0 постов, hf.co — 3, karpathy — 20, openai.com/mistral.ai/googledeepmind не найдены; пишут ai2 (~3/нед), natolambert (~5/нед), emollick, timkellogg — да как вторичный сигнал | A2 | https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles (25 handle) | B1:ev6 | да |
| F5 | bsky-rss-format | RSS профиля Bluesky: без title, только description; pubDate без дня недели и секунд («09 Oct 2026 13:16 +0000»); email.utils разбирает; JSON — public.api.bsky.app getAuthorFeed (createdAt), без ключа | A1 | https://bsky.app/profile/simonwillison.net/rss | B1:ev9 | — |
| F6 | techmeme-late | techmeme.com/feed.xml — нет как ранний сигнал: 200 RSS pubDate, ~130/нед, ИИ — 7 из 15; Decision-1 — 2026-10-11 05:05Z против TestingCatalog 10-09 21:48Z (+31 ч) | A2 | https://www.techmeme.com/feed.xml | B1:ev10; B1:ev11 | да |
| F7 | sdk-ids-late | LiteLLM model_prices…json.atom (200 Atom, updated, ~97/нед) — нет: Opus 5.5 добавлен 2026-09-22 16:52Z, через 20 мин после OpenRouter; models.dev dev.atom — автосинхронизация OpenRouter, нет | A2 | https://openrouter.ai/api/v1/models | B1:ev4; B1:ev5; B1:ev16 | — |
| F8 | reddit-feeds | r/singularity, r/OpenAI, r/ClaudeAI /new/.rss — условно: 200 Atom, поле updated; 160 / 300 / 730 записей в неделю; 429 при частоте выше раза в минуту; пример раннего сигнала не измерен | A2 | https://www.reddit.com/r/singularity/new/.rss, /r/OpenAI/new/.rss, /r/ClaudeAI/new/.rss | B1:ev15 | — |
| F9 | mastodon-weak | Mastodon — нет: на sigmoid.social активны академики без лабораторий; локальная лента — спам; тег /tags/llm.rss ~660/нед — шум; huggingface@mastodon.social — 0 постов | A2 | https://sigmoid.social/api/v1/directory?local=true&order=active&limit=40 | B1:ev12; B1:ev13 | да |
| F10 | llmlearner-no | llmlearner.com/feed.xml (бывший DataLearner) — нет: 200 RSS, только «released» и рейтинги, даты 00:00; /rumors — только HTML | A2 | https://llmlearner.com/feed.xml | B1:ev14 | — |
| F11 | x-api-paid | X API: pay-per-use без подписок; Posts Read $0.005, User Read $0.010; предел 3 млн постов в месяц; повторное чтение за сутки (UTC) не тарифицируется | A1 | https://docs.x.com/x-api/getting-started/pricing | B2:ev1; B2:ev2; B2:ev3; B2:ev4 | да |
| F12 | x-scrape-tos | ToS X (с 2026-10-09) прямо запрещают crawling и scraping без письменного согласия | A1 | https://x.com/en/tos | B2:ev5 | да |
| F13 | xcancel-dead | xcancel приостановлен «до дальнейшего уведомления» из-за судебного разбирательства; /<user>/rss отвечает HTTP 451 | A1 | https://xcancel.com/OpenAI/rss | B2:ev6 | да |
| F14 | nitter-legal | Nitter: C&D от X Corp 2026-08-24 и 2026-09-08; GitHub-репозиторий archived 2026-10-09; nitter.net без юриста, RSS 410 | A1 | https://raw.githubusercontent.com/zedeus/nitter/master/README.md | B2:ev12; B2:ev13; B2:ev14 | да |
| F15 | nitter-public | Публичные инстансы Nitter работают частично: по status.d420.de 2026-10-11 healthy+rss — несколько; проверка RSS @OpenAI: 1 из 3 отдал 21 пост (последний 2026-10-09); RSS «часто отключают из-за злоупотреблений» | B2 | https://raw.githubusercontent.com/zedeus/nitter/master/README.md | B2:ev16; B2:ev17 | — |
| F16 | nitter-selfhost | Свой Nitter требует настоящих аккаунтов X (cookie auth_token/ct0 в sessions.jsonl) | A1 | https://raw.githubusercontent.com/wiki/zedeus/nitter/Creating-session-tokens.md | B2:ev15 | да |
| F17 | rsshub-twitter | Маршрут twitter в своём RSSHub требует данных аккаунта X: TWITTER_USERNAME/PASSWORD или TWITTER_AUTH_TOKEN; ключи X API как замена на странице не названы | A1 | https://docs.rsshub.app/deploy/config | B2:ev18; B2:ev19 | частично |
| F18 | tg-mtproto | MTProto (Telethon): API бесплатен; нужен аккаунт Telegram с номером телефона и свой api_id; аккаунты неофициальных клиентов «автоматически под наблюдением»; Telethon переехал на Codeberg и жив (2026-10-10) | A1 | https://core.telegram.org/api/obtaining_api_id | B2:ev7; B2:ev8; B2:ev9; B2:ev11; B2:ev20 | да |
| F19 | tg-pyrogram | Pyrogram: репозиторий в архиве с 2024-12-23 — брать Telethon | A1 | https://api.github.com/repos/pyrogram/pyrogram | B2:ev21 | — |
| F20 | tg-bot | Бот Telegram получает сообщения только из каналов, где он участник; для чужих каналов не годится (вывод, E) | A2 | https://core.telegram.org/bots/faq | B2:ev22 | — |
| F21 | discord-selfbot | Discord: автоматизация обычного аккаунта (self-bot, user-token) запрещена, за это закрывают аккаунт; scraping запрещён ToS и Developer Policy §20 | A1 | https://discord.com/terms | B2:ev10; B2:ev23; B2:ev24 | да |
| F22 | discord-bot | Бота добавляет на сервер его администратор (OAuth2 bot flow); для MESSAGE_CONTENT достаточно переключателя, пока бот на <100 серверах | A1 | https://raw.githubusercontent.com/discord/discord-api-docs/main/developers/topics/oauth2.mdx | B2:ev25; B2:ev27 | — |
| F23 | discord-follow | Follow Announcement Channel пересылает посты канала объявлений в целевой канал; нужно MANAGE_WEBHOOKS в целевом канале (что целевой канал — на своём сервере, страница прямо не говорит) | A2 | https://raw.githubusercontent.com/discord/discord-api-docs/main/developers/resources/channel.mdx | B2:ev26 | частично |
| F24 | discord-export | DiscordChatExporter жив (2026-10-09); с user-token нарушает ToS — автор предупреждает о бане; с токеном бота — только где есть бот | A1 | https://raw.githubusercontent.com/Tyrrrz/DiscordChatExporter/master/Readme.md | B2:ev28 | — |
| F25 | method-configs | 5 конфигов агрегаторов на GitHub: в каждом 8–13 каналов набора; со-встречаемость даёт кандидатов (5 каналов — в 4 из 5) | D3 | конфиг агрегатора на GitHub | B3:ev2; B3:ev3; B3:ev4; B3:ev5 | да |
| F26 | method-graph | граф 12 каналов × 2–3 стр. разрежен: ≥2 источника только у senior_augur, deep_learning_school_news, neuralshit, dl_stories; ссылок t.me/addlist нет | D3 | https://t.me/s/<12 каналов набора> (30 запросов, 501 пост, 2026-07-24…2026-10-11) | B3:ev1 | — |
| F27 | method-addlist | веб-страница папки t.me/addlist показывает только число чатов, состав — лишь клиентом или MTProto | A2 | https://t.me/addlist/_FjtIq8qMhU0NTYy | B3:ev6 | да |
| F28 | elkornacio | канал, на который README SQL-агента ссылается бейджем «Telegram Follow» рядом с X (что это канал автора — вывод); 6.3 поста/нед, ИИ в 14 из 18, ссылки 0.33, рекламы нет, мнения; Argon 20:09Z против 20:07Z у seeallochnaya; вердикт: да на пробу, скорость | C3 | https://t.me/s/elkornacio | B3:ev7; B3:ev8; B3:ev21; B3:ev24 | частично |
| F29 | senior_augur | автор открытых ru-LLM (профиль GitHub называет канал); цитируют boris_again и rybolos_channel; 2.2/нед, ссылки 0.94, без рекламы; Jev через 3.5 ч после denissexy; содержание+скорость; да | C2 | https://t.me/s/senior_augur | B3:ev10; B3:ev17; B3:ev1; B3:ev2 | да |
| F30 | doomgrad | NLP-разработчик, автор агрегатора статей top_papers (README ссылается); 5.4/нед, ссылки 0.59, без рекламы; доклады; содержание; да | C2 | https://t.me/s/doomgrad | B3:ev14; B3:ev18 | да |
| F31 | stuffynlp | Яндекс: разборы статей инженерами NLP Яндекса, корпоративный бренд-канал; 1.1/нед, ссылки 1.0, без рекламы; содержание; да для статей | C2 | https://t.me/s/stuffyNLP | B3:ev11; B3:ev19 | да |
| F32 | partially_unsupervised | SWE/ML-инженер (профиль GitHub называет канал); 0.9/нед, ссылки 0.9; есть реклама; содержание; да, редкий | C2 | https://t.me/s/partially_unsupervised | B3:ev12; B3:ev20 | да |
| F33 | epsiloncorrect | по постам — исследователь Google; Argon через 6 мин после seeallochnaya; 0.5/нед, ссылки 1.0; автор вне ленты не подтверждён; скорость по Google; да на пробу | C3 | https://t.me/s/epsiloncorrect | B3:ev9 | да |
| F34 | new_yorko_times | DS из Google, личный блог ссылается; 0.5/нед, рекламы нет; карьера и опыт, мало новинок; с оговорками | C2 | https://t.me/s/new_yorko_times | B3:ev13; B3:ev22 | — |
| F35 | cryptovalerii | автор книги по ML system design (ссылка — подкаст DataTalksClub); 2.2/нед, ссылки 0.63; продвигает свои мероприятия; индустрия, менеджмент; с оговорками | C2 | https://t.me/s/cryptovalerii | B3:ev16; B3:ev23 | — |
| F36 | quant_prune_distill | блог о сжатии сетей, разборы статей; 7.4/нед, ссылки 0.44; автор внешне не подтверждён; содержание; да на пробу | C3 | https://t.me/s/quant_prune_distill | B3:ev15; B3:ev2 | — |
| F37 | zvi | Don't Worry About the Vase, Zvi Mowshowitz — https://thezvi.substack.com/feed, RSS, pubDate; ~6.5 в неделю (20 записей 09-18..10-09, за 30 дней ≥20); x.com в 19 из 20, 984 из 2127 ссылок (46 %): цитирует исследователей, лаборатории, политиков; рекламы нет; класс — содержание, хотя самый свежий твит выпуска в среднем 16 ч; вердикт да | A2 | https://thezvi.substack.com/feed | B4:ev1; B4:ev15 | да |
| F38 | bensbites | Ben's Bites, Ben Tossell — https://www.bensbites.com/feed, RSS, pubDate; ~2.3 в неделю (10 за 30 дней); x.com в 10 из 10, 158 из 386 (41 %): строители и разработчики (bcherny, claudedevs, danshipper); реклама BuySellAds; содержание, медиана задержки 43 ч; да | A2 | https://www.bensbites.com/feed | B4:ev2; B4:ev15 | — |
| F39 | rundown | The Rundown AI, редакция — https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml, RSS, pubDate; 5 в неделю по будням (за 30 дней ≥20); x.com в 15 из 20, 31 из 770 (4 %): руководители, лаборатории; спонсор в каждом; скорость, медиана 23 ч; да | A2 | https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml | B4:ev3; B4:ev15 | — |
| F40 | neuron | The Neuron, редакция — https://rss.beehiiv.com/feeds/N4eCstxvgX.xml (объявлена в <head>), RSS, pubDate; ~8 в неделю вместе с подкастом; x.com в 10 из 20, 40 из 815 (5 %); реклама; скорость, медиана 17 ч; да | A2 | https://www.theneurondaily.com/ | B4:ev7; B4:ev8; B4:ev15 | — |
| F41 | tldr | TLDR AI — https://tldr.tech/api/rss/ai, RSS, pubDate; 5 в неделю; в записях нет элемента description (title, link, guid, category, pubDate) — для ссылок watch должен открывать страницу выпуска; x.com 16 % по 5 выпускам; пометки (Sponsor); скорость; да с оговоркой | A2 | https://tldr.tech/api/rss/ai | B4:ev6; B4:ev14; B4:ev15 | частично |
| F42 | marcus | Marcus on AI, Gary Marcus — https://garymarcus.substack.com/feed, RSS, pubDate; ~5.8 в неделю; x.com в 14 из 20, 42 из 112 (38 %): сам Маркус, лаборатории, новостные аккаунты; рекламы нет; быстрее всех, медиана 10 ч, но подбор — его полемика; да с оговоркой | A2 | https://garymarcus.substack.com/feed | B4:ev4; B4:ev15 | — |
| F43 | expview | Exponential View, Azeem Azhar — https://www.exponentialview.co/feed; ~4.4 в неделю; x.com 21 из 237 (9 %); спонсор; содержание, 53 ч; запас | A2 | https://www.exponentialview.co/feed | B4:ev5; B4:ev15 | — |
| F44 | transformer | Transformer, Shakeel Hashim — https://www.transformernews.ai/feed; ~3 в неделю; x.com в 7 из 13, 120 из 765 (16 %), тема — политика ИИ; содержание, 68 ч; запас | A2 | https://www.transformernews.ai/feed | B4:ev9; B4:ev15 | — |
| F45 | hn-first | HN: история создана первой или одновременно с блогом в 9 из 13, медиана 0.0 ч, пропуск 1 (Nano Banana 2.1); лента hn набора с min_points 100 увидит позже — сколько, не измерено | A2 | https://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=points>99 | B5:ev2 | да |
| F46 | or-speed | OpenRouter created: 11 из 11 моделей каталога, медиана +0.2 ч, максимум +1.7 ч (Large 4); Astra +25.9 ч; Gemini 4 Argon и Decision-1 в каталоге нет | A2 | https://openrouter.ai/api/v1/models | B5:ev1 | — |
| F47 | x-vs-feeds | X лаборатории по snowflake: медиана +0.3 ч после первого сообщения, первым 1 раз из 9; Grok 4.7 в X через 27 мин после истории HN, Large 4 — через 66 мин после блога | A2 | https://x.com/SpaceXAI/status/2102069815225586149 | B5:ev3; B5:ev4; B5:ev9; B5:ev10 | — |
| F48 | tc-leaks | TestingCatalog: до анонса в 6 из 13 (Opus 5.5 −32 ч, GPT-6 Sol −6, Sonnet 5.5 −20, Gemini 4, Nano Banana 2.1, Astra — 5–9 дней); после анонса — медиана +4.5 ч; содержание утечек E | A2 | https://www.testingcatalog.com/rss/ | B5:ev13 | — |
| F49 | xmirror-lag | зеркала: медиана +0.2 ч (7 событий); время = посту X: цитата своего поста через 126 и 170 с; для googledeepmind, claudeai, mistralai и др. зеркал нет | A2 | https://bsky.app/profile/anthropicai.xmirror.bot/post/3mw4wascefx2z | B5:ev5; B5:ev6 | да |
| F50 | tg-set-fast | Telegram набора: 11 из 11 в окне, медиана +0.4 ч, ни разу не первым; ai_machinelearning_big_data — раньше всех каналов в 7 событиях | A2 | https://t.me/ai_machinelearning_big_data/10985 | B5:ev7; B5:ev14 | частично |
| F51 | releases | claude-code-releases: Opus 5.5 +0.2 ч, Sonnet 5.5 +0.1, Haiku 5.5 +0.5, Fable 5.1 — первым; только для Anthropic | A2 | https://github.com/anthropics/claude-code/releases/tag/v2.1.280 | B5:ev8 | да |
| F52 | anthropic-site-miss | anthropic-site (sitemap, match.path /news/ /research/ /engineering/) пропускает страницы моделей: в sitemap они в корне — /claude-opus-5-5, /claude-sonnet-5-5, /claude-haiku-5-5, /claude-fable-and-mythos-5-1; 4 выхода Anthropic пропущены | A1 | https://www.anthropic.com/sitemap.xml | B5:ev12 | да |
| F53 | openai-rss-coarse | openai-news: 1195 из 1287 pubDate (93 %) ровно на начале часа; GPT-6.1 Sol 10:00Z при выходе ~17:00Z — время только как дата | A2 | https://openai.com/news/rss.xml | B5:ev11 | да |
| F54 | newsletters-lag | отставание рассылок-кандидатов (медиана, ч): TLDR 6.6 (только дата), Rundown 16.2, Neuron 16.4, Ben's Bites 43.2, Zvi 47.0, Transformer 70.1; Marcus и Exponential View — 0 из 11 | A2 | https://tldr.tech/api/rss/ai | B5:ev18; B5:ev20 | — |
| F55 | tg-cands | elkornacio 3 из 11 (+0.1 ч, GPT-6 Sol за 6 мин до X OpenAI); epsiloncorrect 1 (Gemini 4, +0.2); doomgrad 3 (+13 ч); остальные 6 кандидатов B3 — 0–2 из 13 | C2 | https://t.me/elkornacio/611 | B5:ev16; B5:ev17 | да |

### Рекомендация: набор на пробу

Новые ленты — 8, все `trial`:

| id | класс | тип ленты | адрес | почему |
|---|---|---|---|---|
| testingcatalog | скорость | rss | https://www.testingcatalog.com/rss/ | единственный открытый источник до анонса: 6 из 13 событий заранее |
| xmirror-anthropicai | скорость | rss | https://bsky.app/profile/anthropicai.xmirror.bot/rss | посты X без X, время = X; ловит то, что есть только в X |
| xmirror-openai | скорость | rss | https://bsky.app/profile/openai.xmirror.bot/rss | то же для OpenAI |
| tg-elkornacio | скорость | telegram | elkornacio | медиана +0,1 ч, в одном событии раньше X OpenAI; 3 из 11 |
| zvi | содержание | rss | https://thezvi.substack.com/feed | больше всех пересказывает X: 46 % ссылок, ~6,5 выпуска в неделю |
| tg-senior-augur | содержание | telegram | senior_augur | автор открытых ru-LLM; цитируют каналы набора |
| tg-stuffynlp | содержание | telegram | stuffyNLP | разборы статей инженерами NLP Яндекса — закрывает потребность «Яндекс» |
| tg-doomgrad | содержание | telegram | doomgrad | разборы статей, ссылки в 59 % постов |

Запас: Ben's Bites, quant_prune_distill, partially_unsupervised, epsiloncorrect, xmirror-xai.

Правки набора и кода — важнее новых лент:

| что | почему | улика |
|---|---|---|
| anthropic-site: добавить `/claude-` в `match.path` — страницы моделей лежат в корне сайта | пропущены все 4 выхода Anthropic | B5:ev12, V4 |
| hn: проверить порог `min_points` 100 — снизить или ограничить доменами лабораторий | HN — первый в 9 из 13, порог задерживает | B5:ev2 |
| openai-news: время записи считать только датой | 93 % pubDate на начале часа | B5:ev11 |
| `read_rss`: заголовок из description, если нет title | у RSS Bluesky нет title — зеркала xmirror придут без заголовка | B1:ev9 |

Не брать сейчас: X API — официальные выходы набор видит за 0–1 ч, утечки частично даёт TestingCatalog;
пересмотреть, если по счётчикам watch у testingcatalog и xmirror мало «только он». Nitter, RSSHub
для X, self-bot Discord, DiscordChatExporter с user-token — нарушают условия. Telethon — аккаунт под
наблюдением, t.me/s хватает. Discord Follow — только со своим сервером и ботом, не stdlib.

## 5. Отсеянное

| объект | причина | улика |
|---|---|---|
| Nitter (свой и публичные), xcancel | репозиторий в архиве после требований X Corp.; xcancel — 451; свой сервер требует аккаунтов X; против условий X | B2:ev5, B2:ev6, B2:ev13, B2:ev15 |
| RSSHub, маршрут twitter | требует данных аккаунта X; публичный rsshub.app — 403 | B2:ev18 |
| Discord self-bot, DiscordChatExporter с user-token | запрещено условиями, бан аккаунта | B2:ev23, B2:ev28 |
| Telethon (MTProto) | аккаунт с телефоном под наблюдением; t.me/s хватает | B2:ev7 |
| Pyrogram | репозиторий в архиве с 2024-12-23 | B2:ev21 |
| Techmeme | после TestingCatalog на 31 ч; ИИ — половина записей | B1:ev10, B1:ev11 |
| LiteLLM, models.dev | идентификаторы появляются после OpenRouter | B1:ev5, B1:ev16 |
| r/singularity, r/OpenAI, r/ClaudeAI | 160–730 записей в неделю, 429 чаще раза в минуту | B1:ev15 |
| Mastodon (sigmoid.social, теги) | лаборатории не пишут, теги — шум | B1:ev12, B1:ev13 |
| LLMLearner | только «released», время 00:00 | B1:ev14 |
| LMArena, кодовые имена | открытой ленты нет; кодовые имена есть в TestingCatalog | B1 rejected |
| The Rundown, The Neuron, TLDR AI | редакционные пересказчики; отставание 6,6–16,4 ч — медленнее набора | B4:ev3, B4:ev8, B5:ev18 |
| Marcus on AI, Exponential View | о выходах моделей не пишут — 0 из 11 | B5:ev20 |
| Transformer | отставание 70 ч, тема — политика ИИ | B5 таблица |
| TheSequence, Last Week in AI, AlphaSignal, Elvis Saravia | без ссылок на X, редко или поток коротких новостей | B4:ev10–ev13 |
| Superhuman, Deep View, Mindstream, AI Valley, AI Breakfast | RSS нет | B4:ev16 |
| new_yorko_times, cryptovalerii, nadlskom | карьера и менеджмент, мало новинок; шитпост без подтверждённого автора | B3:ev13, B3:ev16 |
| официальные каналы Яндекса и GigaChat | корпоративный PR, не авторские | B3 rejected |

## 6. Источники

Источники — в столбце «первичный источник» реестра раздела 4 и в уликах `branches/B*.md`. Чаще всего
использованы: docs.x.com (A), x.com/en/tos (A), core.telegram.org (A), discord-api-docs на GitHub (A),
снимки Discord Help Center в веб-архиве (A), testingcatalog.com/rss (A как лента, E по содержанию),
public.api.bsky.app (A), openrouter.ai/api/v1/models (A для каталога), hn.algolia.com (A), t.me/s
каналов (C–D), README профилей авторов на GitHub (C), RSS рассылок (D).

## 7. Метод

- Источники и даты обращения: все — 2026-10-11; веб-архив — для Discord Help Center и Developer Policy
- Запросы: по журналам 57 строк; WebSearch — 7 запросов; пакетные запросы скриптом — граф B3 40,
  история лент B5 54; проверяющие V1–V4 — 34 утверждения, около 50 обращений
- Ключевые приёмы: поиск кода GitHub по конфигам агрегаторов — 20+ кандидатов (B3); время поста X из
  snowflake id ссылок в рассылках — время X без X (B4, B5); сравнение по одной опорной дате (B5)
- Лимиты и фильтры: en, ru; события 2026-09-01..2026-10-09; RSS хранят 10–20 записей — окно каждой
  ленты указано в таблице B5
- Поиск по связям: граф цитирований 12 каналов — 501 пост, 4 канала с ≥2 упоминаниями (B3:ev1)
- Тест полноты: known_items — ai_newz и gonzo_ML уже в наборе, elkornacio найден в конфигах
  агрегаторов (B3:ev2), AINews — в выдаче B4; 4 из 4
- Самопроверка: не пройден п. 4 — у B2 и B3 `log_summary.queries` (13 и 15) не равно числу строк
  `query` в журнале (0 и 2); журналы веток недосчитывают обращения, факт бюджета по журналу занижен.
  Остальные пункты пройдены; ключевые утверждения в `verify.md`: 34, да 27, частично 7, нет 0

## 8. Открытые вопросы, противоречия, план обновления

- Открытые вопросы и пробелы: Discord не измерялся; время X — нижняя граница по ссылкам в
  рассылках; когда история HN набирает 100 очков, Algolia не отдаёт — задержку порога не измерить
  ретроспективно; авторских каналов о Сбере не найдено; 8 каналов из конфигов агрегаторов не
  проверены (dealerai, def_model_train, knowledge_accumulator, black_samorez_channel, mltochka,
  agi_and_rl, aiextime, dl_stories)
- Открытые направления: ещё конфиги агрегаторов на GitHub — 10–20 ru и en каналов (B3); список
  *.xmirror.bot для сотрудников лабораторий (B1); каналы объявлений Discord лабораторий для Follow (B2)
- Находки по обкатке скилла: журналы веток недосчитывают обращения (B4 — 9 строк при 46 открытых
  источниках); `lint --run .` с относительным путём ложно сообщает brief-id; задание ветки в 2000
  символов приходится ужимать в 3–4 прохода; уровень L (60–120) мал для options с ретроспективой —
  ушло 185; пакетные запросы скриптом не имеют места в учёте бюджета

| утверждение | за | против | чем решилось |
|---|---|---|---|
| Nitter жив | B2:ev17 `B2` — отдельные публичные инстансы отдают RSS | B2:ev12, B2:ev13 `A1` — архив, требования X Corp. | кодовая база мертва, инстансы работают через раз — не брать |
| TestingCatalog — первоисточник утечек | B1:ev1 | проверка V2: утверждение — встроенный пост X, подан как слух | первоисточник — X, TestingCatalog — открытый пересказ утечек X |

- План обновления: V3-утверждения (цены X API, живость лент, Nitter) — перепроверить до 2026-11-10
  или перед решением о X API; после 8 запусков watch с новыми лентами — счётчики «первым» и «только
  он» вместо ретроспективы
