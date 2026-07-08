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
