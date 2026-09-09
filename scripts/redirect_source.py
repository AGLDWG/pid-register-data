"""Load PID redirect rules and tests from local RDF or a SPARQL endpoint."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Namespace
from rdflib.namespace import RDF

PID = Namespace("https://linked.data.gov.au/def/pid/")
SCHEMA = Namespace("https://schema.org/")


@dataclass(frozen=True)
class RedirectTest:
    pid: str
    name: str
    source: str
    target: str
    headers: str


@dataclass(frozen=True)
class Redirect:
    pid: str
    rules: str
    sponsor: str
    tests: tuple[RedirectTest, ...]


QUERY = """
PREFIX pid: <https://linked.data.gov.au/def/pid/>
PREFIX schema: <https://schema.org/>
SELECT ?pid ?rules ?sponsor ?test ?name ?from ?to ?headers WHERE {
  ?subject a pid:Pid ;
      schema:url ?pid ;
      schema:sponsor ?sponsor ;
      pid:redirectRules ?rules .
  FILTER(datatype(?rules) = pid:apacheRedirectRules)
  OPTIONAL {
    ?subject pid:redirectTest ?test .
    ?test a pid:RedirectTest ;
        schema:name ?name ;
        pid:from ?from ;
        pid:to ?to ;
        pid:headers ?headers .
  }
}
ORDER BY ?pid ?name
""".strip()


def _redirects_from_graph(graph: Graph) -> list[Redirect]:
    redirects = []
    for subject in graph.subjects(RDF.type, PID.Pid):
        urls = list(graph.objects(subject, SCHEMA.url))
        rules = [value for value in graph.objects(subject, PID.redirectRules) if value.datatype == PID.apacheRedirectRules]
        sponsors = list(graph.objects(subject, SCHEMA.sponsor))
        if not (urls and rules and sponsors):
            continue
        tests = []
        for node in graph.objects(subject, PID.redirectTest):
            names = list(graph.objects(node, SCHEMA.name))
            sources = list(graph.objects(node, PID["from"]))
            targets = list(graph.objects(node, PID.to))
            headers = list(graph.objects(node, PID.headers))
            if names and sources and targets and headers:
                tests.append(RedirectTest(str(urls[0]), str(names[0]), str(sources[0]), str(targets[0]), str(headers[0])))
        redirects.append(Redirect(str(urls[0]), str(rules[0]), str(sponsors[0]), tuple(tests)))
    return sorted(redirects, key=lambda item: item.pid)


def load_local(folder: Path) -> list[Redirect]:
    graph = Graph()
    for path in sorted(folder.rglob("*.ttl")):
        graph.parse(path, format="turtle")
    return _redirects_from_graph(graph)


def _binding_value(binding: dict, name: str) -> str | None:
    value = binding.get(name)
    return value.get("value") if value else None


def load_sparql(endpoint: str, username: str | None, password: str | None) -> list[Redirect]:
    command = ["kurra", "sparql", endpoint, QUERY, "--response-format", "json"]
    if username:
        command.extend(["--username", username])
    if password:
        command.extend(["--password", password])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    grouped: dict[str, dict] = {}
    for row in payload["results"]["bindings"]:
        pid = _binding_value(row, "pid")
        if pid is None:
            continue
        record = grouped.setdefault(pid, {"rules": _binding_value(row, "rules"), "sponsor": _binding_value(row, "sponsor"), "tests": []})
        name = _binding_value(row, "name")
        if name is not None:
            record["tests"].append(RedirectTest(pid, name, _binding_value(row, "from") or "", _binding_value(row, "to") or "", _binding_value(row, "headers") or "{}"))
    return [Redirect(pid, data["rules"], data["sponsor"], tuple(data["tests"])) for pid, data in sorted(grouped.items())]


def load_redirects(source_type: str, source: str, username: str | None = None, password: str | None = None) -> list[Redirect]:
    if source_type == "local":
        return load_local(Path(source))
    if source_type == "sparql":
        return load_sparql(source, username, password)
    raise ValueError("source type must be 'local' or 'sparql'")


def sponsor_slug(iri: str) -> str:
    return iri.rstrip("/").rsplit("/", 1)[-1]
