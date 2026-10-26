"""Single-writer local JSON state and explicit CSV interchange."""
from contextlib import contextmanager
from copy import deepcopy
import re
import csv
import json
import os
from pathlib import Path
import tempfile

from .core import State, ValidationError, identifier, nonnegative

CONTROL_FIELDS = ("product_id", "state", "leads", "forwarded", "sales", "lost")


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def validate_counts(row):
    if not isinstance(row, dict):
        raise ValidationError("Record must be an object")
    if not set(CONTROL_FIELDS).issubset(row):
        raise ValidationError("Missing control fields")
    identifier(row["product_id"])
    State(row["state"])
    for key in CONTROL_FIELDS[2:]:
        nonnegative(row[key], key)
    if not row["sales"] + row["lost"] <= row["forwarded"] <= row["leads"]:
        raise ValidationError("Counts must satisfy sales + lost <= forwarded <= leads")


class Store:
    def __init__(self, workspace):
        self.root = Path(workspace)
        self.path = self.root / "state.json"

    def snapshot(self):
        state = read_json(self.path) if self.path.exists() else {"schema_version": 1, "records": {}, "events": []}
        if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("records"), dict) or not isinstance(state.get("events"), list):
            raise ValidationError("Unsupported or malformed state file")
        for key, row in state["records"].items():
            validate_counts(row)
            if key != row["product_id"]:
                raise ValidationError("Record key mismatch")
        event_ids = set()
        for event in state["events"]:
            if not isinstance(event, dict) or event.get("type") not in {"PREPARE", "publication", "leads", "forwarding", "outcome"}:
                raise ValidationError("Malformed event")
            identifier(event.get("product_id"))
            signature = event.get("fingerprint")
            if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
                raise ValidationError("Malformed event fingerprint")
            if event["type"] != "PREPARE":
                event_id = identifier(event.get("event_id"))
                if event_id in event_ids:
                    raise ValidationError("Duplicate event ID in persisted state")
                event_ids.add(event_id)
        return state

    @contextmanager
    def transaction(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / ".writer.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ValidationError("Workspace locked; inspect active writer before removing a stale lock") from exc
        os.close(descriptor)
        try:
            state = self.snapshot()
            original = deepcopy(state)
            yield state
            if state != original:
                atomic_json(self.path, state)
        finally:
            lock.unlink()


def read_control(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(CONTROL_FIELDS):
            raise ValidationError("Unexpected control CSV schema")
        rows, seen = [], set()
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                raise ValidationError("Inconsistent CSV row width")
            row = {**raw}
            for field in CONTROL_FIELDS[2:]:
                if not raw[field].isdigit():
                    raise ValidationError("Counts must be nonnegative integer strings")
                row[field] = int(raw[field])
            validate_counts(row)
            if row["product_id"] in seen:
                raise ValidationError("Duplicate product in control CSV")
            seen.add(row["product_id"])
            rows.append(row)
        return rows


def write_control(path, rows):
    rows = list(rows)
    seen = set()
    for row in rows:
        validate_counts(row)
        if row["product_id"] in seen:
            raise ValidationError("Duplicate product in control CSV")
        seen.add(row["product_id"])
    # Exclusive creation prevents silently replacing an existing export.
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CONTROL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
