# Neutral Asset Example

This is a generic example for automated image production. Replace every placeholder with local project values before running live generation.

## Example Inputs

- `item_id`: `ASSET-0001`
- `source_assets`: input image, template image, source metadata row
- `prompt`: create a clean final image that follows the visual rules
- `generation_rules`: preserve the main subject, apply the template, keep the background clean, avoid prohibited text or marks
- `provider`: browser-based image tool or API image model
- `candidate_count`: `3`
- `validation_rules`: final selected image must match the required dimensions, decode successfully, pass OCR/text checks, and pass duplicate hash checks
- `selection_criteria`: best subject completeness, cleanest background, least distortion, no visible prohibited text
- `commit_target`: selected-image folder plus `manifest.json`

## Example Reconcile Status

A real project should reconcile a batch into explicit buckets before generating:

- `complete`: items with a verified selected image
- `skipped_source_blocked`: source assets that match configured blocking rules
- `missing`: source assets or rows not found
- `pending`: eligible, source-complete items that still need generation
- `failed`: attempts that were submitted but did not produce a valid committed image

Do not submit anything in `complete`, `skipped_source_blocked`, or `missing` without an explicit human decision.

## Example Provider Failure Types

- `captcha_required`
- `browser_session_not_authenticated`
- `login_required`
- `concurrency_limited`
- `rate_limited`
- `provider_busy`
- `network_error`
- `page_load_failed`
- `browser_crashed`
- `selector_not_found`
- `moderation_blocked`
- `quota_exhausted`
- `upload_not_ready`
- `upload_failed`
- `send_failed`
- `download_failed`
- `download_timeout`
- `generation_timeout`
- `no_candidates_found`
- `result_binding_failed`
- `candidate_validation_failed`
- `forbidden_ocr_text`
- `missing_ocr_evidence`
- `ocr_text_detected`
- `forbidden_visible_mark`

Store failure type and detail on the attempt so a later agent can decide whether to resume, retry, or quarantine.
