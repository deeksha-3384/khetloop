/* renderWhyBox(why) -> HTML string
 * why: the array returned by the backend: [{ code, text }, ...]
 * Renders exactly what the backend sent. Nothing is invented.
 */
var _WHY_CHIPS = {
  IMAGE_SYMPTOMS: "Symptoms", IMAGE_QUALITY: "Photo quality", LOW_CONFIDENCE: "Confidence",
  NEARBY_REPORTS: "Nearby reports", WEATHER_CONTEXT: "Weather", FARM_HISTORY: "Farm history",
  NOT_CONFIRMED: "Please note"
};

function renderWhyBox(why) {
  var items = Array.isArray(why) ? why : [];
  var html = '<section class="why"><h3 class="why-title">Why am I seeing this?</h3>';
  if (items.length === 0) {
    html += '<div class="empty empty-sm">No explanation was returned for this report.</div>';
  } else {
    html += '<ul class="why-list">';
    items.forEach(function (w) {
      var code = w && w.code ? w.code : "";
      html += '<li class="why-item' + (code === "NOT_CONFIRMED" ? " is-notice" : "") + '">' +
        '<span class="why-chip">' + UI.esc(_WHY_CHIPS[code] || code || "Note") + "</span>" +
        "<span>" + UI.esc(w && w.text ? w.text : "") + "</span></li>";
    });
    html += "</ul>";
  }
  html += '<p class="why-foot">Confidence levels are reported by the model and are not calibrated.</p></section>';
  return html;
}