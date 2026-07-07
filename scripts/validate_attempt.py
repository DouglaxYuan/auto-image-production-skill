#!/usr/bin/env python3
"""Validate an auto-image-production attempt manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "item_id",
    "attempt_id",
    "task_id",
    "provider",
    "candidate_count",
    "result_binding",
    "candidates",
)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _binding_references_task(binding: Any, task_id: str) -> bool:
    if isinstance(binding, str):
        return task_id in binding
    if isinstance(binding, dict):
        return any(_binding_references_task(value, task_id) for value in binding.values())
    if isinstance(binding, list):
        return any(_binding_references_task(value, task_id) for value in binding)
    return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _item_dir_name(manifest_path: Path) -> str | None:
    attempt_parent = manifest_path.parent.parent
    if attempt_parent.name not in (".attempts", "attempts"):
        return None
    return attempt_parent.parent.name


def _resolve_attempt_path(attempt_root: Path, relative_path: str, label: str, errors: list[str]) -> Path | None:
    try:
        resolved = (attempt_root / relative_path).resolve()
    except (OSError, ValueError) as exc:
        errors.append(f"{label} is invalid: {relative_path} ({exc})")
        return None
    return resolved


def _load_manifest(manifest_path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not manifest_path.exists():
        errors.append(f"manifest does not exist: {manifest_path}")
        return None
    if not manifest_path.is_file():
        errors.append(f"manifest path is not a file: {manifest_path}")
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        errors.append(f"manifest is not valid UTF-8 text: {exc}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"manifest is not valid JSON: {exc}")
        return None

    if not isinstance(data, dict):
        errors.append("manifest root must be a JSON object")
        return None
    return data


def validate_manifest(manifest_path: str | Path) -> list[str]:
    """Return validation errors for an attempt manifest."""
    path = Path(manifest_path)
    attempt_root = path.parent.resolve()
    errors: list[str] = []
    data = _load_manifest(path, errors)
    if data is None:
        return errors

    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required field: {field}")

    for field in ("item_id", "attempt_id", "provider"):
        if field in data and not _is_non_empty_string(data.get(field)):
            errors.append(f"{field} must be a non-empty string")

    attempt_id = data.get("attempt_id")
    if _is_non_empty_string(attempt_id) and attempt_id != path.parent.name:
        errors.append(f"attempt_id {attempt_id} does not match attempt directory {path.parent.name}")

    item_id = data.get("item_id")
    item_dir = _item_dir_name(path)
    if item_dir and _is_non_empty_string(item_id) and item_id != item_dir:
        errors.append(f"item_id {item_id} does not match item directory {item_dir}")

    task_id = data.get("task_id")
    if not _is_non_empty_string(task_id):
        errors.append("task_id must be a non-empty string")
        task_id = ""

    candidate_count = data.get("candidate_count")
    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool) or candidate_count < 1:
        errors.append("candidate_count must be a positive integer")
        candidate_count = None

    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be a list")
        candidates = []

    if candidate_count is not None and candidate_count != len(candidates):
        errors.append(
            f"candidate_count is {candidate_count} but candidates has {len(candidates)} entries"
        )

    result_binding = data.get("result_binding")
    if "result_binding" in data and task_id and not _binding_references_task(result_binding, task_id):
        errors.append(f"result_binding does not reference task_id: {task_id}")

    resolved_candidate_paths: set[Path] = set()
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            errors.append(f"candidate {index} must be an object")
            continue

        candidate_path = candidate.get("path")
        if not _is_non_empty_string(candidate_path):
            errors.append(f"candidate {index} missing path")
            continue

        resolved = Path(candidate_path)
        if resolved.is_absolute():
            errors.append(f"candidate path must be relative: {candidate_path}")
            continue
        resolved = _resolve_attempt_path(attempt_root, candidate_path, "candidate path", errors)
        if resolved is None:
            continue
        if not _is_relative_to(resolved, attempt_root):
            errors.append(f"candidate path escapes attempt directory: {candidate_path}")
            continue
        if resolved in resolved_candidate_paths:
            errors.append(f"duplicate candidate path: {candidate_path}")
            continue
        resolved_candidate_paths.add(resolved)
        if not resolved.is_file():
            errors.append(f"candidate path does not exist: {candidate_path}")

        candidate_task_id = candidate.get("task_id")
        if candidate_task_id is not None and candidate_task_id != task_id:
            errors.append(f"candidate {index} task_id does not match manifest task_id")

    selected_path = data.get("selected_path")
    if selected_path is not None:
        if not _is_non_empty_string(selected_path):
            errors.append("selected_path must be a non-empty string when present")
        else:
            resolved_selected = Path(selected_path)
            if resolved_selected.is_absolute():
                errors.append(f"selected_path must be relative: {selected_path}")
            else:
                resolved_selected = _resolve_attempt_path(
                    attempt_root, selected_path, "selected_path", errors
                )
                if resolved_selected is not None:
                    if not _is_relative_to(resolved_selected, attempt_root):
                        errors.append(f"selected_path escapes attempt directory: {selected_path}")
                    elif resolved_selected not in resolved_candidate_paths:
                        errors.append(f"selected_path is not listed in candidates: {selected_path}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an auto-image-production attempt manifest.")
    parser.add_argument("manifest", help="Path to attempt manifest JSON")
    args = parser.parse_args(argv)

    errors = validate_manifest(args.manifest)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("attempt manifest valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
