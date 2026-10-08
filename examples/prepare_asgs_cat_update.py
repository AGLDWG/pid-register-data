"""Reproduce the focused Meshblock categories update to the existing ASGS PID.

This worked example is deliberately separate from the new-registration builder.
Production destination availability must be checked before applying the output.
"""

import argparse
import ast
import json
from pathlib import Path
import sys

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS, XSD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_pid import PID, SCHEMA, _apache_destination, _concept_destination, _destination
from redirect_source import load_local

HERE = Path(__file__).resolve().parent
SCHEME = "https://linked.data.gov.au/def/asgs/cat"
RECORD = URIRef("https://linked.data.gov.au/pid/def/asgs")
HTML = "https://resources.bdr.gov.au/catalogues/vocabs:/collections/asgs:cat"
HTML_CONCEPT = HTML + "/items/cat:{slug}"
TURTLE = "https://bdr.azure-api.net/prez-v4/v1/object?iri={iri}&_mediatype=text%2Fturtle"


def build_update():
    original = HERE / "input/asgs-registration.ttl"
    graph = Graph().parse(original, format="turtle")
    vocabulary = Graph().parse(HERE / "input/mesh-block-categories.ttl", format="turtle")
    concepts = sorted(str(s) for s in vocabulary.subjects(SKOS.inScheme, URIRef(SCHEME)))
    if not concepts or any(not iri.startswith(SCHEME + "/") or
                           (URIRef(iri), RDF.type, SKOS.Concept) not in vocabulary
                           for iri in concepts):
        raise ValueError("Unexpected vocabulary membership")
    import re
    if any(not re.fullmatch(r"[A-Za-z0-9-]+", iri[len(SCHEME) + 1:]) for iri in concepts):
        raise ValueError("This example supports single-segment concept slugs only")
    condition = ("RewriteCond %{QUERY_STRING} (^|&)_mediatype=text(/|%2[Ff])turtle(&|$) [OR]\n"
                 "RewriteCond %{HTTP:Accept} text/turtle [NC]")
    scheme_turtle = _apache_destination(_destination(TURTLE, SCHEME))
    concept_turtle = _concept_destination(TURTLE, SCHEME + "/")
    added_rules = "\n".join([
        "# Meshblock categories: specific rules precede the existing ASGS rules.",
        f"RewriteRule ^/def/asgs/cat\\.ttl$ {scheme_turtle} [R=302,NE,L]",
        f"RewriteRule ^/def/asgs/cat/([A-Za-z0-9-]+)\\.ttl$ {concept_turtle} [R=302,NE,L]",
        condition,
        f"RewriteRule ^/def/asgs/cat/?$ {scheme_turtle} [R=302,NE,L]",
        condition,
        f"RewriteRule ^/def/asgs/cat/([A-Za-z0-9-]+)$ {concept_turtle} [R=302,NE,L]",
        f"RewriteRule ^/def/asgs/cat/?$ {HTML} [R=302,NE,L]",
        f"RewriteRule ^/def/asgs/cat/([A-Za-z0-9-]+)$ {HTML_CONCEPT.replace('{slug}', '$1')} [R=302,NE,L]",
    ])
    legacy_rules = str(graph.value(RECORD, PID.redirectRules))
    graph.set((RECORD, PID.redirectRules, Literal(added_rules + "\n" + legacy_rules,
                                               datatype=PID.apacheRedirectRules)))
    graph.set((RECORD, SCHEMA.dateModified, Literal("2026-10-08", datatype=XSD.date)))
    tests = []
    def add(name, source, target, headers=None):
        tests.append({"name": name, "source": source, "target": target, "headers": headers or {}})
    for iri in [SCHEME, *concepts]:
        slug = iri[len(SCHEME) + 1:] if iri != SCHEME else "scheme"
        html = HTML if iri == SCHEME else HTML_CONCEPT.replace("{slug}", slug)
        add(f"Meshblock {slug} — HTML", iri, html, {"Accept": "text/html"})
        add(f"Meshblock {slug} — Turtle", iri, _destination(TURTLE, iri), {"Accept": "text/turtle"})
        add(f"Meshblock {slug} — .ttl alias", iri + ".ttl", _destination(TURTLE, iri))
    for media, target in [("text/html", HTML), ("text/turtle", _destination(TURTLE, SCHEME))]:
        add(f"Meshblock scheme trailing slash — {media}", SCHEME + "/", target, {"Accept": media})
    for iri in [SCHEME, SCHEME + "/residential"]:
        for value in ["text/turtle", "text%2Fturtle"]:
            add(f"Meshblock {iri.rsplit('/', 1)[-1]} — parameter {value}",
                iri + "?_mediatype=" + value, _destination(TURTLE, iri), {"Accept": "text/html"})
        target = HTML if iri == SCHEME else HTML_CONCEPT.replace("{slug}", "residential")
        add(f"Meshblock {iri.rsplit('/', 1)[-1]} — default HTML", iri, target)
    for index, test in enumerate(tests):
        node = BNode(f"meshblockTest{index:03}")
        for predicate, value in [(RDF.type, PID.RedirectTest), (SCHEMA.name, Literal(test["name"])),
                                 (PID["from"], Literal(test["source"])), (PID.to, Literal(test["target"])),
                                 (PID.headers, Literal(", ".join(repr(k) + ": " + repr(v)
                                                                for k, v in test["headers"].items())))]:
            graph.add((node, predicate, value))
        graph.add((RECORD, PID.redirectTest, node))
    legacy_tests = [{"name": t.name, "source": t.source, "target": t.target,
                     "headers": ast.literal_eval("{" + t.headers + "}")}
                    for t in sorted(load_local(original)[0].tests, key=lambda t: t.name)]
    return graph, {"proposal_only": True, "production_verified": False,
                   "registration": str(RECORD), "scheme": SCHEME,
                   "local_concepts": concepts, "new_redirects": tests,
                   "preserved_redirects": legacy_tests,
                   "apply_to": "resources/pids/def/items/asgs.ttl",
                   "catalogue_membership_change": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    preview = args.output.with_suffix(".preview.json")
    if args.output.exists() or preview.exists():
        parser.error("Output already exists; choose a new output path")
    graph, summary = build_update()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("# Local update proposal only: production destinations are not yet verified.\n"
                           "# Existing stable status records the registration, not approval of this update.\n"
                           + graph.serialize(format="longturtle"))
    preview.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {args.output}: {len(summary['new_redirects'])} new tests, "
          f"{len(summary['preserved_redirects'])} preserved tests")


if __name__ == "__main__":
    main()
