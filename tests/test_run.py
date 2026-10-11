"""`lint --run`: бриф, plan.md, ответы веток и журнал прогона."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import (BRIEF_M, BRIEF_S, ISSUE_RE, RUN_ID, TASK_ID, brief_text, deep_search,
                     journal_line, make_run, run_script, write)


class RunCase(unittest.TestCase):
    """Прогон уровня M из шаблонов скилла и отдельный HOME во временной папке."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.run_dir = make_run(base / "runs")

    def lint(self):
        return run_script("lint", "--run", str(self.run_dir), home=self.home)

    def rules(self, out: str) -> set[str]:
        return {m.group(2) for m in ISSUE_RE.finditer(out)}

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.run_dir / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def brief(self, values: dict[str, str]) -> None:
        write(self.run_dir / "brief.md", brief_text(values))

    def assert_only(self, rule: str, code: int = 1) -> str:
        res = self.lint()
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), {rule}, res.stdout)
        return res.stdout


class CleanRunTest(RunCase):
    def test_run_from_templates_is_clean(self):
        res = self.lint()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), set(), res.stdout)
        self.assertIn("нарушений 0", res.stdout)

    def test_s_brief_needs_no_plan(self):
        self.brief(BRIEF_S)
        (self.run_dir / "plan.md").unlink()
        self.assertEqual(self.lint().returncode, 0)

    def test_paths_name_the_run(self):
        (self.run_dir / "plan.md").unlink()
        out = self.assert_only("plan-missing")
        self.assertIn(f"{RUN_ID}/plan.md: plan-missing: ", out)

    def test_missing_run_dir_is_call_error(self):
        res = run_script("lint", "--run", str(self.run_dir / "nope"), home=self.home)
        self.assertEqual(res.returncode, 2)

    def test_lint_without_target_is_call_error(self):
        res = run_script("lint", home=self.home)
        self.assertEqual(res.returncode, 2)
        self.assertIn("--run", res.stderr)


class BriefTest(RunCase):
    def test_s_without_done_criteria(self):
        self.brief({**BRIEF_S, "done_criteria": ""})
        out = self.assert_only("brief-required")
        self.assertIn("done_criteria", out)

    def test_m_requires_o_fields(self):
        self.brief({**BRIEF_M, "stop_rule": "", "prior_work": ""})
        out = self.assert_only("brief-required")
        self.assertIn("prior_work, stop_rule", out)

    def test_s_does_not_require_o_fields(self):
        self.brief({**BRIEF_S, "store_topic": ""})
        self.assertEqual(self.lint().returncode, 0)

    def test_type_fields_from_m(self):
        for qtype, field in (("validation", "hypotheses"), ("options", "type_data"),
                             ("exhaustive_list", "known_items"),
                             ("replacement", "inclusion_criteria"), ("compliance", "type_data")):
            with self.subTest(question_type=qtype):
                self.brief({**BRIEF_M, "question_type": qtype})
                out = self.assert_only("brief-required")
                self.assertIn(field, out)

    def test_type_fields_not_required_on_s(self):
        self.brief({**BRIEF_S, "question_type": "validation"})
        self.assertEqual(self.lint().returncode, 0)

    def test_exhaustive_list_needs_two_known_items(self):
        self.brief({**BRIEF_M, "question_type": "exhaustive_list", "inclusion_criteria": "без сети",
                    "known_items": "Loki"})
        out = self.assert_only("brief-required")
        self.assertIn("known_items", out)
        self.brief({**BRIEF_M, "question_type": "exhaustive_list", "inclusion_criteria": "без сети",
                    "known_items": "Loki, OpenSearch"})
        self.assertEqual(self.lint().returncode, 0)

    def test_quoted_empty_is_unfilled(self):
        self.brief({**BRIEF_M, "concept": '""'})
        self.assertIn("concept", self.assert_only("brief-required"))

    def test_missing_brief(self):
        (self.run_dir / "brief.md").unlink()
        self.assert_only("brief-required")

    def test_unknown_tier_checks_s_fields(self):
        self.brief({**BRIEF_M, "budget_tier": "", "question": ""})
        out = self.assert_only("brief-required")
        self.assertIn("budget_tier", out)
        self.assertIn("question", out)
        self.assertNotIn("plan", out)

    def test_enum(self):
        for field, value in (("question_type", "survey"), ("mode", "monitoring"),
                             ("stakes", "critical"), ("coverage_goal", "all"),
                             ("budget_tier", "XXL"), ("store", "cloud"), ("preset", "science")):
            with self.subTest(field=field):
                self.brief({**BRIEF_M, field: value})
                out = self.assert_only("brief-enum")
                self.assertIn(f"{field}: «{value}»", out)

    def test_preset_from_skill_presets(self):
        # Допустимы пресеты, у которых есть presets/<имя>.md скилла: ai появился вместе с файлом.
        for preset in ("ai", "technology", "none"):
            with self.subTest(preset=preset):
                self.brief({**BRIEF_M, "preset": preset})
                res = self.lint()
                self.assertEqual(res.returncode, 0, res.stdout)

    def test_preset_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            self.assertEqual(deep_search.preset_names(skill), deep_search.BRIEF_ENUMS["preset"])
            write(skill / "presets/science.md", "Когда читать: наука.\n")
            write(skill / "presets/science-feeds.json", "{}")
            self.assertEqual(deep_search.preset_names(skill), ("science", "none"))

    def test_enum_ignores_yaml_comment(self):
        self.brief({**BRIEF_M, "stakes": "high  # решение на год"})
        self.assertEqual(self.lint().returncode, 0)

    def test_store_none_only_on_s(self):
        self.brief({**BRIEF_M, "store": "none"})
        self.assertIn("store: none", self.assert_only("brief-enum"))
        self.brief({**BRIEF_S, "store": "none"})
        self.assertEqual(self.lint().returncode, 0)

    def test_id(self):
        cases = (
            {**BRIEF_M, "id": "log-search"},
            {**BRIEF_M, "id": "2026-10-06-log-search"},
            {**BRIEF_M, "store_topic": "other-topic"},
            {**BRIEF_M, "store_topic": "Log_Search"},
        )
        for values in cases:
            with self.subTest(values={k: values[k] for k in ("id", "store_topic")}):
                self.brief(values)
                self.assert_only("brief-id")

    def test_relative_run_path(self):
        # Из папки прогона: у «.» нет имени, а id брифа сверяется с именем папки.
        res = run_script("lint", "--run", ".", home=self.home, cwd=self.run_dir)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_id_suffix_matches_topic(self):
        run = self.run_dir.parent / f"{RUN_ID}-2"
        self.run_dir.rename(run)
        self.run_dir = run
        self.brief({**BRIEF_M, "id": f"{RUN_ID}-2"})
        self.assertEqual(self.lint().returncode, 0, self.lint().stdout)


