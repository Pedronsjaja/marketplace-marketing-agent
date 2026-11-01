# Marketplace Marketing Agent
Python 3.10+, standard library only. Source: src/marketplace_agent. CLI: python scripts/marketplace.py --help.
Use only fictional sample data. Never import operational datasets, customer contacts, browser sessions or credentials.
Preserve explicit operator confirmation; no real publishing or provider calls exist. Keep deterministic logic separate from adapters.
Tests: python -m unittest discover -s tests -v. Prepublication check: python scripts/validation/audit_public.py.
No premium/cloud escalation without explicit policy. Keep state updates retry-safe and transactional; test failure/rollback paths.

V4: `pipeline.py`, `config/pipeline.v4.example.json`, `docs/pipeline-v4.md`; CLI `v4 plan|prepare|feedback`.
Maintain independent platform feedback/quarantine and count only confirmed LIVE. Do not infer platform integration from publication modes.
Platform-generated category, brand or specifications are not evidence. Keep only fictional fixtures; operational UI observations stay private.
