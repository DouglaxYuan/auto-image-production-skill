# Auto Image Production

`auto-image-production` is a Codex skill for automated image-production workflows. It helps an agent turn user-provided output rules, prompts, source assets, third-party image models, validation rules, selection standards, and target paths into auditable final images.

The skill is provider-agnostic. Browser-based image tools and API image models can all be used if they can return candidates that are bound to the current task.

## What It Does

The skill guides an agent through this flow:

1. Read the local project spec and handoff files.
2. Confirm the item is safe and eligible for generation.
3. Submit source assets and prompt to a third-party model with a unique task id.
4. Bind returned images to the current task instead of scraping old page images.
5. Download candidates into a staging directory.
6. Validate dimensions, decoding, OCR/text safety, duplicates, and project rules.
7. Select the best candidate using explicit criteria.
8. Commit the successful attempt atomically.
9. Export or copy the final selected image to the requested target path.

## Install

Clone this repository into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/lightbulingling/auto-image-production-skill.git ~/.codex/skills/auto-image-production
```

Then start a new Codex session and invoke:

```text
Use $auto-image-production ...
```

## Required Inputs

Provide these fields as clearly as possible:

- `item_id`: stable unit of work, such as asset id, content id, row id, or campaign image id
- `source_assets`: input image(s), template, border, mask, style reference, or source table rows
- `prompt`: exact prompt or prompt template
- `generation_rules`: visual and workflow rules the output must follow
- `provider`: third-party image model or browser/API provider
- `candidate_count`: expected number of candidates
- `result_binding`: how to prove returned images belong to the current task or provider task id
- `validation_rules`: size, OCR/text, duplicate, safety, and quality checks
- `selection_criteria`: how to pick the final image
- `commit_target`: final directory, filename pattern, manifest, or registry destination

## Example Request

```text
Use $auto-image-production to generate final images.

item_id: ASSET-0001
source_assets:
- input image: ./input/ASSET-0001.png
- template image: ./templates/final-frame.png
provider: browser image tool
candidate_count: 3
result_binding: Accept only images returned after the provider echoes TASK-ID ASSET-0001-A001.
prompt: "TASK-ID: ASSET-0001-A001. Create a clean final image. Preserve the main subject shape and color. Use the provided template. Do not include prohibited text, marks, or unrelated text. Output exactly 3 square 2048x2048 images. Echo TASK-ID ASSET-0001-A001."
validation_rules:
- image decodes successfully
- selected image is 2048x2048
- OCR finds no prohibited text
- no duplicate hash against previous committed items
selection_criteria:
- complete subject visible
- cleanest background
- least distortion
- best template alignment
commit_target: ./generated/selected/ASSET-0001__selected.png
```

## Atomic Commit

Atomic commit means the workflow does not write half-finished model output directly into the final image path.

Use a layout like:

```text
ITEM/
  .attempts/
    ATTEMPT_ID/        # staging, can be discarded if failed
  attempts/
    ATTEMPT_ID/        # immutable successful result
  current -> attempts/ATTEMPT_ID
