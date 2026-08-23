from app.ml.voice_emotion import VoiceEmotion, VoiceEmotionAnalyzer


def test_angry_customer_is_sent_to_human_without_offer():
    decision = VoiceEmotionAnalyzer().analyze("This is unacceptable, I am angry and frustrated")

    assert decision.emotion is VoiceEmotion.ANGRY
    assert decision.next_action == "transfer_to_human_empathy_agent"
    assert "connect you with a human" in decision.reply
    assert "payment" not in decision.reply.lower()


def test_hesitant_customer_gets_no_fee_installment_reassurance():
    decision = VoiceEmotionAnalyzer().analyze("I am worried and unsure, maybe later")

    assert decision.emotion is VoiceEmotion.HESITANT
    assert decision.next_action == "offer_installment_plan"
    assert "three payments" in decision.reply
    assert "no extra charges" in decision.reply


def test_happy_customer_gets_upsell_and_nps_prompt():
    decision = VoiceEmotionAnalyzer().analyze("That was excellent and very helpful, thank you")

    assert decision.emotion is VoiceEmotion.HAPPY
    assert decision.next_action == "offer_upsell_and_collect_nps"
    assert "1 to 10" in decision.reply