"""Самопроверка формы скилла (`self`), ограниченный вывод и вызов скрипта."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from support import (CORE, FEED_SET, ISSUE_RE, REFERENCES, REPO, deep_search, make_skill,
                     reference_text, run_script, write, write_feed_set)

TAIL_RE = re.compile(r"^… ещё (\d+)$", re.MULTILINE)


class SkillCase(unittest.TestCase):
    """Эталонный скилл и отдельный HOME во временной папке."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.skill = make_skill(base / "skill")

    def run_self(self):
        return run_script("self", "--skill-dir", str(self.skill), home=self.home)

    def rules(self, out: str) -> set[str]:
        return {m.group(2) for m in ISSUE_RE.finditer(out)}

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.skill / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def assert_only(self, rule: str) -> str:
        """Код 1 и единственное правило в выводе — rule."""
        res = self.run_self()
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), {rule}, res.stdout)
        return res.stdout


class ReferenceSkillTest(SkillCase):
    def test_reference_skill_is_clean(self):
        res = self.run_self()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), set(), res.stdout)
        self.assertIn("нарушений 0", res.stdout)

    def test_fixture_leaves_room_for_core_top(self):
        # Чтобы испортить core-top, не задев core-lines, «Этапы» сдвигаются вниз за строку 60,
        # а ядро остаётся в пределе строк.
        lines = CORE.splitlines()
        stages_end = max(i for i, line in enumerate(lines) if line.startswith("| 6."))
        shift = deep_search.CORE_TOP_LINES - stages_end
        self.assertLessEqual(len(lines) + shift, deep_search.CORE_MAX_LINES)


