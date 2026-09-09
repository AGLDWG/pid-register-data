"""Pytest suite that exercises RDF-defined redirects in a minimal Apache container."""

from __future__ import annotations

import ast
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from rdflib import Graph
from rdflib.namespace import RDF

from redirect_source import PID, SCHEMA, RedirectTest, load_redirects

ROOT = Path(__file__).parent.parent
CONTAINER = "pid-register-redirect-tests"
PORT = int(os.getenv("PID_TEST_PORT", "8080"))


def _source_args() -> tuple[str, str, str | None, str | None]:
    return (
        os.getenv("SOURCE_TYPE", "local"),
        os.getenv("SOURCE", "resources/pids"),
        os.getenv("SPARQL_USERNAME"),
        os.getenv("SPARQL_PASSWORD"),
    )


def _resolve_pid(value: str) -> str:
    if value.startswith("https://linked.data.gov.au/pid/"):
        return value.replace("https://linked.data.gov.au/pid/", "https://linked.data.gov.au/", 1)
    if value.startswith(("https://", "http://")):
        return value

    supplied = Path(value)
    candidates = (supplied, ROOT / supplied, ROOT / "resources" / supplied)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise pytest.UsageError(f"PID file does not exist: {value}")
    graph = Graph().parse(path, format="turtle")
    subjects = set(graph.subjects(RDF.type, PID.Pid)) | set(graph.subjects(RDF.type, PID.PID))
    urls = [str(url) for subject in subjects for url in graph.objects(subject, SCHEMA.url)]
    if len(urls) != 1:
        raise pytest.UsageError(f"Expected exactly one PID with schema:url in {path}; found {len(urls)}")
    return urls[0]


def pytest_generate_tests(metafunc):
    if "redirect_test" not in metafunc.fixturenames:
        return
    tests = [test for redirect in load_redirects(*_source_args()) for test in redirect.tests]
    requested = metafunc.config.getoption("--pid")
    if requested:
        pid = _resolve_pid(requested)
        tests = [test for test in tests if test.pid == pid]
        if not tests:
            raise pytest.UsageError(f"No redirect tests found for PID {pid}")
    metafunc.parametrize("redirect_test", tests, ids=[f"{test.pid} — {test.name}" for test in tests])


@pytest.fixture(scope="session", autouse=True)
def apache_server():
    conf = (ROOT / "tests/conf").resolve()
    if not list(conf.glob("*.conf")):
        pytest.fail("tests/conf contains no generated redirect configurations; run task build-redirects")
    subprocess.run(["docker", "rm", "-f", CONTAINER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    command = [
        "docker", "run", "--rm", "--detach", "--name", CONTAINER,
        "--publish", f"{PORT}:80",
        "--volume", f"{conf}:/usr/local/apache2/conf/pid-conf:ro",
        "httpd:2.4-alpine", "httpd-foreground",
        "-c", "LoadModule rewrite_module modules/mod_rewrite.so",
        "-c", "RewriteEngine On",
        "-c", "IncludeOptional /usr/local/apache2/conf/pid-conf/*.conf",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{PORT}/", timeout=0.5)
            break
        except httpx.TransportError:
            time.sleep(0.2)
    else:
        pytest.fail("Apache test container did not become ready")
    yield
    subprocess.run(["docker", "rm", "-f", CONTAINER], check=False, stdout=subprocess.DEVNULL)


def test_redirect(redirect_test: RedirectTest):
    source = urlsplit(redirect_test.source)
    local_url = f"http://127.0.0.1:{PORT}{source.path}"
    if source.query:
        local_url += f"?{source.query}"
    header_fields = redirect_test.headers.strip()
    headers = ast.literal_eval("{" + header_fields + "}") if header_fields else {}
    headers["Host"] = source.netloc
    response = httpx.get(local_url, headers=headers, follow_redirects=False)
    actual = response.headers.get("location")
    assert response.is_redirect, f"{redirect_test.source} returned HTTP {response.status_code}, not a redirect"
    assert actual == redirect_test.target, f"{redirect_test.source} redirected to {actual!r}; expected {redirect_test.target!r}"
