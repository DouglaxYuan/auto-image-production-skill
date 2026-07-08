import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PlanAttemptRecoveryTest(unittest.TestCase):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "plan_attempt_recovery.py"

    def write_manifest(self, root, data):
        manifest_path = root / "attempt.json"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        return manifest_path

    def failed_manifest(self, root, error_code):
        return {
            "item_id": "ASSET-0001",
            "attempt_id": root.name,
            "task_id": "ASSET-0001-A001",
            "provider": "browser image tool",
            "status": "failed",
            "error_code": error_code,
            "error_detail": f"Provider failed with {error_code}.",
            "candidate_count": 0,
            "result_binding": "TASK-ID ASSET-0001-A001 was submitted",
            "candidates": [],
        }

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script_path), *map(str, args)],
            check=False,
            capture_output=True,
            text=True,
        )

    def run_and_load_plan(self, manifest_path):
        result = self.run_script(manifest_path)
        self.assertEqual("", result.stderr.strip())
        self.assertEqual(0, result.returncode)
        return json.loads(result.stdout)

    def test_cli_classifies_captcha_as_human_intervention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "captcha_required"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("needs_human", plan["action"])
        self.assertEqual(False, plan["retryable"])
        self.assertEqual("captcha_required", plan["error_code"])

    def test_cli_classifies_concurrency_limit_as_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "concurrency_limited"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("backoff", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertGreaterEqual(plan["retry_after_seconds"], 300)

    def test_cli_classifies_network_error_as_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "network_error"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertGreaterEqual(plan["retry_after_seconds"], 30)

    def test_cli_routes_downloaded_attempt_to_image_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            (root / "candidate-a.png").write_bytes(b"not-inspected-here")
            manifest_path = self.write_manifest(
                root,
                {
                    "item_id": "ASSET-0001",
                    "attempt_id": root.name,
                    "task_id": "ASSET-0001-A001",
                    "provider": "browser image tool",
                    "candidate_count": 1,
                    "result_binding": "TASK-ID ASSET-0001-A001 was echoed",
                    "candidates": [
                        {
                            "path": "candidate-a.png",
                            "task_id": "ASSET-0001-A001",
                        }
                    ],
                },
            )

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("inspect_images", plan["action"])
        self.assertEqual(False, plan["retryable"])
        self.assertEqual("python scripts/inspect_attempt_images.py", plan["next_command"])
