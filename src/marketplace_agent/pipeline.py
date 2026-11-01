"""Independent V4 platform queues; external publishing remains adapter-owned."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

from .core import CONFIRMED_STATES, State, ValidationError, identifier, now, product, web_url
from .storage import Store, atomic_json, read_json

PLATFORMS = ("FACEBOOK", "OLX")
MODES = {"PREPARE_ONLY", "ASSISTED_POSTING", "AUTO_POST_WHERE_SUPPORTED"}
STATES = {"READY_TO_POST", "SUBMITTED", "LIVE", "REJECTED_DUPLICATE",
          "REJECTED_OTHER", "NEEDS_REVIEW", "SOLD", "ARCHIVED"}
RESULTS = {"LIVE", "REJECTED_DUPLICATE", "REJECTED_OTHER", "UNKNOWN"}
TIRE_FIELDS = ("brand", "model", "size", "width", "profile", "rim", "load_index",
               "speed_index", "condition", "price", "photos")


def settings(raw):
    if raw.get("agent_version") != "V4":
        raise ValidationError("Expected agent_version V4")
    if raw.get("legacy_platform") not in PLATFORMS:
        raise ValidationError("Explicit legacy platform provenance is required")
    for field in ("daily_target_min", "daily_target_preferred", "reserve_target",
                  "facebook_min_photos", "olx_min_photos", "inventory_max_age_seconds",
                  "price_max_age_seconds"):
        if type(raw.get(field)) is not int or raw[field] <= 0:
            raise ValidationError(f"{field} must be a positive integer")
    if raw["daily_target_min"] > raw["daily_target_preferred"]:
        raise ValidationError("Minimum daily target exceeds preferred target")
    if raw["facebook_duplicate_action"] != "REPLACE_PRODUCT" or raw["auto_retry"] is not False:
        raise ValidationError("Duplicates require replacement without automatic retry")
    if raw["safe_omission"] is not True or raw["price_confirmation_required"] is not True:
        raise ValidationError("Factual omission and price confirmation are required")
    for platform in PLATFORMS:
        if raw[platform.lower()+"_mode"] not in MODES:
            raise ValidationError("Unknown publication mode")
        maximum = raw.get(platform.lower()+"_max_photos")
        if maximum is not None and (type(maximum) is not int or maximum < raw[platform.lower()+"_min_photos"]):
            raise ValidationError("Invalid platform photo limit")
    cep = raw.get("olx_operation_cep")
    if cep is not None and (not isinstance(cep, str) or not re.fullmatch(r"\d{5}-\d{3}", cep)):
        raise ValidationError("Operational CEP must be null or NNNNN-NNN")
    if not isinstance(raw.get("delivery_scope_confirmed"), bool):
        raise ValidationError("Delivery scope needs an explicit confirmation flag")
    offset = raw.get("utc_offset_minutes")
    if type(offset) is not int or not -840 <= offset <= 840:
        raise ValidationError("Invalid reporting UTC offset")
    return dict(raw)


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        return parsed
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError("Expected timezone-aware ISO timestamp") from exc


def normalized_url(value):
    parsed = urlsplit(web_url(value))
    return parsed._replace(query="", fragment="", netloc=parsed.netloc.lower()).geturl().rstrip("/")


def feedback_state(event):
    result = event.get("result")
    if result in {"REJECTED_DUPLICATE", "REJECTED_OTHER"}:
        return result
    if result == "LIVE" and event.get("live_confirmed") is True and event.get("evidence"):
        return "LIVE"
    return "SUBMITTED"


def target_history(item, platform, history):
    return [e for e in history if e["platform"] == platform and (
        e["product_id"] == item["id"] or (e.get("source_url") and
        normalized_url(e["source_url"]) == normalized_url(item["source_url"])))]


def approved_photos(item):
    approved = {}
    for photo in item.get("photos", []):
        if not isinstance(photo, dict):
            continue
        path = Path(photo.get("path", ""))
        if (not path.is_file() or not photo.get("ownership_evidence") or
                photo.get("visual_review_confirmed") is not True or
                photo.get("product_source_url") != item["source_url"]):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == photo.get("sha256"):
            approved.setdefault(digest, {**photo, "path": str(path.resolve())})
    return list(approved.values())


def facts(item):
    if "attributes" in item:
        return [a["value"] for a in item["attributes"] if a.get("status") == "CONFIRMED"
                and isinstance(a.get("value"), str) and a["value"].strip()]
    return list(item["facts"])


def duplicate_risk(item, platform, history):
    if platform == "OLX":
        return "NOT_SCORED"
    relevant = [e for e in history if e["platform"] == platform]
    if any(feedback_state(e) == "REJECTED_DUPLICATE" for e in target_history(item, platform, relevant)):
        return "HIGH"
    photos = {p["sha256"] for p in item.get("approved_photos", [])}
    if any(photos.intersection(e.get("image_hashes", [])) for e in relevant):
        return "HIGH"
    if any(e.get("title") and SequenceMatcher(None, item["title"].casefold(), e["title"].casefold()).ratio() > .8 for e in relevant):
        return "MEDIUM"
    return "LOW"


def preflight(item, platform, policy, history, *, at=None):
    at = at or datetime.now(timezone.utc)
    errors = []
    attempts = target_history(item, platform, history)
    state = feedback_state(attempts[-1]) if attempts else item.get("platform_status", {}).get(platform)
    if any(feedback_state(e) == "REJECTED_DUPLICATE" for e in attempts):
        errors.append("DUPLICATE_QUARANTINE")
    if state == "LIVE": errors.append("ALREADY_LIVE_ON_TARGET")
    if state in {"SUBMITTED", "REJECTED_OTHER", "NEEDS_REVIEW", "SOLD", "ARCHIVED"}:
        errors.append("TARGET_STATE_REQUIRES_REVIEW")
    if item.get("internal_duplicate"): errors.append("PRODUCT_NOT_UNIQUE")
    if item.get("source_valid") is not True: errors.append("SOURCE_NOT_CONFIRMED")
    if item.get("identity_clear") is not True: errors.append("IDENTITY_NOT_CONFIRMED")
    if item.get("price_confirmed") is not True:
        errors.append("PRICE_NOT_CONFIRMED")
    try:
        age = (at - timestamp(item.get("price_confirmed_at"))).total_seconds()
        if not 0 <= age <= policy["price_max_age_seconds"]:
            errors.append("PRICE_EVIDENCE_STALE")
    except ValidationError: errors.append("PRICE_EVIDENCE_REQUIRED")
    if item.get("verified") is not True: errors.append("FACTUAL_REVIEW_REQUIRED")
    if len(item.get("approved_photos", [])) < policy[platform.lower()+"_min_photos"]:
        errors.append("OFFICIAL_PHOTOS_INSUFFICIENT")
    if item.get("kind") == "TIRE" and any(item.get(field) in (None, "", []) for field in TIRE_FIELDS):
        errors.append("TIRE_FACTS_MISSING")
    if duplicate_risk(item, platform, history) == "HIGH": errors.append("HIGH_DUPLICATE_RISK")
    return errors


def upload_gate(item, platform, policy, history, inventory, *, at=None):
    at = at or datetime.now(timezone.utc)
    errors = preflight(item, platform, policy, history, at=at)
    if daily_counts(history, policy, at=at)["TOTAL"] >= policy["daily_target_preferred"]:
        errors.append("DAILY_TARGET_REACHED")
    mode = policy[platform.lower()+"_mode"]
    if mode == "PREPARE_ONLY": errors.append("PREPARE_ONLY")
    # Configuration cannot create a platform integration that does not exist.
    if mode == "AUTO_POST_WHERE_SUPPORTED": errors.append("SUPPORTED_ADAPTER_REQUIRED")
    if not inventory or inventory.get("platform") != platform or inventory.get("authenticated") is not True or inventory.get("complete") is not True:
        return errors + ["SELLER_INVENTORY_NOT_VERIFIED"]
    if inventory.get("blocking_issue"):
        errors.append("HUMAN_ACTION_REQUIRED")
    try:
        age = (at - timestamp(inventory.get("checked_at"))).total_seconds()
        if not 0 <= age <= policy["inventory_max_age_seconds"]: errors.append("SELLER_INVENTORY_STALE")
    except ValidationError: errors.append("SELLER_INVENTORY_STALE")
    for listing in inventory.get("listings", []):
        if listing.get("product_id") == item["id"] or (listing.get("source_url") and
                normalized_url(listing["source_url"]) == normalized_url(item["source_url"])):
            errors.append("EXISTING_LISTING_REVIEW_REQUIRED")
            break
    if platform == "OLX" and not policy.get("olx_operation_cep"):
        errors.append("OLX_CEP_REQUIRED")
    return errors


def daily_counts(history, policy, *, at=None):
    at = at or datetime.now(timezone.utc)
    zone = timezone(timedelta(minutes=policy["utc_offset_minutes"]))
    latest = {(e["platform"], normalized_url(e["source_url"]) if e.get("source_url") else e["product_id"]): e for e in history}
    counts = dict.fromkeys(PLATFORMS, 0)
    for (platform, _), event in latest.items():
        if feedback_state(event) != "LIVE": continue
        stamp = event.get("live_confirmed_at") or event.get("submitted_at")
        if stamp and timestamp(stamp).astimezone(zone).date() == at.astimezone(zone).date():
            counts[platform] += 1
    return {**counts, "TOTAL": sum(counts.values())}


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try: descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc: raise ValidationError("V4 workspace locked; inspect active writer") from exc
    os.close(descriptor)
    try: yield
    finally: path.unlink(missing_ok=True)


def record_feedback(workspace, raw, *, confirmed=False):
    if not confirmed: raise ValidationError("Operator confirmation required")
    event = dict(raw)
    identifier(event["event_id"]); identifier(event["product_id"])
    if event.get("platform") not in PLATFORMS or event.get("result") not in RESULTS:
        raise ValidationError("Unknown platform/result")
    if type(event.get("retry_count", 0)) is not int or event.get("retry_count", 0) < 0:
        raise ValidationError("Invalid retry_count")
    if event.get("submitted_at") is not None: timestamp(event["submitted_at"])
    if event.get("source_url"): web_url(event["source_url"])
    if event["result"] == "LIVE":
        if event.get("live_confirmed") is not True or not event.get("evidence"):
            raise ValidationError("LIVE requires explicit confirmation and evidence")
        event.setdefault("live_confirmed_at", now())
        timestamp(event["live_confirmed_at"])
    else: event["live_confirmed"] = False
    for key in ("title", "price", "submitted_at", "platform_reason"):
        event.setdefault(key, None)
    event.setdefault("retry_count", 0)
    event.setdefault("recorded_at", now())
    root = Path(workspace)/"v4"
    with locked(root/".feedback.lock"):
        path = root/"platform-feedback.json"
        data = read_json(path) if path.exists() else {"agent_version":"V4", "attempts":[]}
        previous = next((e for e in data["attempts"] if e["event_id"] == event["event_id"]), None)
        if previous:
            # Stable event IDs cannot silently rewrite observations.
            comparable = lambda e: {k:v for k,v in e.items() if k not in {"recorded_at", "live_confirmed_at"}}
            if comparable(previous) != comparable(event): raise ValidationError("Event ID collision")
            return previous
        data["attempts"].append(event)
        atomic_json(path, data)
    return event


def plan(catalog, policy, history, *, at=None):
    policy = settings(policy)
    rows = [product(raw) for raw in catalog]
    counts = Counter(normalized_url(x["source_url"]) for x in rows)
    ids = Counter(x["id"] for x in rows)
    for item in rows:
        statuses=item.get("platform_status", {})
        if not isinstance(statuses, dict) or any(p not in PLATFORMS or s not in STATES for p,s in statuses.items()):
            raise ValidationError("Invalid per-platform lifecycle state")
        item["approved_photos"] = approved_photos(item)
        item["internal_duplicate"] = counts[normalized_url(item["source_url"])] > 1 or ids[item["id"]] > 1
    result = {"AGENT_VERSION":"V4", "EVIDENCE_MODE":"FICTIONAL" if rows and all(x.get("fictional") is True for x in rows) else "OPERATOR_ATTESTED",
              "LIVE_TODAY":daily_counts(history, policy, at=at),
              "INBOX_FACEBOOK":"EXTERNAL_REVIEW_REQUIRED", "INBOX_OLX":"EXTERNAL_REVIEW_REQUIRED",
              "TIRE_BLOCKER":None if any(x.get("kind") == "TIRE" for x in rows) else "TIRE_CATALOG_SOURCE_MISSING"}
    for platform in PLATFORMS:
        blockers = {x["id"]:preflight(x,platform,policy,history,at=at) for x in rows}
        pool = [x for x in rows if not blockers[x["id"]]]
        categories = Counter(); selected=[]
        while pool and len(selected) < policy["daily_target_preferred"] + policy["reserve_target"]:
            pool.sort(key=lambda x:(bool(target_history(x,platform,history)),
                                   {"LOW":0,"MEDIUM":1,"HIGH":2,"NOT_SCORED":0}[duplicate_risk(x,platform,history)],
                                   categories[x["category"]],x["id"]))
            item=pool.pop(0);selected.append(item);categories[item["category"]]+=1
        limit=policy["daily_target_preferred"]
        maximum=policy.get(platform.lower()+"_max_photos")
        quality=Counter("MINIMAL" if n <= 2 else "GOOD" if n <= 4 else "EXCELLENT"
                        for x in selected[:limit]
                        for n in [min(len(x["approved_photos"]),maximum) if maximum is not None else len(x["approved_photos"])] )
        result[platform]={"ready":selected[:limit],"reserves":selected[limit:],"blockers":blockers,
                          "ready_count":len(selected[:limit]),"reserve_count":len(selected[limit:]),
                          "photo_quality":{name:quality[name] for name in ("MINIMAL","GOOD","EXCELLENT")},
                          "quarantine":[pid for pid,issues in blockers.items() if "DUPLICATE_QUARANTINE" in issues],
                          "replacement_required":sum("DUPLICATE_QUARANTINE" in issues for issues in blockers.values()),
                          "target_shortfall":max(0,limit-len(selected)),
                          "reserve_shortfall":max(0,policy["reserve_target"]-max(0,len(selected)-limit))}
    return result


def materialize(workspace, result, policy):
    root=Path(workspace)/"v4"/"POSTS_PRONTOS"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    for platform in PLATFORMS:
        for group in ("ready","reserves"):
            base=root/platform if group == "ready" else root/"RESERVAS"/platform
            base.mkdir(parents=True,exist_ok=True);blocks=[]
            for number,item in enumerate(result[platform][group],1):
                folder=base/item["id"];(folder/"imagens").mkdir(parents=True)
                body="\n".join([item["title"],*facts(item),f"Preço: {item['currency']} {item['price']}"])
                if policy["delivery_scope_confirmed"]:body+='\n'+policy["delivery_copy"]
                details=(f"ID: {item['id']}\nPLATFORM: {platform}\nPRICE: {item['currency']} {item['price']}\n"
                         f"CONDITION: {item.get('condition') or 'UNKNOWN'}\nSTATUS: READY_TO_POST\nLIVE: NO\n")
                if platform == "OLX":
                    details+=f"OPERATION_CITY: {policy['olx_operation_city']}\nOPERATION_UF: {policy['olx_operation_uf']}\nCEP: {policy.get('olx_operation_cep') or 'CONFIG_REQUIRED'}\n"
                for name,value in (("anuncio.txt",body),("dados.txt",details),
                                   ("source.txt",item["source_url"]),("validacao.txt","PREFLIGHT: PASS\nPUBLICATION: NOT_EXECUTED\n")):
                    (folder/name).write_text(value+'\n',encoding="utf-8")
                if platform == "FACEBOOK":(folder/"identificacoes.txt").write_text(item["category"]+'\n',encoding="utf-8")
                photos=item["approved_photos"]
                maximum=policy.get(platform.lower()+"_max_photos")
                if maximum is not None:photos=photos[:maximum]
                copied=[]
                for n,photo in enumerate(photos,1):
                    source=Path(photo["path"])
                    if hashlib.sha256(source.read_bytes()).hexdigest()!=photo["sha256"]:raise ValidationError("Photo changed after preflight")
                    target=folder/"imagens"/(f"{n:02}"+source.suffix.lower());shutil.copy2(source,target)
                    if hashlib.sha256(target.read_bytes()).hexdigest()!=photo["sha256"]:raise ValidationError("Photo copy mismatch")
                    copied.append({**photo,"path":str(target.resolve())})
                payload={"product_id":item["id"],"platform":platform,"title":item["title"],
                         "price":item["price"],"currency":item["currency"],"category":item["category"],
                         "condition":item.get("condition"),"description":body,"source_url":item["source_url"],
                         "photos":copied,"status":"READY_TO_POST","live_confirmed":False}
                if platform == "OLX":payload["operation_location"]={"city":policy["olx_operation_city"],"uf":policy["olx_operation_uf"],"cep":policy.get("olx_operation_cep")}
                atomic_json(folder/"payload.json",payload)
                blocks.append(f"POST {number:02}\n{body}\n")
            (base/"TODOS_OS_POSTS.txt").write_text('\n'.join(blocks),encoding="utf-8")
            atomic_json(base/"fila-ativa.json",{"agent_version":"V4","platform":platform,"role":group,"posts":result[platform][group]})
    # The current pointer advances only after every package has passed copying checks.
    atomic_json(Path(workspace)/"v4"/"current-batch.json",{"path":str(root),"agent_version":"V4"})
    return str(root)


def run(workspace, policy, catalog, action, *, feedback=None, confirmed=False):
    policy=settings(policy)
    if action == "feedback":return record_feedback(workspace,feedback,confirmed=confirmed)
    path=Path(workspace)/"v4"/"platform-feedback.json"
    history=read_json(path)["attempts"] if path.exists() else []
    # Legacy confirmed workflow states block repetition without inventing current LIVE evidence.
    legacy=Store(workspace).snapshot()["records"]
    projected=[]
    for raw in catalog:
        item=dict(raw);item["platform_status"]=dict(raw.get("platform_status",{}))
        if item["id"] in legacy and State(legacy[item["id"]]["state"]) in CONFIRMED_STATES:
            item["platform_status"][policy["legacy_platform"]]="NEEDS_REVIEW"
        projected.append(item)
    result=plan(projected,policy,history)
    if action == "prepare":result["output_directory"]=materialize(workspace,result,policy)
    return result
