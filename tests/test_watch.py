"""`watch`: набор лент, разборщики всех типов, окно, виденное, склейка, фильтр, пауза к хосту,
токен GitHub, файлы.

Сеть не трогается: функция запроса подменена и отдаёт образцы из tests/fixtures/watch/, а
общий запрос проверяется на локальном HTTP-сервере 127.0.0.1. Время — параметр `now`.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from support import CARD, deep_search, fill, make_skill, run_script, skill_text, write

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "watch"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
INTERESTS = {
    "models": ["model", "weights", "модель"],
    "agents": ["agent", "MCP", "агент"],
    "providers": ["pricing", "rate limit"],
    "research": ["paper", "arXiv"],
    "apps": ["NotebookLM"],
}


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def feed(fid: str, url: str, kind: str = "rss", group: str = "labs", filt: str = "always",
         **extra) -> dict:
    return {"id": fid, "type": kind, "url": url, "group": group, "lang": "en", "filter": filt,
            **extra}


def rss(items: list[tuple[str, str, datetime | None]]) -> bytes:
    """RSS из записей (заголовок, ссылка, дата) — для окна и пределов, где важны числа, а не
    ловушки разбора."""
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link>"
        + (f"<pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>" if d else "")
        + "</item>" for t, u, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


class FakeNet:
    """Ответы по адресам; каждый запрос записывается с заголовками."""

    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        answer = self.answers.get(url)
        if answer is None:
            return deep_search.Probe(404)
        if isinstance(answer, deep_search.Probe):
            return answer
        if isinstance(answer, Exception):
            raise answer
        return deep_search.Probe(200, answer, url=url)

    def urls(self) -> list[str]:
        return [u for u, _ in self.calls]


class WatchCase(unittest.TestCase):
    """Скилл с временным presets/ai-feeds.json и пустая библиотека."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.skill = make_skill(self.base / "skill")
        self.library = self.base / "library"
        self.library.mkdir()
        self.watch_dir = self.library / "watch"

    def set_feeds(self, feeds: list[dict], interests: dict | None = None) -> None:
        write(self.skill / deep_search.WATCH_FEEDS, json.dumps(
            {"version": 1, "checked": "2026-10-09", "interests": interests or INTERESTS,
             "feeds": feeds}, ensure_ascii=False))

    def set_library(self, **extra) -> None:
        write(self.watch_dir / "feeds.json", json.dumps({"version": 1, **extra}))

    def set_state(self, feeds: dict) -> None:
        write(self.watch_dir / "state.json", json.dumps({"version": 1, "feeds": feeds}))

    def state(self) -> dict:
        return json.loads((self.watch_dir / "state.json").read_text(encoding="utf-8"))["feeds"]

    def run_watch(self, net, now=NOW, **kw) -> deep_search.WatchRun:
        return deep_search.watch(self.skill, self.library, net, now, **kw)

    def keys(self, run) -> list[str]:
        return [r["key"] for r in run.records]


class WatchCallTest(WatchCase):
    """Разбор аргументов и ошибки вызова — через скрипт, как у агента; до опроса лент дело не
    доходит, поэтому сеть не нужна."""

    def script(self, *args):
        return run_script("watch", "--skill-dir", str(self.skill), *args, home=self.base)

    def test_help_lists_watch(self):
        res = run_script("--help", home=self.base)
        self.assertIn("watch", res.stdout)
        res = run_script("watch", "--help", home=self.base)
        for flag in ("--library", "--only", "--since", "--dry-run", "--json"):
            self.assertIn(flag, res.stdout)

    def test_no_library_is_call_error(self):
        self.set_feeds([feed("lab", "https://lab.example/rss.xml")])
        res = self.script()
        self.assertEqual(res.returncode, 2)
        self.assertIn("библиотеки нет", res.stderr)
        self.assertIn("DEEP_SEARCH_LIBRARY", res.stderr)

    def test_unknown_type_names_feed(self):
        self.set_feeds([feed("lab-news", "https://lab.example/rss.xml", kind="atom")])
        res = self.script("--library", str(self.library))
        self.assertEqual(res.returncode, 2)
        self.assertIn("lab-news", res.stderr)
        self.assertIn("неизвестный тип «atom»", res.stderr)

    def test_duplicate_id_names_feed(self):
        self.set_feeds([feed("lab-news", "https://lab.example/rss.xml")])
        self.set_library(add=[feed("lab-news", "https://other.example/rss.xml")])
        res = self.script("--library", str(self.library))
        self.assertEqual(res.returncode, 2)
        self.assertIn("lab-news", res.stderr)
        self.assertIn("повтор id", res.stderr)

    def test_bad_since_and_only(self):
        self.set_feeds([feed("lab-news", "https://lab.example/rss.xml")])
        res = self.script("--library", str(self.library), "--since", "9 октября")
        self.assertEqual(res.returncode, 2)
        res = self.script("--library", str(self.library), "--only", "nope")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--only nope", res.stderr)

    def test_broken_library_feeds_json(self):
        self.set_feeds([feed("lab-news", "https://lab.example/rss.xml")])
        write(self.watch_dir / "feeds.json", "{not json")
        res = self.script("--library", str(self.library))
        self.assertEqual(res.returncode, 2)
        self.assertIn("битый JSON", res.stderr)