class BrokenCopyTest(SkillCase):
    """По одной испорченной копии на правило: код 1 и имя правила в выводе."""

    def test_description_chars(self):
        self.edit("SKILL.md", "обзор.", "обзор." + "я" * deep_search.DESCRIPTION_MAX_CHARS)
        self.assert_only("description-chars")

    def test_description_folded_scalar_counted_whole(self):
        long = "\n".join("  " + "слово " * 20 for _ in range(5))
        text = re.sub(r"(?m)^description: .*$", lambda _: "description: >-\n" + long, CORE)
        (self.skill / "SKILL.md").write_text(text, encoding="utf-8")
        out = self.assert_only("description-chars")
        self.assertIn("599 символов", out)

    def test_description_missing(self):
        self.edit("SKILL.md", "description: ", "summary: ")
        self.assert_only("description-chars")

    def test_core_lines(self):
        lines = CORE.splitlines()
        pad = deep_search.CORE_MAX_LINES + 1 - len(lines)
        (self.skill / "SKILL.md").write_text("\n".join(lines + [""] * pad) + "\n",
                                             encoding="utf-8")
        out = self.assert_only("core-lines")
        self.assertIn("86 строк", out)

    def test_core_chars(self):
        filler = "ж" * (deep_search.CORE_MAX_CHARS - len(CORE) + 1)
        self.edit("SKILL.md", "- Скрипт — `deep_search.py`.", f"- Скрипт — `deep_search.py`. {filler}")
        self.assert_only("core-chars")

    def test_core_headings(self):
        self.edit("SKILL.md", "## Где что лежит", "## Файлы")
        out = self.assert_only("core-headings")
        self.assertIn("«## Где что лежит»", out)

    def test_core_top(self):
        lines = CORE.splitlines()
        stages_end = max(i for i, line in enumerate(lines) if line.startswith("| 6."))
        shift = deep_search.CORE_TOP_LINES - stages_end
        self.edit("SKILL.md", "# Глубокий поиск\n", "# Глубокий поиск\n" + "\n" * shift)
        out = self.assert_only("core-top")
        self.assertIn("«Этапы»", out)

    def test_route_missing(self):
        (self.skill / "references/sources.md").unlink()
        out = self.assert_only("route-missing")
        self.assertIn("references/sources.md", out)

    def test_route_missing_template_slot(self):
        (self.skill / "presets/technology.md").unlink()
        out = self.assert_only("route-missing")
        self.assertIn("presets/<preset>.md", out)

    def test_route_unlisted(self):
        write(self.skill / "references/extra.md", reference_text("extra.md", ["Раздел"]))
        out = self.assert_only("route-unlisted")
        self.assertIn("references/extra.md", out)

    def test_route_unlisted_preset_matches_slot(self):
        write(self.skill / "presets/science.md", "Когда читать: наука.\n")
        res = self.run_self()
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_when_to_read(self):
        self.edit("references/brief.md", "Когда читать:", "Читать:")
        out = self.assert_only("when-to-read")
        self.assertIn("references/brief.md", out)

    def test_ref_lines(self):
        name = "branching.md"
        base = reference_text(name, REFERENCES[name], toc=True)
        filler = deep_search.REF_MAX_LINES + 1 - len(base.splitlines())
        write(self.skill / "references" / name,
              reference_text(name, REFERENCES[name], filler=filler, toc=True))
        out = self.assert_only("ref-lines")
        self.assertIn("201 строк", out)

    def test_ref_chars(self):
        for name, limit in (("sources.md", deep_search.REF_MAX_CHARS),
                            ("verify-merge.md", deep_search.REF_CHAR_BUDGETS["verify-merge.md"]),
                            ("store.md", deep_search.REF_CHAR_BUDGETS["store.md"]),
                            ("watch.md", deep_search.REF_CHAR_BUDGETS["watch.md"])):
            with self.subTest(name=name):
                self.setUp()
                text = reference_text(name, REFERENCES[name])
                text += "ц" * (limit - len(text) + 1) + "\n"
                write(self.skill / "references" / name, text[:limit + 1])
                self.assert_only("ref-chars")

    def test_ref_chars_limit_is_inclusive(self):
        name = "verify-merge.md"
        limit = deep_search.REF_CHAR_BUDGETS[name]
        text = reference_text(name, REFERENCES[name])
        write(self.skill / "references" / name, text + "ц" * (limit - len(text)))
        self.assertEqual(self.run_self().returncode, 0)

    def test_ref_toc(self):
        name = "sources.md"
        filler = deep_search.REF_TOC_MIN_LINES + 1 - len(reference_text(name, REFERENCES[name]).splitlines())
        write(self.skill / "references" / name,
              reference_text(name, REFERENCES[name], filler=filler))
        out = self.assert_only("ref-toc")
        self.assertIn("references/sources.md", out)

    def test_ref_toc_incomplete(self):
        name = "sources.md"
        text = reference_text(name, REFERENCES[name], filler=100, toc=True)
        write(self.skill / "references" / name, text.replace(" · Свежесть", "", 1))
        out = self.assert_only("ref-toc")
        self.assertIn("Свежесть", out)

    def test_preset_chars(self):
        path = self.skill / "presets/technology.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "п" * (deep_search.PRESET_MAX_CHARS - len(text) + 1),
                        encoding="utf-8")
        self.assert_only("preset-chars")

    def test_brief_template_chars(self):
        path = self.skill / "templates/brief.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "б" * (deep_search.BRIEF_TEMPLATE_MAX_CHARS - len(text) + 1),
                        encoding="utf-8")
        self.assert_only("brief-template-chars")

    def test_digest_template_chars(self):
        path = self.skill / deep_search.DIGEST_TEMPLATE
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "д" * (deep_search.DIGEST_TEMPLATE_MAX_CHARS - len(text) + 1),
                        encoding="utf-8")
        self.assert_only("digest-template-chars")

    def test_core_missing(self):
        (self.skill / "SKILL.md").unlink()
        self.assert_only("core-missing")


