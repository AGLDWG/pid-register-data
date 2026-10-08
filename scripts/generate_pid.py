"""Generate a local PID proposal from SKOS Turtle and an explicit JSON plan.

This first version supports one scheme, slash IRIs with single-segment local
concept names, and HTML/Turtle destinations. It never publishes or approves.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SKOS, XSD

PID = Namespace("https://linked.data.gov.au/def/pid/")
SCHEMA = Namespace("https://schema.org/")
LIFECYCLE = Namespace("https://linked.data.gov.au/def/lifecycle/")
TIME = Namespace("http://www.w3.org/2006/time#")
STATUS = Namespace("https://linked.data.gov.au/def/reg-statuses/")
REQUIRED = {
    "scheme", "namespace", "name", "description", "creator", "sponsor",
    "date_created", "date_modified", "html_destination", "turtle_destination",
}


@dataclass(frozen=True)
class Proposal:
    graph: Graph
    scheme: str
    registration: str
    concepts: tuple[str, ...]
    external_concepts: tuple[str, ...]
    rules: str
    tests: tuple[dict, ...]


def _https_iri(value: str, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or any(c.isspace() for c in value):
        raise ValueError(f"{field} must be an absolute HTTPS IRI")


def _destination(template: str, iri: str) -> str:
    if template.count("{iri}") != 1 or re.search(r"[{}]", template.replace("{iri}", "")):
        raise ValueError("Each destination must contain exactly one {iri} placeholder")
    value = template.replace("{iri}", quote(iri, safe=""))
    _https_iri(value, "destination")
    parsed = urlsplit(value)
    if parsed.fragment or parsed.username or parsed.password or any(c in value for c in '\\"<>$'):
        raise ValueError("Destinations cannot contain fragments, credentials, quotes, backslashes or dollar signs")
    # Keep the host fixed: the placeholder belongs inside a query value.
    if "{iri}" not in urlsplit(template).query:
        raise ValueError("The {iri} placeholder must be in the destination query string")
    return value


def _apache_destination(value: str) -> str:
    # mod_rewrite interprets %N as condition backreferences, even with NE.
    return value.replace("%", r"\%")


def _concept_destination(template: str, namespace: str) -> str:
    # Validate the template as an ordinary destination, then put the captured
    # slug inside the encoded IRI rather than after the other query parameters.
    _destination(template, namespace)
    encoded_namespace = _apache_destination(quote(namespace, safe=""))
    before, after = template.split("{iri}")
    return _apache_destination(before) + encoded_namespace + "$1" + _apache_destination(after)


def build_proposal(vocabulary: Graph, plan: dict) -> Proposal:
    if not isinstance(plan, dict):
        raise ValueError("The plan must be a JSON object")
    missing = REQUIRED - plan.keys()
    unknown = plan.keys() - REQUIRED
    if missing or unknown:
        raise ValueError(f"Invalid plan fields; missing={sorted(missing)}, unknown={sorted(unknown)}")
    if not all(isinstance(value, str) and value for value in plan.values()):
        raise ValueError("All plan values must be non-empty strings")
    for field in ("scheme", "namespace", "creator", "sponsor"):
        _https_iri(plan[field], field)
    scheme = plan["scheme"]
    if not re.fullmatch(r"https://linked\.data\.gov\.au/def/[A-Za-z0-9-]+", scheme):
        raise ValueError("This version supports scheme IRIs at https://linked.data.gov.au/def/<slug>")
    namespace = plan["namespace"]
    if namespace != scheme + "/":
        raise ValueError("This version requires namespace = scheme + '/' (no hash or nested namespaces)")
    created, modified = date.fromisoformat(plan["date_created"]), date.fromisoformat(plan["date_modified"])
    if modified < created:
        raise ValueError("date_modified cannot precede date_created")
    subject = URIRef(scheme)
    if (subject, RDF.type, SKOS.ConceptScheme) not in vocabulary:
        raise ValueError("The requested scheme is not a skos:ConceptScheme in the vocabulary")
    members = set(vocabulary.subjects(SKOS.inScheme, subject))
    members.update(vocabulary.objects(subject, SKOS.hasTopConcept))
    members.update(vocabulary.subjects(SKOS.topConceptOf, subject))
    concepts, external = [], []
    for member in sorted(members, key=str):
        if not isinstance(member, URIRef) or (member, RDF.type, SKOS.Concept) not in vocabulary:
            raise ValueError(f"Scheme member must be an IRI explicitly typed skos:Concept: {member}")
        iri = str(member)
        if not iri.startswith(namespace):
            external.append(iri)
            continue
        if not re.fullmatch(r"[A-Za-z0-9-]+", iri[len(namespace):]):
            raise ValueError(f"Unsupported local concept path: {iri}")
        concepts.append(iri)
    if not concepts:
        raise ValueError("No locally defined concepts found in the requested namespace")
    # Prevent silently dropping locally named concepts that lack membership.
    for member in vocabulary.subjects(RDF.type, SKOS.Concept):
        if str(member).startswith(namespace) and member not in members:
            raise ValueError(f"Local concept is missing membership in the scheme: {member}")

    html = plan["html_destination"]
    turtle = plan["turtle_destination"]
    scheme_path = urlsplit(scheme).path  # The restricted scheme syntax has no regex metacharacters.
    condition = (
        "RewriteCond %{QUERY_STRING} (^|&)_mediatype=text(/|%2[Ff])turtle(&|$) [OR]\n"
        "RewriteCond %{HTTP:Accept} text/turtle [NC]"
    )
    # Only safe single-segment concept names are accepted; $1 is their suffix.
    rules = "\n".join([
        condition,
        f"RewriteRule ^{scheme_path}/?$ {_apache_destination(_destination(turtle, scheme))} [R=302,NE,L]",
        condition,
        f"RewriteRule ^{scheme_path}/([A-Za-z0-9-]+)$ {_concept_destination(turtle, namespace)} [R=302,NE,L]",
        f"RewriteRule ^{scheme_path}/?$ {_apache_destination(_destination(html, scheme))} [R=302,NE,L]",
        f"RewriteRule ^{scheme_path}/([A-Za-z0-9-]+)$ {_concept_destination(html, namespace)} [R=302,NE,L]",
    ])

    tests = []
    for iri in (scheme, *concepts):
        label = iri[len(namespace):] if iri != scheme else "scheme"
        for media, template in (("text/html", html), ("text/turtle", turtle)):
            tests.append({"name": f"{label} — {'HTML' if media == 'text/html' else 'Turtle'}",
                          "source": iri, "headers": {"Accept": media}, "target": _destination(template, iri)})
    for media, template in (("text/html", html), ("text/turtle", turtle)):
        tests.append({"name": f"scheme trailing slash — {media}", "source": namespace,
                      "headers": {"Accept": media}, "target": _destination(template, scheme)})
    for iri in (scheme, concepts[0]):
        tests.append({"name": f"{iri.rsplit('/', 1)[-1]} — explicit Turtle parameter",
                      "source": iri + "?_mediatype=text/turtle", "headers": {"Accept": "text/html"},
                      "target": _destination(turtle, iri)})

    graph = Graph()
    for prefix, ns in (("pid", PID), ("schema", SCHEMA), ("lifecycle", LIFECYCLE),
                       ("time", TIME), ("status", STATUS), ("xsd", XSD)):
        graph.bind(prefix, ns)
    registration = scheme.replace("https://linked.data.gov.au/def/", "https://linked.data.gov.au/pid/def/", 1)
    record = URIRef(registration)
    for predicate, value in (
        (RDF.type, PID.Pid), (SCHEMA.name, Literal(plan["name"], lang="en")),
        (SCHEMA.description, Literal(plan["description"], lang="en")),
        (SCHEMA.creator, URIRef(plan["creator"])), (SCHEMA.sponsor, URIRef(plan["sponsor"])),
        (SCHEMA.dateCreated, Literal(created.isoformat(), datatype=XSD.date)),
        (SCHEMA.dateModified, Literal(modified.isoformat(), datatype=XSD.date)),
        (SCHEMA.status, STATUS.submitted), (SCHEMA.url, Literal(scheme, datatype=PID.agldwgPid)),
        (PID.redirectRules, Literal(rules, datatype=PID.apacheRedirectRules)),
    ):
        graph.add((record, predicate, value))
    stage, interval, beginning = BNode("stage"), BNode("interval"), BNode("beginning")
    for triple in ((record, LIFECYCLE.hasLifecycleStage, stage),
                   (stage, RDF.type, LIFECYCLE.LifecycleStage), (stage, SCHEMA.additionalType, STATUS.submitted),
                   (stage, TIME.hasTime, interval), (interval, TIME.hasBeginning, beginning),
                   (beginning, TIME.inXSDDate, Literal(created.isoformat(), datatype=XSD.date))):
        graph.add(triple)
    for index, test in enumerate(tests):
        node = BNode(f"test{index:03}")
        headers = ", ".join(repr(k) + ": " + repr(v) for k, v in test["headers"].items())
        for triple in ((record, PID.redirectTest, node), (node, RDF.type, PID.RedirectTest),
                       (node, SCHEMA.name, Literal(test["name"])), (node, PID["from"], Literal(test["source"])),
                       (node, PID.headers, Literal(headers)), (node, PID.to, Literal(test["target"]))):
            graph.add(triple)
    return Proposal(graph, scheme, registration, tuple(concepts), tuple(external), rules, tuple(tests))


def write_proposal(proposal: Proposal, output: Path) -> None:
    preview = output.with_suffix(".preview.json")
    if output.exists() or preview.exists():
        raise ValueError("Output already exists; choose a new path or remove the old generated files explicitly")
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {"proposal_only": True, "scheme": proposal.scheme, "registration": proposal.registration,
               "local_concepts": proposal.concepts, "external_concepts_not_registered": proposal.external_concepts,
               "catalogue_membership_to_add_after_review": {
                   "catalogue": "https://linked.data.gov.au/reg/pids/defs",
                   "predicate": str(SCHEMA.hasPart), "registration": proposal.registration},
               "redirects": proposal.tests}
    header = "# Generated local proposal: not approved, submitted to maintainers, or deployed.\n"
    header += "# Apache destination percent signs are escaped; Turtle escapes those backslashes again.\n"
    output.write_text(header + proposal.graph.serialize(format="longturtle"))
    preview.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vocabulary", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        proposal = build_proposal(Graph().parse(args.vocabulary, format="turtle"), json.loads(args.plan.read_text()))
        write_proposal(proposal, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Generated {args.output}: scheme + {len(proposal.concepts)} local concepts, {len(proposal.tests)} redirect tests")
    print(f"Excluded {len(proposal.external_concepts)} external concepts; inspect {args.output.with_suffix('.preview.json')}")


if __name__ == "__main__":
    main()
