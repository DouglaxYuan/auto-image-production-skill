# Prompt and Output Contract

Use this contract for automated image-production workflows.

## Required User-Supplied Fields

- `item_id`: stable id for one unit of work.
- `source_assets`: input image(s), template/border/mask/reference files, or source table rows.
- `prompt`: exact generation prompt or a template with variables.
- `generation_rules`: visual and workflow rules the model must follow.
- `provider`: browser image tool or API image model.
- `candidate_count`: expected number of candidates.
- `result_binding`: string or JSON-like metadata containing the task id, provider id, DOM/message-region rule, or API response field proving candidates belong to this attempt.
- `validation_rules`: checks required before accepting candidates.
- `selection_criteria`: how to choose the final image.
- `commit_target`: final output path, filename pattern, manifest/registry destination.
- `quality_rules`: optional local gates for downloaded files, such as required OCR evidence, reject-any-text OCR policy, forbidden OCR text, or forbidden visible marks recorded by the provider adapter/OCR step.
- `status`, `error_code`, and `error_detail`: required in an attempt manifest when the provider fails before usable candidates are downloaded.
- `retry_count`: optional non-negative integer for retryable failed attempts.

## Default Attempt Layout

For each `item_id` and `attempt_id`:

```text
ITEM/
  .attempts/
    ATTEMPT_ID/        # staging, disposable if failed
  attempts/
    ATTEMPT_ID/        # immutable successful publication
  current -> attempts/ATTEMPT_ID
```

The finished image can then be copied or exported to the requested target path, for example:

```text
TARGET_DIR/ITEM__selected.png
TARGET_DIR/manifest.json
```

## Prompt Requirements

Every prompt must include:

- The unique `TASK-ID`.
- The requested output count.
- The expected final dimensions or aspect ratio.
- Forbidden content: project-specific prohibited text, marks, or unrelated text.
- Preservation rules for the source subject.
- Style, background, border/template, lighting, composition, and crop requirements.
- A request to echo the `TASK-ID` in the response when the provider supports text.

The prompt's `TASK-ID` must match the `result_binding` rule recorded for the attempt.

## Attempt Manifest Validation

When an attempt writes a JSON manifest, validate the local bookkeeping before publishing:

```bash
python scripts/validate_attempt.py ITEM/.attempts/ATTEMPT_ID/attempt.json
python scripts/plan_attempt_recovery.py --max-retries 3 ITEM/.attempts/ATTEMPT_ID/attempt.json
python scripts/validate_attempt.py --require-selected ITEM/.attempts/ATTEMPT_ID/attempt.json
python scripts/inspect_attempt_images.py --require-size 2048x2048 ITEM/.attempts/ATTEMPT_ID/attempt.json
```

The validator checks manifest path/read errors, symlinked manifest files, attempt collection directories, and attempt directories, invalid JSON/UTF-8/deep nesting, required fields, non-empty core identity fields, display-safe identity fields with no leading/trailing whitespace, control characters, Unicode format characters, or surrogate characters, `item_id` consistency with `ITEM/.attempts/ATTEMPT_ID/` or `ITEM/attempts/ATTEMPT_ID/` layouts, `attempt_id` consistency with the attempt directory name, `candidate_count`, failed zero-candidate attempts with required `error_code` and `error_detail`, `result_binding` task-id references in nested metadata keys or values, overly deep `result_binding` metadata, invalid or non-relative candidate file paths, parent-directory references, canonical forward-slash artifact path formatting with no control characters, Unicode format characters, surrogate characters, or Unicode path separator lookalikes, artifact symlinks, symlinked artifact directories, candidate path containment inside the attempt directory, duplicate candidate paths, candidate task ids, and normalized relative `selected_path` validity and membership. Use `--require-selected` for publish-time checks that must fail until the selected candidate is recorded. It does not replace image decoding, OCR, perceptual hashing, or project-specific quality checks.

The image inspector checks downloaded candidate files after manifest validation. It fails when an attempt has no candidate images to inspect. It decodes images with Pillow, optionally enforces exact dimensions, rejects duplicate candidate bytes by SHA-256, and enforces recorded OCR/visible-mark evidence. Use `quality_rules.require_ocr_evidence`, `quality_rules.reject_any_ocr_text`, `quality_rules.forbidden_ocr_text`, and `quality_rules.forbidden_visible_marks` with candidate fields such as `ocr_status`, `ocr_text`, and `visible_marks`. OCR status checks normalize whitespace or hyphen separators and match case-insensitively, and forbidden-text checks collapse whitespace before matching case-insensitively, but statuses that claim no text must not be paired with non-empty `ocr_text`. Visible-mark checks collapse whitespace and match case-insensitively so provider mark variants do not bypass rejection. Blank forbidden text or visible-mark entries are ignored after normalization.

For provider interruptions such as CAPTCHA, quota, network errors, or concurrency limits, write a failed attempt instead of abandoning local state:

```json
{
  "item_id": "ASSET-0001",
  "attempt_id": "A-0001-002",
  "task_id": "ASSET-0001-A002",
  "provider": "browser image tool",
  "status": "failed",
  "error_code": "captcha_required",
  "error_detail": "Provider requested interactive verification before returning candidates.",
  "candidate_count": 0,
  "result_binding": "TASK-ID ASSET-0001-A002 submitted before provider verification",
  "candidates": []
}
```

Then run `plan_attempt_recovery.py` to classify the next action. It should route
interactive verification and logged-out sessions to `needs_human`, transient
network and timeout failures to `retry`, model concurrency pressure to
`backoff`, and quality/provider mark failures to reroute or quarantine actions.
The planner normalizes error-code whitespace or hyphen separators for policy
lookup while preserving the original `error_code` in the returned plan.
For retryable failures, increment a numeric `retry_count`; when it reaches
`--max-retries`, the planner returns `review_failure` instead of another retry.
`--max-retries` must be a positive integer. Retryable plans include
`max_retries`, `remaining_retries`, `next_retry_count`, and a
`retry_after_seconds` delay that grows with `retry_count` and caps at one hour.
`failure_category` groups failures for logging and alert routing.
`requires_operator` marks plans that must leave the automation loop for a human
decision. `next_command` is action-specific so a scheduler can tell human
intervention apart from retry and reroute actions.

## Result Validation

Accept a candidate only after:

- It is bound to the current `TASK-ID` or provider task id.
- It is downloaded and decodes successfully.
- It matches size/aspect/format rules.
- It passes OCR or visual text checks.
- It passes duplicate/hash checks.
- It does not contain forbidden visible marks. Treat provider/source marks as reject/reroute evidence rather than removing provenance marks in post-processing.
- It passes any project-specific quality checks.

## Selection

Selection criteria must be explicit. Examples:

- Best subject completeness and least distortion.
- Cleanest background.
- Best border/template alignment.
- No visible prohibited text, marks, or artifacts.
- Closest match to source color/shape.
- Best fit for the requested final use.

Record the selected candidate and the reason before publishing.