class FeedSetTest(WatchCase):
    def test_disable_add_override_interests(self):
        self.set_feeds([feed("a", "https://a.example/rss"), feed("b", "https://b.example/rss")])
        self.set_library(disable=["a", "gone"], add=[feed("c", "https://c.example/rss")],
                         override={"b": {"filter": "interests"}, "ghost": {"filter": "always"}},
                         interests={"apps": ["Cursor"]})
        fs = deep_search.load_feed_set(self.skill, self.library)
        self.assertEqual([f["id"] for f in fs.feeds], ["b", "c"])
        self.assertEqual(fs.feeds[0]["filter"], "interests")
        self.assertEqual(fs.interests["apps"], ["Cursor"])
        self.assertEqual(fs.interests["models"], INTERESTS["models"])
        notes = "\n".join(fs.notes)
        self.assertIn("gone", notes)
        self.assertIn("ghost", notes)

    def test_disabled_skill_feed_may_be_replaced(self):
        self.set_feeds([feed("a", "https://a.example/rss")])
        self.set_library(disable=["a"], add=[feed("a", "https://mirror.example/rss")])
        fs = deep_search.load_feed_set(self.skill, self.library)
        self.assertEqual([f["url"] for f in fs.feeds], ["https://mirror.example/rss"])

    def test_errors_name_the_feed(self):
        cases = [
            ([feed("a", "https://a.example/rss"), feed("a", "https://b.example/rss")], {},
             "повтор id"),
            ([feed("a", "https://a.example/rss")], {"override": {"a": {"type": "json"}}},
             "неизвестный тип «json»"),
            ([{"id": "a", "type": "rss", "url": "https://a.example/rss", "group": "labs",
               "lang": "en"}], {}, "нет полей: filter"),
            ([feed("a", "https://a.example/rss", group="news")], {}, "group «news»"),
        ]
        for feeds, extra, text in cases:
            with self.subTest(text=text):
                self.set_feeds(feeds)
                self.set_library(**extra)
                with self.assertRaises(deep_search.WatchError) as err:
                    deep_search.load_feed_set(self.skill, self.library)
                self.assertIn("лента a", str(err.exception))
                self.assertIn(text, str(err.exception))

    def test_every_type_has_a_reader(self):
        self.assertEqual(set(deep_search.FEED_READERS), set(deep_search.FEED_TYPES))

    def test_params_are_checked(self):
        hn = {"id": "a", "type": "hn", "group": "aggregators", "lang": "en", "filter": "interests"}
        cases = [
            ({**hn, "params": {"min_points": 50}}, "нет params.query"),
            ({**hn, "params": {"query": "LLM", "min_point": 50}}, "лишние: min_point"),
            ({**hn, "params": {"query": "LLM", "min_points": "50"}}, "params.min_points"),
            ({**hn, "params": {"query": []}}, "params.query"),
            ({**hn, "url": "https://hn.algolia.com/api/v1/search", "params": {"query": "LLM"}},
             "url не нужен"),
            ({**hn, "type": "github_releases", "params": {"repo": "acme"}}, "OWNER/REPO"),
            ({**hn, "type": "telegram", "params": {"channel": "t.me/labnews"}},
             "params.channel"),
            ({**hn, "type": "rss", "params": {"query": "x"}}, "адрес — url"),
            (feed("a", "https://a.example/rss", ua="chrome"), "ua «chrome»"),
            (feed("a", "https://a.example/rss", min_interval=-1), "min_interval"),
            (feed("a", "https://a.example/rss", trial="yes"), "trial"),
        ]
        for item, text in cases:
            with self.subTest(text=text):
                self.set_feeds([item])
                with self.assertRaises(deep_search.WatchError) as err:
                    deep_search.load_feed_set(self.skill, self.library)
                self.assertIn("лента a", str(err.exception))
                self.assertIn(text, str(err.exception))