class PlanTest(RunCase):
    def test_plan_missing_from_m(self):
        for tier in ("M", "L", "XL"):
            with self.subTest(tier=tier):
                self.brief({**BRIEF_M, "budget_tier": tier})
                (self.run_dir / "plan.md").unlink(missing_ok=True)
                self.assert_only("plan-missing")


class ReturnTest(RunCase):
    RETURN = f"branches/{TASK_ID}.return.yaml"

    def test_return_chars_5001(self):
        path = self.run_dir / self.RETURN
        text = path.read_text(encoding="utf-8")
        pad = deep_search.RETURN_MAX_CHARS + 1 - len(text)
        self.edit(self.RETURN, 'answer: ""', 'answer: "' + "о" * pad + '"')
        self.assertEqual(len(path.read_text(encoding="utf-8")), 5_001)
        out = self.assert_only("return-chars")
        self.assertIn("5 001 символов", out)

    def test_return_chars_5000_is_ok(self):
        path = self.run_dir / self.RETURN
        text = path.read_text(encoding="utf-8")
        self.edit(self.RETURN, 'answer: ""',
                  'answer: "' + "о" * (deep_search.RETURN_MAX_CHARS - len(text)) + '"')
        self.assertEqual(self.lint().returncode, 0)

    def test_return_keys_missing(self):
        self.edit(self.RETURN, "gaps: []", "")
        self.assertIn("gaps", self.assert_only("return-keys"))

    def test_return_keys_unknown(self):
        self.edit(self.RETURN, "gaps: []", "gaps: []\nfinding: []")
        self.assertIn("finding", self.assert_only("return-keys"))

    def test_return_keys_task_id_matches_file(self):
        self.edit(self.RETURN, "task_id: B2.1", "task_id: B2.2")
        self.assertIn("B2.2", self.assert_only("return-keys"))

    def test_return_status(self):
        self.edit(self.RETURN, "status: done", "status: finished")
        self.assertIn("finished", self.assert_only("return-status"))

    def test_every_return_status_is_ok(self):
        for status in deep_search.RETURN_STATUSES:
            with self.subTest(status=status):
                path = self.run_dir / self.RETURN
                text = path.read_text(encoding="utf-8")
                old = next(line for line in text.splitlines() if line.startswith("status:"))
                path.write_text(text.replace(old, f"status: {status}"), encoding="utf-8")
                self.assertEqual(self.lint().returncode, 0)

    def test_task_chars(self):
        path = self.run_dir / f"branches/{TASK_ID}.task.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "#" * (deep_search.TASK_MAX_CHARS - len(text) + 1),
                        encoding="utf-8")
        self.assert_only("task-chars")


class JournalTest(RunCase):
    LOG = f"branches/{TASK_ID}.jsonl"

    def append(self, line: str) -> None:
        path = self.run_dir / self.LOG
        path.write_text(path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")

    def test_log_json(self):
        self.append('{"ts": "2026-10-05", oops}')
        self.append("[1, 2]")
        out = self.assert_only("log-json")
        self.assertIn("строка 3", out)
        self.assertIn("плохих строк всего 2", out)

    def test_log_fields_missing(self):
        self.append(journal_line().replace('"dupes": 2, ', ""))
        self.assertIn("dupes", self.assert_only("log-fields"))

    def test_log_fields_values(self):
        for over, word in (({"method": "search"}, "method"), ({"branch": "B9"}, "branch"),
                           ({"shown": "10"}, "shown"), ({"kept": "ev1"}, "kept")):
            with self.subTest(over=over):
                self.setUp()
                self.append(journal_line(**over))
                self.assertIn(word, self.assert_only("log-fields"))

    def test_batch_needs_count(self):
        self.append(journal_line(method="batch"))
        self.assertIn("count", self.assert_only("log-fields"))

    def test_log_undercount(self):
        # Ответ насчитал 30 открытых источников, а в журнале их нет: бюджет по журналу занижен.
        rel = f"branches/{TASK_ID}.return.yaml"
        self.edit(rel, "sources_viewed: 0", "sources_viewed: 30")
        res = self.lint()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.rules(res.stdout), {"log-undercount"}, res.stdout)
        # Пакет скрипта — одна строка, но count обращений.
        self.append(journal_line(method="batch", query="t.me/s 12 каналов × 3 страницы",
                                 count=30))
        res = self.lint()
        self.assertEqual(self.rules(res.stdout), set(), res.stdout)

    def test_capture_is_optional_extra(self):
        self.append(journal_line(capture={"archive": "https://web.archive.org/x",
                                          "sha256": "ab" * 32}))
        self.assertEqual(self.lint().returncode, 0)


if __name__ == "__main__":
    unittest.main()
