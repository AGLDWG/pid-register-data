"""Regression checks for role types and the validation command's failure status."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from kurra.shacl import validate
from rdflib import URIRef
from rdflib.namespace import RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_orgs import validation_graph


class OrganisationValidationTests(unittest.TestCase):
    def test_register_passes_with_supporting_roles(self):
        graph = validation_graph(ROOT)
        role = URIRef("https://data.idnau.org/pid/vocab/aarr/partOf")
        self.assertIn((role, RDF.type, SKOS.Concept), graph)
        conforms, _, report, *_ = validate(graph, ROOT / "resources/validators/items/org.ttl")
        self.assertTrue(conforms, report)

    def test_missing_role_type_fails(self):
        graph = validation_graph(ROOT)
        graph.remove((URIRef("https://data.idnau.org/pid/vocab/aarr/partOf"), RDF.type, SKOS.Concept))
        conforms, *_ = validate(graph, ROOT / "resources/validators/items/org.ttl")
        self.assertFalse(conforms)

    def test_invalid_record_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("resources/orgs/items", "resources/persons/items", "resources/supporting-vocabs"):
                shutil.copytree(ROOT / path, root / path)
            (root / "resources/validators/items").mkdir(parents=True)
            shutil.copyfile(ROOT / "resources/validators/items/org.ttl", root / "resources/validators/items/org.ttl")
            (root / "resources/orgs/items/invalid.ttl").write_text(
                'PREFIX schema: <https://schema.org/>\n<https://example.org/org> a schema:Organization.\n')
            result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_orgs.py"), "--root", str(root)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Conforms: False", result.stdout)


if __name__ == "__main__":
    unittest.main()