class ParseTest(WatchCase):
    def poll(self, body: bytes, kind="rss", **extra):
        f = feed("lab", "https://lab.example/feed", kind=kind, **extra)
        net = FakeNet({"https://lab.example/feed": body})
        return deep_search.FEED_READERS[kind](deep_search.FeedPoll(
            f, lambda url: net(url, {}), NOW - timedelta(days=7), NOW, {}))

    def test_rss(self):
        entries = {e.url or e.key: e for e in self.poll(fixture("rss.xml"))}
        first = entries["https://WWW.Lab.Example/news/haiku-5-5?utm_source=rss&ref=feed#top"]
        self.assertEqual(first.key, "https://www.lab.example/news/haiku-5-5?ref=feed")
        self.assertEqual(first.title, "Claude Haiku 5.5 & more")
        self.assertEqual(first.when, datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(first.date_kind, "published")
        # lastBuildDate канала — не дата записи; дата дальше суток в будущем — как нет даты.
        self.assertIsNone(entries["https://www.lab.example/news/undated"].when)
        self.assertIsNone(entries["https://www.lab.example/news/future"].when)
        # Нет ссылки — ключ из guid; dc:date с поясом.
        guid = entries["lab:lab-post-42"]
        self.assertEqual(guid.url, "")
        self.assertEqual(guid.when, datetime(2026, 10, 8, 6, 30, tzinfo=timezone.utc))

    def test_rss_text_is_plain(self):
        first = self.poll(fixture("rss.xml"))[0]
        self.assertLessEqual(len(first.excerpt), deep_search.EXCERPT_MAX_CHARS)
        self.assertTrue(first.excerpt.startswith("New model with «fast» mode. hidden"))
        self.assertNotIn("<", first.excerpt)
        self.assertNotIn("ignore previous", first.excerpt)
        self.assertNotIn("‮", first.excerpt)

    def test_rss_without_title(self):
        # Так отдаёт RSS профиля Bluesky: у записи нет <title>, только текст поста.
        body = ("<rss version='2.0'><channel><item>"
                "<link>https://bsky.app/profile/lab.example/post/3mw4</link>"
                "<description>Claude Opus 5.5 is available today.\nMore in the thread."
                "</description><pubDate>22 Sep 2026 16:31 +0000</pubDate>"
                "</item></channel></rss>").encode()
        entry, = self.poll(body)
        self.assertEqual(entry.title, "Claude Opus 5.5 is available today.")
        self.assertEqual(entry.when, datetime(2026, 9, 22, 16, 31, tzinfo=timezone.utc))

    def test_atom(self):
        agents, release = self.poll(fixture("atom.xml"))
        self.assertEqual(agents.url, "https://lab.example/engineering/agents")
        self.assertEqual(agents.title, "Agents at scale")
        self.assertEqual(agents.when, datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(agents.date_kind, "published")
        self.assertEqual(agents.excerpt, "How we run agents.")
        # Только updated — дата правки.
        self.assertEqual(release.date_kind, "modified")
        self.assertEqual(release.when, datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc))

    def test_html_instead_of_feed(self):
        for kind in ("rss", "sitemap"):
            with self.subTest(kind=kind), self.assertRaises(deep_search.FeedError) as err:
                self.poll(fixture("html-not-feed.html"), kind=kind)
            self.assertIn("не та лента: HTML", str(err.exception))

    def test_wrong_kind_of_feed(self):
        with self.assertRaises(deep_search.FeedError) as err:
            self.poll(fixture("rss.xml"), kind="sitemap")
        self.assertIn("не та лента", str(err.exception))
        with self.assertRaises(deep_search.FeedError):
            self.poll(fixture("sitemap.xml"), kind="rss")

    def test_dates(self):
        parse = deep_search.parse_date
        self.assertEqual(parse("2026-10-07"), datetime(2026, 10, 7, tzinfo=timezone.utc))
        self.assertEqual(parse("2026-10-07T10:00:00Z"),
                         datetime(2026, 10, 7, 10, tzinfo=timezone.utc))
        self.assertEqual(parse("Wed, 07 Oct 26 13:00:00 +0300"),
                         datetime(2026, 10, 7, 10, tzinfo=timezone.utc))
        # Без года — как нет даты.
        self.assertIsNone(parse("Mon, 07 Oct 10:00:00 GMT"))
        self.assertIsNone(parse("October 2"))


class SitemapTest(WatchCase):
    def test_match_path_and_modified(self):
        self.set_feeds([feed("lab-site", "https://lab.example/sitemap.xml", kind="sitemap",
                             match={"path": ["/news/", "/research/"]})])
        run = self.run_watch(FakeNet({"https://lab.example/sitemap.xml": fixture("sitemap.xml")}))
        self.assertEqual(self.keys(run), ["https://lab.example/news/claude-haiku-5-5",
                                          "https://lab.example/research/interpretability-update"])
        self.assertEqual({r["date_kind"] for r in run.records}, {"modified"})
        self.assertEqual(run.records[0]["date"], "2026-10-08")
        self.assertEqual(run.records[0]["title"], "claude haiku 5 5")
        # Запись без lastmod при первом опросе только запоминается.
        self.assertIn("https://lab.example/news/no-lastmod", self.state()["lab-site"]["seen"])

    def test_index_one_level(self):
        self.set_feeds([feed("lab-site", "https://lab.example/sitemap.xml", kind="sitemap",
                             match={"path": "/news/"})])
        net = FakeNet({"https://lab.example/sitemap.xml": fixture("sitemap-index.xml"),
                       "https://lab.example/sitemap-news.xml": fixture("sitemap.xml"),
                       "https://lab.example/sitemap-nested.xml": fixture("sitemap-nested.xml")})
        run = self.run_watch(net)
        self.assertEqual(run.failed, [])
        self.assertEqual(self.keys(run), ["https://lab.example/news/claude-haiku-5-5"])
        # Подкарта, не менявшаяся с начала окна, и второй уровень индекса не запрашиваются.
        self.assertEqual(net.urls(), ["https://lab.example/sitemap.xml",
                                      "https://lab.example/sitemap-news.xml",
                                      "https://lab.example/sitemap-nested.xml"])


class WindowSeenTest(WatchCase):
    URL = "https://lab.example/rss.xml"

    def setUp(self):
        super().setUp()
        self.set_feeds([feed("lab", self.URL)])

    def test_second_run_finds_nothing(self):
        net = FakeNet({self.URL: fixture("rss.xml")})
        first = self.run_watch(net)
        self.assertEqual(self.keys(first), ["lab:lab-post-42",
                                            "https://www.lab.example/news/haiku-5-5?ref=feed"])
        again = self.run_watch(net, now=NOW + timedelta(hours=1))
        self.assertEqual(again.records, [])
        state = self.state()["lab"]
        self.assertEqual(state["runs"], 2)
        self.assertEqual(state["new"], 2)

    def test_first_window_is_seven_days(self):
        body = rss([("eight days", "https://lab.example/8", NOW - timedelta(days=8)),
                    ("six days", "https://lab.example/6", NOW - timedelta(days=6))])
        run = self.run_watch(FakeNet({self.URL: body}))
        self.assertEqual(self.keys(run), ["https://lab.example/6"])

    def test_window_from_last_ok_minus_a_day(self):
        self.set_state({"lab": {"last_ok": "2026-10-08T12:00:00+00:00", "seen": []}})
        body = rss([("before", "https://lab.example/a", datetime(2026, 10, 7, 10, 0,
                                                                  tzinfo=timezone.utc)),
                    ("after", "https://lab.example/b", datetime(2026, 10, 7, 14, 0,
                                                                 tzinfo=timezone.utc)),
                    ("undated", "https://lab.example/c", None)])
        run = self.run_watch(FakeNet({self.URL: body}))
        self.assertEqual(self.keys(run), ["https://lab.example/c", "https://lab.example/b"])
        # Запись без даты у ленты, которую уже опрашивали, — новая с датой опроса.
        undated = run.records[0]
        self.assertEqual((undated["date_kind"], undated["date"]), ("polled", "2026-10-09"))

    def test_since_replaces_window(self):
        self.set_state({"lab": {"last_ok": "2026-10-08T12:00:00+00:00", "seen": []}})
        run = self.run_watch(FakeNet({self.URL: fixture("rss.xml")}), since=date(2026, 9, 1))
        self.assertIn("https://www.lab.example/news/old", self.keys(run))

    def test_seen_is_capped_and_output_bounded(self):
        items = [(f"Item number {n} about pricing", f"https://lab.example/p/{n}",
                  NOW - timedelta(minutes=n)) for n in range(600)]
        run = self.run_watch(FakeNet({self.URL: rss(items)}))
        self.assertEqual(len(run.records), 600)
        self.assertEqual(len(self.state()["lab"]["seen"]), deep_search.SEEN_MAX)
        self.assertEqual(self.state()["lab"]["seen"][0], "https://lab.example/p/0")
        text = deep_search.watch_text(run)
        self.assertLessEqual(len(text), deep_search.OUTPUT_MAX_CHARS)
        self.assertTrue(text.startswith("watch: 2026-10-09 — новых 600 (labs 600); лент 1"))
        shown = sum(1 for line in text.splitlines() if line.startswith("2026-"))
        tail = next(line for line in text.splitlines() if line.startswith("… ещё "))
        self.assertEqual(shown + int(tail.split()[2]), 600)
        self.assertTrue(text.splitlines()[-1].startswith("найденное: "))
        # --json — те же пределы, хвост — объект JSON.
        lines = deep_search.watch_json(run).splitlines()
        self.assertLessEqual(len("\n".join(lines)), deep_search.OUTPUT_MAX_CHARS)
        parsed = [json.loads(line) for line in lines]
        self.assertEqual(len(parsed) - 1 + parsed[-1]["omitted"], 600)


class MergeFilterTest(WatchCase):
    ANSWERS = {"https://lab.example/rss": fixture("merge-labs.xml"),
               "https://agg.example/atom": fixture("merge-agg.xml"),
               "https://letter.example/rss": fixture("merge-news.xml")}

    def setUp(self):
        super().setUp()
        self.set_feeds([feed("labs-a", "https://lab.example/rss"),
                        feed("agg-b", "https://agg.example/atom", group="aggregators",
                             filt="interests"),
                        feed("news-c", "https://letter.example/rss", group="newsletters",
                             trial=True)])

    def test_merge_and_counters(self):
        run = self.run_watch(FakeNet(self.ANSWERS))
        by_key = {r["key"]: r for r in run.records}
        x = by_key["https://lab.example/news/x"]
        self.assertEqual(x["feeds"], ["agg-b", "labs-a", "news-c"])
        self.assertEqual(x["first_feed"], "agg-b")
        self.assertEqual((x["url"], x["date"], x["group"]),
                         ("https://lab.example/news/x", "2026-10-07", "labs"))
        self.assertFalse(x["trial"])
        self.assertTrue(by_key["https://letter.example/issue-9"]["trial"])
        self.assertEqual(len(run.records), 4)
        state = self.state()
        counts = {fid: (s["new"], s["first"], s["unique"]) for fid, s in state.items()}
        self.assertEqual(counts, {"labs-a": (2, 1, 1), "agg-b": (2, 2, 1), "news-c": (2, 1, 1)})
        # labs раньше, затем по числу лент, затем новее раньше.
        self.assertEqual(run.records[0]["key"], "https://lab.example/news/x")
        self.assertEqual(run.records[1]["key"], "https://lab.example/news/y")
        self.assertIn("×3", deep_search.watch_text(run).splitlines()[1])

    def test_interest_filter(self):
        run = self.run_watch(FakeNet(self.ANSWERS))
        by_key = {r["key"]: r for r in run.records}
        self.assertNotIn("https://news.other.example/weather", by_key)
        self.assertEqual(by_key["https://blog.other.example/agent-kit"]["interests"], ["agents"])
        # filter: always проходит и без совпадений; совпавшие группы всё равно отмечены.
        self.assertEqual(by_key["https://lab.example/news/y"]["interests"], [])
        self.assertEqual(by_key["https://lab.example/news/x"]["interests"], ["models"])
        # Отброшенное фильтром — тоже виденное: следующий запуск его не вернёт.
        self.assertIn("https://news.other.example/weather", self.state()["agg-b"]["seen"])

    def test_seen_by_another_feed_is_not_new(self):
        self.set_state({"labs-a": {"last_ok": "2026-10-08T12:00:00+00:00",
                                   "seen": ["https://lab.example/news/x"]}})
        run = self.run_watch(FakeNet(self.ANSWERS))
        self.assertNotIn("https://lab.example/news/x", self.keys(run))

    def test_title_merge(self):
        groups = deep_search.merge_groups([
            deep_search.Entry("https://a.example/1", "Model X is finally here", "", None,
                              "published", feed="a"),
            deep_search.Entry("https://b.example/2", "model x — is finally HERE!", "", None,
                              "published", feed="b"),
            deep_search.Entry("https://c.example/3", "v1.2.0", "", None, "published", feed="c"),
            deep_search.Entry("https://d.example/4", "v1.2.0", "", None, "published", feed="d"),
        ])
        self.assertEqual(sorted(len(g) for g in groups), [1, 1, 2])

    def test_only(self):
        net = FakeNet(self.ANSWERS)
        run = self.run_watch(net, only="aggregators")
        self.assertEqual(net.urls(), ["https://agg.example/atom"])
        self.assertEqual(run.feeds, 1)
        self.assertEqual(set(self.state()), {"agg-b"})
        net = FakeNet(self.ANSWERS)
        self.run_watch(net, only="labs-a")
        self.assertEqual(net.urls(), ["https://lab.example/rss"])

    def test_user_agent(self):
        net = FakeNet(self.ANSWERS)
        self.run_watch(net)
        self.assertTrue(all(h["User-Agent"] == deep_search.WATCH_UA for _, h in net.calls))


class FailureTest(WatchCase):
    def setUp(self):
        super().setUp()
        self.set_feeds([feed("lab", "https://lab.example/rss"),
                        feed("down", "https://down.example/rss", group="releases")])

    def test_failed_feed_does_not_break_run(self):
        net = FakeNet({"https://lab.example/rss": fixture("merge-labs.xml"),
                       "https://down.example/rss": deep_search.Probe(503)})
        run = self.run_watch(net)
        self.assertEqual(len(run.records), 2)
        self.assertEqual(run.failed, [("down", "HTTP 503")])
        state = self.state()["down"]
        self.assertEqual((state["fails"], state["last_error"], state["last_ok"]),
                         (1, "HTTP 503", ""))

    def test_third_failure_in_a_row_is_marked(self):
        self.set_state({"down": {"fails": 2, "last_error": "HTTP 403"}})
        net = FakeNet({"https://lab.example/rss": fixture("merge-labs.xml"),
                       "https://down.example/rss": deep_search.Probe(403)})
        run = self.run_watch(net)
        self.assertEqual(run.failed,
                         [("down", "HTTP 403 ×3 подряд — проверить или отключить")])
        self.assertIn("проверить или отключить", deep_search.watch_text(run))

    def test_success_resets_fails_and_crash_is_contained(self):
        self.set_state({"lab": {"fails": 2, "last_error": "таймаут"}})
        net = FakeNet({"https://lab.example/rss": fixture("merge-labs.xml"),
                       "https://down.example/rss": RuntimeError("boom")})
        run = self.run_watch(net)
        self.assertEqual(run.failed, [("down", "не разобралась: RuntimeError")])
        self.assertEqual((self.state()["lab"]["fails"], self.state()["lab"]["last_error"]),
                         (0, ""))

    def test_html_answer_goes_to_failed(self):
        net = FakeNet({"https://lab.example/rss": fixture("html-not-feed.html"),
                       "https://down.example/rss": fixture("merge-labs.xml")})
        run = self.run_watch(net)
        self.assertEqual(run.failed, [("lab", "не та лента: HTML вместо RSS или Atom")])

    def test_broken_state_is_renamed(self):
        write(self.watch_dir / "state.json", "{not json")
        net = FakeNet({"https://lab.example/rss": fixture("merge-labs.xml"),
                       "https://down.example/rss": fixture("merge-labs.xml")})
        run = self.run_watch(net)
        bad = self.watch_dir / "state.json.bad-2026-10-09"
        self.assertEqual(bad.read_text(encoding="utf-8"), "{not json")
        self.assertEqual(set(self.state()), {"lab", "down"})
        self.assertIn("state.json битый — переименован", deep_search.watch_text(run))
        self.assertEqual(len(run.records), 2)


class TopicsTest(WatchCase):
    """Новость о предмете темы библиотеки помечена темой и проходит фильтр интересов."""

    URL = "https://news.example/rss.xml"

    def setUp(self):
        super().setUp()
        self.set_feeds([feed("news", self.URL, group="newsletters", filt="interests")])

    def topic(self, slug: str, aliases: str, objects: list[str], status: str = "live") -> None:
        values = {**CARD, "topic": slug, "aliases": aliases, "status": status}
        rows = "".join(f"| {name} | система | — | live |\n" for name in objects)
        text = fill(skill_text("templates/topic.md"), values)
        text = text.replace("|---|---|---|---|\n", "|---|---|---|---|\n" + rows, 1)
        write(self.library / f"topics/{slug}.md", text)

    def test_topic_marks_and_passes_filter(self):
        self.topic("vector-db", "векторные базы, vector database", ["Qdrant", "Go"])
        self.topic("old-db", "Weaviate", [], status="archived")
        run = self.run_watch(FakeNet({self.URL: rss([
            ("Qdrant 2.0 released", "https://news.example/1", NOW),
            ("Why every vector database is slow", "https://news.example/2", NOW),
            ("Qdrantish fork, Go 1.30 and Weaviate", "https://news.example/3", NOW),
            ("Weather today", "https://news.example/4", NOW)])}))
        by_key = {r["key"]: r for r in run.records}
        self.assertEqual(sorted(by_key), ["https://news.example/1", "https://news.example/2"])
        self.assertEqual(by_key["https://news.example/1"]["topics"], ["vector-db"])
        self.assertEqual(by_key["https://news.example/2"]["interests"], [])
        self.assertIn("тема: vector-db", deep_search.watch_text(run))

    def test_no_topics_is_empty_list(self):
        self.set_feeds([feed("news", self.URL)])
        run = self.run_watch(FakeNet({self.URL: rss([("Anything", "https://news.example/1",
                                                      NOW)])}))
        self.assertEqual(run.records[0]["topics"], [])


class FilesTest(WatchCase):
    URL = "https://lab.example/rss.xml"

    def setUp(self):
        super().setUp()
        self.set_feeds([feed("lab", self.URL)])

    def test_dry_run_writes_nothing(self):
        write(self.watch_dir / "state.json", "[]")
        run = self.run_watch(FakeNet({self.URL: fixture("rss.xml")}), dry_run=True)
        self.assertEqual(len(run.records), 2)
        self.assertIsNone(run.path)
        self.assertEqual(sorted(p.name for p in self.watch_dir.iterdir()), ["state.json"])
        self.assertIn("найденное не записано: --dry-run", deep_search.watch_text(run))

    def test_record_fields(self):
        run = self.run_watch(FakeNet({self.URL: fixture("rss.xml")}))
        lines = run.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(run.path, self.watch_dir / "new" / "2026-10-09.jsonl")
        self.assertEqual(len(lines), 2)
        for line in lines:
            record = json.loads(line)
            self.assertEqual(tuple(record), deep_search.RECORD_FIELDS)
            self.assertLessEqual(len(record["excerpt"]), deep_search.EXCERPT_MAX_CHARS)
            for text in (record["title"], record["excerpt"]):
                self.assertNotIn("<", text)
                self.assertFalse(any(ord(ch) < 32 or ch in deep_search.INVISIBLE
                                     for ch in text))
        record = json.loads(lines[1])
        self.assertEqual(record["title"], "Claude Haiku 5.5 & more")
        self.assertEqual(record["interests"], ["models"])

    def test_same_day_appends(self):
        self.run_watch(FakeNet({self.URL: rss([("one", "https://lab.example/1", NOW)])}))
        self.run_watch(FakeNet({self.URL: rss([("two", "https://lab.example/2", NOW)])}),
                       now=NOW + timedelta(hours=2))
        lines = (self.watch_dir / "new" / "2026-10-09.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(x)["title"] for x in lines], ["one", "two"])

    def test_empty_run_still_marks_the_day(self):
        run = self.run_watch(FakeNet({self.URL: rss([])}))
        self.assertEqual(run.path.read_text(), "")

    def test_state_written_through_temp_file(self):
        calls = []
        real = deep_search.os.replace

        def spy(src, dst):
            calls.append((Path(src), Path(dst)))
            return real(src, dst)

        with mock.patch.object(deep_search.os, "replace", spy):
            self.run_watch(FakeNet({self.URL: fixture("rss.xml")}))
        src, dst = calls[-1]
        self.assertEqual(dst, self.watch_dir / "state.json")
        self.assertEqual(src.parent, self.watch_dir)
        self.assertTrue(src.name.endswith(".tmp"))
        self.assertEqual(sorted(p.name for p in self.watch_dir.iterdir()), ["new", "state.json"])

    def test_failed_write_keeps_old_state(self):
        self.set_state({"lab": {"runs": 5}})
        before = (self.watch_dir / "state.json").read_text()
        with mock.patch.object(deep_search.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_watch(FakeNet({self.URL: fixture("rss.xml")}))
        self.assertEqual((self.watch_dir / "state.json").read_text(), before)
        self.assertFalse(list(self.watch_dir.glob("*.tmp")))


def api_feed(fid: str, kind: str, params: dict, group: str = "aggregators",
             filt: str = "always", **extra) -> dict:
    return {"id": fid, "type": kind, "params": params, "group": group, "lang": "en",
            "filter": filt, **extra}


class HnNet(FakeNet):
    """Как FakeNet, но любой запрос к Algolia получает образец hn.json."""

    def __call__(self, url, headers):
        if url.startswith("https://hn.algolia.com/"):
            self.calls.append((url, dict(headers)))
            return deep_search.Probe(200, fixture("hn.json"), url=url)
        return super().__call__(url, headers)


GH_URL = "https://api.github.com/repos/acme/agent-kit/releases?per_page=30"
TG_URL = "https://t.me/s/labnews"
TOKEN = "ghp_TESTTOKEN0123456789"


class GithubReleasesTest(WatchCase):
    def setUp(self):
        super().setUp()
        self.set_feeds([api_feed("agent-kit", "github_releases", {"repo": "acme/agent-kit"},
                                 group="releases")])

    def test_releases_from_api(self):
        net = FakeNet({GH_URL: fixture("github-releases.json")})
        run = self.run_watch(net)
        self.assertEqual(net.urls(), [GH_URL])
        self.assertNotIn("releases.atom", " ".join(net.urls()))
        by_title = {r["title"]: r for r in run.records}
        # Черновик и выпуск старше окна — мимо; голая версия получает имя репозитория.
        self.assertEqual(set(by_title), {"acme/agent-kit v2.1.0", "Agent-Kit 2.2 RC1"})
        release = by_title["acme/agent-kit v2.1.0"]
        self.assertEqual((release["url"], release["date"], release["date_kind"]),
                         ("https://github.com/acme/agent-kit/releases/tag/v2.1.0", "2026-10-07",
                          "published"))
        self.assertEqual(release["excerpt"],
                         "What's Changed MCP support by @dev in #12 fast mode")
        self.assertTrue(by_title["Agent-Kit 2.2 RC1"]["excerpt"].startswith("пре-релиз"))

    def test_rate_limit_hint(self):
        run = self.run_watch(FakeNet({GH_URL: deep_search.Probe(403)}))
        self.assertEqual(run.failed[0][0], "agent-kit")
        self.assertIn("лимит API GitHub", run.failed[0][1])


class GithubTokenTest(WatchCase):
    """Токен — только в заголовке к api.github.com: не в других запросах, выводе и файлах."""

    def test_token_goes_only_to_github_api(self):
        self.set_feeds([
            api_feed("agent-kit", "github_releases", {"repo": "acme/agent-kit"},
                     group="releases"),
            api_feed("gone-repo", "github_releases", {"repo": "acme/gone"}, group="releases"),
            feed("lab", "https://lab.example/rss"),
            api_feed("hn-ai", "hn", {"query": "LLM"}),
        ])
        net = FakeNet({GH_URL: fixture("github-releases.json"),
                       "https://lab.example/rss": fixture("merge-labs.xml")})
        run = self.run_watch(net, environ={"GITHUB_TOKEN": TOKEN, "PATH": "/bin"})
        for url, headers in net.calls:
            with self.subTest(url=url):
                if url.startswith("https://api.github.com/"):
                    self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
                else:
                    self.assertNotIn("Authorization", headers)
                    self.assertNotIn(TOKEN, json.dumps(headers))
        self.assertEqual(len([u for u, _ in net.calls if "api.github.com" in u]), 2)
        self.assertEqual(dict(run.failed)["gone-repo"], "HTTP 404")
        outputs = [deep_search.watch_text(run), deep_search.watch_json(run),
                   repr(run.failed), repr(run.notes)]
        outputs += [p.read_text(encoding="utf-8") for p in self.library.rglob("*") if p.is_file()]
        for text in outputs:
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(TOKEN[4:], text)

    def test_token_only_over_https_to_exact_host(self):
        headers = {"User-Agent": "ua"}
        for url in ("http://api.github.com/repos/a/b/releases",
                    "https://api.github.com.evil.example/repos/a/b",
                    "https://github.com/a/b/releases.atom",
                    "https://uploads.github.com/a"):
            with self.subTest(url=url):
                self.assertNotIn("Authorization",
                                 deep_search.request_headers(headers, url, TOKEN))
        self.assertEqual(deep_search.request_headers(headers, GH_URL, TOKEN)["Authorization"],
                         f"Bearer {TOKEN}")
        self.assertNotIn("Authorization", deep_search.request_headers(headers, GH_URL, ""))


class HuggingFaceTest(WatchCase):
    def test_trending_created_in_window(self):
        self.set_feeds([api_feed("hf-trending", "hf_trending", {"limit": 20})])
        url = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=20"
        net = FakeNet({url: fixture("hf-trending.json")})
        run = self.run_watch(net)
        self.assertEqual(net.urls(), [url])
        self.assertNotIn("createdAt", url)
        # Старая модель в тренде и модель без даты создания — не новость.
        self.assertEqual([(r["title"], r["url"], r["date"]) for r in run.records],
                         [("acme/Acme-7B-Instruct", "https://huggingface.co/acme/Acme-7B-Instruct",
                           "2026-10-06")])
        self.assertEqual(run.records[0]["excerpt"], "text-generation · лайков 321")

    def test_papers_by_week_with_threshold(self):
        self.set_feeds([api_feed("hf-papers", "hf_papers", {"min_upvotes": 10})])
        week40 = "https://huggingface.co/api/daily_papers?week=2026-W40"
        week41 = "https://huggingface.co/api/daily_papers?week=2026-W41"
        net = FakeNet({week40: b"[]", week41: fixture("hf-papers.json")})
        run = self.run_watch(net)
        # Окно первого запуска (2026-10-02…09) — две недели ISO; sort=trending не просится.
        self.assertEqual(net.urls(), [week40, week41])
        self.assertEqual(len(run.records), 1)
        paper = run.records[0]
        self.assertEqual((paper["title"], paper["url"]),
                         ("Scaling Agents", "https://huggingface.co/papers/2610.01234"))
        # Дата — когда статью принесли в Daily Papers, а не публикация на arXiv.
        self.assertEqual(paper["date"], "2026-10-06")
        self.assertEqual(paper["excerpt"], "голосов 120. We study agents.")

    def test_paper_merges_with_arxiv(self):
        self.set_feeds([api_feed("hf-papers", "hf_papers", {}),
                        feed("arxiv-cl", "https://rss.arxiv.org/rss/cs.CL", group="aggregators")])
        net = FakeNet({"https://huggingface.co/api/daily_papers?week=2026-W41":
                       fixture("hf-papers.json"),
                       "https://huggingface.co/api/daily_papers?week=2026-W40": b"[]",
                       "https://rss.arxiv.org/rss/cs.CL": rss([
                           ("Scaling agents with less", "https://arxiv.org/abs/2610.01234",
                            NOW - timedelta(days=4))])})
        run = self.run_watch(net)
        merged = [r for r in run.records if len(r["feeds"]) == 2]
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0]["feeds"]), {"hf-papers", "arxiv-cl"})

    def test_iso_weeks(self):
        weeks = deep_search.iso_weeks(datetime(2026, 8, 1, tzinfo=timezone.utc), NOW)
        self.assertEqual(len(weeks), deep_search.HF_PAPERS_WEEKS_MAX)
        self.assertEqual(weeks[-1], "2026-W41")
        self.assertEqual(deep_search.iso_weeks(datetime(2025, 12, 31, tzinfo=timezone.utc),
                                               datetime(2026, 1, 2, tzinfo=timezone.utc)),
                         ["2026-W01"])


