#!/usr/bin/env python3
"""Inspect downloaded image candidates for an auto-image-production attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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

from scripts.validate_attempt import validate_manifest  # noqa: E402


PASSING_OCR_STATUSES = frozenset(("passed", "no_text", "text_absent", "clear"))


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
    return value.strip().casefold()


def _candidate_has_ocr_evidence(candidate: dict[str, Any]) -> bool:
    return isinstance(candidate.get("ocr_status"), str) or isinstance(candidate.get("ocr_text"), str)


def _validate_candidate_ocr(
    index: int, candidate: dict[str, Any], rules: dict[str, Any], errors: list[str]
) -> None:
    if rules.get("require_ocr_evidence") and not _candidate_has_ocr_evidence(candidate):
        errors.append(f"candidate {index} missing OCR evidence")

    ocr_status = candidate.get("ocr_status")
    if isinstance(ocr_status, str) and ocr_status not in PASSING_OCR_STATUSES:
        errors.append(f"candidate {index} OCR status is not passing: {ocr_status}")

    ocr_text = candidate.get("ocr_text")
    if isinstance(ocr_text, str):
        if rules.get("reject_any_ocr_text") and ocr_text.strip():
            errors.append(
                f"candidate {index} contains OCR text while reject_any_ocr_text is enabled"
            )
        normalized_text = ocr_text.casefold()
        for forbidden in _string_list(rules.get("forbidden_ocr_text")):
            if forbidden.casefold() in normalized_text:
                errors.append(f"candidate {index} contains forbidden OCR text: {forbidden}")


def _validate_candidate_marks(
    index: int, candidate: dict[str, Any], rules: dict[str, Any], errors: list[str]
) -> None:
    marks = {_normalized_mark(mark) for mark in _string_list(candidate.get("visible_marks"))}
    for forbidden in _string_list(rules.get("forbidden_visible_marks")):
        if _normalized_mark(forbidden) in marks:
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
    parser.add_argument("manifest", help="Path to attempt manifest JSON")
    args = parser.parse_args(argv)

    errors = inspect_attempt_images(args.manifest, required_size=args.require_size)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("attempt images valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
