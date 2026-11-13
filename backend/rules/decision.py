"""
Critical decisions as plain Python. No LLM is involved here (Master Contract section 9.2).
Imported by: backend/services/report_pipeline.py

decide(assessment, transcript, retry_count) -> {"decision": <AI_DECISIONS value>,
                                                "escalation_reason": str | None}

assessment is the dict from gemini_vision.analyse_leaf()["assessment"], or None when the AI call failed.
retry_count = consecutive abstain reports from the same farm in the last ABSTAIN_RETRY_WINDOW_MIN minutes.
escalation_reason values (plain strings): AI_UNAVAILABLE, UNCLEAR_AFTER_RETRY, SEVERITY_KEYWORD,
MEDIUM_CONFIDENCE_HIGH_RISK.
"""
import re
import unicodedata

from shared.constants import (HIGH_RISK_ISSUES, SEVERITY_KEYWORDS, SEVERITY_KEYWORDS_HI,
                              SEVERITY_KEYWORDS_KN)


def _norm(text) -> str:
    """Unicode-normalise, lowercase and collapse whitespace so matching is reliable."""
    return " ".join(unicodedata.normalize("NFC", text or "").lower().split())


def has_severity_keyword(transcript) -> bool:
    """True if the farmer's words contain a severity keyword (English, Kannada or Hindi)."""
    text = _norm(transcript)
    if not text:
        return False
    # English: whole words only, so "studying" does not match "dying".
    for kw in SEVERITY_KEYWORDS:
        if re.search(r"(?<!\w)" + re.escape(_norm(kw)) + r"(?!\w)", text):
            return True
    # Kannada and Hindi: plain substring match. Checked for every transcript because
    # speech-to-text can mislabel the language.
    for kw in SEVERITY_KEYWORDS_KN + SEVERITY_KEYWORDS_HI:
        if _norm(kw) in text:
            return True
    return False


def _result(decision: str, reason=None) -> dict:
    return {"decision": decision, "escalation_reason": reason}


def decide(assessment, transcript, retry_count: int) -> dict:
    # 1. The AI call failed: a human must look at it.
    if not assessment:
        return _result("escalate_to_expert", "AI_UNAVAILABLE")

    issue = assessment.get("suspected_issue", "unknown")
    band = assessment.get("confidence_band", "low")
    quality = assessment.get("image_quality", "poor")

    # 2. Unclear evidence: ask for a better photo once, then escalate.
    if quality == "poor" or band == "low" or issue == "unknown":
        if retry_count <= 0:
            return _result("abstain_request_better_image")
        return _result("escalate_to_expert", "UNCLEAR_AFTER_RETRY")

    # 3. Concerning cases go to an expert.
    if has_severity_keyword(transcript):
        return _result("escalate_to_expert", "SEVERITY_KEYWORD")
    if band == "medium" and issue in HIGH_RISK_ISSUES:
        return _result("escalate_to_expert", "MEDIUM_CONFIDENCE_HIGH_RISK")

    # 4. Otherwise a preliminary (never confirmed) assessment.
    return _result("preliminary_assessment")