class OpenRouterTest(WatchCase):
    def test_new_models_variants_merged(self):
        self.set_feeds([api_feed("openrouter", "openrouter", {})])
        net = FakeNet({"https://openrouter.ai/api/v1/models": fixture("openrouter.json")})
        run = self.run_watch(net)
        by_url = {r["url"]: r for r in run.records}
        # :free и :batch склеены по canonical_slug; старая модель и модель без даты — мимо.
        self.assertEqual(set(by_url), {"https://openrouter.ai/stepfun/step-5-preview",
                                       "https://openrouter.ai/anthropic/claude-haiku-5.5"})
        step = by_url["https://openrouter.ai/stepfun/step-5-preview"]
        self.assertEqual((step["title"], step["date"], step["date_kind"]),
                         ("StepFun: Step 5 Preview", "2026-10-08", "published"))
        self.assertIn("варианты :free", step["excerpt"])
        self.assertIn("вход $0.3/M", step["excerpt"])
        haiku = by_url["https://openrouter.ai/anthropic/claude-haiku-5.5"]
        self.assertEqual(haiku["title"], "Anthropic: Claude Haiku 5.5")
        self.assertNotIn("polled", {r["date_kind"] for r in run.records})


class HackerNewsTest(WatchCase):
    def test_encoded_filters_threshold_and_queries(self):
        self.set_feeds([api_feed("hn-ai", "hn", {"query": ["LLM", "agents"], "min_points": 50})])
        net = HnNet({})
        run = self.run_watch(net)
        self.assertEqual(len(net.urls()), 2)
        since = int((NOW - timedelta(days=7)).timestamp())
        for url, query in zip(net.urls(), ("LLM", "agents")):
            self.assertTrue(url.startswith("https://hn.algolia.com/api/v1/search_by_date?"))
            self.assertIn(f"query={query}&", url)
            self.assertIn(f"numericFilters=points%3E%3D50%2Ccreated_at_i%3E{since}", url)
            self.assertNotIn(">", url)
            self.assertNotIn(",", url)
        # Два запроса — одна лента, одна история не повторяется; ниже порога — мимо.
        by_title = {r["title"]: r for r in run.records}
        self.assertEqual(set(by_title), {"Lab launches model X", "Ask HN: agents in prod?"})
        self.assertEqual(by_title["Lab launches model X"]["url"], "https://lab.example/news/x")
        ask = by_title["Ask HN: agents in prod?"]
        self.assertEqual(ask["url"], "https://news.ycombinator.com/item?id=45500002")
        self.assertTrue(ask["excerpt"].startswith(
            "HN: очков 80, комментариев 50 — https://news.ycombinator.com/item?id=45500002."))
        self.assertNotIn("<", ask["excerpt"])

    def test_no_threshold_no_points_filter(self):
        self.set_feeds([api_feed("hn-ai", "hn", {"query": "LLM"})])
        net = FakeNet({})
        self.run_watch(net)
        self.assertNotIn("points", net.urls()[0])
        self.assertIn("created_at_i%3E", net.urls()[0])


