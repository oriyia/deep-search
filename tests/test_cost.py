"""`cost`: цена сценариев по размерам файлов — на самом скилле, эталоне и раздутых копиях."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from support import CORE, ISSUE_RE, REPO, deep_search, make_skill, run_script

SCENARIOS = ("quick", "reuse", "brief", "fan-out", "branch", "merge", "save", "resume", "full")
ROW_RE = re.compile(r"^(\S+)\s+([\d ]+?)\s{2,}([\d ]+?)\s{2,}\S", re.MULTILINE)


def parse_rows(out: str) -> dict[str, int]:
    """Сценарий → символы из таблицы вывода."""
    return {m.group(1): int(m.group(2).replace(" ", "")) for m in ROW_RE.finditer(out)
            if m.group(1) in SCENARIOS}


class CostCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.skill = make_skill(base / "skill")

    def cost(self, *args: str, skill: Path | None = None):
        res = run_script("cost", "--skill-dir", str(skill or self.skill), *args, home=self.home)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertLessEqual(len(res.stdout.rstrip("\n")), deep_search.OUTPUT_MAX_CHARS)
        return res.stdout

    def warned(self, out: str) -> set[tuple[str, str]]:
        return {(m.group(1), m.group(2)) for m in ISSUE_RE.finditer(out)}

    def bloat(self, rel: str, chars: int) -> None:
        path = self.skill / rel
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "ж" * (chars - len(text)), encoding="utf-8")


class CleanCostTest(CostCase):
    def test_skill_itself_has_no_warnings(self):
        res = run_script("cost", home=self.home)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("warn: ", res.stdout)
        self.assertIn("предупреждений 0", res.stdout)
        self.assertEqual(set(parse_rows(res.stdout)), set(SCENARIOS))

    def test_default_dir_is_script_dir(self):
        explicit = self.cost(skill=REPO)
        self.assertEqual(run_script("cost", home=self.home).stdout, explicit)

    def test_reference_skill_has_no_warnings(self):
        out = self.cost()
        self.assertEqual(self.warned(out), set(), out)
        self.assertIn("веток 3, ответ ветки 5 000 символов", out)

    def test_bad_arguments_are_call_errors(self):
        for args in (["--branches", "-1"], ["--return-chars", "-5"]):
            with self.subTest(args=args):
                res = run_script("cost", "--skill-dir", str(self.skill), *args, home=self.home)
                self.assertEqual(res.returncode, 2)
        res = run_script("cost", "--skill-dir", str(self.skill / "nope"), home=self.home)
        self.assertEqual(res.returncode, 2)


class BloatedCostTest(CostCase):
    def test_bloated_subfile_warns_its_stages(self):
        self.bloat("references/brief.md", deep_search.STAGE_MAX_CHARS)
        found = self.warned(self.cost())
        self.assertIn(("brief", "cost-stage"), found)
        self.assertIn(("fan-out", "cost-stage"), found)
        self.assertNotIn(("merge", "cost-stage"), found)

    def test_bloated_core_warns_stages_and_full(self):
        self.bloat("SKILL.md", deep_search.FULL_MAX_CHARS + 1)
        out = self.cost()
        found = self.warned(out)
        for name in ("quick", "reuse", "brief", "fan-out", "merge", "save", "resume"):
            self.assertIn((name, "cost-stage"), found)
        self.assertIn(("full", "cost-full"), found)
        # Ветка ядро не читает: её цена от ядра не зависит.
        self.assertNotIn(("branch", "cost-stage"), found)
        self.assertIn("крупнее всего: SKILL.md", out)
        # Тот же раздутый скилл ломает и self (спецификация, 8.2).
        res = run_script("self", "--skill-dir", str(self.skill), home=self.home)
        self.assertEqual(res.returncode, 1)

    def test_many_branches_warn_merge_and_full(self):
        found = self.warned(self.cost("--branches", "12"))
        self.assertIn(("merge", "cost-stage"), found)
        self.assertIn(("full", "cost-full"), found)
        self.assertNotIn(("brief", "cost-stage"), found)

    def test_missing_file_warns_once(self):
        (self.skill / "templates/report.md").unlink()
        out = self.cost()
        self.assertEqual(self.warned(out), {("templates/report.md", "cost-missing")})
        self.assertEqual(out.count("cost-missing"), 1)


class CostFormulaTest(CostCase):
    """Суммы сценариев — размеры файлов эталона плюс бюджеты из констант."""

    def size(self, *rels: str) -> int:
        return sum(len((self.skill / r).read_text(encoding="utf-8")) for r in rels)

    def test_sums(self):
        branches, ret = 2, 1_000
        rows = parse_rows(self.cost("--branches", str(branches), "--return-chars", str(ret)))
        core = len(CORE)
        self.assertEqual(rows["quick"], core)
        self.assertEqual(rows["brief"],
                         self.size("SKILL.md", "references/brief.md", "templates/brief.md"))
        self.assertEqual(rows["fan-out"],
                         rows["brief"] + self.size("references/branching.md",
                                                   "templates/branch-task.yaml")
                         + branches * deep_search.TASK_MAX_CHARS)
        self.assertEqual(rows["merge"],
                         self.size("SKILL.md", "references/verify-merge.md", "templates/report.md")
                         + branches * ret)
        self.assertEqual(rows["resume"], core + deep_search.PLAN_MAX_CHARS)
        # full — без повторов: ядро считается один раз.
        save = self.size("SKILL.md", "references/store.md", "templates/topic.md") \
            + deep_search.SAVE_WRITE_CHARS
        self.assertEqual(rows["save"], save)
        self.assertEqual(rows["full"], rows["fan-out"] + rows["merge"] + save - 2 * core)

    def test_branch_takes_largest_preset(self):
        (self.skill / "presets/science.md").write_text("Когда читать: наука.\n" + "н" * 9_000,
                                                       encoding="utf-8")
        scenarios, _ = deep_search.cost_scenarios(self.skill, 3, 5_000)
        branch = next(s for s in scenarios if s.name == "branch")
        self.assertIn("presets/science.md", [p.label for p in branch.parts])

    def test_no_preset_is_not_a_warning(self):
        (self.skill / "presets/technology.md").unlink()
        self.assertEqual(self.warned(self.cost()), set())


if __name__ == "__main__":
    unittest.main()
