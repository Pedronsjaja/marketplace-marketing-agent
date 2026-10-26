# Agent design

Marketplace Agent modes:
- PREPARE: validated facts → deterministic draft → local state/cache.
- PUBLISH: provide a human checklist; record an already confirmed publication. No click/API operation.
- LEADS: record operator-reported aggregates, forwarding and outcomes. No message sending.
- ANALYZE: calculate counts and ratios; distinguish unknown denominators from zero performance.

The V2.1 principle of partial execution is preserved: a request for public contact information does not silently change policy and does not prevent an otherwise valid preparation. Per-item errors are returned explicitly; persistent policy is not rewritten.

Marketing Manager follows observe → analyze → prioritize → decide → delegate → measure → learn as a conceptual loop. Implemented now: deterministic observations, priority by unresolved forwarded outcomes and generic labeled hypotheses/recommendations. Autonomous delegation, experimentation and qualitative strategy are planned.

Prompts in [agents](../agents/) are original reusable guidance, not background processes. A prompt is not evidence that an LLM was executed.
