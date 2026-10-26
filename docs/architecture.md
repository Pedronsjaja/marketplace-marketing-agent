# Architecture

## Problem and decision
A private V2/V2.1 instruction-driven workflow coupled business-specific records to a particular marketplace. The reusable concepts were local/cache-first preparation, state awareness, explicit confirmation and partial conflict resolution. A read-only audit found instructions and prepared artifacts rather than an executable framework; this repository implements those concepts afresh.

Choose a small Python package with standard-library runtime. No web server, database, container, browser driver or model SDK is required.

| Module | Responsibility |
|---|---|
| core.py | States, transitions, IDs, verified product schema, policy, fingerprints |
| workflow.py | Preparation, independent item results, confirmation, event deduplication |
| storage.py | JSON snapshots/transactions and strict aggregate CSV interchange |
| channels.py | Channel Protocol and ManualMarketplace draft adapter |
| routing.py | Provider Protocol, usage result and pure model-level selection |
| manager.py | Calculations and labeled manager output |
| cli.py | File/argument boundary and machine-readable results |

## Invariants
No externally consequential operation is automated. Publication and subsequent event recording require confirmed=True or --confirmed, an operator attestation. The library cannot establish that the real-world action occurred.
State, counts and event log are saved together. A writer lock prevents concurrent mutation; atomic replace prevents half-written JSON. A crash may leave a lock: inspect processes and the file before manually removing it. This is local single-host storage, not a distributed transaction system.

Preparation validates each item, skips all conflicting duplicate IDs and continues other valid items. A malformed catalog root or global config blocks the command because it cannot safely identify independent work.

## Cache and channels
Fingerprint includes complete product input, persistent policy, template version and channel name. Changed inputs invalidate unpublicized drafts. Published products retain existing copy; repricing/relisiting requires a future explicit workflow.
Only prepared drafts are cached. The router emits a proposed cache key; there is no LLM response cache.

Implement a class with name and draft(product), then pass channel=instance to MarketplaceAgent with matching policy.channel. The CLI currently constructs the manual adapter only: update its adapter registry when introducing another actual implementation. Channel selection does not grant publishing capabilities.

## Limits
No scheduled collection, lead-level identity, multi-channel listings per product, inventory reservation, revenue/commission calculation, image processing, legal-policy compliance engine or external publication. Status describes the latest workflow milestone; aggregate counts remain the source of truth.
