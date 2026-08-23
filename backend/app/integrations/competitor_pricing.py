"""Competitor price lookup used by dynamic recovery offers."""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx


class CompetitorPricingClient:
    """Read a price from merchant-supplied public pricing API metadata."""

    async def fetch_price(self, metadata: Dict[str, Any]) -> Optional[float]:
        configured = metadata.get("competitor_price_inr")
        if configured not in (None, ""):
            try:
                return float(configured)
            except (TypeError, ValueError):
                return None

        url = str(metadata.get("competitor_prices_url") or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return self._price_from_payload(payload)

    @staticmethod
    def _price_from_payload(payload: Any) -> Optional[float]:
        if isinstance(payload, dict):
            for key in ("competitor_price_inr", "competitor_price", "price", "lowest_price"):
                if payload.get(key) is not None:
                    try:
                        return float(payload[key])
                    except (TypeError, ValueError):
                        return None
            prices = payload.get("prices")
            if isinstance(prices, list):
                values = [CompetitorPricingClient._price_from_payload(item) for item in prices]
                valid = [value for value in values if value is not None]
                return min(valid) if valid else None
        return None


_default_client = CompetitorPricingClient()


def get_competitor_pricing_client() -> CompetitorPricingClient:
    return _default_client