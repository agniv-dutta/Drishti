"""Multilingual recovery messaging.

Detects each customer's language (explicit app preference > past-interaction
language > region hint > default) and renders SMS / email / IVR content from
DLT-style registered templates. Languages without a built-in template fall
back to LLM generation (friendly, <160 chars, culturally appropriate) and
finally to English - because localized outreach roughly doubles response
rates in the Indian market.
"""

from __future__ import annotations

import inspect
from enum import Enum
from typing import Callable, Dict, List, Optional

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.integrations.email_provider import EmailContent
from app.integrations.voice_provider import IVRScript


logger = get_logger("drishti.i18n")


class Language(str, Enum):
    ENGLISH = "en"
    HINDI = "hi"
    HINGLISH = "hinglish"
    TAMIL = "ta"


LANGUAGE_DISPLAY = {
    Language.ENGLISH: "English",
    Language.HINDI: "Hindi",
    Language.HINGLISH: "Hinglish",
    Language.TAMIL: "Tamil",
}

# Region hints -> language (only where confident; everything else falls through).
REGION_LANGUAGE = {
    "tamil nadu": Language.TAMIL,
    "tamilnadu": Language.TAMIL,
    "chennai": Language.TAMIL,
    "puducherry": Language.TAMIL,
    "uttar pradesh": Language.HINDI,
    "bihar": Language.HINDI,
    "madhya pradesh": Language.HINDI,
    "rajasthan": Language.HINDI,
    "delhi": Language.HINGLISH,
    "mumbai": Language.HINGLISH,
    "maharashtra": Language.HINGLISH,
}

_SMS_TEMPLATES: Dict[Language, str] = {
    Language.ENGLISH: (
        "Hi {name}, your payment of {amount} to {merchant} could not be processed. "
        "Retry securely here: {link}. Reply STOP to opt out."
    ),
    Language.HINDI: (
        "नमस्ते {name}, आपका {amount} का भुगतान असफल हो गया। "
        "यहां दोबारा कोशिश करें: {link}"
    ),
    Language.HINGLISH: (
        "Hi {name}, aapka {amount} ka payment fail ho gaya. Yaha retry karo: {link}"
    ),
    Language.TAMIL: (
        "வணக்கம் {name}, உங்கள் {amount} பணம் தோல்வி அடைந்தது. "
        "இங்கே மீண்டும் முயற்சிக்கவும்: {link}"
    ),
}

_EMAIL_SUBJECTS: Dict[Language, str] = {
    Language.ENGLISH: "Action needed: your payment of {amount} didn't go through",
    Language.HINDI: "ध्यान दें: आपका {amount} का भुगतान असफल हो गया",
    Language.HINGLISH: "Action needed: aapka {amount} ka payment fail ho gaya",
    Language.TAMIL: "செயல் தேவை: உங்கள் {amount} பணம் தோல்வி அடைந்தது",
}

_EMAIL_BODIES: Dict[Language, str] = {
    Language.ENGLISH: (
        "Hi {name},\n\nYour payment of {amount} to {merchant} failed.\n{cta}\n\n"
        "If you were charged, this amount will be auto-refunded in 5-7 days.\n\n- Team Drishti"
    ),
    Language.HINDI: (
        "नमस्ते {name},\n\nआपका {amount} का भुगतान {merchant} को असफल हो गया।\n{cta}\n\n"
        "यदि भुगतान कट गया है, तो राशि 5-7 दिनों में स्वतः वापस हो जाएगी।\n\n- Team Drishti"
    ),
    Language.HINGLISH: (
        "Hi {name},\n\nAapka {amount} ka payment {merchant} ko fail ho gaya.\n{cta}\n\n"
        "Agar paisa kat gaya tha, toh 5-7 din mein wapas aa jayega.\n\n- Team Drishti"
    ),
    Language.TAMIL: (
        "வணக்கம் {name},\n\n{merchant} க்கான உங்கள் {amount} பணம் தோல்வியடைந்தது.\n{cta}\n\n"
        "பணம் கட்டப்பட்டிருந்தால் 5-7 நாட்களில் திரும்பப் பெறலாம்.\n\n- Team Drishti"
    ),
}

_CTA_LINKED: Dict[Language, str] = {
    Language.ENGLISH: "Retry securely here: {link}",
    Language.HINDI: "यहां दोबारा कोशिश करें: {link}",
    Language.HINGLISH: "Yaha retry karo: {link}",
    Language.TAMIL: "இங்கே மீண்டும் முயற்சிக்கவும்: {link}",
}

_CTA_PLAIN: Dict[Language, str] = {
    Language.ENGLISH: "Please retry from the app.",
    Language.HINDI: "कृपया ऐप से दोबारा प्रयास करें।",
    Language.HINGLISH: "App se retry kar sakte hain.",
    Language.TAMIL: "செயலியில் மீண்டும் முயற்சிக்கவும்.",
}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
def detect_language(meta: Optional[Dict[str, str]] = None, default: Optional[Language] = None) -> Language:
    """Explicit preference > past interaction > region hint > configured default."""
    meta = meta or {}
    settings = get_settings()
    fallback = default or _safe_language(settings.default_language) or Language.ENGLISH

    for key in ("language", "language_preference", "preferred_language", "app_language"):
        value = str(meta.get(key, "")).strip().lower()
        if value:
            lang = _safe_language(value)
            if lang:
                return lang

    for key in ("last_response_language", "last_interaction_language"):
        value = str(meta.get(key, "")).strip().lower()
        if value:
            lang = _safe_language(value)
            if lang:
                return lang

    region = str(meta.get("region", "")).strip().lower()
    if region in REGION_LANGUAGE:
        return REGION_LANGUAGE[region]

    return fallback


