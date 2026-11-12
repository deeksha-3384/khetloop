import base64

from backend.services import gemini_vision as gv

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
GOOD = '{"suspected_issue":"early_blight","confidence_band":"medium","image_quality":"good","visible_symptoms":["brown spots"]}'


def test_parse_json_inside_fence():
    assert gv._parse_model_json("```json\n" + GOOD + "\n```")["suspected_issue"] == "early_blight"


def test_normalise_bad_values_become_safe_defaults():
    out = gv._normalise({"suspected_issue": "alien_rot", "confidence_band": "super", "image_quality": "ok",
                         "visible_symptoms": "not a list", "confirmed": True})
    assert out == {"suspected_issue": "unknown", "confidence_band": "low", "image_quality": "poor",
                   "visible_symptoms": [], "confirmed": False}


def test_invalid_image_is_rejected():
    res = gv.analyse_leaf(b"this is not an image", "tomato", None)
    assert res["ok"] is False and res["error"]["code"] == "INVALID_REQUEST"


def test_no_keys_means_ai_unavailable(monkeypatch):
    monkeypatch.setattr(gv.Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(gv.Config, "GEMINI_API_KEY", "")
    res = gv.analyse_leaf(PNG, "tomato", None)
    assert res["ok"] is False and res["error"]["code"] == "AI_UNAVAILABLE"


def test_success_with_groq(monkeypatch):
    monkeypatch.setattr(gv.Config, "GROQ_API_KEY", "x")
    monkeypatch.setattr(gv, "_call_groq", lambda b64, mime, prompt: GOOD)
    res = gv.analyse_leaf(PNG, "tomato", "spots on leaves")
    assert res["ok"] and res["provider"] == "groq"
    assert res["assessment"]["confirmed"] is False


def test_falls_back_to_gemini_when_groq_fails(monkeypatch):
    monkeypatch.setattr(gv.Config, "GROQ_API_KEY", "x")
    monkeypatch.setattr(gv.Config, "GEMINI_API_KEY", "y")

    def boom(b64, mime, prompt):
        raise RuntimeError("groq down")

    monkeypatch.setattr(gv, "_call_groq", boom)
    monkeypatch.setattr(gv, "_call_gemini", lambda b64, mime, prompt: GOOD)
    res = gv.analyse_leaf(PNG, "tomato", None)
    assert res["ok"] and res["provider"] == "gemini"


def test_garbage_model_reply_fails_cleanly(monkeypatch):
    monkeypatch.setattr(gv.Config, "GROQ_API_KEY", "x")
    monkeypatch.setattr(gv.Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(gv, "_call_groq", lambda b64, mime, prompt: "sorry I cannot help")
    res = gv.analyse_leaf(PNG, "tomato", None)
    assert res["ok"] is False and res["error"]["code"] == "AI_UNAVAILABLE"

def test_parse_ignores_think_block_and_extra_text():
    reply = '<think>maybe {"a": 1} hmm</think> Here you go: ' + GOOD + " Hope this helps."
    assert gv._parse_model_json(reply)["suspected_issue"] == "early_blight"