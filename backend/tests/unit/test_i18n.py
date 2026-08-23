"""Tests for multilingual recovery messaging (app.i18n.messages)."""

from __future__ import annotations

import pytest

from app.agents.executor_agent import ExecutorAgent
from app.i18n.messages import (
    LANGUAGE_DISPLAY,
    LLM_SMS_PROMPT,
    Language,
    detect_language,
    generate_sms_via_llm,
    render_email,
    render_sms,
    render_voice_script,
)
from app.integrations.email_provider import EmailContent
from app.integrations.sms_provider import MessageResult
from app.models.payment import (
    CustomerInfo,
    FailureReason,
    PaymentMethod,
    PaymentStatus,
    PaymentTransaction,
)
from app.models.recovery import RecoveryChannel, RecoveryStep


def _txn(meta: dict | None = None) -> PaymentTransaction:
    return PaymentTransaction(
        payment_id="pay_i18n_1",
        order_id="order_i18n_1",
        customer=CustomerInfo(name="Ravi Kumar", email="ravi@example.com", phone="+919812345678"),
        amount_paise=500000,
        method=PaymentMethod.CARD,
        status=PaymentStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        attempt_number=1,
        meta=meta or {},
    )


# ---------------------------------------------------------------------------
# detection priority chain
# ---------------------------------------------------------------------------
class TestDetectLanguage:
    def test_explicit_meta_preference_wins(self):
        assert detect_language({"language": "hi", "region": "tamil nadu"}) is Language.HINDI

    def test_accepts_preference_alias(self):
        assert detect_language({"preferred_language": "hinglish"}) is Language.HINGLISH

    def test_past_interaction_language_second(self):
        assert (
            detect_language({"last_response_language": "ta", "region": "bihar"})
            is Language.TAMIL
        )

    def test_region_hint_used_when_no_explicit(self):
        assert detect_language({"region": "Tamil Nadu"}) is Language.TAMIL
        assert detect_language({"region": "delhi"}) is Language.HINGLISH

    def test_defaults_to_settings_default(self):
        assert detect_language({}) is Language.ENGLISH
        assert detect_language(None) is Language.ENGLISH

    def test_unknown_values_fall_through_chain(self):
        txn = {"language": "klingon", "last_response_language": "hindi"}
        assert detect_language(txn) is Language.HINDI  # explicit invalid, past valid


# ---------------------------------------------------------------------------
# template rendering
# ---------------------------------------------------------------------------
class TestRenderers:
    @pytest.mark.parametrize("lang,marker", [
        (Language.ENGLISH, "Hi Ravi"),
        (Language.HINDI, "नमस्ते Ravi"),
        (Language.HINGLISH, "aapka ₹5,000 ka payment fail ho gaya"),
        (Language.TAMIL, "வணக்கம் Ravi"),
    ])
    def test_sms_templates_render_per_language(self, lang, marker):
        message = render_sms(lang, "Ravi Kumar", "₹5,000")
        assert marker in message
        assert len(message) <= 160

    def test_sms_with_link_includes_it(self):
        msg = render_sms(Language.HINDI, "Priya", "₹1,200", payment_link="https://rzp.io/i/abc123")
        assert "https://rzp.io/i/abc123" in msg
        assert "यहां दोबारा कोशिश करें" in msg

    def test_sms_hard_cap_160_chars(self):
        long_name = "Verylongfirstnamethatkeepsgoing" * 6
        assert len(render_sms(Language.ENGLISH, long_name, "₹9,999")) <= 160

    @pytest.mark.parametrize("lang,subject_marker", [
        (Language.ENGLISH, "Action needed"),
        (Language.HINDI, "ध्यान दें"),
        (Language.TAMIL, "செயல் தேவை"),
    ])
    def test_email_renders_subject_plain_html(self, lang, subject_marker):
        content = render_email(lang, "Anita Rao", "₹3,400")
        assert isinstance(content, EmailContent)
        assert subject_marker in content.subject
        assert "₹3,400" in content.plain and "₹3,400" in content.subject
        assert content.html  # non-empty html body

    def test_voice_script_language_tagged(self):
        script = render_voice_script(Language.HINGLISH, "Sana", "₹2,000")
        assert script.language == "hinglish"
        assert any("Namaste Sana ji" in line for line in script.lines)

    def test_every_language_has_full_template_set(self):
        for lang in Language:
            assert lang in LANGUAGE_DISPLAY
            assert render_sms(lang, "X Y", "₹1") and len(render_sms(lang, "X Y", "₹1")) <= 160
            assert render_email(lang, "X Y", "₹1").plain
            assert render_voice_script(lang, "X Y", "₹1").lines


# ---------------------------------------------------------------------------
# LLM generation fallback
# ---------------------------------------------------------------------------
class TestLLMGeneration:
    async def test_valid_llm_output_is_used(self):
        async def fake_llm(system, prompt):
            return '"Hi Aman, aapka ₹800 ka payment fail hua. Turant retry karo: app link."'

        text = await generate_sms_via_llm(fake_llm, Language.HINGLISH, "Aman Verma", "₹800")
        assert text is not None
        assert text.startswith("Hi Aman")  # quotes stripped
        assert len(text) <= 160

    async def test_overlong_output_rejected(self):
        async def fake_llm(system, prompt):
            return "x" * 180

        assert await generate_sms_via_llm(fake_llm, Language.HINDI, "Neha", "₹900") is None

    async def test_empty_output_rejected(self):
        async def fake_llm(system, prompt):
            return ""

        assert await generate_sms_via_llm(fake_llm, Language.TAMIL, "Vikram", "₹700") is None

    def test_prompt_carries_language_amount_and_tone_rules(self):
        prompt = LLM_SMS_PROMPT.format(language_display="Tamil", amount="₹450", name="Arun", merchant="your merchant")
        assert "Tamil" in prompt
        assert "₹450" in prompt
        assert "Under 160 characters" in prompt
        assert "culturally appropriate" in prompt.lower()


# ---------------------------------------------------------------------------
# executor integration - localized sends per detected language
# ---------------------------------------------------------------------------
class FakeSMSProvider:
    name = "fake"

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, to_phone, message):
        self.sent.append(message)
        return MessageResult(True, self.name, "ref-sms-1")


@pytest.mark.asyncio
async def test_executor_sms_respects_customer_language(monkeypatch):
    provider = FakeSMSProvider()
    monkeypatch.setattr(
        "app.agents.executor_agent.get_sms_provider", lambda: provider
    )
    agent = ExecutorAgent()
    step = RecoveryStep(sequence=1, channel=RecoveryChannel.SMS, delay_minutes=0, estimated_cost_paise=10)
    detail, reference, _ = await agent._do_sms(_txn({"language": "hi"}), step)

    assert "[hi]" in detail and reference == "ref-sms-1"
    assert "नमस्ते Ravi" in provider.sent[0]


@pytest.mark.asyncio
async def test_executor_sms_defaults_to_english(monkeypatch):
    provider = FakeSMSProvider()
    monkeypatch.setattr(
        "app.agents.executor_agent.get_sms_provider", lambda: provider
    )
    agent = ExecutorAgent()
    step = RecoveryStep(sequence=1, channel=RecoveryChannel.SMS, delay_minutes=0, estimated_cost_paise=10)
    detail, _, _ = await agent._do_sms(_txn({}), step)

    assert "[en]" in detail
    assert provider.sent[0].startswith("Hi Ravi")