class TelegramTest(WatchCase):
    def setUp(self):
        super().setUp()
        self.set_feeds([api_feed("labnews", "telegram", {"channel": "labnews"},
                                 group="telegram")])

    def test_posts_pages_and_text(self):
        net = FakeNet({TG_URL: fixture("telegram-page1.html"),
                       TG_URL + "?before=101": fixture("telegram-page2.html")})
        run = self.run_watch(net)
        # Вторая страница — с меньшего id; на ней пост старше окна, дальше не листается.
        self.assertEqual(net.urls(), [TG_URL, TG_URL + "?before=101"])
        by_url = {r["url"]: r for r in run.records}
        self.assertEqual(set(by_url), {f"https://t.me/labnews/{n}" for n in (100, 101, 102, 104)})
        post = by_url["https://t.me/labnews/104"]
        self.assertEqual((post["title"], post["date"]), ("Lab launches model X", "2026-10-08"))
        # Текст после вложенного div — целиком; ссылки — подписью, без разметки.
        self.assertEqual(post["excerpt"],
                         "Lab launches model X Nested part: 🔥 weights & code open "
                         "Tail after nested div. lab.example/news/x #models repost")
        # Цитата из ответа — не текст поста.
        self.assertEqual(by_url["https://t.me/labnews/102"]["title"],
                         "Reply post about MCP servers")

    def test_stops_at_previous_poll(self):
        self.set_state({"labnews": {"last_ok": "2026-10-08T12:00:00+00:00", "seen": []}})
        net = FakeNet({TG_URL: fixture("telegram-page1.html")})
        run = self.run_watch(net)
        self.assertEqual(net.urls(), [TG_URL])
        self.assertEqual([r["url"] for r in run.records], ["https://t.me/labnews/104"])

    def test_at_most_four_pages(self):
        def page(first: int) -> bytes:
            posts = "".join(
                f'<div class="tgme_widget_message js-widget_message" data-post="labnews/{n}">'
                f'<div class="tgme_widget_message_text js-message_text">Post {n} text</div>'
                f'<time datetime="2026-10-09T10:00:00+00:00"></time></div>'
                for n in (first, first + 1))
            return f"<html><body>{posts}</body></html>".encode()

        net = FakeNet({TG_URL: page(20), **{f"{TG_URL}?before={n}": page(n - 2)
                                            for n in (20, 18, 16, 14)}})
        self.run_watch(net)
        self.assertEqual(len(net.urls()), deep_search.TELEGRAM_PAGES_MAX)

    def test_redirect_means_no_preview(self):
        net = FakeNet({TG_URL: deep_search.Probe(200, b"<html>channel</html>",
                                                 url="https://t.me/labnews")})
        run = self.run_watch(net)
        self.assertEqual(run.failed, [("labnews", "нет превью: t.me/s/ ведёт на страницу канала")])

    def test_link_merges_blog_hn_and_channel(self):
        self.set_feeds([feed("labs-a", "https://lab.example/rss"),
                        api_feed("hn-ai", "hn", {"query": "LLM", "min_points": 50}),
                        api_feed("labnews", "telegram", {"channel": "labnews"}, group="telegram")])
        run = self.run_watch(HnNet({"https://lab.example/rss": fixture("merge-labs.xml"),
                                  TG_URL: fixture("telegram-page1.html"),
                                  TG_URL + "?before=101": fixture("telegram-page2.html")}))
        x = next(r for r in run.records if r["key"] == "https://lab.example/news/x")
        self.assertEqual(x["feeds"], ["labs-a", "hn-ai", "labnews"])
        self.assertEqual((x["first_feed"], x["group"]), ("labs-a", "labs"))
        self.assertIn("×3", deep_search.watch_text(run).splitlines()[1])


