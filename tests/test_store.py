"""`init`, `index` и `lint --store`: раскладка, оглавление и правила хранилища."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from support import (CARD, CLAIM_ROWS, CLAIMS_HEAD, INDEX, ISSUE_RE, RUN_ID, SLUG,
                     SOURCES_HEAD, deep_search, fill, make_store, run_script, skill_text, write)


class StoreCase(unittest.TestCase):
    """Хранилище из шаблонов скилла и отдельный HOME во временной папке."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.store = make_store(self.base / "store")

    def lint(self, *extra: str):
        return run_script("lint", "--store", str(self.store), *extra, home=self.home)

    def index(self):
        res = run_script("index", str(self.store), home=self.home)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res

    def rules(self, out: str) -> set[str]:
        return {m.group(2) for m in ISSUE_RE.finditer(out)}

    def text(self, rel: str) -> str:
        return (self.store / rel).read_text(encoding="utf-8")

    def edit(self, rel: str, old: str, new: str) -> None:
        text = self.text(rel)
        self.assertIn(old, text)
        (self.store / rel).write_text(text.replace(old, new, 1), encoding="utf-8")

    def append(self, rel: str, line: str) -> None:
        (self.store / rel).write_text(self.text(rel) + line + "\n", encoding="utf-8")

    def card(self, slug: str, **over: str) -> None:
        values = {**CARD, "topic": slug, "expires": "—", **over}
        write(self.store / f"topics/{slug}.md", fill(skill_text("templates/topic.md"), values))

    def assert_only(self, rule: str, code: int = 1) -> str:
        res = self.lint()
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), {rule}, res.stdout)
        return res.stdout


class CleanStoreTest(StoreCase):
    def test_store_from_templates_is_clean(self):
        res = self.lint()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), set(), res.stdout)

    def test_store_and_run_together(self):
        res = self.lint("--run", str(self.store / "runs" / RUN_ID))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("нарушений 0, предупреждений 0", res.stdout)

    def test_not_a_store_is_call_error(self):
        res = run_script("lint", "--store", str(self.base / "home"), home=self.home)
        self.assertEqual(res.returncode, 2)
        self.assertIn("init", res.stderr)


class InitTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def init(self, path: Path):
        return run_script("init", str(path), home=self.base)

    def test_creates_layout(self):
        store = self.base / "lib"
        res = self.init(store)
        self.assertEqual(res.returncode, 0, res.stderr)
        for name in ("INDEX.md", "log.md", "sources.md", ".gitignore", ".ignore"):
            self.assertTrue((store / name).is_file(), name)
        for name in deep_search.STORE_DIRS:
            self.assertTrue((store / name).is_dir(), name)
        self.assertEqual((store / "INDEX.md").read_text(encoding="utf-8"),
                         INDEX.split("\n", 2)[0] + "\n" + INDEX.split("\n", 2)[1] + "\n")
        self.assertEqual((store / "sources.md").read_text(encoding="utf-8"), SOURCES_HEAD)
        self.assertIn("raw/", (store / ".gitignore").read_text(encoding="utf-8").splitlines())
        self.assertIn("archive/", (store / ".ignore").read_text(encoding="utf-8").splitlines())

    def test_fresh_store_is_clean_and_index_keeps_it(self):
        store = self.base / "lib"
        self.init(store)
        before = (store / "INDEX.md").stat().st_mtime_ns
        self.assertIn("без изменений", run_script("index", str(store), home=self.base).stdout)
        self.assertEqual((store / "INDEX.md").stat().st_mtime_ns, before)
        res = run_script("lint", "--store", str(store), home=self.base)
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_refuses_existing_store(self):
        store = self.base / "lib"
        self.init(store)
        (store / "log.md").write_text("## [2026-10-05] verify | x | —\n", encoding="utf-8")
        res = self.init(store)
        self.assertEqual(res.returncode, 2)
        self.assertIn("уже есть", res.stderr)
        self.assertEqual((store / "log.md").read_text(encoding="utf-8"),
                         "## [2026-10-05] verify | x | —\n")

    def test_project_folder_with_other_files(self):
        # research/ проекта может уже содержать что-то своё и .gitignore: init дописывает.
        store = self.base / "research"
        write(store / "notes/old.md", "заметки\n")
        write(store / ".gitignore", "*.tmp")
        self.assertEqual(self.init(store).returncode, 0)
        self.assertEqual((store / ".gitignore").read_text(encoding="utf-8"), "*.tmp\nraw/\n")

    def test_file_is_call_error(self):
        path = self.base / "file"
        path.write_text("x", encoding="utf-8")
        self.assertEqual(self.init(path).returncode, 2)


