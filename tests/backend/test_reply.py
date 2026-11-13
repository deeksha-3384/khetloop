import json

import pytest

from backend.services import reply_writer as rw
from shared.constants import ALERT_TEMPLATE

LANGS = ["kn", "hi", "en"]
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


@pytest.fixture(autouse=True)
def no_guidance_file(tmp_path, monkeypatch):
    """Default: no approved_guidance.json present, so the built-in guidance is used."""
    monkeypatch.setattr(rw, "GUIDANCE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(rw, "USE_LLM_WORDING", False)


# ------------------------------------------------------------------ safety filter
@pytest.mark.parametrize("text", [
    "Use 5 ml per litre of water", "Mix 2.5 g in a tank", "apply 10 kg per acre", "Spray the leaves",
    "Apply mancozeb weekly", "use a fungicide", "Copper oxychloride works", "dose twice a week",
    "5 ML now", "it is an outbreak", "छिड़काव करें", "कीटनाशक डालें", "ಸಿಂಪಡಿಸಿ", "ಔಷಧ ಬಳಸಿ", "5 मिली डालें",
])
def test_unsafe_text_is_blocked(text):
    assert rw.is_safe(text) is False


@pytest.mark.parametrize("text", [
    "Please send a new photo in 2 days.", "Remove the 3 worst leaves.", "Keep 2 leaves apart.",
    "Remove affected leaves and keep foliage dry.",
])
def test_ordinary_text_with_numbers_is_allowed(text):
    assert rw.is_safe(text) is True


def test_empty_text_is_not_safe():
    assert rw.is_safe("   ") is False


# ------------------------------------------------------------------ replies
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("case", list(CASES))
def test_every_reply_is_safe_non_empty_and_has_no_placeholders(case, lang):
    text = rw.write_reply(CASES[case], lang)
    assert text and rw.is_safe(text)
    assert "{" not in text and "}" not in text
    assert "outbreak" not in text.lower()


@pytest.mark.parametrize("lang", LANGS)
def test_alert_followup_and_expert_texts_exist_and_are_clean(lang):
    assert "{" not in rw.write_alert("tomato", "Kolar North", lang)
    assert "Kolar North" in rw.write_alert("tomato", "Kolar North", lang)
    assert "outbreak" not in rw.write_alert("tomato", "Kolar North", lang).lower()
    assert rw.write_followup(lang)
    assert "Use it well" in rw.write_expert_message("Use it well", lang)


def test_english_alert_matches_the_contract_template():
    assert rw.write_alert("tomato", "Kolar North", "en") == ALERT_TEMPLATE.format(
        crop="tomato", area_label="Kolar North")


def test_alert_without_area_uses_a_fallback():
    assert "your area" in rw.write_alert("tomato", None, "en")


def test_unknown_language_falls_back_to_english():
    assert rw.write_reply(CASES["abstain"], "fr") == rw.TEXT["en"]["abstain"]


def test_blurry_and_escalated_replies_never_give_a_diagnosis():
    assert "early blight" not in rw.write_reply(CASES["abstain"], "en")
    assert "early blight" not in rw.write_reply(CASES["escalate"], "en")


def test_preliminary_reply_names_the_issue_and_says_not_confirmed():
    text = rw.write_reply(CASES["preliminary"], "en")
    assert "early blight" in text and "not a confirmed diagnosis" in text


# ------------------------------------------------------------------ approved guidance file
def _write_guidance(tmp_path, monkeypatch, data):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rw, "GUIDANCE_PATH", path)


def test_guidance_comes_from_the_approved_file(tmp_path, monkeypatch):
    _write_guidance(tmp_path, monkeypatch, {"early_blight": {"guidance": {"en": ["Thin the plants for airflow."]}}})
    assert "Thin the plants for airflow." in rw.write_reply(CASES["preliminary"], "en")


def test_unsafe_guidance_sentences_are_dropped(tmp_path, monkeypatch):
    _write_guidance(tmp_path, monkeypatch, {"early_blight": {"guidance": {"en": [
        "Spray mancozeb 2 g per litre.", "Remove affected leaves."]}}})
    text = rw.write_reply(CASES["preliminary"], "en")
    assert "mancozeb" not in text.lower() and "Remove affected leaves." in text


def test_all_unsafe_guidance_falls_back_to_builtin(tmp_path, monkeypatch):
    _write_guidance(tmp_path, monkeypatch, {"early_blight": {"guidance": {"en": ["Spray 5 ml per litre."]}}})
    assert rw.BUILTIN_GUIDANCE["en"] in rw.write_reply(CASES["preliminary"], "en")


def test_missing_language_in_file_uses_builtin_not_english(tmp_path, monkeypatch):
    _write_guidance(tmp_path, monkeypatch, {"early_blight": {"guidance": {"en": ["Only English here."]}}})
    assert rw.BUILTIN_GUIDANCE["kn"] in rw.write_reply(CASES["preliminary"], "kn")


def test_default_entry_is_used_for_issues_without_their_own(tmp_path, monkeypatch):
    _write_guidance(tmp_path, monkeypatch, {"default": {"guidance": {"en": ["General default advice."]}}})
    assert "General default advice." in rw.write_reply(CASES["preliminary"], "en")


def test_corrupt_guidance_file_does_not_crash(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(rw, "GUIDANCE_PATH", path)
    assert rw.BUILTIN_GUIDANCE["en"] in rw.write_reply(CASES["preliminary"], "en")


# ------------------------------------------------------------------ optional LLM wording
def _enable_llm(monkeypatch, reply):
    monkeypatch.setattr(rw, "USE_LLM_WORDING", True)
    monkeypatch.setattr(rw.Config, "GROQ_API_KEY", "x")
    monkeypatch.setattr(rw, "_llm_reword", lambda template, lang: reply)


def test_dosage_in_llm_output_is_replaced_by_the_template(monkeypatch):
    """Checklist test 19: forced LLM output containing '5 ml per litre' never reaches the farmer."""
    _enable_llm(monkeypatch, "This is a preliminary assessment, not confirmed. Mix 5 ml per litre mancozeb.")
    assert rw.write_reply(CASES["preliminary"], "en") == rw._template_reply(CASES["preliminary"], "en")


def test_llm_output_that_adds_numbers_is_rejected(monkeypatch):
    _enable_llm(monkeypatch, "Preliminary only, not a confirmed diagnosis. Check again in 7 days.")
    assert rw.write_reply(CASES["preliminary"], "en") == rw._template_reply(CASES["preliminary"], "en")


def test_llm_output_in_the_wrong_script_is_rejected(monkeypatch):
    _enable_llm(monkeypatch, "This is only a preliminary assessment, not a confirmed diagnosis.")
    assert rw.write_reply(CASES["preliminary"], "kn") == rw._template_reply(CASES["preliminary"], "kn")


def test_clean_llm_output_is_accepted(monkeypatch):
    nice = "This is only a preliminary look, not a confirmed diagnosis. It resembles early blight. Please be careful."
    _enable_llm(monkeypatch, nice)
    assert rw.write_reply(CASES["preliminary"], "en") == nice


def test_llm_failure_falls_back_to_the_template(monkeypatch):
    monkeypatch.setattr(rw, "USE_LLM_WORDING", True)
    monkeypatch.setattr(rw.Config, "GROQ_API_KEY", "x")

    def boom(template, lang):
        raise RuntimeError("down")

    monkeypatch.setattr(rw, "_llm_reword", boom)
    assert rw.write_reply(CASES["abstain"], "en") == rw.TEXT["en"]["abstain"]