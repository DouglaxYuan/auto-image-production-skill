# Prompt and Output Contract

Use this contract for automated image-production workflows.

## Required User-Supplied Fields

- `item_id`: stable id for one unit of work.
- `source_assets`: input image(s), template/border/mask/reference files, or source table rows.
- `prompt`: exact generation prompt or a template with variables.
- `generation_rules`: visual and workflow rules the model must follow.
- `provider`: browser image tool or API image model.
- `candidate_count`: expected number of candidates.
- `result_binding`: task id, provider id, DOM/message-region rule, or API response field proving candidates belong to this attempt.
- `validation_rules`: checks required before accepting candidates.
- `selection_criteria`: how to choose the final image.
- `commit_target`: final output path, filename pattern, manifest/registry destination.

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
```

The validator checks required fields, `candidate_count`, `result_binding`, candidate file paths, candidate path containment inside the attempt directory, duplicate candidate paths, candidate task ids, and `selected_path` membership. It does not replace image decoding, OCR, perceptual hashing, or project-specific quality checks.

## Result Validation

Accept a candidate only after:

- It is bound to the current `TASK-ID` or provider task id.
- It is downloaded and decodes successfully.
- It matches size/aspect/format rules.
- It passes OCR or visual text checks.
- It passes duplicate/hash checks.
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
