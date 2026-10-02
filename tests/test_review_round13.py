"""Author compatibility controls using generated identities and inert helpers."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    path = ROOT / "tools/make_fixtures.py"
    namespace = {"__name__": "smith13_fixtures", "__file__": str(path)}
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    return namespace["review13_publication_cases"]()


def publication_helpers(namespace):
    path = ROOT / "skills/skill-smith/scripts/fleet_check.py"
    tree = ast.parse(path.read_bytes(), str(path))
    names = {"publication_identity", "private_publication_proof"}
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(selected) != len(names):
        raise AssertionError("Publication helper definition set changed")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class PublicationCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures()

    def default_helpers(self, fetch=None):
        calls = []
        def identity(path):
            calls.append(("identity", path))
            return self.case["fetch"] if fetch is None else fetch
        def routes(path):
            calls.append(("routes", path))
            return self.case["selected"], self.case["routes"]
        return publication_helpers({"origin_slug": identity, "publication_routes": routes}), calls

    def test_default_single_argument_helpers_reach_visibility_decision(self):
        for visibility in self.case["visibility"]:
            with self.subTest(visibility=visibility):
                namespace, calls = self.default_helpers()
                identity = namespace["publication_identity"](self.case["repo_path"])
                self.assertEqual(identity, (self.case["fetch"], self.case["selected"], self.case["routes"]))
                self.assertEqual(calls, [("identity", self.case["repo_path"]),
                                         ("routes", self.case["repo_path"])])
                oracle = SimpleNamespace(visibility=lambda _: (visibility, self.case["how"]))
                if visibility == "PRIVATE":
                    self.assertIn("PRIVATE", namespace["private_publication_proof"](identity, oracle))
                else:
                    with self.assertRaisesRegex(ValueError, "PRIVATE"):
                        namespace["private_publication_proof"](identity, oracle)

    def test_explicit_timeouts_reach_both_helpers(self):
        for timeout in self.case["timeouts"]:
            with self.subTest(timeout=timeout):
                calls = []
                def identity(path, *, timeout):
                    calls.append(("identity", path, timeout))
                    return self.case["fetch"]
                def routes(path, *, timeout):
                    calls.append(("routes", path, timeout))
                    return self.case["selected"], self.case["routes"]
                namespace = publication_helpers({"origin_slug": identity, "publication_routes": routes})
                result = namespace["publication_identity"](self.case["repo_path"], timeout=timeout)
                self.assertEqual(result, (self.case["fetch"], self.case["selected"], self.case["routes"]))
                self.assertEqual(calls, [("identity", self.case["repo_path"], timeout),
                                         ("routes", self.case["repo_path"], timeout)])

    def test_missing_fetch_identity_never_queries_routes(self):
        for missing in self.case["missing_identities"]:
            with self.subTest(missing=missing):
                calls = []
                def identity(path):
                    calls.append("identity")
                    return missing
                def routes(path):
                    calls.append("routes")
                    raise AssertionError("Missing fetch identity must refuse before routes")
                namespace = publication_helpers({"origin_slug": identity, "publication_routes": routes})
                with self.assertRaisesRegex(ValueError, "PRIVATE"):
                    namespace["publication_identity"](self.case["repo_path"])
                self.assertEqual(calls, ["identity"])

    def test_helper_errors_propagate_without_compatibility_retry(self):
        for failing in ("identity", "routes"):
            with self.subTest(helper=failing):
                calls = []
                failure = ValueError(self.case["helper_failure"])
                def identity(path):
                    calls.append("identity")
                    if failing == "identity":
                        raise failure
                    return self.case["fetch"]
                def routes(path):
                    calls.append("routes")
                    raise failure
                namespace = publication_helpers({"origin_slug": identity, "publication_routes": routes})
                with self.assertRaises(ValueError) as raised:
                    namespace["publication_identity"](self.case["repo_path"])
                self.assertIs(raised.exception, failure)
                self.assertEqual(calls, ["identity"] if failing == "identity" else ["identity", "routes"])

    def test_private_proof_checks_all_fetch_and_push_destinations(self):
        namespace, _ = self.default_helpers()
        queries = []
        def visibility(target):
            queries.append(target)
            return "PRIVATE", self.case["how"]
        identity = self.case["fetch"], self.case["selected"], self.case["routes"]
        proof = namespace["private_publication_proof"](identity, SimpleNamespace(visibility=visibility))
        expected = {self.case["fetch"],
                    *(target for targets in self.case["routes"].values() for target in targets)}
        self.assertEqual(queries, sorted(expected))
        self.assertIn("PRIVATE fetch=" + self.case["fetch"], proof)
        self.assertIn("default=" + self.case["selected"], proof)
        for remote, targets in self.case["routes"].items():
            self.assertIn("push[%s]=%s" % (remote, ",".join(targets)), proof)

    def test_public_diagnosis_and_unknown_refusal_cover_every_destination(self):
        namespace, _ = self.default_helpers()
        identity = self.case["fetch"], self.case["selected"], self.case["routes"]
        targets = sorted({identity[0], *(target for values in identity[2].values() for target in values)})
        for target in targets:
            for denied in ("PUBLIC", "UNKNOWN"):
                with self.subTest(target=target, visibility=denied):
                    queries = []
                    def visibility(current):
                        queries.append(current)
                        return (denied if current == target else "PRIVATE"), self.case["how"]
                    with self.assertRaises(ValueError) as raised:
                        namespace["private_publication_proof"](identity, SimpleNamespace(visibility=visibility))
                    message = str(raised.exception)
                    self.assertIn("PRIVATE", message)
                    self.assertIn(denied, message)
                    self.assertIn(target, message)
                    self.assertIn(self.case["how"], message)
                    if denied == "PUBLIC":
                        self.assertIn("PUBLIC repo " + target, message)
                    self.assertIn(target, queries)
