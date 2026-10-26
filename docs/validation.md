# Validation — 2026-10-26

## Executed locally
- Python standard-library unittest suite: **37 tests passed**.
- **17 documented commands** executed successfully, including source CLI examples, tests and public-candidate audit.
- Worked demo: two leads, two forwarded, one converted lead, one lost lead; sales_per_lead 0.5 and outcome coverage 1.0.
- Repository-local Markdown target checks: **17 links**, no missing target after this validation record was added.
- Public-candidate heuristic audit: no findings before publication.
- Additional private audit compared candidate content against selected private configuration identifiers; no matches. Original operational files were checked against pre-work hashes and remained unchanged.

## Coverage and review
States/confirmation, incremental outcomes in both arrival orders, forwarding remaining leads, new leads while outcomes remain pending, invalid catalog items, partial success, duplicate IDs/URLs, retry identity, changed-input cache invalidation, published-draft preservation, counts/ratios, CSV round-trip/schema, config types, malformed state/event data and model routing.
Failure tests cover lock contention, rollback after invalid events and a simulated atomic-replace failure. A separate code review identified incremental-state defects; regression cases were added and passed after correction.
This is not exhaustive concurrency/crash or security verification.

## Not executed
No LLM calls, paid benchmarks, browser automation, external publication, lead forwarding, sales verification or production-data migration. No token/cost savings measured.
GitHub CI is configured for Python 3.10/3.13 on Linux and Windows; its remote status is reported separately after push.

## Reproduce
From the repository root:
```text
python -m unittest discover -s tests -v
python scripts/validation/audit_public.py
```
Run the [worked example](marketplace-example.md) with a fresh ignored workspace. Export refuses an existing file; event retries use the same event ID.

## Evidence limits
Fixture results are FICTIONAL or CALCULATED_FROM_FICTIONAL. Tests establish software behavior under their inputs, not actual business improvement or platform compliance. The public audit is heuristic and was supplemented by manual file review and source separation.