```

Only after candidates pass validation and a final image is selected should the attempt be published and `current` moved to the successful attempt. This prevents failed, partial, duplicate, or mismatched images from polluting the final output.

If a provider interrupts the run before returning candidates, keep the attempt in
staging with `status: "failed"`, `error_code`, `error_detail`,
`candidate_count: 0`, and `candidates: []`. Examples include `captcha_required`,
`login_required`, `concurrency_limited`, `rate_limited`, `provider_busy`, `network_error`,
`page_load_failed`, `browser_crashed`, `selector_not_found`, `moderation_blocked`, `upload_failed`, `download_failed`, `download_timeout`, `generation_timeout`, `no_candidates_found`, `forbidden_ocr_text`, `missing_ocr_evidence`, `ocr_text_detected`, and `ocr_status_failed`. This lets automation resume, back off, switch providers,
or request human intervention without losing the task record.

Validate attempt bookkeeping while the attempt is still staged:

```bash
python scripts/validate_attempt.py ITEM/.attempts/ATTEMPT_ID/attempt.json
```

Plan the next automation action before resubmitting a failed attempt:

```bash
python scripts/plan_attempt_recovery.py --max-retries 3 ITEM/.attempts/ATTEMPT_ID/attempt.json
```

The recovery planner returns JSON actions such as `needs_human`, `retry`,
`backoff`, `quarantine`, `reroute_provider`, or `inspect_images`. Use it to keep
CAPTCHA, login-required sessions, browser crashes, missing UI selectors, page load, network, upload, or download errors, provider-busy responses, rate limits, and concurrency limits from all
collapsing into the same interrupted state. It also routes missing OCR evidence
and OCR/text-residue quality failures to approved reroute or skip actions rather than post-processing
the downloaded image. It normalizes error-code whitespace
or hyphen separators for policy lookup while preserving the original
`error_code` in the returned plan; failed plans also include
`normalized_error_code` for scheduler diagnostics. For retryable failures, record a
non-negative integer `retry_count`; when it reaches `--max-retries`, the planner
escalates to `review_failure` instead of looping forever. `--max-retries` must
be a positive integer. Retryable plans include `remaining_retries` so schedulers
can decide whether to retry, back off, or escalate, `max_retries` so logs show
the configured budget, and `next_retry_count` so the next attempt records the
incremented counter. `retry_after_seconds` grows with `retry_count` and is
capped at one hour, so repeated network or queue failures do not retry in a
tight loop. `failure_category` groups failures for logging and alert routing,
for example `network`, `capacity`, `human_intervention`, `automation_contract`, `quality_gate`, or
`compliance`. `requires_operator` marks plans that must leave the automation
loop for a human decision, such as CAPTCHA, moderation, or exhausted retry
budgets. The `next_command` field is action-specific, for example `request
human intervention` for CAPTCHA or logged out sessions.

Before publishing a successful attempt, also require the manifest to name the selected candidate:

```bash
python scripts/validate_attempt.py --require-selected ITEM/.attempts/ATTEMPT_ID/attempt.json
```

Inspect downloaded image files before publish-time selection:

```bash
python scripts/inspect_attempt_images.py --require-size 2048x2048 ITEM/.attempts/ATTEMPT_ID/attempt.json
```

Automation runners can request a structured report for diagnostics and failed-attempt routing:

```bash
python scripts/inspect_attempt_images.py --json --require-size 2048x2048 ITEM/.attempts/ATTEMPT_ID/attempt.json
```

The image inspection step decodes each candidate, checks exact dimensions when requested,
rejects duplicate candidate bytes, and enforces recorded OCR/visible-mark evidence such as
`quality_rules.reject_any_ocr_text` and `quality_rules.forbidden_visible_marks`.
OCR status checks normalize whitespace or hyphen separators and match case-insensitively, and forbidden-text checks
collapse whitespace before matching case-insensitively,
but statuses that claim no text must not include non-empty `ocr_text`.
Visible-mark checks collapse whitespace and match case-insensitively.
Blank forbidden text or visible-mark entries are ignored after normalization.
With `--json`, the inspector writes `item_id`, `attempt_id`, `task_id`,
`provider`, `status`, `errors`, `suggested_error_code`, and
`failed_attempt_patch` to stdout so schedulers can persist failures such as
`forbidden_visible_mark`,
`forbidden_ocr_text`, `missing_ocr_evidence`, `ocr_text_detected`,
`ocr_status_failed`, `no_candidates_found`, or `candidate_validation_failed`
before invoking the recovery planner. The inspector does not mutate the
manifest; runners may apply `failed_attempt_patch.status`, `error_code`, and
`error_detail` when they intentionally mark the attempt failed.
It is only for attempts with downloaded candidate files; failed zero-candidate
attempts should pass manifest validation but fail image inspection.

## 注意事项

- 不要把第三方模型页面里的历史图片当成本次结果。
- 每次提交都要有唯一 `TASK-ID` 或 provider task id。
- 不要生成来源素材中已经命中禁用规则的任务。
- 不要跳过尺寸、OCR、重复哈希和业务质量检查。
- 不要把第三方平台来源标识或 AI 生成水印作为后处理去除目标；应自动检测并拒收，或切换到合规的无水印导出/provider。
- 不要把失败 attempt 的 staging 文件复制到最终目录。
- 不要用部分导出的 registry 覆盖生产 registry。
- 不要在公开仓库提交真实客户数据、账号信息、cookie、token、本机绝对路径或未脱敏的业务批次状态。

## Files

- `SKILL.md`: skill trigger metadata and core workflow
- `references/prompt-and-output-contract.md`: provider-agnostic prompt/output contract
- `references/asset-example.md`: neutral example
- `scripts/validate_attempt.py`: local attempt manifest validator
- `scripts/inspect_attempt_images.py`: downloaded candidate image quality gate
- `scripts/plan_attempt_recovery.py`: failed-attempt retry/backoff/human-action planner
- `agents/openai.yaml`: UI metadata for Codex
