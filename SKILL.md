---
name: auto-image-production
description: Safely run, resume, audit, or maintain an automated image-production pipeline using user-provided output rules, prompts, source assets/items, a third-party image model, validation criteria, selection criteria, target finished-image paths, atomic attempt commits, registry export, source blocking rules, batches, or migration from old flat image artifacts.
---

# Auto Image Production

## Core Rule

Preserve the image pipeline as an auditable production workflow. Never treat third-party model output as complete until the local filesystem, state records, image dimensions, OCR/safety checks, hash gates, selection, and export path all agree.

Before any live generation in a real project, read the local project handoff/spec files first. A production project should define:

- workspace path and output root;
- source asset table or input manifest;
- provider account/model/browser/API details;
- validation rules and skip rules;
- selected-image target path;
- state database, manifest, or registry location.

For the provider-agnostic input/output contract, read `references/prompt-and-output-contract.md`. For a neutral example, read `references/asset-example.md`.

## Inputs

Treat each requested output as one stable item. The reusable contract is:

- `item_id`: asset id, content id, campaign id, row id, or any stable unit of work.
- `source_assets`: source image(s), border/template files, masks, style references, or audit rows.
- `generation_rules`: visual and workflow rules the output must obey.
- `prompt` or `prompt_template`: the model-facing prompt with variables filled per item.
- `provider`: a third-party image model, browser tool, or API adapter.
- `candidate_count`: expected number of returned candidates.
- `result_binding`: how to prove returned images belong to this attempt.
- `validation_rules`: size, format, OCR/text, duplicate, safety, and project-specific checks.
- `selection_criteria`: how to pick the final image from candidates.
- `commit_target`: final directory, manifest, registry, and exported selected-image name.

## Workflow

1. Inspect current state before acting.
   - Run `git status --short` in the project workspace when the project is versioned.
   - Reconcile the requested item or batch range before submitting anything.
   - Check the configured state database or manifest integrity.
   - Confirm the item is not already complete or skipped.

2. Block unsafe or missing sources.
   - Do not generate for source rows or source assets that match configured blocking rules.
   - Do not generate if source data is missing.
   - Keep blocked item status as skipped, with explicit reason.
   - Prompts must include the configured forbidden-content rules.

3. Use the atomic attempt lifecycle.
   - Create one attempt id per submission, e.g. `A-068-004`.
   - Write new candidates only to `ITEM/.attempts/ATTEMPT_ID/`.
   - Advance durable state through `prepared -> submitting -> submitted -> generated -> downloaded -> validated -> selected -> committed`.
   - Record failures with `status: "failed"`, `error_code`, and `error_detail`; do not silently retry. Failed attempts may use `candidate_count: 0` and `candidates: []` when the provider returns no images.
   - Run recovery planning before resubmitting a failed attempt; human-only failures such as CAPTCHA or logged-out sessions must not spin in a retry loop.
   - Publish only after the expected candidates are downloaded, decoded, dimension-checked, hash-checked, OCR-checked, selected, and recorded in durable state.
   - Publish to `ITEM/attempts/ATTEMPT_ID/` and atomically point `ITEM/current` at the successful attempt.

4. Bind browser/model results to the submitted task.
   - Use a unique TASK-ID in the prompt and require the model to echo it.
   - Attach a DOM observer before sending the prompt.
   - Bind results to the message region that appears after submission, not to all images on the page.
   - Reject historical gallery images, pre-existing DOM nodes, and images after the next TASK-ID.
   - Detect quota, moderation, upload, alert, and red error states quickly; write evidence.

5. Validate outputs before declaring completion.
   - Decode every candidate image.
   - Require `2048x2048` for final selected images unless the batch spec changes.
   - Check duplicate hashes within the attempt and across completed item outputs.
   - OCR or otherwise scan for prohibited text or marks.
   - Treat provider/source marks as quality-gate evidence: reject, reroute, or use an approved watermark-free export path rather than removing provenance marks after download.
   - Write candidate, selection, and commit records.
   - Re-run tests and reconcile after code changes or real generation.

6. Export final records one way from the state source.
   - Export selected-image metadata to the configured CSV/JSON/Markdown registry.
   - Do not overwrite a production registry from partial state exports.
   - If migrating old flat artifacts, import and verify them before replacing the official registry.

7. Update handoff when finished.
   - Update the project handoff/spec file with exact date/time, completed items, failed attempts, skipped/missing counts, tests run, and next action.

## Third-Party Model Adapter Rules

When moving from one image provider to another, keep the local contract unchanged:

- The provider must accept source asset attachment(s), generation rules, prompt text, and a TASK-ID.
- The provider adapter must return exactly the candidate images for the active task, not a page-wide scrape.
- The adapter must expose clear failure types such as `captcha_required`, `browser_session_not_authenticated`, `quota_exhausted`, `concurrency_limited`, `network_error`, `moderation_blocked`, `upload_not_ready`, `send_failed`, `generation_timeout`, and `result_binding_failed`.
- The pipeline owns storage, validation, selection, durable state, and export. The provider owns only submission and task-bound candidate retrieval.
- Prefer isolating each provider behind a small adapter with `submit`, `wait`, `download`, and `classify_failure` behavior.

## Commands

Adapt these checks to the current project:

```bash
git status --short
python scripts/validate_attempt.py path/to/ITEM/.attempts/ATTEMPT_ID/attempt.json
python scripts/plan_attempt_recovery.py path/to/ITEM/.attempts/ATTEMPT_ID/attempt.json
python scripts/validate_attempt.py --require-selected path/to/ITEM/.attempts/ATTEMPT_ID/attempt.json
python scripts/inspect_attempt_images.py --require-size 2048x2048 path/to/ITEM/.attempts/ATTEMPT_ID/attempt.json
python -m unittest discover -s tests -q
python -m compileall -q src scripts tests
sqlite3 path/to/image_pipeline.sqlite 'PRAGMA integrity_check;'
sqlite3 path/to/image_pipeline.sqlite 'PRAGMA foreign_key_check;'
```

Use `validate_attempt.py` for both successful and failed attempts. Use
`plan_attempt_recovery.py` to classify failed attempts into retry, backoff,
human-intervention, quarantine, or reroute actions. Use
`inspect_attempt_images.py` only after candidate files have been downloaded; a
failed zero-candidate attempt should stay recorded but should not pass image
inspection.

## Hard Stops

- Do not bypass project approval flows for externally visible or irreversible actions.
- Do not log passwords, cookies, tokens, or verification codes.
- Do not generate from blocked source images.
- Do not resubmit already complete items unless the user explicitly asks and the previous output is quarantined or superseded.
- Do not use page-wide image scraping as recovery.
- Do not remove third-party provenance or AI-generated watermarks as a post-processing shortcut; detect them and fail or route to an approved export/provider path.
- Do not copy failed staging artifacts into `current`.
- Do not modify `state/automation.sqlite` for image-pipeline state.
- Do not overwrite production registry from partial state exports.
