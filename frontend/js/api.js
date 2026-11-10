/* KhetLoop API layer (owner: P3)
 * One function per endpoint (contract section 6). Every page uses ONLY these.
 * Every function returns:
 *   success: { ok: true,  data: {...} }
 *   failure: { ok: false, error: { code, message } }
 * It never throws. Network failures return error.code = "NETWORK_ERROR"
 * (client-side code, not in ERROR_CODES).
 * Requires config.js and constants.js to be loaded first.
 */

const REQUEST_TIMEOUT_MS = 15000;
const UPLOAD_TIMEOUT_MS = 60000;   // report uploads wait for AI processing
const MOCK_LATENCY_MS = 350;       // fake delay so loading states are visible

/* ---------------- helpers ---------------- */

function _err(code, message) {
  return { ok: false, error: { code: code, message: message } };
}

function _sleep(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

function _hex8() {
  var s = "";
  for (var i = 0; i < 8; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

function _nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function _statusError(status) {
  switch (status) {
    case 400: return _err("INVALID_REQUEST", "The request was not valid.");
    case 401: return _err("UNAUTHORIZED", "Expert access key is missing or incorrect.");
    case 404: return _err("NOT_FOUND", "The requested item was not found.");
    case 409: return _err("CONFLICT", "This item was already updated.");
    default:  return _err("INTERNAL_ERROR", "The server had a problem (HTTP " + status + "). Please try again.");
  }
}

/* Fetches a URL and ALWAYS resolves to an envelope. */
async function _fetchEnvelope(url, options, timeoutMs) {
  var controller = new AbortController();
  var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
  try {
    var res = await fetch(url, Object.assign({}, options, { signal: controller.signal }));
    var json = null;
    try { json = await res.json(); } catch (e) { json = null; }

    if (json && typeof json.ok === "boolean") {
      if (json.ok) {
        if (json.data === undefined || json.data === null) {
          return _err("INTERNAL_ERROR", "The server returned an empty response.");
        }
        return json;
      }
      var e = json.error || {};
      return _err(e.code || _statusError(res.status).error.code,
                  e.message || _statusError(res.status).error.message);
    }
    if (!res.ok) return _statusError(res.status);
    return _err("INTERNAL_ERROR", "The server sent an unexpected response.");
  } catch (e) {
    if (e && e.name === "AbortError") {
      return _err("NETWORK_ERROR", "The server took too long to respond. Please try again.");
    }
    return _err("NETWORK_ERROR", "Cannot reach the KhetLoop server. Check that it is running and you are online.");
  } finally {
    clearTimeout(timer);
  }
}

/* Live request to Flask. opts: { body, form, expert } */
function _real(method, path, opts) {
  opts = opts || {};
  var headers = { "Accept": "application/json" };
  if (opts.expert) headers["X-Expert-Key"] = EXPERT_KEY;
  var init = { method: method, headers: headers };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  } else if (opts.form) {
    init.body = opts.form; // browser sets multipart boundary itself
  }
  return _fetchEnvelope(API_BASE + path, init, opts.form ? UPLOAD_TIMEOUT_MS : REQUEST_TIMEOUT_MS);
}

/* Mock request: reads MOCK_BASE + file. */
async function _mockFile(name) {
  await _sleep(MOCK_LATENCY_MS);
  var r = await _fetchEnvelope(MOCK_BASE + name, { cache: "no-store" }, REQUEST_TIMEOUT_MS);
  if (!r.ok && r.error.code === "NOT_FOUND") {
    return _err("NOT_FOUND", "Mock file missing: " + MOCK_BASE + name);
  }
  return r;
}

/* ---------------- mock-only session state ---------------- */
/* Remembers reviews submitted in mock mode so the dashboard, report and
   timeline pages stay consistent during a demo. Resets on page reload. */
var _mockReviewed = {};

var _MOCK_REPORT_FILES = [
  "report_escalated.json", "report_expert_reviewed.json",
  "report_preliminary.json", "report_abstain.json"
];

async function _mockReport(id) {
  var lastError = null;
  for (var i = 0; i < _MOCK_REPORT_FILES.length; i++) {
    var r = await _mockFile(_MOCK_REPORT_FILES[i]);
    if (!r.ok) { lastError = r; continue; }
    if (r.data.id === id) {
      var rev = _mockReviewed[id];
      if (rev && !r.data.expert_review) {
        r.data.status = "expert_reviewed";
        r.data.expert_review = rev;
        r.data.assessment.confirmed = rev.confirmed_issue !== null;
        r.data.events.push({ status: "expert_reviewed", actor: "expert", timestamp: rev.created_at });
      }
      return r;
    }
  }
  if (lastError && lastError.error.code !== "NOT_FOUND") return lastError;
  return _err("NOT_FOUND", "Report not found");
}

/* ---------------- endpoint functions ---------------- */

/* 3. GET /api/farms */
function listFarms() {
  return USE_MOCK ? _mockFile("farms.json") : _real("GET", "/api/farms");
}

/* 2. GET /api/reports/<id> */
function getReport(id) {
  if (!id) return Promise.resolve(_err("INVALID_REQUEST", "Report id is missing."));
  return USE_MOCK ? _mockReport(id)
                  : _real("GET", "/api/reports/" + encodeURIComponent(id));
}

/* 4. GET /api/farms/<farm_id>/timeline */
async function getFarmTimeline(farmId) {
  if (!farmId) return _err("INVALID_REQUEST", "Farm id is missing.");
  if (!USE_MOCK) return _real("GET", "/api/farms/" + encodeURIComponent(farmId) + "/timeline");
  var r = await _mockFile("farm_timeline.json");
  if (r.ok) {
    r.data.items.forEach(function (item) {
      var rev = _mockReviewed[item.report_id];
      if (rev) { item.status = "expert_reviewed"; item.expert_guidance = rev.guidance; }
    });
  }
  return r;
}

/* 5. GET /api/expert/cases?status=  (key required) */
async function listExpertCases(status) {
  var wanted = status || "expert_review_pending";
  if (!USE_MOCK) {
    return _real("GET", "/api/expert/cases?status=" + encodeURIComponent(wanted), { expert: true });
  }
  var r = await _mockFile("expert_cases.json");
  if (!r.ok) return r;
  if (wanted !== "expert_review_pending") {
    r.data.cases = []; r.data.count = 0;
  } else {
    r.data.cases = r.data.cases.filter(function (c) { return !_mockReviewed[c.report_id]; });
    r.data.count = r.data.cases.length;
  }
  return r;
}

/* 6. POST /api/expert/cases/<report_id>/review  (key required)
   body: { expert_name, guidance, confirmed_issue } */
async function submitReview(reportId, body) {
  if (!reportId) return _err("INVALID_REQUEST", "Report id is missing.");
  if (!USE_MOCK) {
    return _real("POST", "/api/expert/cases/" + encodeURIComponent(reportId) + "/review",
                 { body: body, expert: true });
  }
  await _sleep(MOCK_LATENCY_MS);
  if (!body || !body.expert_name || !body.guidance) {
    return _err("INVALID_REQUEST", "expert_name and guidance are required");
  }
  if (body.confirmed_issue !== null && body.confirmed_issue !== undefined &&
      ISSUES.indexOf(body.confirmed_issue) === -1) {
    return _err("INVALID_REQUEST", "confirmed_issue must be one of the known issues or null");
  }
  var rep = await _mockReport(reportId);
  if (!rep.ok) return rep;
  if (rep.data.expert_review || _mockReviewed[reportId]) {
    return _err("CONFLICT", "Report already reviewed");
  }
  var review = {
    id: "rev_" + _hex8(),
    report_id: reportId,
    expert_name: body.expert_name,
    guidance: body.guidance,
    confirmed_issue: body.confirmed_issue === undefined ? null : body.confirmed_issue,
    created_at: _nowIso()
  };
  _mockReviewed[reportId] = review;
  return { ok: true, data: { report_id: reportId, status: "expert_reviewed", review: review } };
}

/* 7. GET /api/radar/clusters (public) */
function getClusters() {
  return USE_MOCK ? _mockFile("radar_clusters.json") : _real("GET", "/api/radar/clusters");
}

/* 8. GET /api/radar/clusters/<id>  (key required) */
async function getClusterDetail(id) {
  if (!id) return _err("INVALID_REQUEST", "Cluster id is missing.");
  if (!USE_MOCK) {
    return _real("GET", "/api/radar/clusters/" + encodeURIComponent(id), { expert: true });
  }
  if (!EXPERT_KEY) return _statusError(401);
  return _mockFile("cluster_detail.json");
}

/* 9. POST /api/reminders/run  (key required) */
async function runReminders() {
  if (!USE_MOCK) return _real("POST", "/api/reminders/run", { expert: true });
  await _sleep(MOCK_LATENCY_MS);
  return { ok: true, data: { sent: 2, failed: 0 } };
}

/* 10. POST /api/demo/simulate-cluster  (key required)
   body: { crop, suspected_issue, area_label, target_farm_id } */
async function simulateCluster(body) {
  if (!USE_MOCK) return _real("POST", "/api/demo/simulate-cluster", { body: body, expert: true });
  await _sleep(MOCK_LATENCY_MS);
  body = body || {};
  return {
    ok: true,
    data: {
      cluster: {
        id: "clu_" + _hex8(),
        crop: body.crop || "tomato",
        suspected_issue: body.suspected_issue || "early_blight",
        area_label: body.area_label || "Kolar North",
        centroid_lat: 13.14, centroid_lng: 78.13,
        severity: "watch", report_count: 3, window_hours: RADAR_TIME_WINDOW_HOURS,
        label: CLUSTER_LABEL, data_source: "simulated", created_at: _nowIso()
      },
      alerts_sent: 1,
      data_source: "simulated"
    }
  };
}

/* 11. GET /api/health */
async function getHealth() {
  if (!USE_MOCK) return _real("GET", "/api/health");
  await _sleep(MOCK_LATENCY_MS);
  return { ok: true, data: { status: "ok", services: { database: "memory", gemini: "configured", weather: "not_checked" } } };
}

/* 1. POST /api/reports  (multipart/form-data: farm_id, image, optional audio, voice_text, language) */
async function submitReport(formData) {
  if (!formData || typeof formData.get !== "function") {
    return _err("INVALID_REQUEST", "Report form data is missing.");
  }
  if (!USE_MOCK) return _real("POST", "/api/reports", { form: formData });
  await _sleep(MOCK_LATENCY_MS);
  if (!formData.get("image")) return _err("INVALID_REQUEST", "image is required");
  if (!formData.get("farm_id")) return _err("INVALID_REQUEST", "farm_id is required");
  return _mockFile("report_preliminary.json");
}