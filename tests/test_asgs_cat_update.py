"""Check the proposed subtree update without changing the active ASGS record."""

from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from rdflib import Graph, URIRef
from rdflib.compare import isomorphic

import test_generate_pid as generator_tests
ROOT = generator_tests.ROOT
sys.path.insert(0, str(ROOT / "examples"))
from prepare_asgs_cat_update import build_update, RECORD, PID, SCHEMA


class UpdateTests(unittest.TestCase):
    def test_only_rules_tests_and_modified_date_change(self):
        graph, summary = build_update()
        original = Graph().parse(ROOT / "examples/input/asgs-registration.ttl")
        self.assertTrue(str(graph.value(RECORD, PID.redirectRules)).endswith(
            str(original.value(RECORD, PID.redirectRules))))
        for predicate in (PID.redirectRules, SCHEMA.dateModified):
            graph.remove((RECORD, predicate, None)); original.remove((RECORD, predicate, None))
        for node in list(graph.objects(RECORD, PID.redirectTest)):
            if node not in set(original.objects(RECORD, PID.redirectTest)):
                # Compare by source and name because parser blank-node IDs differ.
                name = graph.value(node, SCHEMA.name)
                if any(original.value(old, SCHEMA.name) == name
                       for old in original.objects(RECORD, PID.redirectTest)):
                    continue
                graph.remove((RECORD, PID.redirectTest, node)); graph.remove((node, None, None))
        self.assertTrue(isomorphic(graph, original))
        self.assertFalse(summary["production_verified"])

    def test_frozen_baseline_matches_active_record(self):
        self.assertEqual((ROOT / "examples/input/asgs-registration.ttl").read_bytes(),
                         (ROOT / "resources/pids/def/items/asgs.ttl").read_bytes())

    def test_reproducible_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("first", "second"):
                path = Path(directory) / (name + ".ttl")
                subprocess.run([sys.executable, str(ROOT / "examples/prepare_asgs_cat_update.py"),
                                "--output", str(path)], check=True, capture_output=True)
                self.assertEqual(path.read_bytes(), (ROOT / "examples/asgs-cat-update.ttl").read_bytes())
                self.assertEqual(path.with_suffix(".preview.json").read_bytes(),
                                 (ROOT / "examples/asgs-cat-update.preview.json").read_bytes())


def boundary_tests():
    return [{"name": "unchanged ASGS path " + suffix,
             "source": "https://linked.data.gov.au/def/asgs" + suffix,
             "headers": {"Accept": "text/html"},
             "target": "https://raw.githack.com/AGLDWG/asgs-ont/master/asgs-" + file + ".ttl"}
            for suffix, file in [("/code", "code"), ("/cat-extra", "cat"),
                                 ("/cat/nested/concept", "cat")]]


class AsgsApacheTests(generator_tests.ApacheTests):
    expected_concepts = 16
    expected_tests = 66
    negative_paths = ()  # Existing ASGS catch-all rules still handle other paths.

    def get_proposal(self):
        graph, summary = build_update()
        tests = summary["new_redirects"] + summary["preserved_redirects"]
        tests.extend(boundary_tests())
        return SimpleNamespace(graph=graph, registration=str(RECORD),
                               concepts=summary["local_concepts"], tests=tests)


class AsgsBaselineApacheTests(generator_tests.ApacheTests):
    expected_concepts = 0
    expected_tests = 3
    negative_paths = ()

    def get_proposal(self):
        return SimpleNamespace(graph=Graph().parse(ROOT / "examples/input/asgs-registration.ttl"),
                               registration=str(RECORD), concepts=(), tests=boundary_tests())


if __name__ == "__main__":
    unittest.main()