class IndexTest(StoreCase):
    def test_fixture_index_is_what_index_builds(self):
        before = (self.store / "INDEX.md").stat().st_mtime_ns
        self.assertIn("без изменений", self.index().stdout)
        self.assertEqual(self.text("INDEX.md"), INDEX)
        self.assertEqual((self.store / "INDEX.md").stat().st_mtime_ns, before)

    def test_sorted_without_archived_and_stable(self):
        self.card("zeta-topic")
        self.card("alpha-topic", tldr="Тема | с чертой")
        self.card("beta-topic", status="archived")
        self.assertIn("обновлён", self.index().stdout)
        slugs = [line.split(" | ")[0][2:] for line in self.text("INDEX.md").splitlines()[2:]]
        self.assertEqual(slugs, ["alpha-topic", SLUG, "zeta-topic"])
        self.assertIn("Тема \\| с чертой", self.text("INDEX.md"))
        first = self.text("INDEX.md")
        self.assertIn("без изменений", self.index().stdout)
        self.assertEqual(self.text("INDEX.md"), first)
        self.assertEqual(self.lint().returncode, 0, self.lint().stdout)

    def test_card_without_frontmatter_is_skipped_with_warning(self):
        write(self.store / "topics/broken.md", "# без шапки\n")
        res = self.index()
        self.assertIn("warn: topics/broken.md: card-header: ", res.stdout)
        self.assertEqual(self.text("INDEX.md"), INDEX)

    def test_not_a_store_is_call_error(self):
        res = run_script("index", str(self.base / "home"), home=self.home)
        self.assertEqual(res.returncode, 2)


