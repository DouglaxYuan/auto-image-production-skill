#!/usr/bin/env python3
"""Plan the next automation action for an image-production attempt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_attempt import validate_manifest  # noqa: E402


MAX_RETRY_AFTER_SECONDS = 3600


POLICIES: dict[str, dict[str, Any]] = {
    "captcha_required": {
        "action": "needs_human",
        "failure_category": "human_intervention",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "interactive provider verification is required",
    },
    "browser_session_not_authenticated": {
        "action": "needs_human",
        "failure_category": "human_intervention",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "provider browser session is not logged in",
    },
    "login_required": {
        "action": "needs_human",
        "failure_category": "human_intervention",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "provider requires an authenticated browser session",
    },
    "concurrency_limited": {
        "action": "backoff",
        "failure_category": "capacity",
        "retryable": True,
        "retry_after_seconds": 300,
        "reason": "provider concurrency limit or model queue pressure",
    },
    "rate_limited": {
        "action": "backoff",
        "failure_category": "capacity",
        "retryable": True,
        "retry_after_seconds": 300,
        "reason": "provider rate limit or HTTP 429 backpressure",
    },
    "provider_busy": {
        "action": "backoff",
        "failure_category": "capacity",
        "retryable": True,
        "retry_after_seconds": 300,
        "reason": "provider is busy or temporarily overloaded",
    },
    "quota_exhausted": {
        "action": "backoff",
        "failure_category": "capacity",
        "retryable": True,
        "retry_after_seconds": 3600,
        "reason": "provider quota is exhausted or temporarily unavailable",
    },
    "network_error": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "transient network error",
    },
    "page_load_failed": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "provider page load or navigation failed",
    },
    "browser_crashed": {
        "action": "retry",
        "failure_category": "provider_runtime",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "browser process or page crashed",
    },
    "selector_not_found": {
        "action": "review_failure",
        "failure_category": "automation_contract",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "provider UI selector was not found or changed",
    },
    "generation_timeout": {
        "action": "retry",
        "failure_category": "provider_runtime",
        "retryable": True,
        "retry_after_seconds": 120,
        "reason": "provider did not return candidates before timeout",
    },
    "no_candidates_found": {
        "action": "retry",
        "failure_category": "provider_runtime",
        "retryable": True,
        "retry_after_seconds": 120,
        "reason": "provider returned no usable image candidates",
    },
    "upload_not_ready": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 30,
        "reason": "source upload was not accepted before submit",
    },
    "upload_failed": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "source upload failed before prompt submission",
    },
    "send_failed": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "prompt submission failed",
    },
    "download_failed": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "candidate download failed",
    },
    "download_timeout": {
        "action": "retry",
        "failure_category": "network",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "candidate download timed out",
    },
    "result_binding_failed": {
        "action": "retry_with_new_task",
        "failure_category": "result_integrity",
        "retryable": True,
        "retry_after_seconds": 60,
        "reason": "provider returned output but it was not bound to the task id",
    },
    "moderation_blocked": {
        "action": "quarantine",
        "failure_category": "compliance",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "provider or project moderation blocked this item",
    },
    "candidate_validation_failed": {
        "action": "reroute_or_skip",
        "failure_category": "quality_gate",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "downloaded candidates failed local quality gates",
    },
    "forbidden_ocr_text": {
        "action": "reroute_or_skip",
        "failure_category": "quality_gate",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "candidate contains forbidden OCR text",
    },
    "missing_ocr_evidence": {
        "action": "reroute_or_skip",
        "failure_category": "quality_gate",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "candidate is missing required OCR evidence",
    },
    "forbidden_visible_mark": {
        "action": "reroute_provider",
        "failure_category": "quality_gate",
        "retryable": False,
        "retry_after_seconds": None,
        "reason": "candidate contains a forbidden visible mark",
    },
}


def _load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--max-retries must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("--max-retries must be a positive integer")
    return parsed


def _base_plan(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": data.get("item_id"),
        "attempt_id": data.get("attempt_id"),
        "task_id": data.get("task_id"),
        "status": data.get("status", "candidate_available"),
        "error_code": data.get("error_code"),
        "retry_count": data.get("retry_count", 0),
    }


def _retry_budget_exhausted(data: dict[str, Any], max_retries: int) -> bool:
    retry_count = data.get("retry_count", 0)
    return isinstance(retry_count, int) and not isinstance(retry_count, bool) and retry_count >= max_retries


def _remaining_retries(data: dict[str, Any], max_retries: int) -> int:
    retry_count = data.get("retry_count", 0)
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        return 0
    return max(max_retries - retry_count, 0)


def _next_retry_count(data: dict[str, Any]) -> int:
    retry_count = data.get("retry_count", 0)
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        return 1
    return retry_count + 1


def _normalized_error_code(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return "_".join(value.replace("-", " ").split()).casefold()


def _retry_after_seconds(policy: dict[str, Any], data: dict[str, Any]) -> Any:
    retry_after = policy.get("retry_after_seconds")
    retry_count = data.get("retry_count", 0)
    if not isinstance(retry_after, int) or isinstance(retry_after, bool):
        return retry_after
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        return retry_after
    return min(retry_after * (2**retry_count), MAX_RETRY_AFTER_SECONDS)


def _next_command_for_action(action: Any) -> str:
    if action == "needs_human":
        return "request human intervention"
    if action in ("retry", "retry_with_new_task", "backoff"):
        return "schedule retry after retry_after_seconds"
    if action in ("reroute_provider", "reroute_or_skip"):
        return "route to approved alternate provider or skip"
    if action == "quarantine":
        return "quarantine item and record operator decision"
    return "inspect the failed attempt manifest"


def _requires_operator(action: Any) -> bool:
    return action in {"needs_human", "quarantine", "review_failure"}


def plan_attempt_recovery(
    manifest_path: str | Path, *, max_retries: int = 3
) -> tuple[dict[str, Any] | None, list[str]]:
    path = Path(manifest_path)
    errors = validate_manifest(path)
    if errors:
        return None, errors

    data = _load_manifest(path)
    plan = _base_plan(data)
    if data.get("status") == "failed":
        error_code = data.get("error_code")
        normalized_error_code = _normalized_error_code(error_code)
        plan["normalized_error_code"] = normalized_error_code
        policy = POLICIES.get(normalized_error_code)
        if policy is None:
            plan.update(
                {
                    "action": "review_failure",
                    "failure_category": "unknown",
                    "retryable": False,
                    "retry_after_seconds": None,
                    "requires_operator": True,
                    "reason": "unrecognized provider failure code",
                    "next_command": "inspect the failed attempt manifest",
                }
            )
        else:
            plan.update(policy)
            plan["next_command"] = _next_command_for_action(plan.get("action"))
            plan["requires_operator"] = _requires_operator(plan.get("action"))
            if policy.get("retryable"):
                remaining_retries = _remaining_retries(data, max_retries)
                plan["max_retries"] = max_retries
                plan["remaining_retries"] = remaining_retries
                if remaining_retries > 0:
                    plan["next_retry_count"] = _next_retry_count(data)
                plan["retry_after_seconds"] = _retry_after_seconds(policy, data)
            if policy.get("retryable") and _retry_budget_exhausted(data, max_retries):
                plan.update(
                    {
                        "action": "review_failure",
                        "retryable": False,
                        "retry_after_seconds": None,
                        "requires_operator": True,
                        "reason": "retry budget exhausted",
                        "next_command": "review failed attempt before retrying",
                    }
                )
        return plan, []

    plan.update(
        {
            "action": "inspect_images",
            "retryable": False,
            "retry_after_seconds": None,
            "requires_operator": False,
            "reason": "attempt has candidate files that need local quality inspection",
            "next_command": "python scripts/inspect_attempt_images.py",
        }
    )
    return plan, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan recovery or next validation action for an attempt manifest."
    )
    parser.add_argument(
        "--max-retries",
        type=_positive_int,
        default=3,
        help="Maximum retry_count allowed before escalating retryable failures.",
    )
    parser.add_argument("manifest", help="Path to attempt manifest JSON")
    args = parser.parse_args(argv)

    try:
        plan, errors = plan_attempt_recovery(args.manifest, max_retries=args.max_retries)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors = [f"manifest could not be loaded for recovery planning: {exc}"]
        plan = None

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
