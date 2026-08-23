"""Consent-aware emotion classification for voice recovery transcripts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VoiceEmotion(str, Enum):
    ANGRY = "angry"
    HESITANT = "hesitant"
    HAPPY = "happy"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class EmotionDecision:
    sentiment: float
    emotion: VoiceEmotion
    next_action: str
    reply: str


class VoiceEmotionAnalyzer:
    """Small local classifier; a transcript from any STT provider is accepted."""

    _negative = {"angry", "upset", "terrible", "frustrated", "unacceptable", "hate", "problem", "complaint"}
    _positive = {"happy", "great", "thanks", "thank", "excellent", "love", "helpful", "easy"}
    _hesitant = {"maybe", "unsure", "worry", "worried", "expensive", "later", "not sure", "think"}

    def analyze(self, transcript: str, customer_name: str = "") -> EmotionDecision:
        text = transcript.strip().lower()
        negative = sum(word in text for word in self._negative)
        positive = sum(word in text for word in self._positive)
        hesitant = sum(word in text for word in self._hesitant)
        sentiment = max(-1.0, min(1.0, (positive - negative) * 0.3 - hesitant * 0.1))
        if negative and sentiment >= -0.5:
            sentiment = -0.6
        if positive and sentiment <= 0.5:
            sentiment = 0.6

        if sentiment < -0.5:
            emotion = VoiceEmotion.ANGRY
            action = "transfer_to_human_empathy_agent"
            reply = "I am sorry this has been frustrating. I will connect you with a human teammate who can help right away."
        elif -0.2 <= sentiment <= 0.2:
            emotion = VoiceEmotion.HESITANT
            action = "offer_installment_plan"
            reply = "I understand. We can make this easier with three payments and no extra charges."
        elif sentiment > 0.5:
            emotion = VoiceEmotion.HAPPY
            action = "offer_upsell_and_collect_nps"
            reply = "I am glad we could help. While we are here, would you like to hear about another product? How happy are you with us from 1 to 10?"
        else:
            emotion = VoiceEmotion.NEUTRAL
            action = "continue_standard_recovery"
            reply = "We can help you complete the payment securely whenever you are ready."
        return EmotionDecision(round(sentiment, 3), emotion, action, reply)


_default_analyzer = VoiceEmotionAnalyzer()


def get_voice_emotion_analyzer() -> VoiceEmotionAnalyzer:
    return _default_analyzer