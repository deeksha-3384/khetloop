"""
Builds the 'Why am I seeing this?' list. Every item is {"code": <WHY_CODES value>, "text": str}.
Imported by: backend/services/report_pipeline.py

build_why(assessment, weather, nearby_count, decision, history_count=0) -> list[dict]
decision can be the dict from decide() or just the decision string.
When assessment is None (AI failed) the LOW_CONFIDENCE code carries the 'AI unavailable' message,
because WHY_CODES has no dedicated code for it.
"""
from shared.constants import RADAR_TIME_WINDOW_HOURS


def _decision_name(decision) -> str:
    if isinstance(decision, dict):
        return decision.get("decision", "")
    return decision or ""


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def build_why(assessment, weather, nearby_count: int, decision, history_count: int = 0) -> list:
    why = []
    decision_name = _decision_name(decision)

    if not assessment:
        why.append({"code": "LOW_CONFIDENCE",
                    "text": "The automatic photo analysis was not available, so an expert will review this report."})
    else:
        issue = assessment.get("suspected_issue", "unknown")
        band = assessment.get("confidence_band", "low")
        quality = assessment.get("image_quality", "poor")

        if quality == "poor":
            why.append({"code": "IMAGE_QUALITY", "text": "The photo is too blurry, dark or unclear to assess."})
        elif issue != "unknown" and decision_name != "abstain_request_better_image":
            if issue == "healthy":
                text = "The photo shows no clear disease symptoms."
            else:
                text = "The photo shows visible symptoms resembling %s." % issue.replace("_", " ")
            why.append({"code": "IMAGE_SYMPTOMS", "text": text})

        if band == "low" or issue == "unknown":
            why.append({"code": "LOW_CONFIDENCE",
                        "text": "The assessment confidence is low, so no result is given."})

    if nearby_count > 0:
        why.append({"code": "NEARBY_REPORTS",
                    "text": "%d similar %s submitted nearby in the last %d hours." % (
                        nearby_count,
                        _plural(nearby_count, "report was", "reports were"),
                        RADAR_TIME_WINDOW_HOURS)})

    if weather:
        label = "%s forecast" % weather.get("data_source", "live")
        if weather.get("rain_expected"):
            text = "Rain is forecast in the next 48 hours (%s)." % label
        else:
            text = "No rain is forecast in the next 48 hours (%s)." % label
        why.append({"code": "WEATHER_CONTEXT", "text": text})

    if history_count > 0:
        why.append({"code": "FARM_HISTORY",
                    "text": "This farm has %d earlier %s on record." % (
                        history_count, _plural(history_count, "report", "reports"))})

    why.append({"code": "NOT_CONFIRMED",
                "text": "This is a preliminary assessment, not a confirmed diagnosis."})
    return why