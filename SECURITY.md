# Security Policy

## Public Repository Rules

Do not open public issues or pull requests containing:

- provider cookies, session data, passwords, verification codes, API keys, or
  bearer tokens;
- customer or private source images;
- local browser profiles, machine-specific paths, or unredacted run logs;
- provider account screenshots that expose personal or business account data.

Use synthetic ids and redacted examples when reporting bugs.

## Reporting a Vulnerability

If GitHub Security Advisories are enabled for this repository, use a private
advisory. Otherwise, contact the repository owner through a private channel
before posting technical details publicly.

Please include:

- affected script or workflow;
- minimal redacted reproduction steps;
- expected and actual behavior;
- whether the issue can expose secrets, private files, customer assets, or
  provider account state.

## Automation Safety Scope

This project treats the following as security-relevant behavior:

- CAPTCHA or login loops that should require human action;
- logs that leak local absolute paths or provider/account data;
- attempts that can publish unvalidated generated images;
- result binding failures that can select historical provider-page images;
- OCR/text or visible-mark failures that should reject or reroute output rather
  than silently post-process it.
