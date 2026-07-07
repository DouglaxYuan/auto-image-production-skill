#!/usr/bin/env python3
"""Validate an auto-image-production attempt manifest."""

from __future__ import annotations

import argparse
import json
import re
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


def _string_references_task(value: str, task_id: str) -> bool:
    task_pattern = re.escape(task_id)
    return (
        re.search(rf"(?<![A-Za-z0-9_-]){task_pattern}(?![A-Za-z0-9_-])", value)
        is not None
    )


def _binding_references_task(binding: Any, task_id: str) -> bool:
    if isinstance(binding, str):
        return _string_references_task(binding, task_id)
    if isinstance(binding, dict):
        return any(
            _binding_references_task(key, task_id)
            or _binding_references_task(value, task_id)
            for key, value in binding.items()
        )
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
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} is invalid: {relative_path} ({exc})")
        return None
    return resolved


def _attempt_path_is_symlink(
    attempt_root: Path, relative_path: str, label: str, errors: list[str]
) -> bool:
    try:
        is_symlink = (attempt_root / relative_path).is_symlink()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} is invalid: {relative_path} ({exc})")
        return True

    if is_symlink:
        errors.append(f"{label} must not be a symlink: {relative_path}")
        return True
    return False


def _attempt_path_has_symlinked_directory(
    attempt_root: Path, relative_path: str, label: str, errors: list[str]
) -> bool:
    current_path = attempt_root
    try:
        for part in Path(relative_path).parts[:-1]:
            current_path = current_path / part
            if current_path.is_symlink():
                errors.append(f"{label} must not contain symlinked directories: {relative_path}")
                return True
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} is invalid: {relative_path} ({exc})")
        return True
    return False


def _load_manifest(manifest_path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        manifest_path.resolve(strict=True)
    except FileNotFoundError:
        errors.append(f"manifest does not exist: {manifest_path}")
        return None
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"manifest path is invalid: {manifest_path} ({exc})")
        return None

    if manifest_path.is_symlink():
        errors.append(f"manifest path must not be a symlink: {manifest_path}")
        return None

    if not manifest_path.is_file():
        errors.append(f"manifest path is not a file: {manifest_path}")
        return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"manifest could not be read: {exc}")
        return None
    except UnicodeDecodeError as exc:
        errors.append(f"manifest is not valid UTF-8 text: {exc}")
        return None
    except RecursionError as exc:
        errors.append(f"manifest is too deeply nested: {exc}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"manifest is not valid JSON: {exc}")
        return None

    if not isinstance(data, dict):
        errors.append("manifest root must be a JSON object")
        return None
    return data


def validate_manifest(manifest_path: str | Path, *, require_selected: bool = False) -> list[str]:
    """Return validation errors for an attempt manifest."""
    path = Path(manifest_path)
    errors: list[str] = []
    try:
        attempt_root = path.parent.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"manifest parent directory is invalid: {path.parent} ({exc})")
        return errors

    try:
        parent_is_symlink = path.parent.is_symlink()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"manifest parent directory is invalid: {path.parent} ({exc})")
        return errors

    if parent_is_symlink:
        errors.append(f"manifest parent directory must not be a symlink: {path.parent}")
        return errors

    data = _load_manifest(path, errors)
    if data is None:
        return errors
    normalized_manifest_path = attempt_root / path.name

    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing required field: {field}")

    for field in ("item_id", "attempt_id", "provider"):
        if field in data and not _is_non_empty_string(data.get(field)):
            errors.append(f"{field} must be a non-empty string")

    attempt_id = data.get("attempt_id")
    if _is_non_empty_string(attempt_id) and attempt_id != attempt_root.name:
        errors.append(f"attempt_id {attempt_id} does not match attempt directory {attempt_root.name}")

    item_id = data.get("item_id")
    item_dir = _item_dir_name(normalized_manifest_path)
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

        candidate_task_id = candidate.get("task_id")
        if candidate_task_id is not None:
            if not _is_non_empty_string(candidate_task_id):
                errors.append(f"candidate {index} task_id must be a non-empty string when present")
            elif candidate_task_id != task_id:
                errors.append(f"candidate {index} task_id does not match manifest task_id")

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
        if _attempt_path_is_symlink(attempt_root, candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_symlinked_directory(
            attempt_root, candidate_path, "candidate path", errors
        ):
            continue
        if not _is_relative_to(resolved, attempt_root):
            errors.append(f"candidate path escapes attempt directory: {candidate_path}")
            continue
        if resolved in resolved_candidate_paths:
            errors.append(f"duplicate candidate path: {candidate_path}")
            continue
        resolved_candidate_paths.add(resolved)
        if not resolved.exists():
            errors.append(f"candidate path does not exist: {candidate_path}")
        elif not resolved.is_file():
            errors.append(f"candidate path is not a file: {candidate_path}")

    selected_path = data.get("selected_path")
    if selected_path is None:
        if require_selected:
            errors.append("selected_path is required when --require-selected is used")
    else:
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
                    if _attempt_path_is_symlink(
                        attempt_root, selected_path, "selected_path", errors
                    ):
                        pass
                    elif _attempt_path_has_symlinked_directory(
                        attempt_root, selected_path, "selected_path", errors
                    ):
                        pass
                    elif not _is_relative_to(resolved_selected, attempt_root):
                        errors.append(f"selected_path escapes attempt directory: {selected_path}")
                    else:
                        if not resolved_selected.exists():
                            errors.append(f"selected_path does not exist: {selected_path}")
                        elif not resolved_selected.is_file():
                            errors.append(f"selected_path is not a file: {selected_path}")
                        if resolved_selected not in resolved_candidate_paths:
                            errors.append(f"selected_path is not listed in candidates: {selected_path}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an auto-image-production attempt manifest.")
    parser.add_argument(
        "--require-selected",
        action="store_true",
        help="Require selected_path for publish-time validation.",
    )
    parser.add_argument("manifest", help="Path to attempt manifest JSON")
    args = parser.parse_args(argv)

    errors = validate_manifest(args.manifest, require_selected=args.require_selected)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("attempt manifest valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
