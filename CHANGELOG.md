# Changelog

All notable changes to this repository are documented here. Dates use
`YYYY-MM-DD`.

## Unreleased

### Added

- Public-safe project documentation links in `README.md`.
- Contribution and security policies for public GitHub use.
- Chinese version-comparison notes covering the earliest recoverable repository
  baseline and the current maintenance branch.

## 2026-07-08 - Maintenance Branch

### Added

- Attempt manifest validation via `scripts/validate_attempt.py`.
- Failed-attempt recovery planning via `scripts/plan_attempt_recovery.py`.
- Downloaded candidate inspection via `scripts/inspect_attempt_images.py`.
- Unit tests for validation, recovery planning, and image inspection.
- Machine-readable JSON reports for automation runners.
- Retry metadata including `retry_count`, `next_retry_count`,
  `remaining_retries`, `max_retries`, and `retry_after_seconds`.
- Operator escalation metadata including `requires_operator` and
  `operator_block_key`.

### Changed

- Replaced provider- or marketplace-specific public examples with neutral asset
  examples.
- Expanded the prompt and output contract with `result_binding`,
  `quality_rules`, failed-attempt fields, and retry semantics.
- Routed CAPTCHA, login, moderation, exhausted retry budgets, invalid manifests,
  OCR residue, visible marks, network errors, rate limits, and provider capacity
  failures into explicit recovery actions.
- Clarified that third-party provenance marks and AI-generated watermarks should
  be detected, rejected, or routed to an approved export/provider path rather
  than removed as post-processing.

### Security

- Redacted local absolute paths from JSON reports.
- Hardened manifest validation against unsafe paths, symlinked artifacts,
  malformed identity fields, invalid JSON/UTF-8, and inconsistent selected
  candidate references.

## 1.0.0 - Initial Public Skill

### Added

- Initial `auto-image-production` skill workflow.
- Provider-agnostic prompt/output contract.
- Atomic attempt layout.
- Public README, skill metadata, neutral example, and Codex agent metadata.
