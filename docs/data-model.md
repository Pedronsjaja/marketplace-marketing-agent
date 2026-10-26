# Data model

## Product catalog
A JSON list. Required fields: id, title, price, currency, category, source_url, verified, verified_at and nonempty facts.
IDs use letters/digits/underscore/hyphen and are at most 64 characters. Price is a positive finite decimal string with at most two decimal places. Currency is a three-letter uppercase code; this validates syntax, not the ISO currency registry. verified must be true and verified_at a calendar date.

Verification is supplied by the operator. No external fact checker runs; choose freshness/reverification requirements locally. The fixture's flag applies only to its fictional specification. No availability, delivery, discount or warranty is inferred.

## Persistent policy
Exact fields: channel, allow_public_contact, allow_groups, allow_paid_promotion, allow_free_shipping, max_images. Flags are actual JSON booleans; max_images is 1–20.
The manual adapter does not implement these optional features or image acquisition even when allowed. Requests are reported as unsupported; max_images is reserved policy metadata.

## Local state
schema_version 1; records map keyed by product ID; events list. A record holds state, aggregate counts, product snapshot, draft, fingerprint and timestamps. Publication adds a URL. Event IDs are retry keys, not contact identifiers. No customer names, phone numbers, conversations or individual commission fields are defined.

The JSON file is the source of truth. CSV export is an explicit snapshot, not another independently updated database. No real CSV migration tool is included.

## Control interchange
Exact UTF-8/comma CSV header:
```csv
product_id,state,leads,forwarded,sales,lost
```
Counts must be nonnegative integers and sales + lost <= forwarded <= leads. Duplicate products and inconsistent row width are rejected. Export creates a new file exclusively; choose another filename rather than silently overwriting an existing snapshot.

## Metrics
products = number of rows; leads/forwarded/sales/lost = sums.
sales_per_lead = sales/leads; forwarding_rate = forwarded/leads; outcome_coverage = (sales+lost)/forwarded.
A zero denominator produces null. Ratios describe recorded totals; they do not measure impressions, attribution, causality or revenue. Sample CSV values are derived from fictional counts.
