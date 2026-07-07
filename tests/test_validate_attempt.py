import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.validate_attempt import validate_manifest


class ValidateAttemptManifestTest(unittest.TestCase):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "validate_attempt.py"

    def attempt_root(self, tmp):
        root = Path(tmp) / "A-0001-001"
        root.mkdir()
        return root

    def staged_attempt_root(self, tmp):
        root = Path(tmp) / "ASSET-0001" / ".attempts" / "A-0001-001"
        root.mkdir(parents=True)
        return root

    def write_manifest(self, root, data):
        manifest_path = root / "attempt.json"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        return manifest_path

    def valid_manifest(self, root):
        candidate_a = root / "candidate-a.png"
        candidate_b = root / "candidate-b.png"
        candidate_a.write_bytes(b"png-a")
        candidate_b.write_bytes(b"png-b")
        return {
            "item_id": "ASSET-0001",
            "attempt_id": "A-0001-001",
            "task_id": "ASSET-0001-A001",
            "provider": "browser image tool",
            "candidate_count": 2,
            "result_binding": {
                "task_id": "ASSET-0001-A001",
                "method": "provider echoed TASK-ID in the response",
            },
            "candidates": [
                {"path": "candidate-a.png", "task_id": "ASSET-0001-A001"},
                {"path": "candidate-b.png", "task_id": "ASSET-0001-A001"},
            ],
            "selected_path": "candidate-b.png",
        }

    def test_valid_manifest_has_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_cli_exits_zero_for_valid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, result.returncode)
        self.assertEqual("attempt manifest valid", result.stdout.strip())
        self.assertEqual("", result.stderr.strip())

    def test_cli_exits_nonzero_for_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidate_count"] = 3
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("candidate_count is 3 but candidates has 2 entries", result.stderr)

    def test_requires_result_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data.pop("result_binding")
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("missing required field: result_binding", errors)

    def test_result_binding_can_be_nested_provider_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = {
                "provider_response": {
                    "task_id": "ASSET-0001-A001",
                    "message_region": "assistant response after submit",
                }
            }
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_core_identity_fields_must_be_non_empty_strings(self):
        for field in ("item_id", "attempt_id", "provider"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self.attempt_root(tmp)
                    data = self.valid_manifest(root)
                    data[field] = "   "
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                self.assertIn(f"{field} must be a non-empty string", errors)

    def test_attempt_id_must_match_attempt_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["attempt_id"] = "A-0001-999"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("attempt_id A-0001-999 does not match attempt directory A-0001-001", errors)

    def test_item_id_must_match_item_directory_in_attempt_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_attempt_root(tmp)
            data = self.valid_manifest(root)
            data["item_id"] = "ASSET-9999"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("item_id ASSET-9999 does not match item directory ASSET-0001", errors)

    def test_candidate_count_must_match_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidate_count"] = 3
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate_count is 3 but candidates has 2 entries", errors)

    def test_candidate_paths_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            (root / "candidate-a.png").unlink()
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path does not exist: candidate-a.png", errors)

    def test_candidate_paths_must_be_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            absolute_path = root / "candidate-a.png"
            data["candidates"][0]["path"] = str(absolute_path)
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(f"candidate path must be relative: {absolute_path}", errors)

    def test_candidate_paths_must_stay_inside_attempt_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            attempt_root = root / "attempt"
            attempt_root.mkdir()
            outside = root / "outside.png"
            outside.write_bytes(b"png-outside")
            data = self.valid_manifest(attempt_root)
            data["candidates"][0]["path"] = "../outside.png"
            manifest_path = self.write_manifest(attempt_root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path escapes attempt directory: ../outside.png", errors)

    def test_candidate_paths_must_be_unique_after_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][1]["path"] = "./candidate-a.png"
            data["selected_path"] = "candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("duplicate candidate path: ./candidate-a.png", errors)

    def test_selected_path_matches_candidate_after_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][1]["path"] = "./candidate-b.png"
            data["selected_path"] = "candidate-b.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_selected_path_must_be_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            absolute_path = root / "candidate-b.png"
            data["selected_path"] = str(absolute_path)
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(f"selected_path must be relative: {absolute_path}", errors)

    def test_selected_path_must_reference_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "not-a-candidate.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path is not listed in candidates: not-a-candidate.png", errors)


if __name__ == "__main__":
    unittest.main()
