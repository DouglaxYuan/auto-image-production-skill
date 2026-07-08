import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


class InspectAttemptImagesTest(unittest.TestCase):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "inspect_attempt_images.py"

    def write_png(self, path, size=(64, 64), color=(20, 120, 200)):
        Image.new("RGB", size, color).save(path)

    def write_manifest(self, root, data):
        manifest_path = root / "attempt.json"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        return manifest_path

    def valid_manifest(self, root):
        self.write_png(root / "candidate-a.png")
        return {
            "item_id": "ASSET-0001",
            "attempt_id": root.name,
            "task_id": "ASSET-0001-A001",
            "provider": "browser image tool",
            "candidate_count": 1,
            "result_binding": {
                "task_id": "ASSET-0001-A001",
                "method": "provider echoed TASK-ID in the response",
            },
            "candidates": [
                {
                    "path": "candidate-a.png",
                    "task_id": "ASSET-0001-A001",
                    "ocr_status": "no_text",
                    "visible_marks": [],
                }
            ],
            "selected_path": "candidate-a.png",
            "quality_rules": {
                "forbidden_visible_marks": ["doubao_ai_generated"],
                "require_ocr_evidence": True,
            },
        }

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script_path), *map(str, args)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_cli_passes_for_decodable_image_with_ocr_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = self.run_script(manifest_path)

        self.assertEqual(0, result.returncode)
        self.assertEqual("attempt images valid", result.stdout.strip())
        self.assertEqual("", result.stderr.strip())

    def test_cli_normalizes_passing_ocr_status_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["ocr_status"] = " No_Text "
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(0, result.returncode)
        self.assertEqual("attempt images valid", result.stdout.strip())
        self.assertEqual("", result.stderr.strip())

    def test_cli_normalizes_passing_ocr_status_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["ocr_status"] = " No-Text "
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(0, result.returncode)
        self.assertEqual("attempt images valid", result.stdout.strip())
        self.assertEqual("", result.stderr.strip())

    def test_cli_rejects_wrong_required_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = self.run_script("--require-size", "2048x2048", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("candidate 1 size is 64x64 but expected 2048x2048", result.stderr)

    def test_cli_rejects_duplicate_candidate_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            (root / "candidate-b.png").write_bytes((root / "candidate-a.png").read_bytes())
            data["candidate_count"] = 2
            data["candidates"].append(
                {
                    "path": "candidate-b.png",
                    "task_id": "ASSET-0001-A001",
                    "ocr_status": "no_text",
                    "visible_marks": [],
                }
            )
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "candidate 2 duplicates candidate 1 by SHA-256: candidate-b.png",
            result.stderr,
        )

    def test_cli_rejects_forbidden_visible_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["visible_marks"] = ["doubao_ai_generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "candidate 1 contains forbidden visible mark: doubao_ai_generated",
            result.stderr,
        )

    def test_cli_matches_forbidden_visible_mark_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["visible_marks"] = [" DouBao_AI_Generated "]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "candidate 1 contains forbidden visible mark: doubao_ai_generated",
            result.stderr,
        )

    def test_cli_normalizes_forbidden_visible_mark_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["forbidden_visible_marks"] = ["doubao ai generated"]
            data["candidates"][0]["visible_marks"] = ["Doubao\nAI   Generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "candidate 1 contains forbidden visible mark: doubao ai generated",
            result.stderr,
        )

    def test_cli_ignores_blank_forbidden_visible_mark_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["forbidden_visible_marks"] = ["   "]
            data["candidates"][0]["visible_marks"] = ["\n\t"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(0, result.returncode)

    def test_cli_rejects_missing_required_ocr_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0].pop("ocr_status")
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn("candidate 1 missing OCR evidence", result.stderr)

    def test_cli_rejects_any_ocr_text_when_rule_requires_text_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["reject_any_ocr_text"] = True
            data["candidates"][0]["ocr_text"] = "SALE"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "candidate 1 contains OCR text while reject_any_ocr_text is enabled",
            result.stderr,
        )

    def test_cli_normalizes_forbidden_ocr_text_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["forbidden_ocr_text"] = [" SALE "]
            data["candidates"][0]["ocr_status"] = "passed"
            data["candidates"][0]["ocr_text"] = "summer sale"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn("candidate 1 contains forbidden OCR text:  SALE ", result.stderr)

    def test_cli_normalizes_forbidden_ocr_text_pattern_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["forbidden_ocr_text"] = ["brand name"]
            data["candidates"][0]["ocr_status"] = "passed"
            data["candidates"][0]["ocr_text"] = "brand\nname"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn("candidate 1 contains forbidden OCR text: brand name", result.stderr)

    def test_cli_rejects_ocr_text_that_conflicts_with_no_text_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["ocr_status"] = "no_text"
            data["candidates"][0]["ocr_text"] = "SALE"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn(
            "candidate 1 OCR status no_text conflicts with non-empty OCR text",
            result.stderr,
        )

    def test_cli_rejects_failed_attempt_without_candidate_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = {
                "item_id": "ASSET-0001",
                "attempt_id": "A-0001-001",
                "task_id": "ASSET-0001-A001",
                "provider": "doubao browser",
                "status": "failed",
                "error_code": "captcha_required",
                "error_detail": "Provider requested interactive CAPTCHA before download.",
                "candidate_count": 0,
                "result_binding": "TASK-ID ASSET-0001-A001 failed before candidates",
                "candidates": [],
            }
            manifest_path = self.write_manifest(root, data)

            result = self.run_script(manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertIn("attempt has no candidate images to inspect", result.stderr)

    def test_cli_json_reports_suggested_failure_code_for_forbidden_visible_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["visible_marks"] = ["doubao_ai_generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("failed", report["status"])
        self.assertEqual("forbidden_visible_mark", report["suggested_error_code"])
        self.assertIn(
            "candidate 1 contains forbidden visible mark: doubao_ai_generated",
            report["errors"],
        )

    def test_cli_json_reports_suggested_failure_code_for_missing_ocr_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0].pop("ocr_status")
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("missing_ocr_evidence", report["suggested_error_code"])

    def test_cli_json_reports_suggested_failure_code_for_ocr_text_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["reject_any_ocr_text"] = True
            data["candidates"][0]["ocr_text"] = "SALE"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("ocr_text_detected", report["suggested_error_code"])

    def test_cli_json_reports_suggested_failure_code_for_forbidden_ocr_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["forbidden_ocr_text"] = ["sale"]
            data["candidates"][0]["ocr_status"] = "passed"
            data["candidates"][0]["ocr_text"] = "summer sale"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("forbidden_ocr_text", report["suggested_error_code"])

    def test_cli_json_sanitizes_unsafe_characters_in_report_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["quality_rules"]["forbidden_ocr_text"] = ["brand\nname"]
            data["candidates"][0]["ocr_status"] = "passed"
            data["candidates"][0]["ocr_text"] = "brand name"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        self.assertNotIn("brand\\nname", result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual("forbidden_ocr_text", report["suggested_error_code"])
        self.assertTrue(all("\n" not in error for error in report["errors"]))
        self.assertIn("brand name", report["errors"][0])
        self.assertNotIn("\n", report["failed_attempt_patch"]["error_detail"])

    def test_cli_json_reports_suggested_failure_code_for_ocr_status_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["ocr_status"] = "failed"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("ocr_status_failed", report["suggested_error_code"])

    def test_cli_json_reports_candidate_validation_failure_for_other_quality_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = self.run_script("--json", "--require-size", "2048x2048", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("candidate_validation_failed", report["suggested_error_code"])

    def test_cli_json_reports_passing_status_without_suggested_failure_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = self.run_script("--json", manifest_path)

        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertEqual("passed", report["status"])
        self.assertEqual([], report["errors"])
        self.assertIsNone(report["suggested_error_code"])

    def test_cli_json_includes_attempt_identity_for_scheduler_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["visible_marks"] = ["doubao_ai_generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("ASSET-0001", report.get("item_id"))
        self.assertEqual("A-0001-001", report.get("attempt_id"))
        self.assertEqual("ASSET-0001-A001", report.get("task_id"))
        self.assertEqual("browser image tool", report.get("provider"))

    def test_cli_json_omits_unsafe_identity_fields_from_scheduler_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["provider"] = "doubao\nbrowser"
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        self.assertIsNone(report.get("provider"))
        self.assertNotIn("doubao\\nbrowser", result.stdout)

    def test_cli_json_redacts_absolute_path_identity_fields_from_scheduler_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            absolute_item_id = Path(tmp) / "private" / "asset-id"
            data = self.valid_manifest(root)
            data["item_id"] = str(absolute_item_id)
            data["candidates"][0]["visible_marks"] = ["doubao_ai_generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        report_text = json.dumps(report)
        self.assertEqual("<path>", report.get("item_id"))
        self.assertNotIn(str(absolute_item_id), report_text)

    def test_cli_json_includes_failed_attempt_patch_for_scheduler_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["visible_marks"] = ["doubao_ai_generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual(
            {
                "status": "failed",
                "error_code": "forbidden_visible_mark",
                "error_detail": (
                    "Image inspection failed: candidate 1 contains forbidden visible "
                    "mark: doubao_ai_generated"
                ),
            },
            report.get("failed_attempt_patch"),
        )

    def test_cli_json_omits_failed_attempt_patch_when_images_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = self.run_script("--json", manifest_path)

        self.assertEqual(0, result.returncode)
        report = json.loads(result.stdout)
        self.assertIsNone(report.get("failed_attempt_patch"))

    def test_cli_json_includes_recovery_hint_for_suggested_failure_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["visible_marks"] = ["doubao_ai_generated"]
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual(
            {
                "action": "reroute_provider",
                "failure_category": "quality_gate",
                "retryable": False,
                "requires_operator": False,
                "next_command": "route to approved alternate provider or skip",
            },
            report.get("recovery_hint"),
        )

    def test_cli_json_omits_recovery_hint_when_images_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            result = self.run_script("--json", manifest_path)

        self.assertEqual(0, result.returncode)
        report = json.loads(result.stdout)
        self.assertIsNone(report.get("recovery_hint"))

    def test_cli_json_classifies_manifest_validation_errors_as_contract_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "A-0001-001"
            root.mkdir()
            data = self.valid_manifest(root)
            data.pop("candidate_count")
            manifest_path = self.write_manifest(root, data)

            result = self.run_script("--json", manifest_path)

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("attempt_manifest_invalid", report["suggested_error_code"])
        self.assertEqual(
            {
                "status": "failed",
                "error_code": "attempt_manifest_invalid",
                "error_detail": (
                    "Image inspection failed: missing required field: candidate_count; "
                    "candidate_count must be a positive integer unless status is failed"
                ),
            },
            report["failed_attempt_patch"],
        )
        self.assertEqual("review_failure", report["recovery_hint"]["action"])
        self.assertEqual("automation_contract", report["recovery_hint"]["failure_category"])
        self.assertEqual(True, report["recovery_hint"]["requires_operator"])

    def test_cli_json_redacts_absolute_paths_from_report_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_manifest = Path(tmp) / "private" / "A-0001-001" / "attempt.json"

            result = self.run_script("--json", missing_manifest)

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        report_text = json.dumps(report)
        self.assertNotIn(str(missing_manifest), report_text)
        self.assertIn("<path>", report_text)
        self.assertEqual("attempt_manifest_invalid", report["suggested_error_code"])
        self.assertIn("<path>", report["failed_attempt_patch"]["error_detail"])
