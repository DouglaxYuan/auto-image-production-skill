#!/usr/bin/env python3
"""Inspect downloaded image candidates for an auto-image-production attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover - exercised only in environments without Pillow.
    Image = None  # type: ignore[assignment]
    UnidentifiedImageError = OSError  # type: ignore[assignment,misc]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_attempt import _safe_report_path_value, validate_manifest  # noqa: E402
from scripts.plan_attempt_recovery import (  # noqa: E402
    POLICIES,
    _next_command_for_action,
    _normalized_error_code,
    _operator_block_key,
    _requires_operator,
    _retry_after_seconds,
)


NO_TEXT_OCR_STATUSES = frozenset(("no_text", "text_absent", "clear"))
PASSING_OCR_STATUSES = frozenset(("passed", *NO_TEXT_OCR_STATUSES))
NO_CANDIDATE_ERROR = "attempt has no candidate images to inspect"
ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![\w<])/(?:[^\s;:(),]+/?)+")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_size(value: str) -> tuple[int, int]:
    if "x" not in value.lower():
        raise argparse.ArgumentTypeError("size must use WIDTHxHEIGHT")
    width_text, height_text = value.lower().split("x", 1)
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must use integer dimensions") from exc
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("size dimensions must be positive")
    return width, height


def _read_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_size(path: Path) -> tuple[int, int]:
    if Image is None:
        raise RuntimeError("Pillow is required to inspect candidate images")
    with Image.open(path) as image:
        image.load()
        return image.size


def _quality_rules(data: dict[str, Any]) -> dict[str, Any]:
    rules = data.get("quality_rules")
    return rules if isinstance(rules, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _normalized_mark(value: str) -> str:
    separated = re.sub(r"[_\-\u2010-\u2015]+", " ", value)
    return " ".join(separated.split()).casefold()


def _normalized_status(value: str) -> str:
    separated = re.sub(r"[\-\u2010-\u2015]+", " ", value)
    return "_".join(separated.split()).casefold()


def _normalized_ocr_text(value: str) -> str:
    separated = re.sub(r"[_\-\u2010-\u2015]+", " ", value)
    return " ".join(separated.split()).casefold()


def _candidate_has_ocr_evidence(candidate: dict[str, Any]) -> bool:
    return isinstance(candidate.get("ocr_status"), str) or isinstance(candidate.get("ocr_text"), str)


def _manifest_failed_error_code(errors: list[str], data: dict[str, Any] | None) -> str | None:
    if not any(NO_CANDIDATE_ERROR in error for error in errors):
        return None
    if not isinstance(data, dict) or data.get("status") != "failed":
        return None

    normalized_error_code = _normalized_error_code(data.get("error_code"))
    if isinstance(normalized_error_code, str) and normalized_error_code in POLICIES:
        return normalized_error_code
    return None


def _suggested_error_code(errors: list[str], data: dict[str, Any] | None = None) -> str | None:
    if not errors:
        return None

    manifest_error_code = _manifest_failed_error_code(errors, data)
    if manifest_error_code is not None:
        return manifest_error_code

    prioritized_error_codes = (
        ("missing required field:", "attempt_manifest_invalid"),
        ("manifest ", "attempt_manifest_invalid"),
        ("candidate_count is", "attempt_manifest_invalid"),
        ("result_binding ", "attempt_manifest_invalid"),
        ("attempt_id ", "attempt_manifest_invalid"),
        ("item_id ", "attempt_manifest_invalid"),
        ("candidate path ", "attempt_manifest_invalid"),
        ("selected_path ", "attempt_manifest_invalid"),
        ("contains forbidden visible mark", "forbidden_visible_mark"),
        ("contains forbidden OCR text", "forbidden_ocr_text"),
        ("missing OCR evidence", "missing_ocr_evidence"),
        ("contains OCR text while reject_any_ocr_text is enabled", "ocr_text_detected"),
        ("OCR status is not passing", "ocr_status_failed"),
        ("conflicts with non-empty OCR text", "ocr_status_failed"),
        (NO_CANDIDATE_ERROR, "no_candidates_found"),
    )
    for needle, error_code in prioritized_error_codes:
        if any(needle in error for error in errors):
            return error_code
    return "candidate_validation_failed"


def _failed_attempt_patch(errors: list[str], data: dict[str, Any] | None = None) -> dict[str, str] | None:
    error_code = _suggested_error_code(errors, data)
    if error_code is None:
        return None
    return {
        "status": "failed",
        "error_code": error_code,
        "error_detail": f"Image inspection failed: {'; '.join(errors)}",
    }


def _redact_local_paths(value: str) -> str:
    return ABSOLUTE_PATH_PATTERN.sub("<path>", value)


def _replace_unsafe_display_characters(value: str) -> str:
    return "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
        for character in value
    )


def _safe_report_error_value(value: str) -> str:
    redacted = _redact_local_paths(value)
    return _replace_unsafe_display_characters(redacted)


def _report_errors(errors: list[str]) -> list[str]:
    return [_safe_report_error_value(error) for error in errors]


def _recovery_hint(errors: list[str], data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    error_code = _suggested_error_code(errors, data)
    if error_code is None:
        return None
    policy = POLICIES.get(error_code)
    if policy is None:
        return None
    action = policy.get("action")
    hint = {
        "action": action,
        "failure_category": policy.get("failure_category"),
        "retryable": policy.get("retryable"),
        "requires_operator": _requires_operator(action),
        "next_command": _next_command_for_action(action),
    }
    retry_context = data if isinstance(data, dict) else {}
    retry_after_seconds = _retry_after_seconds(policy, retry_context)
    if retry_after_seconds is not None:
        hint["retry_after_seconds"] = retry_after_seconds
    plan_context = {
        "item_id": data.get("item_id") if isinstance(data, dict) else None,
        "provider": data.get("provider") if isinstance(data, dict) else None,
        "error_code": error_code,
        "normalized_error_code": error_code,
        "requires_operator": hint["requires_operator"],
    }
    operator_block_key = _operator_block_key(plan_context)
    if operator_block_key is not None:
        hint["operator_block_key"] = operator_block_key
    return hint


def _inspection_report(errors: list[str], data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    report_errors = _report_errors(errors)
    return {
        "item_id": _safe_report_path_value(data.get("item_id")),
        "attempt_id": _safe_report_path_value(data.get("attempt_id")),
        "task_id": _safe_report_path_value(data.get("task_id")),
        "provider": _safe_report_path_value(data.get("provider")),
        "status": "failed" if errors else "passed",
        "suggested_error_code": _suggested_error_code(errors, data),
        "failed_attempt_patch": _failed_attempt_patch(report_errors, data),
        "recovery_hint": _recovery_hint(errors, data),
        "errors": report_errors,
    }


def _validate_candidate_ocr(
    index: int, candidate: dict[str, Any], rules: dict[str, Any], errors: list[str]
) -> None:
    if rules.get("require_ocr_evidence") and not _candidate_has_ocr_evidence(candidate):
        errors.append(f"candidate {index} missing OCR evidence")

    ocr_status = candidate.get("ocr_status")
    normalized_status = _normalized_status(ocr_status) if isinstance(ocr_status, str) else None
    if normalized_status is not None and normalized_status not in PASSING_OCR_STATUSES:
        errors.append(f"candidate {index} OCR status is not passing: {ocr_status}")

    ocr_text = candidate.get("ocr_text")
    if isinstance(ocr_text, str):
        if normalized_status in NO_TEXT_OCR_STATUSES and ocr_text.strip():
            errors.append(
                f"candidate {index} OCR status {ocr_status} conflicts with non-empty OCR text"
            )
        if rules.get("reject_any_ocr_text") and ocr_text.strip():
            errors.append(
                f"candidate {index} contains OCR text while reject_any_ocr_text is enabled"
            )
        normalized_text = _normalized_ocr_text(ocr_text)
        for forbidden in _string_list(rules.get("forbidden_ocr_text")):
            normalized_forbidden = _normalized_ocr_text(forbidden)
            if normalized_forbidden and normalized_forbidden in normalized_text:
                errors.append(f"candidate {index} contains forbidden OCR text: {forbidden}")


def _validate_candidate_marks(
    index: int, candidate: dict[str, Any], rules: dict[str, Any], errors: list[str]
) -> None:
    marks = {_normalized_mark(mark) for mark in _string_list(candidate.get("visible_marks"))}
    for forbidden in _string_list(rules.get("forbidden_visible_marks")):
        normalized_forbidden = _normalized_mark(forbidden)
        if normalized_forbidden and normalized_forbidden in marks:
            errors.append(f"candidate {index} contains forbidden visible mark: {forbidden}")


def inspect_attempt_images(
    manifest_path: str | Path, *, required_size: tuple[int, int] | None = None
) -> list[str]:
    path = Path(manifest_path)
    errors = validate_manifest(path)
    if errors:
        return errors

    data = _load_json(path)
    if data is None:
        return ["manifest could not be loaded for image inspection"]

    attempt_root = path.parent.resolve()
    rules = _quality_rules(data)
    seen_hashes: dict[str, int] = {}
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return ["candidates must be a list"]
    if not candidates:
        return ["attempt has no candidate images to inspect"]

    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        candidate_path = candidate.get("path")
        if not isinstance(candidate_path, str):
            continue
        image_path = attempt_root / candidate_path
        try:
            width, height = _image_size(image_path)
        except (OSError, UnidentifiedImageError, RuntimeError) as exc:
            errors.append(f"candidate {index} image could not be decoded: {candidate_path} ({exc})")
            continue

        if required_size is not None and (width, height) != required_size:
            expected_width, expected_height = required_size
            errors.append(
                f"candidate {index} size is {width}x{height} "
                f"but expected {expected_width}x{expected_height}"
            )

        digest = _read_sha256(image_path)
        if digest in seen_hashes:
            errors.append(
                f"candidate {index} duplicates candidate {seen_hashes[digest]} "
                f"by SHA-256: {candidate_path}"
            )
        else:
            seen_hashes[digest] = index

        _validate_candidate_ocr(index, candidate, rules, errors)
        _validate_candidate_marks(index, candidate, rules, errors)

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect downloaded image candidates for an attempt manifest."
    )
    parser.add_argument(
        "--require-size",
        type=_parse_size,
        help="Require each candidate image to be exactly WIDTHxHEIGHT.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write a machine-readable inspection report to stdout.",
    )
    parser.add_argument("manifest", help="Path to attempt manifest JSON")
    args = parser.parse_args(argv)

    errors = inspect_attempt_images(args.manifest, required_size=args.require_size)
    if args.json:
        data = _load_json(Path(args.manifest))
        print(json.dumps(_inspection_report(errors, data), ensure_ascii=False, sort_keys=True))
        return 1 if errors else 0

    if errors:
        for error in _report_errors(errors):
            print(error, file=sys.stderr)
        return 1

    print("attempt images valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
