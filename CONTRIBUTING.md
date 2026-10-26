# Contributing
Use a focused branch and small changes. Discuss new providers/channels before introducing dependencies.
Run python -m unittest discover -s tests -v and python scripts/validation/audit_public.py.
Add tests for state/count invariants, failure rollback, idempotency and missing data. Use fictional fixtures only.
Document implemented versus planned behavior and preserve privacy/operator confirmation.
Disclose third-party source/license before reuse in THIRD_PARTY_CREDITS.md. Do not upload private evidence to issues or PRs.