class StoreErrorsTest(StoreCase):
    """По одной испорченной копии на правило-ошибку: код 1 и имя правила."""

    def test_index_coverage_card_without_row(self):
        self.edit("INDEX.md", INDEX.splitlines()[2] + "\n", "")
        out = self.assert_only("index-coverage")
        self.assertIn(f"topics/{SLUG}.md: index-coverage: ", out)

    def test_index_coverage_row_without_card(self):
        self.append("INDEX.md", "| gone | — | — | live | 2026-10-05 | — |")
        self.assertIn("gone", self.assert_only("index-coverage"))

    def test_index_coverage_stale_row(self):
        self.edit(f"topics/{SLUG}.md", "tldr: Хранение", "tldr: Хранилища")
        self.assertIn("deep_search.py index", self.assert_only("index-coverage"))

    def test_card_header(self):
        cases = (
            ("tldr: Хранение журналов и поиск по ним: варианты и выбор\n", ""),
            ("status: live", "status: done"),
            ("checked: 2026-10-05", "checked: вчера"),
            ("runs: 2026-10-05-log-search", "runs: [2026-10-05-log-search]"),
            ("topic: log-search", "topic: other"),
            ("expires: 2999-01-03", "expires: 2999-02-01"),
        )
        for old, new in cases:
            with self.subTest(new=new or f"без {old.split(':')[0]}"):
                self.setUp()
                self.edit(f"topics/{SLUG}.md", old, new)
                self.index()
                self.assert_only("card-header")

    def test_card_header_tldr_length(self):
        long = "т" * (deep_search.TLDR_MAX_CHARS + 1)
        self.edit(f"topics/{SLUG}.md", "tldr: Хранение журналов и поиск по ним: варианты и выбор",
                  f"tldr: {long}")
        self.index()
        self.assertIn("tldr", self.assert_only("card-header"))

    def test_claim_id(self):
        cases = (
            ("C-log-search-002 |", "C-log-search-2 |"),
            ("C-log-search-002 |", "C-other-002 |"),
            ("C-log-search-002 |", "C-log-search-001 |"),
        )
        for old, new in cases:
            with self.subTest(new=new):
                self.setUp()
                self.edit(f"claims/{SLUG}.md", old, new)
                self.assert_only("claim-id")

    def test_claim_source_unknown(self):
        # S-7b1c04aa остаётся в строке 003, так что сирот нет.
        self.edit(f"claims/{SLUG}.md", "| S-7b1c04aa | «The", "| S-deadbeef | «The")
        out = self.assert_only("claim-source")
        self.assertIn("S-deadbeef нет в sources.md", out)

    def test_claim_source_synthesis(self):
        self.edit(f"claims/{SLUG}.md", "| S-7b1c04aa | «The", "| topics/log-search.md | «The")
        self.assertIn("синтез", self.assert_only("claim-source"))

    def test_source_dup_same_id(self):
        self.append("sources.md", "| S-7b1c04aa | paper | Копия | Автор | 2025-01-01 | "
                                  "2026-10-06 | 10.1234/x.5678 | — | формат |")
        self.assert_only("source-dup")

    def test_source_dup_same_key(self):
        # Тот же URL без utm_* и фрагмента — тот же ключ под другим id.
        self.append("sources.md", "| S-11111111 | docs | Лицензия | Project X | 2026-09-01 | "
                                  "2026-10-05 | https://EXAMPLE.org/x/license | — | лицензия |")
        self.edit(f"claims/{SLUG}.md", "S-3f2a91c0 §3;", "S-11111111 §3;")
        out = self.assert_only("source-dup")
        self.assertIn("S-11111111 и S-3f2a91c0", out)

    def test_source_dup_doi_case(self):
        self.append("sources.md", "| S-22222222 | paper | Формат | Автор | 2025-01-01 | "
                                  "2026-10-05 | https://doi.org/10.1234/x.5678 | — | формат |")
        self.edit(f"claims/{SLUG}.md", "S-3f2a91c0 §3; S-7b1c04aa", "S-3f2a91c0 §3; S-22222222")
        self.assert_only("source-dup")

    def test_source_orphan(self):
        self.append("sources.md", "| S-33333333 | forum | Обсуждение | — | 2026-01-01 | "
                                  "2026-10-05 | https://example.org/forum | — | опыт |")
        self.assertIn("S-33333333", self.assert_only("source-orphan"))

    def test_source_orphan_counts_archive(self):
        (self.store / "archive/claims/old-logs.md").unlink()
        self.assertIn("S-0a1b2c3d", self.assert_only("source-orphan"))

    def test_claim_format(self):
        cases = (
            ("| B2 |", "| G7 |"),
            ("«Licensed under the Apache License 2.0»", "Licensed under the Apache License 2.0"),
            ("| V0 |", "| V0→2027-01-01 |"),
            ("superseded→C-log-search-003", "superseded→C-log-search-009"),
            ("| live |", "| alive |"),
            ("AGPL \\| двойной", "AGPL | двойной"),
            ("«Licensed under the Apache License 2.0»", "«" + "слово " * 26 + "»"),
        )
        for old, new in cases:
            with self.subTest(new=new):
                self.setUp()
                self.edit(f"claims/{SLUG}.md", old, new)
                self.assert_only("claim-format")

    def test_claim_format_registry_is_table_only(self):
        self.edit(f"claims/{SLUG}.md", CLAIMS_HEAD, "# Утверждения\n\n" + CLAIMS_HEAD)
        self.assert_only("claim-format")

    def test_source_format(self):
        self.edit("sources.md", "S-0a1b2c3d", "S-0A1B2C3D")
        self.edit("archive/claims/old-logs.md", "S-0a1b2c3d", "S-0A1B2C3D")
        self.assert_only("source-format")

    def test_log_entry(self):
        cases = (
            ("] search |", "] found |"),
            (f"| {RUN_ID}\n", "|\n"),
            ("Тема ушла в архив.\n", "Тема ушла в архив.\nВторая.\nТретья.\n"),
        )
        for old, new in cases:
            with self.subTest(new=new):
                self.setUp()
                self.edit("log.md", old, new)
                self.assert_only("log-entry")


