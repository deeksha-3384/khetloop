"""Prints every reply in every language so a Kannada/Hindi speaker can review them.
Run:  python -m tests.backend.try_reply"""
from backend.services import reply_writer as rw

ASSESS = {"suspected_issue": "early_blight", "confidence_band": "medium", "image_quality": "good",
          "visible_symptoms": [], "confirmed": False}
CASES = {
    "preliminary": {"decision": "preliminary_assessment", "assessment": ASSESS},
    "healthy": {"decision": "preliminary_assessment", "assessment": {**ASSESS, "suspected_issue": "healthy"}},
    "abstain": {"decision": "abstain_request_better_image", "assessment": {**ASSESS, "image_quality": "poor"}},
    "escalate": {"decision": {"decision": "escalate_to_expert", "escalation_reason": "SEVERITY_KEYWORD"},
                 "assessment": ASSESS},
    "ai_down": {"decision": {"decision": "escalate_to_expert", "escalation_reason": "AI_UNAVAILABLE"},
                "assessment": None},
}
for lang in ("kn", "hi", "en"):
    print("=" * 20, lang, "=" * 20)
    for name, ctx in CASES.items():
        print("[%s] %s\n" % (name, rw.write_reply(ctx, lang)))
    print("[alert] %s\n" % rw.write_alert("tomato", "Kolar North", lang))
    print("[followup] %s\n" % rw.write_followup(lang))
    print("[expert] %s\n" % rw.write_expert_message("Remove affected leaves.", lang))