# Worked fictional marketplace example

All products, URLs and counts below are invented. Facebook Marketplace motivated the initial workflow, but this example has no Facebook API/browser integration and sends no messages.

Run from the repository root:

```text
python scripts/marketplace.py --workspace workspace/demo prepare --product DEMO-001 --request public_contact
python scripts/marketplace.py --workspace workspace/demo prepare --product DEMO-001
python scripts/marketplace.py --workspace workspace/demo record-publication DEMO-001 --event-id demo-pub-1 --url https://example.invalid/listing/demo-001 --confirmed
python scripts/marketplace.py --workspace workspace/demo record-leads DEMO-001 --event-id demo-lead-1 --count 2 --confirmed
python scripts/marketplace.py --workspace workspace/demo record-forwarding DEMO-001 --event-id demo-forward-1 --count 2 --confirmed
python scripts/marketplace.py --workspace workspace/demo record-outcome DEMO-001 --event-id demo-outcome-1 --sales 1 --lost 1 --confirmed
python scripts/marketplace.py --workspace workspace/demo metrics
python scripts/marketplace.py --workspace workspace/demo analyze
python scripts/marketplace.py --workspace workspace/demo export --output workspace/demo/control-export.csv
```

Preparation continues while public_contact is ignored and persistent policy preserved. The second command returns CACHE_HIT.
The publication command records a fictional operator assertion; it does not publish anything. The final counts are leads=2, forwarded=2, sales=1, lost=1, sales_per_lead=0.5 and outcome_coverage=1.0.
Rerunning event commands with identical IDs/payloads returns DUPLICATE_IGNORED. Repeating export intentionally fails rather than replacing a file. Use a new workspace/export name for a fresh experiment.

Actual use: review the local draft and image rights; publish manually using the channel's interface; only then record its real URL in your ignored private workspace. Confirm leads/outcomes only when evidence exists. Never use --confirmed to simulate unverified real performance.
