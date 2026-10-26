"""Deterministic observations; recommendations are not measured effects."""
from .storage import validate_counts


def metrics(rows):
    rows = list(rows)
    seen = set()
    for row in rows:
        validate_counts(row)
        if row["product_id"] in seen:
            raise ValueError("Duplicate product metrics would double-count")
        seen.add(row["product_id"])
    leads = sum(row["leads"] for row in rows)
    forwarded = sum(row["forwarded"] for row in rows)
    sales = sum(row["sales"] for row in rows)
    lost = sum(row["lost"] for row in rows)
    return {
        "products": len(rows), "leads": leads, "forwarded": forwarded,
        "sales": sales, "lost": lost,
        "sales_per_lead": sales / leads if leads else None,
        "forwarding_rate": forwarded / leads if leads else None,
        "outcome_coverage": (sales + lost) / forwarded if forwarded else None,
        "basis": "Aggregate recorded counts; no attribution or causal inference",
    }


def analyze(rows):
    rows = list(rows)
    result = metrics(rows)
    return {
        "FATO": result,
        "HIPOTESE": ["Pending outcomes may explain part of the observed conversion; not tested."],
        "RECOMENDACAO": ["Review missing outcomes before comparing categories or changing copy."],
        "priority": [row["product_id"] for row in sorted(rows, key=lambda r: (-(r["forwarded"] - r["sales"] - r["lost"]), r["product_id"]))],
        "priority_basis": "Outstanding forwarded outcomes, descending; ID breaks ties.",
    }