class PageTest(WatchCase):
    URL = "https://lab.example/changelog"

    def setUp(self):
        super().setUp()
        self.set_feeds([feed("lab-changelog", self.URL, kind="page", group="releases")])

    def test_added_lines_since_snapshot(self):
        first = self.run_watch(FakeNet({self.URL: fixture("page-v1.html")}))
        self.assertEqual(first.records, [])
        state_text = (self.watch_dir / "state.json").read_text(encoding="utf-8")
        # Снимок — хеши строк, не сам текст.
        self.assertNotIn("Batch requests", state_text)
        # Заголовок страницы и h1 совпадают — одна строка снимка.
        self.assertEqual(len(self.state()["lab-changelog"]["page_lines"]), 3)

        later = NOW + timedelta(days=1)
        second = self.run_watch(FakeNet({self.URL: fixture("page-v2.html")}), now=later)
        # Меню, подвал, скрипты и короткие строки не в счёт; две новые строки подряд — одна запись.
        self.assertEqual(len(second.records), 1)
        record = second.records[0]
        self.assertEqual((record["title"], record["excerpt"], record["url"]),
                         ("2026-10-08 — Rate limit changes", "New rate limit tiers for the API.",
                          self.URL))
        self.assertEqual((record["date"], record["date_kind"]), ("2026-10-10", "polled"))

        third = self.run_watch(FakeNet({self.URL: fixture("page-v2.html")}),
                               now=later + timedelta(hours=1))
        self.assertEqual(third.records, [])

    def test_empty_page_is_an_error(self):
        run = self.run_watch(FakeNet({self.URL: b"<html><body><div id='app'></div>"
                                                b"<script>boot()</script></body></html>"}))
        self.assertIn("на странице нет текста", run.failed[0][1])


