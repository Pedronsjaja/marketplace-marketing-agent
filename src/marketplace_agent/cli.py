"""Commands only prepare files or record user-confirmed observations."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .core import ValidationError, config
from .manager import analyze, metrics
from .routing import route
from .storage import Store, read_control, read_json, write_control
from .workflow import MarketplaceAgent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--config", default="config/config.example.json")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--catalog", default="data/catalog.sample.json")
    prepare.add_argument("--product", action="append")
    prepare.add_argument("--request", action="append", default=[])
    for name in ("record-publication", "record-leads", "record-forwarding", "record-outcome"):
        cmd = sub.add_parser(name)
        cmd.add_argument("product_id")
        cmd.add_argument("--event-id", required=True)
        cmd.add_argument("--confirmed", action="store_true")
        if name == "record-publication":
            cmd.add_argument("--url", required=True)
        elif name == "record-leads":
            cmd.add_argument("--count", type=int, required=True)
        elif name == "record-forwarding":
            cmd.add_argument("--count", type=int, required=True)
        else:
            cmd.add_argument("--sales", type=int, default=0)
            cmd.add_argument("--lost", type=int, default=0)
    for name in ("metrics", "analyze"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--control", help="Optional aggregate CSV; otherwise use workspace")
    export = sub.add_parser("export")
    export.add_argument("--output", required=True)
    router = sub.add_parser("route")
    router.add_argument("task")
    router.add_argument("--level", type=int, action="append", default=[])
    router.add_argument("--failed-level", type=int, action="append", default=[])
    router.add_argument("--allow-cloud", action="store_true")
    router.add_argument("--allow-premium", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = Store(args.workspace)
        if args.command == "route":
            result = asdict(route(args.task, {}, available_levels=args.level, failed_levels=args.failed_level,
                                  allow_cloud=args.allow_cloud, allow_premium=args.allow_premium))
        elif args.command in {"metrics", "analyze", "export"}:
            if getattr(args, "control", None):
                rows = read_control(args.control)
            else:
                if not store.path.exists():
                    raise ValidationError("Workspace has no records; run prepare first")
                rows = list(store.snapshot()["records"].values())
            if args.command == "export":
                write_control(args.output, rows)
                result = {"result": "EXPORTED", "records": len(rows)}
            else:
                result = (analyze if args.command == "analyze" else metrics)(rows)
        else:
            agent = MarketplaceAgent(store, config(read_json(args.config)))
            if args.command == "prepare":
                catalog = read_json(args.catalog)
                if not isinstance(catalog, list):
                    raise ValidationError("Catalog must be a list")
                if args.product:
                    missing = set(args.product) - {p.get("id") for p in catalog if isinstance(p, dict)}
                    if missing:
                        raise ValidationError("Selected product ID not found")
                    catalog = [p for p in catalog if isinstance(p, dict) and p.get("id") in args.product]
                result = agent.prepare(catalog, args.request)
            else:
                kind = args.command.removeprefix("record-")
                kwargs = {"event_id": args.event_id, "confirmed": args.confirmed}
                if kind == "publication":
                    kwargs["listing_url"] = args.url
                elif kind in {"leads", "forwarding"}:
                    kwargs["leads" if kind == "leads" else "forwarded"] = args.count
                else:
                    kwargs.update(sales=args.sales, lost=args.lost)
                result = agent.record(kind, args.product_id, **kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if args.command == "prepare" and any(row["result"] == "ERROR" for row in result["results"]) else 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
