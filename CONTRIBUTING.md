# Contributing

Thanks for helping improve `auto-image-production`.

## Development Workflow

1. Create a branch for the change.
2. Keep examples public-safe and provider-agnostic unless a provider-specific
   integration is intentionally documented.
3. Add or update tests for behavior changes.
4. Run the validation commands before opening a pull request.

```bash
python -m unittest discover -s tests -q
python -m compileall -q scripts tests
git diff --check HEAD
```

If you maintain this as a local Codex skill and have a skill validator
available, run that validator as well. If not, run the unit tests and compile
checks, then mention the missing validator in the pull request.

## Documentation Standards

- Prefer clear Markdown headings, short paragraphs, and runnable command blocks.
- Use neutral ids such as `ASSET-0001` in public examples.
- Document failure behavior as structured states, not as free-form anecdotes.
- Do not include screenshots or logs that expose account names, cookies, tokens,
  local paths, browser profiles, or customer data.

## Safety Rules

- Do not add automation that solves CAPTCHA or bypasses provider safety flows.
- Do not add watermark-removal behavior for third-party provenance or
  AI-generated marks. Detect, reject, quarantine, or route to an approved
  watermark-free export/provider path instead.
- Do not commit generated customer assets, private source images, provider
  cookies, API keys, or unredacted local run logs.

## Pull Request Checklist

- [ ] The change keeps task results bound to a current `TASK-ID` or provider task id.
- [ ] Failed attempts are recorded with `status`, `error_code`, and
      `error_detail`.
- [ ] Retryable failures respect retry counts and backoff metadata.
- [ ] Human-only failures such as CAPTCHA or login-required sessions leave the
      automation loop.
- [ ] Tests and documentation were updated when behavior changed.
- [ ] Public examples contain no private or customer-specific data.
