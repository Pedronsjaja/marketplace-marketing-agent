"""Validated domain objects and workflow transitions."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from urllib.parse import urlsplit


class ValidationError(ValueError):
    pass


class State(str, Enum):
    IDENTIFICADO = "IDENTIFICADO"
    COLETANDO = "COLETANDO"
    VALIDADO = "VALIDADO"
    PRONTO_PARA_PUBLICAR = "PRONTO_PARA_PUBLICAR"
    PUBLICADO = "PUBLICADO"
    LEAD_RECEBIDO = "LEAD_RECEBIDO"
    ENCAMINHADO = "ENCAMINHADO"
    VENDA = "VENDA"
    SEM_VENDA = "SEM_VENDA"
    ERRO = "ERRO"


TRANSITIONS = {
    State.IDENTIFICADO: {State.COLETANDO, State.ERRO},
    State.COLETANDO: {State.VALIDADO, State.ERRO},
    State.VALIDADO: {State.PRONTO_PARA_PUBLICAR, State.ERRO},
    State.PRONTO_PARA_PUBLICAR: {State.PUBLICADO, State.COLETANDO, State.ERRO},
    State.PUBLICADO: {State.LEAD_RECEBIDO, State.ERRO},
    State.LEAD_RECEBIDO: {State.ENCAMINHADO, State.VENDA, State.SEM_VENDA, State.ERRO},
    State.ENCAMINHADO: {State.LEAD_RECEBIDO, State.VENDA, State.SEM_VENDA, State.ERRO},
    State.VENDA: {State.LEAD_RECEBIDO, State.ENCAMINHADO, State.ERRO},
    State.SEM_VENDA: {State.LEAD_RECEBIDO, State.ENCAMINHADO, State.VENDA, State.ERRO},
    State.ERRO: {State.IDENTIFICADO},
}
CONFIRMED_STATES = {State.PUBLICADO, State.LEAD_RECEBIDO, State.ENCAMINHADO, State.VENDA, State.SEM_VENDA}


def transition(current, target, *, confirmed=False):
    current, target = State(current), State(target)
    if target not in TRANSITIONS[current]:
        raise ValidationError(f"Invalid transition: {current.value} -> {target.value}")
    if target in CONFIRMED_STATES and not confirmed:
        raise ValidationError("Operator confirmation required")
    return target.value


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValidationError("Invalid identifier")
    return value


def text(value, field, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f"Invalid {field}")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValidationError(f"Control character in {field}")
    return value.strip()


def web_url(value):
    value = text(value, "URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError("Expected HTTP(S) URL without credentials")
    return value


def nonnegative(value, field):
    if type(value) is not int or value < 0:
        raise ValidationError(f"{field} must be a nonnegative integer")
    return value


def product(raw):
    if not isinstance(raw, dict):
        raise ValidationError("Product must be an object")
    try:
        identifier(raw["id"])
        for field in ("title", "category", "currency"):
            text(raw[field], field, 200)
        if not re.fullmatch(r"[A-Z]{3}", raw["currency"]):
            raise ValidationError("currency must be a three-letter uppercase code")
        if not isinstance(raw["price"], str):
            raise ValidationError("price must be a decimal string")
        price = Decimal(raw["price"])
        if not price.is_finite() or price <= 0 or price.as_tuple().exponent < -2:
            raise ValidationError("price must be positive with at most two decimal places")
        web_url(raw["source_url"])
        date.fromisoformat(raw["verified_at"])
        if raw["verified"] is not True:
            raise ValidationError("Facts need explicit verification")
        if not isinstance(raw["facts"], list) or not raw["facts"]:
            raise ValidationError("At least one verified fact is required")
        for fact in raw["facts"]:
            text(fact, "fact", 500)
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValidationError("Missing or malformed product fields") from exc
    return dict(raw)


POLICY_FIELDS = {"channel", "allow_public_contact", "allow_groups", "allow_paid_promotion", "allow_free_shipping", "max_images"}


def config(raw):
    if not isinstance(raw, dict) or set(raw) != POLICY_FIELDS:
        raise ValidationError("Config must contain exactly the documented fields")
    identifier(raw["channel"])
    for field in POLICY_FIELDS - {"channel", "max_images"}:
        if type(raw[field]) is not bool:
            raise ValidationError(f"{field} must be boolean")
    if type(raw["max_images"]) is not int or not 1 <= raw["max_images"] <= 20:
        raise ValidationError("max_images must be an integer from 1 to 20")
    return dict(raw)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
