#!/usr/bin/env python3
"""Validate an auto-image-production attempt manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
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
FAILED_STATUS = "failed"
ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![\w<])/(?:[^\s;:(),]+/?)+")

UNICODE_PATH_SEPARATOR_LOOKALIKES = frozenset(
    (
        "\u2044",  # fraction slash
        "\u2215",  # division slash
        "\u29f8",  # big solidus
        "\uff0f",  # fullwidth solidus
        "\u2216",  # set minus
        "\u29f5",  # reverse solidus operator
        "\u29f9",  # big reverse solidus
        "\ufe68",  # small reverse solidus
        "\uff3c",  # fullwidth reverse solidus
    )
)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_has_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _string_has_unicode_format_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cf" for character in value)


def _string_has_surrogate_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cs" for character in value)


def _string_has_unsafe_display_character(value: str) -> bool:
    return (
        _string_has_control_character(value)
        or _string_has_unicode_format_character(value)
        or _string_has_surrogate_character(value)
    )


def _json_key_has_unsafe_display_character(value: str) -> bool:
    return _string_has_unsafe_display_character(value)


def _identity_has_unsafe_character(value: str, label: str, errors: list[str]) -> bool:
    has_error = False
    if value != value.strip():
        errors.append(f"{label} must not have leading or trailing whitespace")
        has_error = True
    if _string_has_control_character(value):
        errors.append(f"{label} must not contain control characters")
        has_error = True
    if _string_has_unicode_format_character(value):
        errors.append(f"{label} must not contain Unicode format characters")
        has_error = True
    if _string_has_surrogate_character(value):
        errors.append(f"{label} must not contain surrogate characters")
        has_error = True
    return has_error


def _string_references_task(value: str, task_id: str) -> bool:
    task_pattern = re.escape(task_id)
    return (
        re.search(
            rf"(?<![\w-]){task_pattern}(?![\w-]|\.\w)",
            value,
        )
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


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _redact_local_paths(value: str) -> str:
    return ABSOLUTE_PATH_PATTERN.sub("<path>", value)


def _validation_report(errors: list[str], *, require_selected: bool) -> dict[str, Any]:
    report_errors = [_redact_local_paths(error) for error in errors]
    return {
        "valid": not errors,
        "status": "failed" if errors else "passed",
        "error_code": "attempt_manifest_invalid" if errors else None,
        "error_count": len(errors),
        "require_selected": require_selected,
        "errors": report_errors,
    }


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            if _json_key_has_unsafe_display_character(key):
                raise ValueError("duplicate JSON key with unsafe characters")
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


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


def _attempt_collection_is_symlink(manifest_path: Path, errors: list[str]) -> bool:
    manifest_path = Path(os.path.normpath(str(manifest_path)))
    attempt_collection = manifest_path.parent.parent
    if attempt_collection.name not in (".attempts", "attempts"):
        return False

    try:
        is_symlink = attempt_collection.is_symlink()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(
            f"manifest attempt collection directory is invalid: {attempt_collection} ({exc})"
        )
        return True

    if is_symlink:
        errors.append(
            f"manifest attempt collection directory must not be a symlink: {attempt_collection}"
        )
        return True
    return False


def _item_dir_is_symlink(manifest_path: Path, errors: list[str]) -> bool:
    manifest_path = Path(os.path.normpath(str(manifest_path)))
    attempt_collection = manifest_path.parent.parent
    if attempt_collection.name not in (".attempts", "attempts"):
        return False

    item_dir = attempt_collection.parent
    try:
        is_symlink = item_dir.is_symlink()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"manifest item directory is invalid: {item_dir} ({exc})")
        return True

    if is_symlink:
        errors.append(f"manifest item directory must not be a symlink: {item_dir}")
        return True
    return False


def _resolve_attempt_path(attempt_root: Path, relative_path: str, label: str, errors: list[str]) -> Path | None:
    try:
        resolved = (attempt_root / relative_path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} is invalid: {relative_path} ({exc})")
        return None
    return resolved


def _attempt_path_segments(relative_path: str) -> list[str]:
    return [segment for segment in re.split(r"[\\/]+", relative_path) if segment]


def _attempt_path_has_parent_reference(relative_path: str, label: str, errors: list[str]) -> bool:
    if ".." in _attempt_path_segments(relative_path):
        errors.append(f"{label} must not contain parent directory references: {relative_path}")
        return True
    return False


def _attempt_path_has_trailing_separator(relative_path: str, label: str, errors: list[str]) -> bool:
    if relative_path.endswith(("/", "\\")):
        errors.append(f"{label} must not end with a path separator: {relative_path}")
        return True
    return False


def _attempt_path_has_current_directory_reference(
    relative_path: str, label: str, errors: list[str]
) -> bool:
    segments = _attempt_path_segments(relative_path)
    if "." in segments:
        errors.append(f"{label} must not contain current directory references: {relative_path}")
        return True
    return False


def _attempt_path_has_repeated_separator(relative_path: str, label: str, errors: list[str]) -> bool:
    if "//" in relative_path:
        errors.append(f"{label} must not contain repeated path separators: {relative_path}")
        return True
    return False


def _attempt_path_has_control_character(relative_path: str, label: str, errors: list[str]) -> bool:
    if _string_has_control_character(relative_path):
        errors.append(f"{label} must not contain control characters")
        return True
    return False


def _attempt_path_has_unicode_format_character(
    relative_path: str, label: str, errors: list[str]
) -> bool:
    if _string_has_unicode_format_character(relative_path):
        errors.append(f"{label} must not contain Unicode format characters")
        return True
    return False


def _attempt_path_has_surrogate_character(relative_path: str, label: str, errors: list[str]) -> bool:
    if _string_has_surrogate_character(relative_path):
        errors.append(f"{label} must not contain surrogate characters")
        return True
    return False


def _attempt_path_has_unicode_separator_lookalike(
    relative_path: str, label: str, errors: list[str]
) -> bool:
    if any(character in UNICODE_PATH_SEPARATOR_LOOKALIKES for character in relative_path):
        errors.append(f"{label} must not contain Unicode path separator lookalikes")
        return True
    return False


def _attempt_path_has_backslash(relative_path: str, label: str, errors: list[str]) -> bool:
    if "\\" in relative_path:
        errors.append(f"{label} must use forward slashes: {relative_path}")
        return True
    return False


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
        data = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
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
    except ValueError as exc:
        if str(exc).startswith("duplicate JSON key: "):
            errors.append(f"manifest contains {exc}")
        elif str(exc) == "duplicate JSON key with unsafe characters":
            errors.append(f"manifest contains {exc}")
        else:
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
    manifest_path_text = str(path)
    if _string_has_control_character(manifest_path_text):
        errors.append("manifest path must not contain control characters")
        return errors
    if _string_has_unicode_format_character(manifest_path_text):
        errors.append("manifest path must not contain Unicode format characters")
        return errors
    if _string_has_surrogate_character(manifest_path_text):
        errors.append("manifest path must not contain surrogate characters")
        return errors

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

    if _attempt_collection_is_symlink(path, errors):
        return errors

    if _item_dir_is_symlink(path, errors):
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

    unsafe_identity_fields: set[str] = set()
    for field in ("item_id", "attempt_id", "task_id", "provider"):
        value = data.get(field)
        if isinstance(value, str):
            if _identity_has_unsafe_character(value, field, errors):
                unsafe_identity_fields.add(field)

    status = data.get("status")
    is_failed_attempt = status == FAILED_STATUS
    if status is not None:
        if not _is_non_empty_string(status):
            errors.append("status must be a non-empty string when present")
        elif _identity_has_unsafe_character(status, "status", errors):
            pass

    if is_failed_attempt:
        for field in ("error_code", "error_detail"):
            value = data.get(field)
            if not _is_non_empty_string(value):
                errors.append(f"failed attempts require non-empty {field}")
            elif _identity_has_unsafe_character(value, field, errors):
                pass

    retry_count = data.get("retry_count")
    if retry_count is not None and (
        not isinstance(retry_count, int) or isinstance(retry_count, bool) or retry_count < 0
    ):
        errors.append("retry_count must be a non-negative integer when present")

    attempt_id = data.get("attempt_id")
    if (
        "attempt_id" not in unsafe_identity_fields
        and _is_non_empty_string(attempt_id)
        and attempt_id != attempt_root.name
    ):
        errors.append(f"attempt_id {attempt_id} does not match attempt directory {attempt_root.name}")

    item_id = data.get("item_id")
    item_dir = _item_dir_name(normalized_manifest_path)
    if (
        "item_id" not in unsafe_identity_fields
        and item_dir
        and _is_non_empty_string(item_id)
        and item_id != item_dir
    ):
        errors.append(f"item_id {item_id} does not match item directory {item_dir}")

    task_id = data.get("task_id")
    if not _is_non_empty_string(task_id):
        errors.append("task_id must be a non-empty string")
        task_id = ""

    candidate_count = data.get("candidate_count")
    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count < 0
        or (candidate_count == 0 and not is_failed_attempt)
    ):
        errors.append("candidate_count must be a positive integer unless status is failed")
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
    if "result_binding" in data and task_id and "task_id" not in unsafe_identity_fields:
        try:
            binding_references_task = _binding_references_task(result_binding, task_id)
        except RecursionError as exc:
            errors.append(f"result_binding is too deeply nested: {exc}")
        else:
            if not binding_references_task:
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
            elif _identity_has_unsafe_character(
                candidate_task_id, f"candidate {index} task_id", errors
            ):
                pass
            elif candidate_task_id != task_id:
                errors.append(f"candidate {index} task_id does not match manifest task_id")

        candidate_path = candidate.get("path")
        if not _is_non_empty_string(candidate_path):
            errors.append(f"candidate {index} missing path")
            continue

        if _attempt_path_has_control_character(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_unicode_format_character(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_surrogate_character(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_unicode_separator_lookalike(
            candidate_path, "candidate path", errors
        ):
            continue
        resolved = Path(candidate_path)
        if resolved.is_absolute():
            errors.append(f"candidate path must be relative: {candidate_path}")
            continue
        if _attempt_path_has_trailing_separator(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_current_directory_reference(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_parent_reference(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_repeated_separator(candidate_path, "candidate path", errors):
            continue
        if _attempt_path_has_backslash(candidate_path, "candidate path", errors):
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
            if _attempt_path_has_control_character(selected_path, "selected_path", errors):
                pass
            elif _attempt_path_has_unicode_format_character(
                selected_path, "selected_path", errors
            ):
                pass
            elif _attempt_path_has_surrogate_character(selected_path, "selected_path", errors):
                pass
            elif _attempt_path_has_unicode_separator_lookalike(
                selected_path, "selected_path", errors
            ):
                pass
            else:
                resolved_selected = Path(selected_path)
                if resolved_selected.is_absolute():
                    errors.append(f"selected_path must be relative: {selected_path}")
                elif _attempt_path_has_trailing_separator(selected_path, "selected_path", errors):
                    pass
                elif _attempt_path_has_current_directory_reference(
                    selected_path, "selected_path", errors
                ):
                    pass
                elif _attempt_path_has_parent_reference(selected_path, "selected_path", errors):
                    pass
                elif _attempt_path_has_repeated_separator(selected_path, "selected_path", errors):
                    pass
                elif _attempt_path_has_backslash(selected_path, "selected_path", errors):
                    pass
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write a machine-readable validation report to stdout.",
    )
    parser.add_argument("manifest", help="Path to attempt manifest JSON")
    args = parser.parse_args(argv)

    errors = validate_manifest(args.manifest, require_selected=args.require_selected)
    if args.json:
        print(
            json.dumps(
                _validation_report(errors, require_selected=args.require_selected),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1 if errors else 0

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("attempt manifest valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
