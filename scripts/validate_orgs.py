"""Validate register organisations with local agent records and role vocabulary types."""

import argparse
from pathlib import Path

from kurra.shacl import validate
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]


def validation_graph(root: Path) -> Graph:
    graph = Graph()
    for kind in ("orgs", "persons"):
        paths = sorted((root / "resources" / kind / "items").glob("*.ttl"))
        if not paths:
            raise ValueError(f"No {kind} records found")
        for path in paths:
            graph.parse(path, format="turtle")
    vocabularies = sorted((root / "resources/supporting-vocabs").glob("*.ttl"))
    if not vocabularies:
        raise ValueError("No supporting vocabularies found")
    for path in vocabularies:
        vocabulary = Graph().parse(path, format="turtle")
        concepts = set(vocabulary.subjects(RDF.type, SKOS.Concept))
        if not concepts or any(not isinstance(concept, URIRef) for concept in concepts):
            raise ValueError(f"Expected named SKOS concepts in {path}")
        # Import the class assertions required by role validation. Publisher
        # descriptions in external vocabularies must not alter register agents.
        for concept in concepts:
            graph.add((concept, RDF.type, SKOS.Concept))
    return graph


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Register repository root")
    args = parser.parse_args(argv)
    graph = validation_graph(args.root)
    conforms, _, report, *_ = validate(graph, args.root / "resources/validators/items/org.ttl")
    print(report)
    return 0 if conforms else 1


if __name__ == "__main__":
    raise SystemExit(main())
