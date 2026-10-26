"""Channel contract and an explicitly manual initial adapter."""
from typing import Protocol


class Channel(Protocol):
    name: str

    def draft(self, product: dict) -> str: ...


class ManualMarketplace:
    name = "manual-marketplace"

    def draft(self, product):
        facts = "\n".join("- " + fact for fact in product["facts"])
        return f'{product["title"]}\n{product["currency"]} {product["price"]}\n{facts}\n'

    def checklist(self):
        return [
            "Review verified facts, price, availability and image rights.",
            "Open the chosen channel yourself and review its current rules.",
            "Confirm publication in the platform, then record the listing URL locally.",
            "Stop for authentication, CAPTCHA or platform restrictions.",
        ]
