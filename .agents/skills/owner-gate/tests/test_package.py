"""Manual-only static checks of this skill package; NOT a project audit."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OwnerGatePackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    def test_skill_metadata_and_manual_gate(self):
        self.assertTrue(self.skill.startswith("---\nname: owner-gate\n"))
        for marker in ("Manual activation", "DORMANT", "explicit user approval", "separate explicit"):
            self.assertIn(marker.lower(), self.skill.lower())

    def test_canonical_axes_and_status(self):
        matrix = (ROOT / "references/adversarial-matrix.md").read_text(encoding="utf-8")
        for axis in (
            "CROSS_BOUNDARY_SYMMETRY", "PUBLIC_API_MISUSE", "SKIPPED_VERIFIER_PATH",
            "HOSTILE_VALID_INPUTS", "MUTATION_TOCTOU_CONCURRENCY", "RESOURCE_SAFETY",
            "DETERMINISM_RUNTIME_REPLAY", "SCHEMA_DOCS_CODE_PARITY",
            "EVOLUTION_BREAKING_CHANGE", "MOST_LIKELY_INTEGRATOR_MISUSE"
        ):
            self.assertIn(axis, matrix)
        self.assertIn("NO_KNOWN_MATERIAL_DEFECTS_READY_FOR_EXTERNAL_AUDIT", self.skill)
        self.assertIn("SELF_ADVERSARIAL_PASS != INDEPENDENT_AUDIT", self.skill)

    def test_inert_example_and_authorization(self):
        x = json.loads((ROOT / "templates/owner-gate-run.example.json").read_text(encoding="utf-8"))
        self.assertTrue(x["example_only"])
        self.assertEqual(x["status"], "NOT_RUN")
        self.assertEqual(x["activation"]["mode"], "DORMANT")
        self.assertEqual(x["delegation"]["claude"], "NOT_AUTHORIZED")
        self.assertEqual(x["delegation"]["codex"], "NOT_AUTHORIZED")
        self.assertIsNone(x["canonical_closure_receipt_ref"])

    def test_no_automatic_execution_files(self):
        forbidden = (".github/workflows", "cron", "hooks", "postinstall", "launchd")
        for rel in forbidden:
            self.assertFalse((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
