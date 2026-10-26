"""Pure routing decisions and provider contracts; no SDK or model calls."""
from dataclasses import dataclass
from typing import Protocol
from .core import ValidationError, fingerprint, nonnegative

DETERMINISTIC = {"validate", "state", "metrics", "ids", "files", "csv", "json", "duplicates", "sort", "cache"}
QUALITATIVE = {"copy", "classification", "interpretation", "strategy", "hypothesis"}


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: str | None = None


class Provider(Protocol):
    def generate(self, prompt: str, *, model: str) -> GenerationResult: ...


@dataclass(frozen=True)
class Route:
    level: int | None
    reason: str
    cache_key: str


def route(task, payload, *, prompt_version="1", available_levels=(), failed_levels=(), allow_cloud=False, allow_premium=False):
    if task not in DETERMINISTIC | QUALITATIVE:
        raise ValidationError("Unknown task type")
    available, failed = set(available_levels), set(failed_levels)
    if any(type(level) is not int or level not in {1, 2, 3} for level in available | failed):
        raise ValidationError("Model levels must be 1, 2 or 3")
    if type(allow_cloud) is not bool or type(allow_premium) is not bool:
        raise ValidationError("Routing permissions must be boolean")
    key = fingerprint({"task": task, "payload": payload, "prompt_version": prompt_version})
    if task in DETERMINISTIC:
        return Route(0, "Use deterministic code", key)
    for level in sorted(available - failed):
        if level >= 2 and not allow_cloud:
            continue
        if level == 3 and not allow_premium:
            continue
        lower_available = {candidate for candidate in available if candidate < level}
        if not lower_available.issubset(failed):
            continue
        return Route(level, "Lowest permitted available level not already failed", key)
    return Route(None, "No permitted provider; human review or configure a local model", key)


def validate_benchmark(record):
    for field in ("input_tokens", "output_tokens", "retries", "tool_calls"):
        if record.get(field) is not None:
            nonnegative(record[field], field)
    if record.get("status") not in {"NOT_RUN", "SUCCESS", "FAILED"}:
        raise ValidationError("Invalid benchmark status")
