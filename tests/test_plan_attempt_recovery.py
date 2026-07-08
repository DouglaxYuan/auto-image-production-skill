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
        self.assertEqual("request human intervention", plan["next_command"])

    def test_cli_marks_captcha_as_requiring_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "captcha_required"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertIn("requires_operator", plan)
        self.assertEqual(True, plan["requires_operator"])

    def test_cli_classifies_login_required_as_human_intervention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "login_required"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("needs_human", plan["action"])
        self.assertEqual(False, plan["retryable"])
        self.assertEqual("human_intervention", plan["failure_category"])
        self.assertEqual("request human intervention", plan["next_command"])

    def test_cli_classifies_concurrency_limit_as_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "concurrency_limited"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("backoff", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertGreaterEqual(plan["retry_after_seconds"], 300)

    def test_cli_classifies_rate_limit_as_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "rate_limited"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("backoff", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual("capacity", plan["failure_category"])

    def test_cli_classifies_provider_busy_as_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "provider_busy"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("backoff", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual("capacity", plan["failure_category"])
        self.assertEqual("schedule retry after retry_after_seconds", plan["next_command"])

    def test_cli_classifies_network_error_as_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "network_error"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertGreaterEqual(plan["retry_after_seconds"], 30)
        self.assertEqual("schedule retry after retry_after_seconds", plan["next_command"])

    def test_cli_classifies_page_load_failure_as_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "page_load_failed"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual("network", plan["failure_category"])
        self.assertEqual("schedule retry after retry_after_seconds", plan["next_command"])

    def test_cli_classifies_browser_crash_as_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "browser_crashed"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual("provider_runtime", plan["failure_category"])
        self.assertEqual("schedule retry after retry_after_seconds", plan["next_command"])

    def test_cli_classifies_missing_selector_as_automation_contract_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "selector_not_found"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("review_failure", plan["action"])
        self.assertEqual(False, plan["retryable"])
        self.assertEqual("automation_contract", plan["failure_category"])
        self.assertEqual(True, plan["requires_operator"])
        self.assertEqual("inspect the failed attempt manifest", plan["next_command"])

    def test_cli_classifies_download_failure_as_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "download_failed"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual("network", plan["failure_category"])
        self.assertEqual("schedule retry after retry_after_seconds", plan["next_command"])

    def test_cli_normalizes_error_code_separators_for_policy_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "Network-Error"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual("Network-Error", plan["error_code"])
        self.assertEqual("network", plan["failure_category"])

    def test_cli_reports_normalized_error_code_for_failed_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "Network-Error"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertEqual("Network-Error", plan["error_code"])
        self.assertEqual("network_error", plan["normalized_error_code"])

    def test_cli_marks_network_retry_as_not_requiring_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "network_error"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertIn("requires_operator", plan)
        self.assertEqual(False, plan["requires_operator"])

    def test_cli_reports_failure_category_for_retryable_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "network_error"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertIn("failure_category", plan)
        self.assertEqual("network", plan["failure_category"])

    def test_cli_reports_failure_category_for_human_intervention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "captcha_required"))

            plan = self.run_and_load_plan(manifest_path)

        self.assertIn("failure_category", plan)
        self.assertEqual("human_intervention", plan["failure_category"])

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

    def test_cli_stops_retryable_failure_after_retry_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 3
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "3", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual("review_failure", plan["action"])
        self.assertEqual(False, plan["retryable"])
        self.assertEqual("retry budget exhausted", plan["reason"])

    def test_cli_marks_exhausted_retry_budget_as_requiring_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 3
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "3", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual("review_failure", plan["action"])
        self.assertIn("requires_operator", plan)
        self.assertEqual(True, plan["requires_operator"])

    def test_cli_keeps_retryable_failure_when_retry_budget_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 2
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "3", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(True, plan["retryable"])
        self.assertEqual(1, plan["remaining_retries"])
        self.assertEqual(3, plan["max_retries"])

    def test_cli_reports_next_retry_count_for_retryable_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 2
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "5", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual("retry", plan["action"])
        self.assertIn("next_retry_count", plan)
        self.assertEqual(3, plan["next_retry_count"])

    def test_cli_expands_retry_delay_after_previous_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 2
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "5", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(240, plan["retry_after_seconds"])
        self.assertEqual(3, plan["remaining_retries"])

    def test_cli_caps_retry_delay_after_many_previous_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 10
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "12", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual("retry", plan["action"])
        self.assertEqual(3600, plan["retry_after_seconds"])

    def test_cli_reports_zero_remaining_retries_after_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.failed_manifest(root, "network_error")
            data["retry_count"] = 3
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--max-retries", "3", manifest_path)
            self.assertEqual("", result.stderr.strip())
            self.assertEqual(0, result.returncode)
            plan = json.loads(result.stdout)

        self.assertEqual(0, plan["remaining_retries"])

    def test_cli_rejects_non_positive_max_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.failed_manifest(root, "network_error"))

            result = self.run_script("--max-retries", "0", manifest_path)

        self.assertEqual(2, result.returncode)
        self.assertIn("--max-retries must be a positive integer", result.stderr)