class StoreWarningsTest(StoreCase):
    """Бюджеты и просрочка — предупреждения: код 0."""

    def test_index_lines(self):
        for n in range(deep_search.INDEX_MAX_LINES):
            self.card(f"topic-{n:03d}")
        self.index()
        out = self.assert_only("index-lines", code=0)
        self.assertIn("warn: INDEX.md: index-lines: ", out)

    def test_card_lines(self):
        self.append(f"topics/{SLUG}.md", "строка\n" * deep_search.CARD_MAX_LINES)
        self.assert_only("card-lines", code=0)

    def test_claims_lines(self):
        rows = [CLAIM_ROWS[1].replace("002", f"{n:03d}") for n in range(4, 4 + 198)]
        self.append(f"claims/{SLUG}.md", "\n".join(rows))
        self.assert_only("claims-lines", code=0)

    def test_claims_at_limit_is_quiet(self):
        rows = [CLAIM_ROWS[1].replace("002", f"{n:03d}") for n in range(4, 4 + 197)]
        self.append(f"claims/{SLUG}.md", "\n".join(rows))
        self.assertEqual(self.rules(self.lint().stdout), set())

    def test_claim_expired(self):
        self.edit(f"claims/{SLUG}.md", "V2→2999-01-03", "V2→2000-01-03")
        self.edit(f"topics/{SLUG}.md", "expires: 2999-01-03", "expires: 2000-01-03")
        self.index()
        out = self.assert_only("claim-expired", code=0)
        self.assertIn("warn: claims/log-search.md: claim-expired: C-log-search-003", out)

    def test_stale_claim_is_not_warned(self):
        self.edit(f"claims/{SLUG}.md", "V2→2027-01-03", "V2→2000-01-03")
        self.assertEqual(self.rules(self.lint().stdout), set())

    def test_all_v0_card_expires_dash(self):
        self.edit(f"claims/{SLUG}.md", "V2→2999-01-03", "V0")
        self.edit(f"topics/{SLUG}.md", "expires: 2999-01-03", "expires: —")
        self.index()
        self.assertEqual(self.rules(self.lint().stdout), set())


class SkillFormatsTest(unittest.TestCase):
    """Форматы в скрипте совпадают с файлами скилла: правка одной стороны ловится тестом."""

    def test_return_keys_match_template(self):
        text = skill_text("templates/branch-return.yaml")
        keys = list(deep_search.yaml_fields(text.splitlines()))
        self.assertEqual(keys, list(deep_search.RETURN_KEYS))

    def test_brief_template_has_checked_fields(self):
        fields = deep_search.frontmatter(skill_text("templates/brief.md")) or {}
        checked = (set(deep_search.BRIEF_M_FIELDS) | set(deep_search.BRIEF_ENUMS)
                   | {f for fs in deep_search.BRIEF_TYPE_FIELDS.values() for f in fs})
        self.assertEqual(checked - set(fields), set())

    def test_card_fields_match_template(self):
        fields = deep_search.frontmatter(skill_text("templates/topic.md")) or {}
        self.assertEqual(list(fields), list(deep_search.CARD_FIELDS))

    def test_table_headers_in_store_reference(self):
        store = skill_text("references/store.md")
        for header in (deep_search.CLAIMS_HEADER, deep_search.SOURCES_HEADER,
                       deep_search.INDEX_HEADER):
            self.assertIn("`" + deep_search.table_row(header) + "`", store)
        self.assertIn("## [ГГГГ-ММ-ДД] <вид> | <slug> | <прогон>", store)

    def test_enums_in_brief_reference(self):
        brief = skill_text("references/brief.md")
        for values in deep_search.BRIEF_ENUMS.values():
            for value in values:
                self.assertRegex(brief, rf"`{re.escape(value)}`")


if __name__ == "__main__":
    unittest.main()