def _safe_language(value: str) -> Optional[Language]:
    try:
        normalized = value.strip().lower()
        if normalized == "english":
            return Language.ENGLISH
        if normalized == "hindi":
            return Language.HINDI
        if normalized == "tamil":
            return Language.TAMIL
        return Language(normalized)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def render_sms(
    language: Language,
    customer_name: str,
    amount_str: str,
    merchant: str = "your merchant",
    payment_link: Optional[str] = None,
) -> str:
    first_name = customer_name.split(" ")[0]
    template = _SMS_TEMPLATES[language]
    message = template.format(
        name=first_name,
        amount=amount_str,
        merchant=merchant,
        link=payment_link or (_default_link_text(language)),
    )
    return message[:160]


def _default_link_text(language: Language) -> str:
    return {
        Language.ENGLISH: "your app",
        Language.HINDI: "ऐप",
        Language.HINGLISH: "app",
        Language.TAMIL: "செயலி",
    }[language]


def render_email(
    language: Language,
    customer_name: str,
    amount_str: str,
    merchant: str = "your merchant",
    payment_link: Optional[str] = None,
) -> LocalizedEmail:
    first_name = customer_name.split(" ")[0]
    cta = (
        _CTA_LINKED[language].format(link=payment_link)
        if payment_link
        else _CTA_PLAIN[language]
    )
    subject = _EMAIL_SUBJECTS[language].format(amount=amount_str)
    plain = _EMAIL_BODIES[language].format(name=first_name, amount=amount_str, merchant=merchant, cta=cta)
    html_cta = (
        f'<a href="{payment_link}" style="background:#0ea5e9;color:#fff;padding:12px 24px;'
        'border-radius:6px;text-decoration:none">Complete Payment</a>'
        if payment_link
        else _CTA_PLAIN[language]
    )
    html = f"<p>{plain.replace(chr(10), '<br>')}</p><p>{html_cta}</p>"
    return EmailContent(subject=subject, plain=plain, html=html)


def render_voice_script(
    language: Language,
    customer_name: str,
    amount_str: str,
    merchant: str = "merchant",
    payment_link: Optional[str] = None,
) -> IVRScript:
    first_name = customer_name.split(" ")[0]
    scripts: Dict[Language, List[str]] = {
        Language.ENGLISH: [
            f"Hello {first_name}! This is Drishti calling on behalf of {merchant}.",
            f"Your payment of {amount_str} could not be processed earlier.",
            "You can complete it securely now - we have sent you a payment link by SMS.",
            "Thank you!",
        ],
        Language.HINDI: [
            f"नमस्ते {first_name} जी! मैं Drishti की ओर से बोल रही हूँ।",
            f"आपका {amount_str} का भुगतान {merchant} को असफल हो गया था।",
            "आपको SMS में payment link भेज दिया गया है, वहां से सुरक्षित भुगतान करें।",
            "धन्यवाद!",
        ],
        Language.HINGLISH: [
            f"Namaste {first_name} ji! Main Drishti se bol rahi hoon.",
            f"Aapki {amount_str} ki payment {merchant} ko fail ho gayi thi.",
            "Link aapke phone par SMS mein bhej diya hai - wahan se turant payment kar sakte hain.",
            "Dhanyavaad!",
        ],
        Language.TAMIL: [
            f"வணக்கம் {first_name}! {merchant} சார்பாக Drishti பேசுகிறது.",
            f"உங்கள் {amount_str} பணம் தோல்வியடைந்தது.",
            "SMS-ல் payment link அனுப்பப்பட்டுள்ளது, அதன் மூலம் செலுத்தலாம்.",
            "நன்றி!",
        ],
    }
    return IVRScript(lines=scripts[language], language=language.value)


# ---------------------------------------------------------------------------
# LLM generation for languages without registered templates
# ---------------------------------------------------------------------------
LLM_SMS_PROMPT = (
    "Generate an SMS recovery message in {language_display} for a payment amount of {amount}. "
    "The customer's first name is {name}. Tone: Friendly, not pushy. Under 160 characters. "
    "Include a retry instruction. Be culturally appropriate. Reply with the SMS text only."
)


async def generate_sms_via_llm(
    llm_fn: Callable[[str, str], Optional[str]],
    language: Language,
    customer_name: str,
    amount_str: str,
    merchant: str = "your merchant",
) -> Optional[str]:
    """LLM-authored SMS for ad-hoc locales; validated before use."""
    prompt = LLM_SMS_PROMPT.format(
        language_display=LANGUAGE_DISPLAY[language],
        amount=amount_str,
        name=customer_name.split(" ")[0],
        merchant=merchant,
    )
    system = (
        "You are an expert Indian-market copywriter for payment recovery SMS. "
        "Write only the final SMS body, no quotes, no explanations."
    )
    text = llm_fn(system, prompt)
    if inspect.isawaitable(text):
        text = await text
    if not text:
        return None
    cleaned = " ".join(text.strip().strip('"').split())
    if not cleaned or len(cleaned) > 160:
        logger.warning("i18n.llm_sms_rejected", length=len(cleaned))
        return None
    return cleaned