class PaceAndAgentTest(WatchCase):
    def test_min_interval_per_host_and_user_agent(self):
        self.set_feeds([feed("arxiv-cl", "https://rss.arxiv.org/rss/cs.CL", min_interval=3),
                        feed("arxiv-ai", "https://rss.arxiv.org/rss/cs.AI"),
                        feed("lab", "https://lab.example/rss", ua="browser"),
                        api_feed("hn-ai", "hn", {"query": ["LLM", "agents"]}, min_interval=2)])
        sleeps: list[float] = []
        net = HnNet({})
        self.run_watch(net, sleep=sleeps.append)
        # Между двумя запросами к хосту — одна пауза; первый запрос к хосту не ждёт.
        self.assertEqual(len(sleeps), 2)
        low, high = sorted(sleeps)
        self.assertTrue(1.5 < low <= 2 and 2.5 < high <= 3, sleeps)
        agents = {url: h["User-Agent"] for url, h in net.calls}
        self.assertEqual(agents["https://lab.example/rss"], deep_search.BROWSER_UA)
        self.assertEqual(agents["https://rss.arxiv.org/rss/cs.CL"], deep_search.WATCH_UA)
        self.assertTrue(deep_search.BROWSER_UA.startswith("Mozilla/5.0"))

    def test_no_interval_no_sleep(self):
        self.set_feeds([feed("a", "https://lab.example/a"), feed("b", "https://lab.example/b")])
        sleeps: list[float] = []
        self.run_watch(FakeNet({}), sleep=sleeps.append)
        self.assertEqual(sleeps, [])


