"""Groq-powered advisory capabilities for merchant recovery workflows.

The advisor enriches deterministic agent decisions; it never executes recovery
actions. When Groq is unavailable, each operation returns a useful fallback so
the recovery pipeline remains operational.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from app.agents.base_agent import BaseAgent
from app.core.config import get_settings


class GroqAdvisor(BaseAgent):
    """LLM advisor, message generator, and compliance protector."""

    name = "groq_advisor"
    description = "Provides contextual recovery insights without making decisions."

    def __init__(self, api_key: Optional[str] = None) -> None:
        super().__init__()
        self.api_key = api_key or get_settings().groq_api_key
        self.model = get_settings().groq_model

    async def run(self, *args: Any, **kwargs: Any) -> None:
        """The advisor exposes named capabilities rather than a single run."""
        raise NotImplementedError("Use a named GroqAdvisor capability")

    async def _complete(self, system: str, prompt: str) -> Optional[str]:
        return await asyncio.to_thread(self.llm_complete, system, prompt)

    @staticmethod
    def _json_response(text: Optional[str], fallback: Dict[str, Any]) -> Dict[str, Any]:
        if not text:
            return fallback
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return fallback
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return fallback
        return value if isinstance(value, dict) else fallback

    async def analyze_merchant_performance(self, merchant_id: str, metrics: dict) -> str:
        prompt = f"""Analyze merchant recovery performance and give concise, actionable advice.
Merchant: {merchant_id}
Metrics: {json.dumps(metrics, default=str)}
Explain differences between strategies, recommend one next step, estimate recovery-rate impact,
and mention risks. Keep the answer under 150 words and distinguish facts from estimates."""
        return (await self._complete(
            "You are a revenue recovery advisor. Do not invent facts or take actions.", prompt
        )) or "Insufficient data for an LLM analysis. Continue the current strategy and collect more outcomes."

    async def generate_personalized_message(
        self, payment: dict, customer: dict, strategy: str
    ) -> str:
        prompt = f"""Write one payment-recovery SMS under 160 characters.
Customer: {json.dumps(customer, default=str)}
Payment: {json.dumps(payment, default=str)}
Strategy: {strategy}
Use the customer's preferred language when supplied. Be friendly and professional, include [link],
and reply with only the SMS text."""
        result = await self._complete(
            "You write compliant, non-coercive payment recovery messages.", prompt
        )
        if result:
            return " ".join(result.strip().strip('"').split())[:160]
        name = str(customer.get("name", "there")).split()[0]
        amount = payment.get("amount", payment.get("amount_inr", "the payment"))
        return f"Hi {name}, your payment of INR {amount} could not be processed. Retry securely: [link]"

    async def check_compliance_risks(
        self, payment: dict, customer: dict, strategy: str, action: str
    ) -> dict:
        prompt = f"""Assess this payment-recovery action for compliance.
Customer: {json.dumps(customer, default=str)}
Payment: {json.dumps(payment, default=str)}
Strategy: {strategy}; action: {action}
Return JSON with compliance_approved, regulation, precautions, risks, and recommended_action.
Flag uncertainty instead of asserting jurisdiction-specific legal advice."""
        fallback = {
            "compliance_approved": False,
            "regulation": "Manual review required",
            "precautions": ["Verify consent, jurisdiction, and contact hours before sending"],
            "risks": ["LLM compliance assessment is unavailable"],
            "recommended_action": "Pause and obtain a compliance review",
        }
        return self._json_response(await self._complete("You are a cautious compliance assistant.", prompt), fallback)

    async def suggest_strategy_optimization(self, payment: dict, history: dict) -> dict:
        prompt = f"""Suggest one recovery strategy based on this payment and historical outcomes.
Payment: {json.dumps(payment, default=str)}
History: {json.dumps(history, default=str)}
Return JSON with suggested_strategy, rationale, expected_success_rate, improvement_vs_current,
offer_details, timing, and confidence. Recommendations are advisory only."""
        fallback = {
            "suggested_strategy": payment.get("current_strategy", "smart_retry"),
            "rationale": "Insufficient historical data for optimization",
            "expected_success_rate": payment.get("current_confidence", 0.0),
            "improvement_vs_current": "0%",
            "offer_details": {},
            "timing": "immediate",
            "confidence": 0.0,
        }
        return self._json_response(await self._complete("You optimize recovery strategies conservatively.", prompt), fallback)

    async def predict_customer_intent(self, customer: dict, payment: dict) -> dict:
        prompt = f"""Predict whether this customer will retry a failed payment without contact.
Customer: {json.dumps(customer, default=str)}
Payment: {json.dumps(payment, default=str)}
Return JSON with will_self_recover, recovery_probability, expected_time_hours, reasoning, and recommendation."""
        fallback = {
            "will_self_recover": False,
            "recovery_probability": 0.3,
            "expected_time_hours": 24,
            "reasoning": "Unable to predict without the LLM",
            "recommendation": "contact customer",
        }
        return self._json_response(await self._complete("You make calibrated, explainable predictions.", prompt), fallback)

    async def explain_anomaly(self, anomaly: str, context: dict) -> str:
        prompt = f"""Explain this recovery-metric anomaly using only the supplied facts.
Anomaly: {anomaly}
Context: {json.dumps(context, default=str)}
Cover likely root cause, strategy changes, whether it is concerning, and one recommended action.
Keep the answer under 150 words and label uncertainty."""
        return (await self._complete("You explain operational metrics precisely and cautiously.", prompt)) or (
            "An explanation is unavailable because the LLM is not configured. Review the supplied "
            "events and strategy deltas manually."
        )