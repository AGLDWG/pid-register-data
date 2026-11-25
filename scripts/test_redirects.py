"""Pytest suite that exercises RDF-defined redirects in a minimal Apache container."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from rdflib import Graph, Literal
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
        return value.replace(
            "https://linked.data.gov.au/pid/", "https://linked.data.gov.au/", 1
        )
    if value.startswith(("https://", "http://")):
        return value

    supplied = Path(value)
    candidates = (supplied, ROOT / supplied, ROOT / "resources" / supplied)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise pytest.UsageError(f"PID file does not exist: {value}")
    graph = Graph().parse(path, format="turtle")
    subjects = set(graph.subjects(RDF.type, PID.Pid)) | set(
        graph.subjects(RDF.type, PID.PID)
    )
    urls = [
        str(url) for subject in subjects for url in graph.objects(subject, SCHEMA.url)
    ]
    if len(urls) != 1:
        raise pytest.UsageError(
            f"Expected exactly one PID with schema:url in {path}; found {len(urls)}"
        )
    return urls[0]


def pytest_generate_tests(metafunc):
    if "redirect_test" not in metafunc.fixturenames:
        return
    _require_docker(check_daemon=not metafunc.config.option.collectonly)
    tests = [
        test for redirect in load_redirects(*_source_args()) for test in redirect.tests
    ]
    requested = metafunc.config.getoption("--pid")
    if requested:
        pid = _resolve_pid(requested)
        tests = [test for test in tests if test.pid == pid]
        if not tests:
            raise pytest.UsageError(_missing_tests_reason(pid))
    if not tests:
        source_type, source, _, _ = _source_args()
        raise pytest.UsageError(
            f"Cannot run redirect tests: no runnable pid:redirectTest blocks found in {source_type} source {source!r}. "
            "Registrations need schema:url, schema:sponsor and pid:redirectRules typed as pid:apacheRedirectRules; "
            "each test needs schema:name, pid:from, pid:to and pid:headers (which may be empty)."
        )
    metafunc.parametrize(
        "redirect_test", tests, ids=[f"{test.pid} — {test.name}" for test in tests]
    )


def _missing_tests_reason(pid: str) -> str:
    source_type, source, _, _ = _source_args()
    prefix = f"Cannot run redirect tests for {pid}: "
    if source_type != "local":
        return (
            prefix
            + "the SPARQL source returned no complete test cases; check registration metadata and pid:redirectTest blocks."
        )
    graph = Graph()
    paths = sorted(Path(source).rglob("*.ttl"))
    if not paths:
        return prefix + f"local source {source!r} contains no Turtle files."
    for path in paths:
        graph.parse(path, format="turtle")
    subjects = list(graph.subjects(SCHEMA.url, Literal(pid, datatype=PID.agldwgPid)))
    if not subjects:
        subjects = [
            subject
            for subject, url in graph.subject_objects(SCHEMA.url)
            if str(url) == pid
        ]
    if not subjects:
        return prefix + f"no registration with schema:url {pid!r} exists in {source!r}."
    reasons = []
    for subject in subjects:
        if (subject, RDF.type, PID.Pid) not in graph:
            reasons.append("registration is not typed pid:Pid")
        if not list(graph.objects(subject, SCHEMA.sponsor)):
            reasons.append("registration is missing schema:sponsor")
        if not any(
            getattr(rule, "datatype", None) == PID.apacheRedirectRules
            for rule in graph.objects(subject, PID.redirectRules)
        ):
            reasons.append(
                "registration has no pid:redirectRules typed as pid:apacheRedirectRules"
            )
        nodes = list(graph.objects(subject, PID.redirectTest))
        if not nodes:
            reasons.append(
                "registration has no pid:redirectTest blocks; add expected request URLs, headers and destinations"
            )
        for index, node in enumerate(nodes, 1):
            missing = [
                name
                for predicate, name in [
                    (SCHEMA.name, "schema:name"),
                    (PID["from"], "pid:from"),
                    (PID.to, "pid:to"),
                    (PID.headers, "pid:headers"),
                ]
                if not list(graph.objects(node, predicate))
            ]
            if missing:
                reasons.append(f"test block {index} is missing {', '.join(missing)}")
    return prefix + "; ".join(dict.fromkeys(reasons)) + "."


@pytest.fixture(scope="session", autouse=True)
def apache_server():
    conf = (ROOT / os.getenv("PID_TEST_CONF", "conf")).resolve()
    if not list(conf.glob("*.conf")):
        pytest.fail(
            f"Cannot run redirect tests: {conf} contains no generated .conf files. Run task build-redirects, or set PID_TEST_CONF to the builder's output directory.",
            pytrace=False,
        )
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--detach",
        "--name",
        CONTAINER,
        "--publish",
        f"{PORT}:80",
        "--volume",
        f"{conf}:/usr/local/apache2/conf/pid-conf:ro",
        "httpd:2.4-alpine",
        "httpd-foreground",
        "-c",
        "LoadModule rewrite_module modules/mod_rewrite.so",
        "-c",
        "RewriteEngine On",
        "-c",
        "IncludeOptional /usr/local/apache2/conf/pid-conf/*.conf",
    ]
    started = subprocess.run(command, check=False, capture_output=True, text=True)
    if started.returncode:
        pytest.fail(
            f"Cannot start the Apache test container (port {PORT}).\n{started.stderr.strip()}",
            pytrace=False,
        )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{PORT}/", timeout=0.5)
            break
        except httpx.TransportError:
            time.sleep(0.2)
    else:
        logs = subprocess.run(
            ["docker", "logs", CONTAINER], check=False, capture_output=True, text=True
        )
        subprocess.run(
            ["docker", "rm", "-f", CONTAINER], check=False, capture_output=True
        )
        pytest.fail(
            f"Apache did not become ready on port {PORT} within 20 seconds. Check the generated configuration.\n{logs.stdout}\n{logs.stderr}",
            pytrace=False,
        )
    yield
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER], check=False, stdout=subprocess.DEVNULL
    )


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
    assert response.is_redirect, (
        f"{redirect_test.source} returned HTTP {response.status_code}, not a redirect"
    )
    assert actual == redirect_test.target, (
        f"{redirect_test.source} redirected to {actual!r}; expected {redirect_test.target!r}"
    )


def _require_docker(*, check_daemon: bool = True) -> None:
    if shutil.which("docker") is None:
        pytest.exit(
            "Cannot run redirect tests: Docker is not installed or is not on PATH. "
            "Install Docker and start it before running this script.",
            returncode=4,
        )
    if not check_daemon:
        return
    try:
        ready = subprocess.run(
            ["docker", "info"], check=False, capture_output=True, text=True, timeout=20
        )
    except subprocess.TimeoutExpired:
        pytest.exit(
            "Cannot run redirect tests: Docker did not respond within 20 seconds. Start or restart Docker and retry.",
            returncode=4,
        )
    if ready.returncode:
        pytest.exit(
            f"Cannot run redirect tests: Docker is unavailable. Start Docker and retry.\n{ready.stderr.strip()}",
            returncode=4,
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), *sys.argv[1:]]))
