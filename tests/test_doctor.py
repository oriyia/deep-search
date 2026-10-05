"""`doctor`: проба среды без настоящих сетевых запросов.

Через subprocess скрипт видит подменённый PATH и прокси на закрытом локальном порту: каждый
запрос к API уходит в этот «прокси» и сразу получает отказ, так что наружу не уходит ничего, а
проба проходит путь «нет сети» целиком. Разбор ответов API проверяется импортом с подменённой
функцией запроса.
"""

from __future__ import annotations

import json
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from support import ISSUE_RE, SCRIPT, deep_search, run_script

SECRET_PASSWORD = "proxy-pass-7f3a"
SECRET_KEYS = {"TAVILY_API_KEY": "tvly-secret-91c2", "GITHUB_TOKEN": "ghp_secret_04bd"}
ENV_KEYS = {"checked", "commands", "network", "api", "searxng", "proxy", "keys", "library",
            "warnings"}


def closed_port() -> int:
    """Порт 127.0.0.1, который никто не слушает: соединение с ним сразу отклоняется."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fake_bin(folder: Path, *names: str) -> Path:
    """Папка для PATH с пустыми исполняемыми файлами-заглушками."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = folder / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return folder


class DoctorScriptTest(unittest.TestCase):
    """Скрипт целиком: PATH из двух заглушек, сеть недоступна, секреты в окружении."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        dead = f"127.0.0.1:{closed_port()}"
        self.env = {
            "HOME": str(self.home),
            "PATH": str(fake_bin(base / "bin", "curl", "rg")),
            "HTTP_PROXY": f"http://user:{SECRET_PASSWORD}@{dead}",
            "HTTPS_PROXY": f"http://user:{SECRET_PASSWORD}@{dead}",
            "SEARXNG_URL": f"http://{dead}",
            **SECRET_KEYS,
        }

    def doctor(self, *args: str, **over: str) -> subprocess.CompletedProcess:
        env = {**self.env, **over}
        start = time.monotonic()
        res = subprocess.run([sys.executable, str(SCRIPT), "doctor", *args], env=env,
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        # Отказ закрытого порта мгновенный: долгая проба значит, что запрос ушёл не туда.
        self.assertLess(time.monotonic() - start, deep_search.DOCTOR_TIMEOUT * 2)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res

    def assert_no_secrets(self, out: str) -> None:
        for secret in (SECRET_PASSWORD, *SECRET_KEYS.values()):
            self.assertNotIn(secret, out)

    def issues(self, out: str) -> set[tuple[str, str]]:
        return {(m.group(1), m.group(2)) for m in ISSUE_RE.finditer(out)}

    def test_offline_text(self):
        out = self.doctor().stdout
        self.assertIn("нет сети", out)
        self.assertIn("команды: есть — curl, rg; нет — pandoc, pdftotext", out)
        found = self.issues(out)
        self.assertIn(("api", "doctor-network"), found)
        self.assertIn(("pandoc", "doctor-command"), found)
        self.assertIn(("pdftotext", "doctor-command"), found)
        self.assertNotIn(("curl", "doctor-command"), found)
        self.assertIn(("NO_PROXY", "doctor-proxy"), found)
        self.assertIn("SearXNG", out)
        self.assertIn("не отвечает", out)
        self.assertLessEqual(len(out.rstrip("\n")), deep_search.OUTPUT_MAX_CHARS)
        self.assert_no_secrets(out)

    def test_json_for_manifest(self):
        res = self.doctor("--json")
        self.assert_no_secrets(res.stdout)
        env = json.loads(res.stdout)
        self.assertEqual(set(env), ENV_KEYS)
        self.assertFalse(env["network"])
        self.assertEqual({k for k, _ in deep_search.DOCTOR_COMMANDS}, set(env["commands"]))
        self.assertTrue(env["commands"]["curl"])
        self.assertFalse(env["commands"]["pandoc"])
        self.assertEqual({k for k, *_ in deep_search.DOCTOR_APIS}, set(env["api"]))
        self.assertTrue(all(a["status"] is None and not a["ok"] for a in env["api"].values()))
        self.assertFalse(env["searxng"]["ok"])
        self.assertTrue(env["proxy"]["HTTPS_PROXY"])
        self.assertFalse(env["proxy"]["local_bypass"])
        # Ключи — только наличие: значения флагов булевы.
        self.assertEqual(set(env["keys"]), set(deep_search.KEY_VARS))
        self.assertTrue(all(isinstance(v, bool) for v in env["keys"].values()))
        self.assertTrue(env["keys"]["TAVILY_API_KEY"])
        self.assertFalse(env["keys"]["EXA_API_KEY"])
        self.assertEqual(env["library"], {"set": False, "store": False})
        self.assertTrue(any("doctor-network" in w for w in env["warnings"]))

    def test_no_proxy_with_local_hosts_has_no_trap(self):
        out = self.doctor(NO_PROXY="localhost,127.0.0.1").stdout
        self.assertNotIn("doctor-proxy", out)
        self.assertIn("localhost и 127.0.0.1 — в обход прокси", out)

    def test_library_store(self):
        store = self.home / "library"
        self.assertEqual(run_script("init", str(store), home=self.home).returncode, 0)
        env = json.loads(self.doctor("--json", DEEP_SEARCH_LIBRARY=str(store)).stdout)
        self.assertEqual(env["library"], {"set": True, "store": True})


class DoctorParseTest(unittest.TestCase):
    """Разбор ответов: функция запроса подменена, сети нет совсем."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(fake_bin(Path(tmp.name) / "bin", "curl", "pandoc", "pdftotext",
                                 "chromium-browser"))
        self.calls: list[tuple[str, bool]] = []

    def fetcher(self, answers: dict[str, deep_search.Probe]):
        def fetch(method, url, data, proxy, want_body):
            self.calls.append((url, proxy))
            for part, probe in answers.items():
                if part in url:
                    return probe
            return deep_search.Probe(200)
        return fetch

    def run_doctor(self, answers=None, **environ):
        environ = {"PATH": self.path, **environ}
        return deep_search.doctor(environ, self.fetcher(answers or {}), date(2026, 10, 5))

    def test_all_reachable(self):
        rate = json.dumps({"resources": {"core": {"limit": 60, "remaining": 57}}}).encode()
        env, issues, text = self.run_doctor({"api.github.com": deep_search.Probe(200, rate)})
        self.assertTrue(env["network"])
        self.assertEqual(issues, [])
        self.assertEqual(env["api"]["github"]["remaining"], 57)
        self.assertIn("GitHub 200, осталось 57 из 60 в час", text)
        self.assertTrue(env["commands"]["chromium"])
        self.assertEqual(env["checked"], "2026-10-05")
        # Локальный SearXNG — мимо прокси, API — как настроено окружением.
        by_url = dict(self.calls)
        self.assertTrue(all(proxy for url, proxy in by_url.items() if "search?q=" not in url))
        self.assertFalse(next(p for u, p in by_url.items() if "search?q=" in u))
        self.assertEqual(len(self.calls), len(deep_search.DOCTOR_APIS) + 1)

    def test_github_rate_low(self):
        rate = json.dumps({"resources": {"core": {"limit": 60, "remaining": 3}}}).encode()
        _, issues, _ = self.run_doctor({"api.github.com": deep_search.Probe(200, rate)})
        self.assertEqual([(i.path, i.rule) for i in issues], [("GitHub", "doctor-api")])
        self.assertIn("GITHUB_TOKEN", issues[0].detail)

    def test_one_api_down(self):
        env, issues, text = self.run_doctor(
            {"web.archive.org": deep_search.Probe(error="таймаут")})
        self.assertTrue(env["network"])
        self.assertEqual([(i.path, i.rule) for i in issues], [("Wayback", "doctor-api")])
        self.assertIn("Wayback — таймаут", text)

    def test_http_error_is_reachable(self):
        env, issues, _ = self.run_doctor({"api.osv.dev": deep_search.Probe(503)})
        self.assertEqual(env["api"]["osv"], {"ok": False, "status": 503})
        self.assertEqual(issues, [])

    def test_offline(self):
        down = deep_search.Probe(error="нет соединения")
        env, issues, text = self.run_doctor({"https://": down})
        self.assertFalse(env["network"])
        self.assertEqual([i.rule for i in issues], ["doctor-network"])
        self.assertIn("нет сети", text)

    def test_searxng_without_json(self):
        env, _, text = self.run_doctor({"search?q=": deep_search.Probe(403)},
                                       SEARXNG_URL="http://user:pw@searx.local:8888/")
        self.assertEqual(env["searxng"], {"ok": True, "status": 403, "json": False})
        self.assertIn("SearXNG (http://searx.local:8888): отвечает 403", text)
        self.assertNotIn("pw", text)

    def test_proxy_lowercase_and_wildcard(self):
        env, issues, _ = self.run_doctor(https_proxy="http://127.0.0.1:1", no_proxy="*")
        self.assertTrue(env["proxy"]["HTTPS_PROXY"])
        self.assertTrue(env["proxy"]["local_bypass"])
        self.assertEqual(issues, [])

    def test_secrets_never_in_output(self):
        secrets = {name: f"value-of-{name.lower()}" for name in deep_search.KEY_VARS}
        env, issues, text = self.run_doctor(**secrets,
                                            HTTPS_PROXY="http://u:hidden-pass@proxy.example:3128")
        dumped = json.dumps(env, ensure_ascii=False) + text
        for value in [*secrets.values(), "hidden-pass", "proxy.example"]:
            self.assertNotIn(value, dumped)
        self.assertTrue(all(env["keys"].values()))


if __name__ == "__main__":
    unittest.main()