class TrialTest(WatchCase):
    def test_idle_trial_is_offered_for_disabling(self):
        self.set_feeds([feed("trial-a", "https://a.example/rss", trial=True),
                        feed("trial-b", "https://b.example/rss", trial=True),
                        feed("steady", "https://c.example/rss")])
        self.set_state({"trial-a": {"runs": 7, "unique": 0, "last_ok": "2026-10-08T12:00:00+00:00"},
                        "trial-b": {"runs": 9, "unique": 1},
                        "steady": {"runs": 20, "unique": 0}})
        empty = rss([])
        run = self.run_watch(FakeNet({"https://a.example/rss": empty,
                                      "https://b.example/rss": empty,
                                      "https://c.example/rss": empty}))
        self.assertEqual(run.idle_trials, ["trial-a"])
        self.assertIn("на пробу без своего за 8 запусков: trial-a — предложить отключить",
                      deep_search.watch_text(run))

    def test_fresh_trial_is_not_marked(self):
        self.set_feeds([feed("trial-a", "https://a.example/rss", trial=True)])
        self.set_state({"trial-a": {"runs": 6, "unique": 0}})
        run = self.run_watch(FakeNet({"https://a.example/rss": rss([])}))
        self.assertEqual(run.idle_trials, [])
        self.assertNotIn("предложить отключить", deep_search.watch_text(run))


class Handler(BaseHTTPRequestHandler):
    """Локальный сервер: gzip без запроса, длинное тело, редирект, эхо User-Agent."""

    def do_GET(self):  # noqa: N802  имя метода задаёт http.server
        if self.path in ("/redirect", "/redirect-auth"):
            self.send_response(302)
            self.send_header("Location", "/plain" if self.path == "/redirect" else "/auth")
            self.end_headers()
            return
        if self.path == "/gzip":
            body = gzip.compress(fixture("rss.xml"))
        elif self.path == "/big":
            body = b"x" * 2_000
        elif self.path == "/ua":
            body = self.headers.get("User-Agent", "").encode()
        elif self.path == "/auth":
            body = self.headers.get("Authorization", "none").encode()
        else:
            body = fixture("rss.xml")
        self.send_response(200)
        if self.path == "/gzip":
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HttpRequestTest(unittest.TestCase):
    """Общий запрос на 127.0.0.1, мимо прокси: в сеть не уходит."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, limit=deep_search.FEED_BODY_MAX, headers=None):
        return deep_search.http_request("GET", self.base + path, None, headers or {},
                                        proxy=False, timeout=5, limit=limit)

    def test_gzip_without_asking_is_unpacked(self):
        probe = self.get("/gzip")
        self.assertEqual(probe.status, 200)
        self.assertEqual(probe.body, fixture("rss.xml"))

    def test_gzip_feed_parses_end_to_end(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        skill = make_skill(Path(tmp.name) / "skill")
        library = Path(tmp.name) / "library"
        library.mkdir()
        write(skill / deep_search.WATCH_FEEDS, json.dumps(
            {"version": 1, "interests": INTERESTS,
             "feeds": [feed("lab", self.base + "/gzip")]}))

        def fetch(url, headers):
            return deep_search.http_request("GET", url, None, headers, proxy=False, timeout=5,
                                            limit=deep_search.FEED_BODY_MAX)

        run = deep_search.watch(skill, library, fetch, NOW)
        self.assertEqual(run.failed, [])
        self.assertEqual(len(run.records), 2)

    def test_body_limit(self):
        probe = self.get("/big", limit=1_000)
        self.assertTrue(probe.truncated)
        self.assertEqual(len(probe.body), 1_000)
        self.assertFalse(self.get("/big", limit=2_000).truncated)

    def test_redirect_and_user_agent(self):
        self.assertEqual(self.get("/redirect").url, self.base + "/plain")
        self.assertEqual(self.get("/ua", headers={"User-Agent": "probe-ua"}).body, b"probe-ua")

    def test_authorization_does_not_follow_redirect(self):
        auth = {"Authorization": "Bearer secret"}
        self.assertEqual(self.get("/auth", headers=auth).body, b"Bearer secret")
        self.assertEqual(self.get("/redirect-auth", headers=auth).body, b"none")


if __name__ == "__main__":
    unittest.main()
