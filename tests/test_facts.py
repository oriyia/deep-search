"""`facts`: разбор цели, сборка полей из ответов API, пустое поле на 404, источник без ответа,
предел вывода, токен GitHub.

Сеть не трогается: функция запроса подменена и отдаёт урезанные настоящие ответы из
tests/fixtures/facts/.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from support import deep_search, run_script

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "facts"
TODAY = date(2026, 10, 9)
DAY = TODAY.isoformat()
TOKEN = "ghp_FACTSTOKEN0123456789"

GH = "https://api.github.com/repos/psf/requests"
DEPS_PROJECT = "https://api.deps.dev/v3/projects/github.com%2Fpsf%2Frequests:packageversions"
DEPS_PACKAGE = "https://api.deps.dev/v3/systems/pypi/packages/requests"
ECOSYSTEMS = "https://packages.ecosyste.ms/api/v1/registries/pypi.org/packages/requests"
SCORECARD = "https://api.securityscorecards.dev/projects/github.com/psf/requests"
OSV = "https://api.osv.dev/v1/query"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def eol(name: str) -> str:
    return f"https://endoflife.date/api/v1/products/{name}/"


def repology(name: str) -> str:
    return f"https://repology.org/api/v1/project/{name}"


class FakeNet:
    """Ответы по адресам: bytes — 200 с телом, int — код без тела, Probe — как есть. Каждый
    запрос записывается с методом, телом и заголовками; неизвестный адрес — 404."""

    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.calls: list[tuple[str, str, bytes | None, dict]] = []

    def __call__(self, method, url, data, headers):
        self.calls.append((method, url, data, dict(headers)))
        answer = self.answers.get(url)
        if answer is None:
            return deep_search.Probe(404, b"not found", url=url)
        if isinstance(answer, deep_search.Probe):
            return answer
        if isinstance(answer, int):
            return deep_search.Probe(answer, url=url)
        return deep_search.Probe(200, answer, url=url)

    def urls(self) -> list[str]:
        return [url for _, url, _, _ in self.calls]


def github_answers() -> dict[str, object]:
    """Репозиторий GitHub целиком: хостинг, Scorecard, связь с пакетом и его источники; у
    endoflife.date продукта нет (404 с HTML, как отвечает сайт)."""
    return {
        GH: fixture("github-repo.json"),
        f"{GH}/releases/latest": fixture("github-release.json"),
        f"{GH}/commits?per_page=1": fixture("github-commits.json"),
        SCORECARD: fixture("scorecard.json"),
        DEPS_PROJECT: fixture("depsdev-project.json"),
        DEPS_PACKAGE: fixture("depsdev-package.json"),
        f"{DEPS_PACKAGE}/versions/2.34.2": fixture("depsdev-version.json"),
        ECOSYSTEMS: fixture("ecosystems.json"),
        eol("requests"): deep_search.Probe(404, fixture("endoflife-404.html")),
        repology("requests"): fixture("repology.json"),
    }


def run(target: str, answers: dict[str, object], environ: dict | None = None):
    net = FakeNet(answers)
    result = deep_search.facts(target, fetch=net, environ=environ or {}, today=TODAY)
    return result, net


def by_field(result) -> dict[str, deep_search.Fact]:
    return {f.field: f for f in result.facts}


class ParseTargetTest(unittest.TestCase):
    def check(self, text: str, **expected):
        target = deep_search.parse_target(text)
        for key, value in expected.items():
            self.assertEqual(getattr(target, key), value, f"{text}: {key}")

    def test_github(self):
        for text in ("https://github.com/psf/requests", "https://github.com/psf/requests.git",
                     "https://github.com/psf/requests/tree/main/src", "github.com/psf/requests",
                     "https://www.github.com/psf/requests/", "psf/requests"):
            self.check(text, kind="repo", forge="github", host="github.com", path="psf/requests")

    def test_gitlab_with_subgroups_and_own_host(self):
        self.check("https://gitlab.com/gitlab-org/gitlab-runner/-/tree/main", forge="gitlab",
                   host="gitlab.com", path="gitlab-org/gitlab-runner")
        self.check("https://gitlab.com/group/sub/project", forge="gitlab", path="group/sub/project")
        self.check("https://gitlab.example.org/team/app", forge="gitlab",
                   host="gitlab.example.org", path="team/app")

    def test_forgejo_gitea_and_gitee(self):
        self.check("https://codeberg.org/forgejo/forgejo/src/branch/forgejo", forge="gitea",
                   host="codeberg.org", path="forgejo/forgejo")
        self.check("https://git.example.org:3000/owner/repo", forge="gitea",
                   host="git.example.org:3000", path="owner/repo")
        self.check("https://gitee.com/openharmony/docs", forge="gitee", path="openharmony/docs")

    def test_purl(self):
        self.check("pkg:pypi/requests", kind="package", system="pypi", name="requests",
                   version="")
        self.check("pkg:pypi/Requests_Toolbelt@1.0.0", name="requests-toolbelt", version="1.0.0")
        self.check("pkg:npm/react@18.3.1", system="npm", name="react", version="18.3.1")
        self.check("pkg:npm/react@18.3.1?repository_url=x#lib", name="react", version="18.3.1")
        self.check("pkg:npm/%40types/node@20.1.0", name="@types/node", version="20.1.0")
        self.check("pkg:npm/@types/node", name="@types/node", version="")

    def test_unknown_target_lists_examples(self):
        for text in ("", "requests", "https://github.com/psf", "pkg:cargo/serde", "pkg:pypi/",
                     "pkg:npm/react@", "ftp://github.com/a/b", "a/b/c", "psf/requests extra",
                     "codeberg.org/forgejo"):
            with self.assertRaises(deep_search.FactsError, msg=text) as caught:
                deep_search.parse_target(text)
            self.assertIn("pkg:npm/react@18.3.1", str(caught.exception))

    def test_cli_unknown_target_exits_2(self):
        with tempfile.TemporaryDirectory() as home:
            proc = run_script("facts", "not a target", home=Path(home))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("цель не распознана", proc.stderr)
        self.assertIn("https://github.com/psf/requests", proc.stderr)


class GithubRepoTest(unittest.TestCase):
    def test_fields_with_source_and_path(self):
        result, net = run("psf/requests", github_answers())
        self.assertEqual(result.failed, [])
        f = by_field(result)
        self.assertEqual(f["license"], deep_search.Fact("license", "Apache-2.0", GH,
                                                        "license.spdx_id"))
        self.assertEqual((f["archived"].value, f["archived"].path), ("нет", "archived"))
        self.assertEqual((f["stars"].value, f["stars"].path), ("54509", "stargazers_count"))
        self.assertEqual(f["last_commit"].value, "2026-09-21")
        self.assertEqual(f["last_commit"].source, f"{GH}/commits?per_page=1")
        self.assertEqual(f["last_commit"].path, "[0].commit.committer.date")
        self.assertEqual(f["last_release"].value, "v2.34.2 (2026-05-14)")
        self.assertEqual(f["scorecard"].value, "8.3 из 10 (2026-10-05); Maintained 10 из 10")
        self.assertEqual(f["scorecard"].source, SCORECARD)
        # Подделка с бо́льшим числом версий проигрывает подтверждённой связи; модуль Go — не пакет.
        self.assertEqual(f["package"].value, "pkg:pypi/requests, других кандидатов 1")
        self.assertEqual(f["versions"].value, "по умолчанию 2.34.2 (2026-05-14), всего 3")
        self.assertEqual(f["version"].source, f"{DEPS_PACKAGE}/versions/2.34.2")
        self.assertTrue(f["version"].value.startswith("2.34.2: лицензии Apache-2.0; уязвимостей 6"))
        self.assertIn("GHSA-9hjg-9r4m-mvj7", f["version"].value)
        self.assertEqual(f["usage"].source, ECOSYSTEMS)
        self.assertIn("1186076091 за last-month", f["usage"].value)
        self.assertIn("зависимых пакетов 32025, репозиториев 679836", f["usage"].value)
        self.assertIn("репозиториев 4, новейшая 2.34.2", f["distros"].value)
        self.assertIn("по имени «requests»", f["distros"].value)
        # Репозиторий у цели-репозитория не повторяется; OSV — только для заданной версии.
        self.assertNotIn("repository", f)
        self.assertNotIn(OSV, net.urls())
        order = list(deep_search.FACT_FIELDS)
        self.assertEqual([x.field for x in result.facts],
                         sorted((x.field for x in result.facts), key=order.index))

    def test_endoflife_404_is_empty_field_not_failure(self):
        result, _ = run("psf/requests", github_answers())
        self.assertEqual(by_field(result)["eol"],
                         deep_search.Fact("eol", None, eol("requests"), "HTTP 404"))
        text = deep_search.facts_text(result)
        self.assertIn(f"конец поддержки | — | {eol('requests')} §HTTP 404 | {DAY}", text)
        self.assertNotIn("не ответили:", text)

    def test_text_lines(self):
        result, _ = run("https://github.com/psf/requests", github_answers())
        lines = deep_search.facts_text(result).splitlines()
        self.assertEqual(lines[0], f"facts: github.com/psf/requests — полей {len(result.facts)}, "
                                   "не ответили 0")
        self.assertIn(f"лицензия | Apache-2.0 | {GH} §license.spdx_id | {DAY}", lines)
        self.assertEqual(len(lines), 1 + len(result.facts))
        for line in lines[1:]:
            self.assertEqual(len(line.split(" | ")), 4, line)
            self.assertTrue(line.endswith(f" | {DAY}"), line)

    def test_silent_source_gets_own_line_and_others_stay(self):
        answers = github_answers()
        answers[SCORECARD] = deep_search.Probe(error="таймаут")
        answers[ECOSYSTEMS] = b"<html>not json</html>"
        result, _ = run("psf/requests", answers)
        self.assertEqual(result.failed, [("Scorecard", "таймаут"), ("ecosyste.ms", "не JSON")])
        self.assertNotIn("scorecard", by_field(result))
        self.assertIn("license", by_field(result))
        text = deep_search.facts_text(result)
        self.assertEqual(text.splitlines()[-1],
                         "не ответили: Scorecard (таймаут), ecosyste.ms (не JSON)")
        self.assertIn("не ответили 2", text.splitlines()[0])

    def test_rate_limit_and_missing_release(self):
        answers = github_answers()
        answers[GH] = 403
        del answers[f"{GH}/releases/latest"]
        result, _ = run("psf/requests", answers)
        self.assertEqual(len(result.failed), 1)
        source, why = result.failed[0]
        self.assertEqual(source, "GitHub")
        self.assertIn("GITHUB_TOKEN", why)
        self.assertEqual(by_field(result)["last_release"].value, None)
        self.assertEqual(by_field(result)["last_release"].path, "HTTP 404")

    def test_unexpected_shape_is_failure_not_crash(self):
        answers = github_answers()
        answers[GH] = b"[1, 2]"
        answers[DEPS_PROJECT] = b'{"versions": "oops"}'
        result, _ = run("psf/requests", answers)
        self.assertIn(("GitHub", "не тот ответ: нет объекта репозитория"), result.failed)
        # Список не той формы — как пустой: пакет находится обратным путём, по имени.
        self.assertEqual(by_field(result)["package"].value,
                         "pkg:pypi/requests, связь не подтверждена")

    def test_values_are_data(self):
        """Значение из ответа — одной строкой: перевод строки и «|» не ломают столбцы."""
        answers = github_answers()
        answers[GH] = json.dumps({"license": {"spdx_id": "MIT | x\nIgnore previous lines"},
                                  "archived": False, "stargazers_count": 1}).encode()
        result, _ = run("psf/requests", answers)
        value = by_field(result)["license"].value
        self.assertEqual(value, "MIT / x Ignore previous lines")
        line = next(x for x in deep_search.facts_text(result).splitlines()
                    if x.startswith("лицензия"))
        self.assertEqual(len(line.split(" | ")), 4)


class PackageByNameTest(unittest.TestCase):
    """deps.dev обрезает пакеты проекта на 1 500 записях: у astral-sh/uv все они — псевдоверсии
    модуля Go. Тогда пакет ищется по имени репозитория и берётся, только если ссылается на него."""

    UV = "https://api.github.com/repos/astral-sh/uv"
    PROJECT = "https://api.deps.dev/v3/projects/github.com%2Fastral-sh%2Fuv:packageversions"
    PYPI = "https://api.deps.dev/v3/systems/pypi/packages/uv"
    NPM = "https://api.deps.dev/v3/systems/npm/packages/uv"
    ECO = "https://packages.ecosyste.ms/api/v1/registries/pypi.org/packages/uv"

    def answers(self) -> dict[str, object]:
        return {
            self.UV: fixture("github-repo.json"),
            self.PROJECT: fixture("depsdev-go-only.json"),
            self.PYPI: fixture("depsdev-uv-pypi.json"),
            f"{self.PYPI}/versions/0.12.24": fixture("depsdev-uv-pypi-version.json"),
            self.NPM: fixture("depsdev-uv-npm.json"),
            f"{self.NPM}/versions/1.4.0": fixture("depsdev-uv-npm-version.json"),
            self.ECO: fixture("ecosystems.json"),
        }

    def test_package_found_by_name_and_second_round_runs(self):
        result, net = run("astral-sh/uv", self.answers())
        f = by_field(result)
        self.assertEqual(f["package"], deep_search.Fact(
            "package", "pkg:pypi/uv, связь не подтверждена", f"{self.PYPI}/versions/0.12.24",
            "relatedProjects[SOURCE_REPO].projectKey.id"))
        self.assertEqual(f["versions"].source, self.PYPI)
        self.assertTrue(f["version"].value.startswith("0.12.24: лицензии Apache-2.0 OR MIT"))
        self.assertEqual(f["usage"].source, self.ECO)
        self.assertIn(self.ECO, net.urls())
        self.assertNotIn(self.NPM, net.urls())  # нашёлся в PyPI — дальше не ищется
        self.assertLessEqual(len(deep_search.facts_text(result)), deep_search.FACTS_MAX_CHARS)
        self.assertLessEqual(len(deep_search.facts_json(result)), deep_search.FACTS_MAX_CHARS)

    def test_package_of_other_repository_is_not_taken(self):
        answers = self.answers()
        del answers[self.PYPI]  # в PyPI нет; в npm `uv` ссылается на github.com/micnic/uv
        result, net = run("astral-sh/uv", answers)
        f = by_field(result)
        self.assertIsNone(f["package"].value)
        self.assertEqual(f["package"].source, self.PROJECT)
        self.assertIn("не найден", f["package"].path)
        self.assertNotIn("обрезан", f["package"].path)
        self.assertIn(f"{self.NPM}/versions/1.4.0", net.urls())
        self.assertFalse({"versions", "version", "usage"} & set(f))
        self.assertNotIn(self.ECO, net.urls())

    def test_clipped_list_is_said(self):
        go = json.loads(fixture("depsdev-go-only.json"))["versions"][0]
        answers = {self.UV: fixture("github-repo.json"),
                   self.PROJECT: json.dumps({"versions": [go] * 1500}).encode()}
        result, _ = run("astral-sh/uv", answers)
        path = by_field(result)["package"].path
        self.assertIn("не найден; список обрезан на 1500", path)


class PackageTest(unittest.TestCase):
    def answers(self) -> dict[str, object]:
        return {
            DEPS_PACKAGE: fixture("depsdev-package.json"),
            f"{DEPS_PACKAGE}/versions/2.31.0": fixture("depsdev-version.json"),
            OSV: fixture("osv.json"),
            ECOSYSTEMS: fixture("ecosystems.json"),
            eol("requests"): fixture("endoflife.json"),
            repology("python:requests"): fixture("repology.json"),
        }

    def test_pypi_with_version(self):
        result, net = run("pkg:pypi/requests@2.31.0", self.answers())
        self.assertEqual(result.target, "pkg:pypi/requests@2.31.0")
        self.assertEqual(result.failed, [])
        f = by_field(result)
        self.assertEqual(f["repository"].value, "github.com/psf/requests, связь не подтверждена")
        self.assertEqual(f["repository"].path, "relatedProjects[SOURCE_REPO].projectKey.id")
        self.assertTrue(f["version"].value.startswith("2.31.0: лицензии Apache-2.0"))
        self.assertEqual(f["vulns"].value, "2.31.0: 2 — GHSA-9hjg-9r4m-mvj7, GHSA-9wx4-h78v-vm56")
        self.assertTrue(f["vulns"].source.startswith(f"POST {OSV} "))
        self.assertIn("репозиториев 4", f["distros"].value)
        # Хостинг и Scorecard — только у цели-репозитория.
        self.assertFalse({"license", "stars", "scorecard"} & set(f))
        method, _, data, headers = next(c for c in net.calls if c[1] == OSV)
        self.assertEqual(method, "POST")
        self.assertEqual(json.loads(data), {"package": {"name": "requests", "ecosystem": "PyPI"},
                                            "version": "2.31.0"})
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_endoflife_cycle_of_version_or_first_cycles(self):
        answers = self.answers()
        result, _ = run("pkg:pypi/requests@14.0.2", answers)
        self.assertEqual(by_field(result)["eol"].value, "14.0 — снят с поддержки 2026-04-30")
        result, _ = run("pkg:pypi/requests", answers)
        self.assertEqual(by_field(result)["eol"].value,
                         "16.0 — поддержка до 2026-10-29; 15.0 — поддержка до 2027-07-15; "
                         "14.0 — снят с поддержки 2026-04-30")

    def test_without_version_uses_default_and_skips_osv(self):
        answers = self.answers()
        answers[f"{DEPS_PACKAGE}/versions/2.34.2"] = fixture("depsdev-version.json")
        result, net = run("pkg:pypi/requests", answers)
        self.assertIn(f"{DEPS_PACKAGE}/versions/2.34.2", net.urls())
        self.assertNotIn(OSV, net.urls())
        self.assertNotIn("vulns", by_field(result))

    def test_missing_package_and_repology_name(self):
        result, _ = run("pkg:npm/%40types/node@20.1.0", {})
        f = by_field(result)
        deps = "https://api.deps.dev/v3/systems/npm/packages/%40types%2Fnode"
        self.assertEqual(f["versions"], deep_search.Fact("versions", None, deps, "HTTP 404"))
        self.assertEqual(f["usage"].source, "https://packages.ecosyste.ms/api/v1/registries/"
                                            "npmjs.org/packages/%40types%2Fnode")
        self.assertEqual(f["eol"].source, eol("types-node"))
        self.assertEqual(f["distros"].source, repology("node:types-node"))
        self.assertEqual(f["distros"].value,
                         "проекта «node:types-node» нет — имя в Repology может быть другим")
        self.assertEqual(result.failed, [])


class OtherForgesTest(unittest.TestCase):
    def test_gitlab(self):
        api = "https://gitlab.com/api/v4/projects/gitlab-org%2Fgitlab-runner"
        result, net = run("https://gitlab.com/gitlab-org/gitlab-runner", {
            f"{api}?license=true": fixture("gitlab-project.json"),
            f"{api}/releases?per_page=1": fixture("gitlab-releases.json"),
            f"{api}/repository/commits?per_page=1": fixture("gitlab-commits.json"),
        })
        f = by_field(result)
        self.assertEqual((f["license"].value, f["license"].path), ("mit", "license.key"))
        self.assertEqual((f["stars"].value, f["stars"].path), ("2573", "star_count"))
        self.assertNotIn("archived", f)  # GitLab без входа отдаёт null
        self.assertEqual(f["last_release"].value, "v19.4.1 (2026-09-24)")
        self.assertEqual(f["last_release"].path, "[0].tag_name, [0].released_at")
        self.assertEqual(f["last_commit"].value, "2026-10-09")
        self.assertIn("https://api.deps.dev/v3/projects/gitlab.com%2Fgitlab-org%2Fgitlab-runner"
                      ":packageversions", net.urls())
        self.assertFalse(any("securityscorecards" in u for u in net.urls()))

    def test_codeberg(self):
        api = "https://codeberg.org/api/v1/repos/forgejo/forgejo"
        result, net = run("https://codeberg.org/forgejo/forgejo", {
            api: fixture("gitea-repo.json"),
            f"{api}/releases/latest": fixture("gitea-release.json"),
            f"{api}/commits?limit=1&stat=false&verification=false&files=false":
                fixture("gitea-commits.json"),
            eol("forgejo"): fixture("endoflife.json"),
        })
        f = by_field(result)
        self.assertEqual((f["stars"].value, f["stars"].path), ("5611", "stars_count"))
        self.assertEqual(f["archived"].value, "нет")
        self.assertNotIn("license", f)  # licenses: null
        self.assertEqual(f["last_release"].value, "v16.0.5 (2026-09-17)")
        self.assertEqual(f["last_commit"].value, "2026-10-09")
        self.assertTrue(f["eol"].value.startswith("16.0 — поддержка до 2026-10-29"))
        self.assertFalse(any("deps.dev" in u or "securityscorecards" in u for u in net.urls()))
        self.assertEqual(result.failed, [])

    def test_gitee(self):
        api = "https://gitee.com/api/v5/repos/openharmony/docs"
        result, _ = run("https://gitee.com/openharmony/docs", {
            api: fixture("gitee-repo.json"),
            f"{api}/releases/latest": fixture("gitee-release.json"),
            f"{api}/commits?per_page=1": fixture("gitee-commits.json"),
        })
        f = by_field(result)
        self.assertEqual((f["license"].value, f["license"].path), ("CC-BY-4.0", "license"))
        self.assertEqual(f["stars"].value, "7596")
        self.assertEqual(f["last_release"].value, "OpenHarmony-1.0 (2020-09-09)")
        self.assertEqual(f["last_release"].path, "tag_name, created_at")
        self.assertEqual(f["last_commit"].value, "2026-04-27")


class TokenTest(unittest.TestCase):
    def test_token_only_to_github_api_and_never_in_output(self):
        environ = {"GITHUB_TOKEN": TOKEN, "PATH": "/bin"}
        answers = github_answers()
        answers[SCORECARD] = deep_search.Probe(error="таймаут")
        result, net = run("psf/requests", answers, environ)
        github_calls = 0
        for method, url, data, headers in net.calls:
            self.assertNotIn(TOKEN, url)
            self.assertNotIn(TOKEN, (data or b"").decode())
            if url.startswith("https://api.github.com/"):
                github_calls += 1
                self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
            else:
                self.assertNotIn("Authorization", headers, url)
                self.assertNotIn(TOKEN, json.dumps(headers), url)
        self.assertEqual(github_calls, 3)
        for out in (deep_search.facts_text(result), deep_search.facts_json(result)):
            self.assertNotIn(TOKEN, out)
            self.assertNotIn(TOKEN[4:], out)

    def test_no_token_to_other_hostings(self):
        api = "https://gitlab.com/api/v4/projects/a%2Fb"
        _, net = run("https://gitlab.com/a/b", {f"{api}?license=true": b"{}"},
                     {"GITHUB_TOKEN": TOKEN, "GH_TOKEN": TOKEN})
        for _, url, _, headers in net.calls:
            self.assertNotIn(TOKEN, json.dumps(headers), url)


class OutputTest(unittest.TestCase):
    def big_run(self) -> deep_search.FactsRun:
        rows = [deep_search.Fact("license", "x" * 150, f"https://example.org/{i}", "a.b")
                for i in range(40)]
        return deep_search.FactsRun("github.com/a/b", DAY, rows,
                                    [("Scorecard", "таймаут"), ("Repology", "HTTP 503")])

    def test_text_within_limit_with_tail_and_failed_line(self):
        text = deep_search.facts_text(self.big_run())
        self.assertLessEqual(len(text), deep_search.FACTS_MAX_CHARS)
        lines = text.splitlines()
        self.assertRegex(lines[-2], r"^… ещё \d+$")
        self.assertEqual(lines[-1], "не ответили: Scorecard (таймаут), Repology (HTTP 503)")

    def test_json_within_limit_same_fields(self):
        big = json.loads(deep_search.facts_json(self.big_run()))
        self.assertLessEqual(len(deep_search.facts_json(self.big_run())),
                             deep_search.FACTS_MAX_CHARS)
        self.assertEqual(big["omitted"] + len(big["facts"]), 40)
        self.assertEqual(big["failed"][0], {"source": "Scorecard", "error": "таймаут"})

        result, _ = run("psf/requests", github_answers())
        out = deep_search.facts_json(result)
        self.assertLessEqual(len(out), deep_search.FACTS_MAX_CHARS)
        obj = json.loads(out)
        self.assertEqual(obj["target"], "github.com/psf/requests")
        self.assertEqual(obj["date"], DAY)
        self.assertEqual(obj["columns"], ["field", "value", "source", "path"])
        self.assertNotIn("omitted", obj)
        self.assertEqual(obj["facts"], [[f.field, f.value, f.source, f.path]
                                        for f in result.facts])
        self.assertIn(["eol", None, eol("requests"), "HTTP 404"], obj["facts"])

    def test_full_github_run_fits_text(self):
        result, _ = run("psf/requests", github_answers())
        text = deep_search.facts_text(result)
        self.assertLessEqual(len(text), deep_search.FACTS_MAX_CHARS)
        self.assertEqual(len(text.splitlines()), 1 + len(result.facts))


if __name__ == "__main__":
    unittest.main()
