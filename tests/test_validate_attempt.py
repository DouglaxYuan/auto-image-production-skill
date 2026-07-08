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

    def deeply_nested_list(self, depth):
        value = "no-task"
        for _ in range(depth):
            value = [value]
        return value

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

    def test_cli_json_reports_invalid_manifest_without_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_manifest = Path(tmp) / "private" / "A-0001-001" / "attempt.json"

            result = subprocess.run(
                [sys.executable, str(self.script_path), "--json", str(missing_manifest)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr.strip())
        report = json.loads(result.stdout)
        report_text = json.dumps(report)
        self.assertEqual(False, report["valid"])
        self.assertEqual("failed", report["status"])
        self.assertEqual("attempt_manifest_invalid", report["error_code"])
        self.assertEqual("attempt_manifest_invalid", report["normalized_error_code"])
        self.assertEqual("automation_contract", report["failure_category"])
        self.assertEqual(True, report["requires_operator"])
        self.assertEqual("inspect the failed attempt manifest", report["next_command"])
        self.assertEqual(1, report["error_count"])
        self.assertIn("<path>", report_text)
        self.assertNotIn(str(missing_manifest), report_text)

    def test_failed_attempt_can_record_provider_interrupt_without_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_attempt_root(tmp)
            data = {
                "item_id": "ASSET-0001",
                "attempt_id": root.name,
                "task_id": "ASSET-0001-A001",
                "provider": "doubao browser",
                "status": "failed",
                "error_code": "captcha_required",
                "error_detail": "Provider requested interactive image CAPTCHA after submit.",
                "candidate_count": 0,
                "result_binding": {
                    "task_id": "ASSET-0001-A001",
                    "method": "provider interrupted before returning candidates",
                },
                "candidates": [],
            }
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_failed_attempt_requires_error_code_and_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_attempt_root(tmp)
            data = {
                "item_id": "ASSET-0001",
                "attempt_id": root.name,
                "task_id": "ASSET-0001-A001",
                "provider": "doubao browser",
                "status": "failed",
                "candidate_count": 0,
                "result_binding": "TASK-ID ASSET-0001-A001 failed before download",
                "candidates": [],
            }
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("failed attempts require non-empty error_code", errors)
        self.assertIn("failed attempts require non-empty error_detail", errors)

    def test_candidate_count_zero_requires_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_attempt_root(tmp)
            data = {
                "item_id": "ASSET-0001",
                "attempt_id": root.name,
                "task_id": "ASSET-0001-A001",
                "provider": "doubao browser",
                "status": "submitted",
                "candidate_count": 0,
                "result_binding": "TASK-ID ASSET-0001-A001 is still pending",
                "candidates": [],
            }
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate_count must be a positive integer unless status is failed", errors)

    def test_retry_count_must_be_non_negative_integer_when_present(self):
        cases = ("3", -1, True)
        for value in cases:
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self.staged_attempt_root(tmp)
                    data = self.valid_manifest(root)
                    data["retry_count"] = value
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                self.assertIn("retry_count must be a non-negative integer when present", errors)

    def test_cli_reports_directory_path_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(self.script_path), tmp],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest path is not a file:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_does_not_echo_unsafe_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "bad\nattempt.json"

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest path must not contain control characters", result.stderr)
        self.assertNotIn("bad\nattempt.json", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reports_non_utf8_manifest_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "attempt.json"
            manifest_path.write_bytes(b"\xff\xfe")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest is not valid UTF-8 text:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reports_deeply_nested_manifest_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "attempt.json"
            depth = sys.getrecursionlimit() + 1000
            manifest_path.write_text("[" * depth + "]" * depth, encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest is too deeply nested:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reports_unreadable_manifest_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "attempt.json"
            manifest_path.write_text(json.dumps({"item_id": "ASSET-0001"}), encoding="utf-8")
            manifest_path.chmod(0)
            try:
                result = subprocess.run(
                    [sys.executable, str(self.script_path), str(manifest_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                manifest_path.chmod(0o600)

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest could not be read:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reports_invalid_manifest_parent_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop_path = Path(tmp) / "loop"
            try:
                loop_path.symlink_to("loop")
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(loop_path / "attempt.json")],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest parent directory is invalid:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reports_invalid_manifest_path_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "attempt.json"
            try:
                manifest_path.symlink_to("attempt.json")
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest path is invalid:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_non_standard_json_constants_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            manifest_path = root / "attempt.json"
            manifest_path.write_text(
                """
                {
                    "item_id": "ASSET-0001",
                    "attempt_id": "A-0001-001",
                    "task_id": "ASSET-0001-A001",
                    "provider": "browser image tool",
                    "candidate_count": 1,
                    "result_binding": "TASK-ID ASSET-0001-A001",
                    "candidates": [
                        {"path": "candidate-a.png", "task_id": "ASSET-0001-A001"}
                    ],
                    "selected_path": "candidate-a.png",
                    "quality_score": NaN
                }
                """,
                encoding="utf-8",
            )
            (root / "candidate-a.png").write_bytes(b"png-a")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest is not valid JSON:", result.stderr)
        self.assertIn("NaN", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_duplicate_json_keys_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            manifest_path = root / "attempt.json"
            manifest_path.write_text(
                """
                {
                    "item_id": "ASSET-9999",
                    "item_id": "ASSET-0001",
                    "attempt_id": "A-0001-001",
                    "task_id": "ASSET-0001-A001",
                    "provider": "browser image tool",
                    "candidate_count": 1,
                    "result_binding": "TASK-ID ASSET-0001-A001",
                    "candidates": [
                        {"path": "candidate-a.png", "task_id": "ASSET-0001-A001"}
                    ],
                    "selected_path": "candidate-a.png"
                }
                """,
                encoding="utf-8",
            )
            (root / "candidate-a.png").write_bytes(b"png-a")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest contains duplicate JSON key: item_id", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_does_not_echo_unsafe_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            manifest_path = root / "attempt.json"
            manifest_path.write_text(
                '{"bad\\nkey": 1, "bad\\nkey": 2}',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest contains duplicate JSON key with unsafe characters", result.stderr)
        self.assertNotIn("bad\nkey", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_manifest_file_symlink_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            target_path = Path(tmp) / "outside-attempt.json"
            target_path.write_text(json.dumps(self.valid_manifest(root)), encoding="utf-8")
            manifest_path = root / "attempt.json"
            try:
                manifest_path.symlink_to(target_path)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest path must not be a symlink:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_manifest_parent_symlink_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_root = self.attempt_root(tmp)
            manifest_path = self.write_manifest(real_root, self.valid_manifest(real_root))
            link_root = Path(tmp) / "attempt-link"
            try:
                link_root.symlink_to(real_root)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(link_root / manifest_path.name)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest parent directory must not be a symlink:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_manifest_item_directory_symlink_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_root = Path(tmp) / "real-ASSET-0001" / ".attempts" / "A-0001-001"
            real_root.mkdir(parents=True)
            data = self.valid_manifest(real_root)
            data["item_id"] = "real-ASSET-0001"
            self.write_manifest(real_root, data)
            link_item = Path(tmp) / "ASSET-0001"
            try:
                link_item.symlink_to(real_root.parent.parent, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.script_path),
                    str(link_item / ".attempts" / "A-0001-001" / "attempt.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("manifest item directory must not be a symlink:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

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

    def test_result_binding_can_reference_task_id_in_metadata_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = {
                "provider_tasks": {
                    "ASSET-0001-A001": {
                        "message_region": "assistant response after submit",
                    }
                }
            }
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_result_binding_requires_exact_task_id_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = "provider echoed TASK-ID ASSET-0001-A001-extra"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("result_binding does not reference task_id: ASSET-0001-A001", errors)

    def test_cli_does_not_echo_unsafe_task_id_in_result_binding_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["task_id"] = "ASSET-0001-A001\nextra"
            data["result_binding"] = "provider did not echo the task id"
            for candidate in data["candidates"]:
                candidate["task_id"] = data["task_id"]
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("task_id must not contain control characters", result.stderr)
        self.assertNotIn("result_binding does not reference task_id", result.stderr)
        self.assertNotIn("ASSET-0001-A001\nextra", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_result_binding_rejects_task_id_with_dotted_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = "provider echoed TASK-ID ASSET-0001-A001.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("result_binding does not reference task_id: ASSET-0001-A001", errors)

    def test_result_binding_rejects_task_id_with_unicode_letter_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = "provider echoed TASK-ID ASSET-0001-A001\u65e7"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("result_binding does not reference task_id: ASSET-0001-A001", errors)

    def test_result_binding_accepts_task_id_followed_by_sentence_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = "provider echoed TASK-ID ASSET-0001-A001."
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_result_binding_accepts_task_id_in_unicode_sentence_when_spaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = "\u4efb\u52a1 ASSET-0001-A001 \u5df2\u5b8c\u6210"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertEqual([], errors)

    def test_cli_reports_deeply_nested_result_binding_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["result_binding"] = self.deeply_nested_list(600)
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("result_binding is too deeply nested:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

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

    def test_core_identity_fields_must_not_contain_control_characters(self):
        cases = (
            ("item_id", "ASSET-0001\nextra"),
            ("attempt_id", "A-0001-001\nextra"),
            ("task_id", "ASSET-0001-A001\nextra"),
            ("provider", "browser\nimage tool"),
            ("provider", "browser\x00image tool"),
            ("provider", "browser\u0085image tool"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self.attempt_root(tmp)
                    data = self.valid_manifest(root)
                    data[field] = value
                    if field == "task_id":
                        data["result_binding"] = f"TASK-ID {value}"
                        for candidate in data["candidates"]:
                            candidate["task_id"] = value
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                self.assertIn(f"{field} must not contain control characters", errors)

    def test_cli_does_not_echo_unsafe_attempt_id_in_layout_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["attempt_id"] = "A-0001-001\nextra"
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("attempt_id must not contain control characters", result.stderr)
        self.assertNotIn("does not match attempt directory", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_does_not_echo_unsafe_item_id_in_layout_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_attempt_root(tmp)
            data = self.valid_manifest(root)
            data["item_id"] = "ASSET-0001\nextra"
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("item_id must not contain control characters", result.stderr)
        self.assertNotIn("does not match item directory", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_core_identity_fields_must_not_contain_unicode_format_characters(self):
        cases = (
            ("item_id", "ASSET-0001\u202e"),
            ("attempt_id", "A-0001-001\u202e"),
            ("task_id", "ASSET-0001-A001\u202e"),
            ("provider", "browser\u202e image tool"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self.attempt_root(tmp)
                    data = self.valid_manifest(root)
                    data[field] = value
                    if field == "task_id":
                        data["result_binding"] = f"TASK-ID {value}"
                        for candidate in data["candidates"]:
                            candidate["task_id"] = value
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                self.assertIn(f"{field} must not contain Unicode format characters", errors)

    def test_core_identity_fields_must_not_contain_surrogate_characters(self):
        cases = (
            ("item_id", "ASSET-0001\ud800"),
            ("attempt_id", "A-0001-001\ud800"),
            ("task_id", "ASSET-0001-A001\ud800"),
            ("provider", "browser\ud800 image tool"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self.attempt_root(tmp)
                    data = self.valid_manifest(root)
                    data[field] = value
                    if field == "task_id":
                        data["result_binding"] = f"TASK-ID {value}"
                        for candidate in data["candidates"]:
                            candidate["task_id"] = value
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                self.assertIn(f"{field} must not contain surrogate characters", errors)

    def test_core_identity_fields_must_not_have_surrounding_whitespace(self):
        cases = (
            ("item_id", " ASSET-0001"),
            ("attempt_id", "A-0001-001 "),
            ("task_id", " ASSET-0001-A001"),
            ("provider", "browser image tool "),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self.attempt_root(tmp)
                    data = self.valid_manifest(root)
                    data[field] = value
                    if field == "task_id":
                        data["result_binding"] = value
                        for candidate in data["candidates"]:
                            candidate["task_id"] = value
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                self.assertIn(f"{field} must not have leading or trailing whitespace", errors)

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

    def test_item_id_layout_check_normalizes_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_attempt_root(tmp)
            data = self.valid_manifest(root)
            data["item_id"] = "ASSET-9999"
            manifest_path = self.write_manifest(root, data)
            unnormalized_manifest_path = root / ".." / root.name / manifest_path.name

            errors = validate_manifest(unnormalized_manifest_path)

        self.assertIn("item_id ASSET-9999 does not match item directory ASSET-0001", errors)

    def test_attempt_collection_symlink_is_rejected_in_item_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            item_root = Path(tmp) / "ASSET-0001"
            item_root.mkdir()
            outside_attempts = Path(tmp) / "outside-attempts"
            outside_attempts.mkdir()
            attempt_collection = item_root / ".attempts"
            try:
                attempt_collection.symlink_to(outside_attempts, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")
            root = attempt_collection / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))

            errors = validate_manifest(manifest_path)

        self.assertIn(
            f"manifest attempt collection directory must not be a symlink: {attempt_collection}",
            errors,
        )

    def test_attempt_collection_symlink_is_rejected_with_unnormalized_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            item_root = Path(tmp) / "ASSET-0001"
            item_root.mkdir()
            outside_attempts = Path(tmp) / "outside-attempts"
            outside_attempts.mkdir()
            attempt_collection = item_root / ".attempts"
            try:
                attempt_collection.symlink_to(outside_attempts, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")
            root = attempt_collection / "A-0001-001"
            root.mkdir()
            manifest_path = self.write_manifest(root, self.valid_manifest(root))
            unnormalized_manifest_path = root / ".." / root.name / manifest_path.name

            errors = validate_manifest(unnormalized_manifest_path)

        self.assertIn(
            f"manifest attempt collection directory must not be a symlink: {attempt_collection}",
            errors,
        )

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

    def test_candidate_path_must_be_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            (root / "candidate-a.png").unlink()
            (root / "candidate-a.png").mkdir()
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path is not a file: candidate-a.png", errors)

    def test_candidate_paths_must_be_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            absolute_path = root / "candidate-a.png"
            data["candidates"][0]["path"] = str(absolute_path)
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(f"candidate path must be relative: {absolute_path}", errors)

    def test_cli_does_not_echo_unsafe_absolute_candidate_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = str(root / "bad\nname.png")
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("candidate path must not contain control characters", result.stderr)
        self.assertNotIn("candidate path must be relative:", result.stderr)
        self.assertNotIn("bad\nname.png", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_candidate_paths_must_not_end_with_path_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "candidate-a.png/"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path must not end with a path separator: candidate-a.png/", errors)

    def test_candidate_paths_must_not_contain_current_directory_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "candidate-a.png/."
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate path must not contain current directory references: candidate-a.png/.",
            errors,
        )

    def test_candidate_paths_must_not_start_with_current_directory_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "./candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate path must not contain current directory references: ./candidate-a.png",
            errors,
        )

    def test_candidate_paths_must_not_contain_repeated_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            generated = root / "generated"
            generated.mkdir()
            (generated / "candidate-a.png").write_bytes(b"png-a")
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "generated//candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate path must not contain repeated path separators: "
            "generated//candidate-a.png",
            errors,
        )

    def test_candidate_paths_must_not_contain_control_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            for control_path in ("candidate\nname.png", "candidate\u0085name.png"):
                with self.subTest(path=control_path):
                    (root / control_path).write_bytes(b"png-a")
                    data = self.valid_manifest(root)
                    data["candidates"][0]["path"] = control_path
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                    self.assertIn("candidate path must not contain control characters", errors)

    def test_candidate_paths_must_not_contain_unicode_format_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            format_path = "candidate\u202ename.png"
            (root / format_path).write_bytes(b"png-a")
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = format_path
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path must not contain Unicode format characters", errors)

    def test_candidate_paths_must_not_contain_surrogate_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "candidate\ud800name.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path must not contain surrogate characters", errors)

    def test_candidate_paths_must_not_contain_unicode_separator_lookalikes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            lookalike_path = "generated\u2044candidate-a.png"
            (root / lookalike_path).write_bytes(b"png-a")
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = lookalike_path
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate path must not contain Unicode path separator lookalikes",
            errors,
        )

    def test_candidate_paths_must_not_escape_with_parent_references(self):
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

        self.assertIn("candidate path must not contain parent directory references: ../outside.png", errors)

    def test_candidate_paths_must_not_contain_parent_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            nested = root / "nested"
            nested.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "nested/../candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path must not contain parent directory references: nested/../candidate-a.png", errors)

    def test_candidate_paths_must_not_contain_windows_parent_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "nested\\..\\candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate path must not contain parent directory references: "
            "nested\\..\\candidate-a.png",
            errors,
        )

    def test_candidate_paths_must_use_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            backslash_path = "generated\\candidate-a.png"
            (root / backslash_path).write_bytes(b"png-a")
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = backslash_path
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(f"candidate path must use forward slashes: {backslash_path}", errors)

    def test_candidate_path_with_invalid_filesystem_characters_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "bad\x00name.png"
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("candidate path must not contain control characters", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_candidate_path_symlink_loop_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            loop_path = root / "loop.png"
            try:
                loop_path.symlink_to("loop.png")
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "loop.png"
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("candidate path is invalid: loop.png", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_candidate_path_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            target_path = root / "candidate-target.png"
            target_path.write_bytes(b"png-target")
            link_path = root / "candidate-link.png"
            try:
                link_path.symlink_to(target_path)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "candidate-link.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate path must not be a symlink: candidate-link.png", errors)

    def test_candidate_path_symlinked_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            target_dir = root / "generated"
            target_dir.mkdir()
            target_path = target_dir / "candidate-target.png"
            target_path.write_bytes(b"png-target")
            link_dir = root / "candidate-link-dir"
            try:
                link_dir.symlink_to(target_dir, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            data = self.valid_manifest(root)
            data["candidates"][0]["path"] = "candidate-link-dir/candidate-target.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate path must not contain symlinked directories: "
            "candidate-link-dir/candidate-target.png",
            errors,
        )

    def test_candidate_paths_must_be_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][1]["path"] = "candidate-a.png"
            data["selected_path"] = "candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("duplicate candidate path: candidate-a.png", errors)

    def test_candidate_task_id_must_be_non_empty_string_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["task_id"] = "   "
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate 1 task_id must be a non-empty string when present", errors)

    def test_candidate_task_id_must_not_contain_unicode_format_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["task_id"] = "ASSET-0001-A001\u202e"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate 1 task_id must not contain Unicode format characters", errors)

    def test_candidate_task_id_must_not_contain_surrogate_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["task_id"] = "ASSET-0001-A001\ud800"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate 1 task_id must not contain surrogate characters", errors)

    def test_candidate_task_id_must_not_have_surrounding_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["task_id"] = "ASSET-0001-A001 "
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "candidate 1 task_id must not have leading or trailing whitespace",
            errors,
        )

    def test_candidate_task_id_must_not_contain_nul(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["task_id"] = "ASSET-0001-A001\x00"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate 1 task_id must not contain control characters", errors)

    def test_candidate_task_id_must_not_contain_unicode_control_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][0]["task_id"] = "ASSET-0001-A001\u0085"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("candidate 1 task_id must not contain control characters", errors)

    def test_candidate_task_id_mismatch_is_reported_when_path_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["candidates"][1]["path"] = "candidate-a.png"
            data["candidates"][1]["task_id"] = "ASSET-0001-A999"
            data["selected_path"] = "candidate-a.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("duplicate candidate path: candidate-a.png", errors)
        self.assertIn("candidate 2 task_id does not match manifest task_id", errors)

    def test_selected_path_matches_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
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

    def test_cli_does_not_echo_unsafe_absolute_selected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = str(root / "bad\nname.png")
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("selected_path must not contain control characters", result.stderr)
        self.assertNotIn("selected_path must be relative:", result.stderr)
        self.assertNotIn("bad\nname.png", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_selected_path_must_not_end_with_path_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "candidate-b.png/"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path must not end with a path separator: candidate-b.png/", errors)

    def test_selected_path_must_not_contain_current_directory_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "candidate-b.png/."
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "selected_path must not contain current directory references: candidate-b.png/.",
            errors,
        )

    def test_selected_path_must_not_start_with_current_directory_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "./candidate-b.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "selected_path must not contain current directory references: ./candidate-b.png",
            errors,
        )

    def test_selected_path_must_not_contain_repeated_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            generated = root / "generated"
            generated.mkdir()
            (generated / "candidate-target.png").write_bytes(b"png-target")
            data = self.valid_manifest(root)
            data["candidates"].append(
                {"path": "generated/candidate-target.png", "task_id": "ASSET-0001-A001"}
            )
            data["candidate_count"] = 3
            data["selected_path"] = "generated//candidate-target.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "selected_path must not contain repeated path separators: "
            "generated//candidate-target.png",
            errors,
        )

    def test_selected_path_must_not_contain_control_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            for control_path in ("candidate\tname.png", "candidate\u0085name.png"):
                with self.subTest(path=control_path):
                    (root / control_path).write_bytes(b"png-target")
                    data = self.valid_manifest(root)
                    data["candidates"].append({"path": control_path, "task_id": "ASSET-0001-A001"})
                    data["candidate_count"] = 3
                    data["selected_path"] = control_path
                    manifest_path = self.write_manifest(root, data)

                    errors = validate_manifest(manifest_path)

                    self.assertIn("selected_path must not contain control characters", errors)

    def test_selected_path_must_not_contain_unicode_format_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            format_path = "candidate\u200dname.png"
            (root / format_path).write_bytes(b"png-target")
            data = self.valid_manifest(root)
            data["candidates"].append({"path": format_path, "task_id": "ASSET-0001-A001"})
            data["candidate_count"] = 3
            data["selected_path"] = format_path
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path must not contain Unicode format characters", errors)

    def test_selected_path_must_not_contain_surrogate_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "candidate\ud800name.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path must not contain surrogate characters", errors)

    def test_selected_path_must_not_contain_unicode_separator_lookalikes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            lookalike_path = "generated\uff0fcandidate-target.png"
            (root / lookalike_path).write_bytes(b"png-target")
            data = self.valid_manifest(root)
            data["candidates"].append({"path": lookalike_path, "task_id": "ASSET-0001-A001"})
            data["candidate_count"] = 3
            data["selected_path"] = lookalike_path
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "selected_path must not contain Unicode path separator lookalikes",
            errors,
        )

    def test_selected_path_must_not_contain_parent_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            nested = root / "nested"
            nested.mkdir()
            data = self.valid_manifest(root)
            data["candidates"][1]["path"] = "./candidate-b.png"
            data["selected_path"] = "nested/../candidate-b.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path must not contain parent directory references: nested/../candidate-b.png", errors)

    def test_selected_path_must_not_contain_windows_parent_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "nested\\..\\candidate-b.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "selected_path must not contain parent directory references: "
            "nested\\..\\candidate-b.png",
            errors,
        )

    def test_selected_path_must_use_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            backslash_path = "generated\\candidate-target.png"
            (root / backslash_path).write_bytes(b"png-target")
            data = self.valid_manifest(root)
            data["candidates"].append({"path": backslash_path, "task_id": "ASSET-0001-A001"})
            data["candidate_count"] = 3
            data["selected_path"] = backslash_path
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(f"selected_path must use forward slashes: {backslash_path}", errors)

    def test_selected_path_must_be_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            (root / "candidate-b.png").unlink()
            (root / "candidate-b.png").mkdir()
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path is not a file: candidate-b.png", errors)

    def test_selected_path_with_invalid_filesystem_characters_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "bad\x00name.png"
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("selected_path must not contain control characters", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_selected_path_symlink_loop_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            loop_path = root / "loop.png"
            try:
                loop_path.symlink_to("loop.png")
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            data = self.valid_manifest(root)
            data["selected_path"] = "loop.png"
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("selected_path is invalid: loop.png", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_selected_path_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            target_path = root / "candidate-target.png"
            target_path.write_bytes(b"png-target")
            link_path = root / "candidate-link.png"
            try:
                link_path.symlink_to(target_path)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            data = self.valid_manifest(root)
            data["candidates"].append({"path": "candidate-target.png", "task_id": "ASSET-0001-A001"})
            data["candidate_count"] = 3
            data["selected_path"] = "candidate-link.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path must not be a symlink: candidate-link.png", errors)

    def test_selected_path_symlinked_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            target_dir = root / "generated"
            target_dir.mkdir()
            target_path = target_dir / "candidate-target.png"
            target_path.write_bytes(b"png-target")
            link_dir = root / "candidate-link-dir"
            try:
                link_dir.symlink_to(target_dir, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            data = self.valid_manifest(root)
            data["candidates"].append(
                {"path": "generated/candidate-target.png", "task_id": "ASSET-0001-A001"}
            )
            data["candidate_count"] = 3
            data["selected_path"] = "candidate-link-dir/candidate-target.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn(
            "selected_path must not contain symlinked directories: "
            "candidate-link-dir/candidate-target.png",
            errors,
        )

    def test_selected_path_must_reference_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data["selected_path"] = "not-a-candidate.png"
            manifest_path = self.write_manifest(root, data)

            errors = validate_manifest(manifest_path)

        self.assertIn("selected_path is not listed in candidates: not-a-candidate.png", errors)

    def test_cli_can_require_selected_path_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.attempt_root(tmp)
            data = self.valid_manifest(root)
            data.pop("selected_path")
            manifest_path = self.write_manifest(root, data)

            result = subprocess.run(
                [sys.executable, str(self.script_path), "--require-selected", str(manifest_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("selected_path is required when --require-selected is used", result.stderr)


if __name__ == "__main__":
    unittest.main()
