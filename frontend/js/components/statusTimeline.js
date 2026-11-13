/* renderStatusTimeline(events) -> HTML string
 * Shows ONLY the events that exist (report.events). No future steps are drawn.
 * Each event: { status, actor, timestamp, note? }
 */
var _TL_ACTORS = { farmer: "Farmer", ai: "AI", rules: "Rules engine", expert: "Expert", system: "System" };

function renderStatusTimeline(events) {
  if (!Array.isArray(events) || events.length === 0) {
    return '<div class="empty empty-sm">No status events have been recorded yet.</div>';
  }
  var list = events.slice().sort(function (a, b) {
    var ta = Date.parse(a.timestamp), tb = Date.parse(b.timestamp);
    if (isNaN(ta) || isNaN(tb)) return 0;
    return ta - tb;
  });
  var html = '<ol class="tl">';
  list.forEach(function (ev, i) {
    var last = i === list.length - 1;
    var actor = _TL_ACTORS[ev.actor] || ev.actor || "";
    html += '<li class="tl-step ' + (last ? "is-current" : "is-done") + '" style="--i:' + i + '">' +
      '<span class="tl-dot"></span><div>' +
      '<div class="tl-title">' + UI.esc(UI.label(STATUS_LABELS, ev.status)) + "</div>" +
      '<div class="tl-meta">' + UI.esc(actor) + (actor ? " \u00b7 " : "") + UI.esc(UI.formatDateTime(ev.timestamp)) + "</div>" +
      (ev.note ? '<div class="tl-note">' + UI.esc(ev.note) + "</div>" : "") +
      "</div></li>";
  });
  return html + "</ol>";
}