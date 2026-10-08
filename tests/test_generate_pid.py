"""Proposal generation checks, runnable with Python's standard unittest runner."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_pid import PID, SCHEMA, STATUS, build_proposal, write_proposal
from redirect_source import load_local


def plan():
    return json.loads((ROOT / "examples/odrl-action-plan.json").read_text())


def vocabulary():
    return Graph().parse(data='''
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
        PREFIX cs: <https://linked.data.gov.au/def/odrl-action>
        PREFIX local: <https://linked.data.gov.au/def/odrl-action/>
        cs: a skos:ConceptScheme; skos:hasTopConcept local:fulfil-commitments.
        local:fulfil-commitments a skos:Concept, odrl:Action; skos:inScheme cs:.
        local:cooperate a skos:Concept, odrl:Action; skos:inScheme cs:.
        odrl:transfer a skos:Concept, odrl:Action; skos:inScheme cs:.
    ''', format="turtle")


class GeneratorTests(unittest.TestCase):
    def test_dual_typed_members_and_external_namespace(self):
        proposal = build_proposal(vocabulary(), plan())
        self.assertEqual(len(proposal.concepts), 2)
        self.assertEqual(proposal.external_concepts, ("http://www.w3.org/ns/odrl/2/transfer",))
        record = URIRef(proposal.registration)
        self.assertEqual(proposal.graph.value(record, SCHEMA.status), STATUS.submitted)
        self.assertEqual(proposal.graph.value(record, SCHEMA.creator), URIRef("https://kurrawong.ai"))
        self.assertNotIn("http://www.w3.org/ns/odrl/2/transfer", proposal.rules)

    def test_wrong_scheme_and_unsupported_paths_are_rejected(self):
        changed = plan(); changed["scheme"] += "-other"; changed["namespace"] = changed["scheme"] + "/"
        with self.assertRaisesRegex(ValueError, "not a skos:ConceptScheme"):
            build_proposal(vocabulary(), changed)
        graph = vocabulary(); member = URIRef(plan()["namespace"] + "nested/concept")
        graph.add((member, RDF.type, SKOS.Concept)); graph.add((member, SKOS.inScheme, URIRef(plan()["scheme"])))
        with self.assertRaisesRegex(ValueError, "Unsupported local concept path"):
            build_proposal(graph, plan())

    def test_missing_membership_is_not_silently_dropped(self):
        graph = vocabulary(); graph.add((URIRef(plan()["namespace"] + "orphan"), RDF.type, SKOS.Concept))
        with self.assertRaisesRegex(ValueError, "missing membership"):
            build_proposal(graph, plan())

    def test_invalid_dates_and_templates_are_rejected(self):
        for template in ("https://example.org/no-placeholder", "https://{iri}.example.org/",
                         "https://example.org/?iri={iri}\nRewriteRule", "https://example.org/?iri={iri}#fragment"):
            changed = plan(); changed["html_destination"] = template
            with self.assertRaises(ValueError): build_proposal(vocabulary(), changed)
        changed = plan(); changed["date_modified"] = "2020-01-01"
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            build_proposal(vocabulary(), changed)

    def test_unknown_plan_fields_are_rejected(self):
        changed = plan(); changed["status"] = "stable"
        with self.assertRaisesRegex(ValueError, "unknown"):
            build_proposal(vocabulary(), changed)

    def test_outputs_are_repeatable_and_existing_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); source = folder / "vocab.ttl"; config = folder / "plan.json"
            vocabulary().serialize(destination=source, format="turtle"); config.write_text(json.dumps(plan()))
            paths = [folder / "first.ttl", folder / "second.ttl"]
            for path in paths:
                subprocess.run([sys.executable, str(ROOT / "scripts/generate_pid.py"),
                                "--vocabulary", str(source), "--plan", str(config), "--output", str(path)],
                               check=True, capture_output=True)
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
            self.assertEqual(paths[0].with_suffix(".preview.json").read_bytes(), paths[1].with_suffix(".preview.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "already exists"):
                write_proposal(build_proposal(vocabulary(), plan()), paths[0])

    def test_generated_record_works_with_existing_redirect_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proposal.ttl"
            proposal = build_proposal(vocabulary(), plan())
            write_proposal(proposal, output)
            direct = load_local(output)
            self.assertEqual(direct, load_local(Path(directory)))
            self.assertEqual(len(direct), 1)
            self.assertEqual(direct[0].rules, proposal.rules)
            self.assertEqual(len(direct[0].tests), len(proposal.tests))

    def test_worked_example_can_be_regenerated(self):
        proposal = build_proposal(Graph().parse(ROOT / "examples/input/odrl-action.ttl"), plan())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "odrl-action.ttl"
            write_proposal(proposal, output)
            self.assertEqual(output.read_bytes(), (ROOT / "examples/odrl-action.ttl").read_bytes())
            self.assertEqual(output.with_suffix(".preview.json").read_bytes(),
                             (ROOT / "examples/odrl-action.preview.json").read_bytes())


@unittest.skipUnless(sys.platform == "darwin" and Path("/usr/sbin/httpd").exists(), "native macOS Apache unavailable; use the repository Docker harness")
class ApacheTests(unittest.TestCase):
    expected_concepts = 8
    expected_tests = 22
    negative_paths = ("/def/odrl-action-extra", "/def/other/cooperate", "/def/odrl-action/nested/concept")

    def get_proposal(self):
        return build_proposal(Graph().parse(ROOT / "examples/input/odrl-action.ttl"), plan())

    def test_actual_redirect_headers_and_namespace_boundary(self):
        proposal = self.get_proposal()
        self.assertEqual(len(proposal.concepts), self.expected_concepts)
        self.assertEqual(len(proposal.tests), self.expected_tests)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            # Exercise RDF serialization/deserialization, not just the raw builder string.
            data = Graph().parse(data=proposal.graph.serialize(format="longturtle"), format="turtle")
            rules = str(data.value(URIRef(proposal.registration), PID.redirectRules))
            (folder / "rules.conf").write_text(rules)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
            config = folder / "httpd.conf"
            config.write_text(f'''ServerRoot "{folder}"
Listen 127.0.0.1:{port}
ServerName linked.data.gov.au
LoadModule mpm_prefork_module /usr/libexec/apache2/mod_mpm_prefork.so
LoadModule unixd_module /usr/libexec/apache2/mod_unixd.so
LoadModule authz_core_module /usr/libexec/apache2/mod_authz_core.so
LoadModule rewrite_module /usr/libexec/apache2/mod_rewrite.so
PidFile "{folder}/httpd.pid"
ErrorLog "{folder}/error.log"
DocumentRoot "{folder}"
RewriteEngine On
Include "{folder}/rules.conf"
''')
            process = subprocess.Popen(["/usr/sbin/httpd", "-X", "-f", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs): return None
            opener = urllib.request.build_opener(NoRedirect)
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.2): break
                    except OSError:
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail((folder / "error.log").read_text())
                        time.sleep(.05)
                for test in proposal.tests:
                    request = urllib.request.Request(test["source"].replace("https://linked.data.gov.au", f"http://127.0.0.1:{port}"),
                                                     headers={**test["headers"], "Host": "linked.data.gov.au"})
                    with self.subTest(test=test["name"]):
                        try: response = opener.open(request, timeout=3)
                        except urllib.error.HTTPError as exc: response = exc
                        self.assertEqual(response.code, 302)
                        self.assertEqual(response.headers.get("Location"), test["target"])
                        response.close()
                for path in self.negative_paths:
                    try: response = opener.open(f"http://127.0.0.1:{port}{path}", timeout=3)
                    except urllib.error.HTTPError as exc: response = exc
                    self.assertIsNone(response.headers.get("Location")); response.close()
            finally:
                process.terminate()
                try: process.wait(timeout=4)
                except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__ == "__main__":
    unittest.main()
