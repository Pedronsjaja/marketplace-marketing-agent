"""Local workflow with explicit confirmation and retry-safe event IDs."""
from copy import deepcopy
from collections import Counter
from .channels import ManualMarketplace
from .core import State, ValidationError, config, fingerprint, identifier, nonnegative, now, product, transition, web_url

LOCKED_STATES = {s.value for s in (State.PUBLICADO, State.LEAD_RECEBIDO, State.ENCAMINHADO, State.VENDA, State.SEM_VENDA)}


class MarketplaceAgent:
    def __init__(self, store, policy, channel=None):
        self.store = store
        self.policy = config(policy)
        self.channel = channel or ManualMarketplace()
        if self.channel.name != self.policy["channel"]:
            raise ValidationError("Configured channel has no matching adapter")

    def prepare(self, products, requested_features=()):
        allowed_features = {"public_contact", "groups", "paid_promotion", "free_shipping"}
        adjustments = []
        for feature in requested_features:
            if feature not in allowed_features:
                adjustments.append(f"{feature}: unsupported request ignored")
            elif not self.policy["allow_" + feature]:
                adjustments.append(f"{feature}: persistent policy preserved")
            else:
                adjustments.append(f"{feature}: permitted by policy but not implemented by manual adapter")
        if not isinstance(products, list):
            raise ValidationError("Catalog must be a list")
        ids = [p.get("id") for p in products if isinstance(p, dict) and isinstance(p.get("id"), str)]
        duplicates = {key for key, count in Counter(ids).items() if count > 1}
        results = []
        for raw in products:
            try:
                if isinstance(raw, dict) and raw.get("id") in duplicates:
                    raise ValidationError("Duplicate catalog ID; conflicting entries skipped")
                item = product(raw)
                key = item["id"]
                signature = fingerprint({"product": item, "policy": self.policy, "template_version": "1", "channel": self.channel.name})
                with self.store.transaction() as state:
                    previous = state["records"].get(key)
                    if previous and previous["state"] in LOCKED_STATES:
                        results.append({"product_id": key, "result": "PRESERVED_PUBLISHED", "state": previous["state"]})
                        continue
                    if previous and previous.get("fingerprint") == signature and previous["state"] == State.PRONTO_PARA_PUBLICAR.value:
                        results.append({"product_id": key, "result": "CACHE_HIT", "state": previous["state"]})
                        continue
                    record = deepcopy(previous) if previous else {
                        "product_id": key, "state": State.IDENTIFICADO.value,
                        "leads": 0, "forwarded": 0, "sales": 0, "lost": 0,
                    }
                    if record["state"] == State.ERRO.value:
                        record["state"] = transition(record["state"], State.IDENTIFICADO)
                    for target in (State.COLETANDO, State.VALIDADO, State.PRONTO_PARA_PUBLICAR):
                        record["state"] = transition(record["state"], target)
                    record.update(fingerprint=signature, draft=self.channel.draft(item), product=item, prepared_at=now())
                    state["records"][key] = record
                    state["events"].append({"type": "PREPARE", "product_id": key, "at": now(), "fingerprint": signature})
                    results.append({"product_id": key, "result": "PREPARED", "state": record["state"]})
            except (ValueError, TypeError, KeyError) as exc:
                results.append({"product_id": raw.get("id") if isinstance(raw, dict) else None, "result": "ERROR", "reason": str(exc)})
        return {"results": results, "adjustments": adjustments}

    def record(self, kind, product_id, *, event_id, confirmed=False, listing_url=None, leads=0, forwarded=0, sales=0, lost=0):
        if confirmed is not True:
            raise ValidationError("Confirm observed external action before recording it")
        identifier(product_id)
        identifier(event_id)
        if kind not in {"publication", "leads", "forwarding", "outcome"}:
            raise ValidationError("Unknown event type")
        for field, value in (("leads", leads), ("forwarded", forwarded), ("sales", sales), ("lost", lost)):
            nonnegative(value, field)
        payload = {"kind": kind, "product_id": product_id, "listing_url": listing_url,
                   "leads": leads, "forwarded": forwarded, "sales": sales, "lost": lost}
        signature = fingerprint(payload)
        with self.store.transaction() as state:
            previous_event = next((e for e in state["events"] if e.get("event_id") == event_id), None)
            if previous_event:
                if previous_event["fingerprint"] != signature:
                    raise ValidationError("Event ID already used with different data")
                return {"result": "DUPLICATE_IGNORED", "event_id": event_id}
            if product_id not in state["records"]:
                raise ValidationError("Prepare this product first")
            row = state["records"][product_id]
            current = State(row["state"])
            if kind == "publication":
                if any((leads, forwarded, sales, lost)):
                    raise ValidationError("Publication accepts no lead counts")
                url = web_url(listing_url)
                if any(r.get("listing_url") == url for r in state["records"].values()):
                    raise ValidationError("Listing URL already recorded")
                target = State.PUBLICADO
                row["listing_url"] = url
                row["published_at"] = now()
            elif kind == "leads":
                if not leads or any((forwarded, sales, lost)) or listing_url is not None:
                    raise ValidationError("Supply a positive lead count only")
                if current not in {State.PUBLICADO, State.LEAD_RECEBIDO, State.ENCAMINHADO, State.VENDA, State.SEM_VENDA}:
                    raise ValidationError("Finish the current forwarding/outcome stage before adding a new batch")
                row["leads"] += leads
                target = State.LEAD_RECEBIDO
            elif kind == "forwarding":
                if not forwarded or any((leads, sales, lost)) or listing_url is not None:
                    raise ValidationError("Supply a positive forwarded count only")
                if current not in {State.LEAD_RECEBIDO, State.ENCAMINHADO, State.VENDA, State.SEM_VENDA}:
                    raise ValidationError("Record leads before forwarding")
                if row["forwarded"] + forwarded > row["leads"]:
                    raise ValidationError("Cannot forward more leads than recorded")
                row["forwarded"] += forwarded
                target = State.ENCAMINHADO
            else:
                if not sales + lost or any((leads, forwarded)) or listing_url is not None:
                    raise ValidationError("Supply positive outcome counts only")
                if current not in {State.LEAD_RECEBIDO, State.ENCAMINHADO, State.VENDA, State.SEM_VENDA}:
                    raise ValidationError("Record forwarding before outcomes")
                if row["sales"] + row["lost"] + sales + lost > row["forwarded"]:
                    raise ValidationError("Outcomes exceed forwarded leads")
                row["sales"] += sales
                row["lost"] += lost
                target = State.VENDA if row["sales"] else State.SEM_VENDA
            # Outcomes may arrive incrementally after the initial outcome.
            if current != target:
                row["state"] = transition(current, target, confirmed=True)
            state["events"].append({"type": kind, "event_id": event_id, "fingerprint": signature, "at": now(), **payload})
            return {"result": "RECORDED", "event_id": event_id, "state": row["state"]}