class FeedSetTest(SkillCase):
    """Набор лент presets/*-feeds.json: по одной порче — ровно одно нарушение."""

    def setUp(self):
        super().setUp()
        self.path = write_feed_set(self.skill)

    def feeds(self, **over) -> list[dict]:
        """Копия лент набора; over — поля первой ленты (None — убрать поле)."""
        feeds = [dict(f) for f in FEED_SET["feeds"]]
        for key, value in over.items():
            if value is None:
                feeds[0].pop(key)
            else:
                feeds[0][key] = value
        return feeds

    def assert_one(self, rule: str) -> str:
        out = self.assert_only(rule)
        self.assertEqual(len(ISSUE_RE.findall(out)), 1, out)
        self.assertIn("presets/ai-feeds.json", out)
        return out

    def test_feed_set_is_clean(self):
        res = self.run_self()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(self.rules(res.stdout), set(), res.stdout)

    def test_skill_itself_is_clean(self):
        res = run_script("self", home=self.home)
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("нарушений 0, предупреждений 0", res.stdout)
        self.assertTrue((REPO / deep_search.WATCH_FEEDS).is_file())

    def test_broken_json(self):
        self.path.write_text('{"version": 1, "feeds": [', encoding="utf-8")
        self.assertIn("битый JSON", self.assert_one("feeds-json"))

    def test_required_field(self):
        for key in ("lang", "group", "filter", "url"):
            with self.subTest(key=key):
                write_feed_set(self.skill, {**FEED_SET, "feeds": self.feeds(**{key: None})})
                out = self.assert_one("feeds-json")
                self.assertIn("лента lab-blog: нет полей", out)
                self.assertIn("url или params" if key == "url" else key, out)

    def test_unknown_type(self):
        write_feed_set(self.skill, {**FEED_SET, "feeds": self.feeds(type="atom")})
        self.assertIn("неизвестный тип «atom»", self.assert_one("feeds-type"))

    def test_duplicate_id(self):
        feeds = self.feeds()
        feeds[1]["id"] = "lab-blog"
        write_feed_set(self.skill, {**FEED_SET, "feeds": feeds})
        self.assertIn("лента lab-blog: повтор id", self.assert_one("feeds-id"))

    def test_every_feed_set_is_checked(self):
        write_feed_set(self.skill, {**FEED_SET, "feeds": self.feeds(type="atom")},
                       name="science-feeds.json")
        out = self.assert_only("feeds-type")
        self.assertIn("presets/science-feeds.json", out)


class BoundedOutputTest(SkillCase):
    def test_forty_violations_are_cut_with_tail(self):
        total = 40
        for n in range(total):
            name = f"unlisted-reference-with-a-deliberately-long-name-to-fill-the-output-{n:02d}"
            write(self.skill / "references" / f"{name}-{'x' * 60}.md",
                  reference_text(name, ["Раздел"]))
        res = self.run_self()
        out = res.stdout.rstrip("\n")
        self.assertEqual(res.returncode, 1)
        self.assertLessEqual(len(out), deep_search.OUTPUT_MAX_CHARS)
        tail = TAIL_RE.search(out)
        self.assertIsNotNone(tail, out[-500:])
        assert tail is not None
        shown = len(ISSUE_RE.findall(out))
        self.assertGreater(shown, 0)
        self.assertEqual(shown + int(tail.group(1)), total)
        # Главное — в начале: первое нарушение целиком в первых OUTPUT_HEAD_CHARS символах.
        first = out.splitlines()[0]
        self.assertRegex(first, ISSUE_RE)
        self.assertLessEqual(len(first), deep_search.OUTPUT_HEAD_CHARS)
        self.assertIn(f"нарушений {total}", out.splitlines()[-1])

    def test_long_line_is_capped(self):
        issue = deep_search.Issue("SKILL.md", "core-chars", "я" * 5000)
        report = deep_search.bounded_report([issue], "итог")
        self.assertLessEqual(len(report.splitlines()[0]), deep_search.LINE_MAX_CHARS)

    def test_errors_before_warnings(self):
        warn = deep_search.Issue("INDEX.md", "index-lines", "длинно", warn=True)
        err = deep_search.Issue("SKILL.md", "core-lines", "длинно")
        report = deep_search.bounded_report([warn, err], "итог")
        self.assertTrue(report.startswith("SKILL.md: core-lines: "), report)
        self.assertIn("warn: INDEX.md: index-lines: ", report)

    def test_head_counts_toward_limit(self):
        head = "шапка\n" + "т" * 3_000
        issues = [deep_search.Issue("SKILL.md", "core-chars", "я" * 300) for _ in range(40)]
        report = deep_search.bounded_report(issues, "итог", head=head)
        self.assertTrue(report.startswith(head + "\n"), report[:100])
        self.assertLessEqual(len(report), deep_search.OUTPUT_MAX_CHARS)
        tail = TAIL_RE.search(report)
        self.assertIsNotNone(tail)
        assert tail is not None
        self.assertEqual(len(ISSUE_RE.findall(report)) + int(tail.group(1)), len(issues))


class StubCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)

    def test_help_lists_commands(self):
        res = run_script("--help", home=self.home)
        self.assertEqual(res.returncode, 0)
        for cmd in ("doctor", "init", "lint", "index", "cost", "self"):
            self.assertIn(cmd, res.stdout)

    def test_no_command_is_call_error(self):
        self.assertEqual(run_script(home=self.home).returncode, 2)

    def test_self_without_skill_dir_is_call_error(self):
        res = run_script("self", "--skill-dir", str(self.home / "nope"), home=self.home)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
