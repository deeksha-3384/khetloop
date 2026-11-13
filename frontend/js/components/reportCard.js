/* renderReportCard(item, opts) -> HTML string
 * Works for timeline items (endpoint 4) and expert cases (endpoint 5).
 * opts.crop     crop to show when the item has none (timeline items have no crop)
 * opts.href     link target; pass null for a non-link card (used by the dashboard queue)
 * opts.selected highlights the card
 */
function renderReportCard(item, opts) {
  opts = opts || {};
  item = item || {};
  var id = item.report_id || item.id || "";
  var crop = item.crop || opts.crop || "";
  var tag = opts.href === null ? "div" : "a";
  var href = opts.href === undefined ? "report.html?id=" + encodeURIComponent(id) : opts.href;
  var levels = { high: 3, medium: 2, low: 1 };
  var lvl = levels[item.confidence_band] || 0;
  var bars = "";
  for (var i = 1; i <= 3; i++) bars += '<i class="' + (i <= lvl ? "on" : "") + '"></i>';

  var meta = [];
  if (crop) meta.push(UI.label(CROP_LABELS, crop));
  if (item.area_label) meta.push(item.area_label);

  var html = "<" + tag + ' class="card card-hover spot rcard' + (opts.selected ? " is-selected" : "") + '"' +
    (tag === "a" ? ' href="' + UI.esc(href) + '"' : ' data-report-id="' + UI.esc(id) + '" tabindex="0" role="button"') + ">" +
    '<div class="rcard-media">' + UI.img(item.image_url, "Leaf photo") +
    '<div class="rcard-badges">' +
    (item.status ? '<span class="pill pill-' + UI.esc(item.status) + '">' + UI.esc(UI.label(STATUS_LABELS, item.status)) + "</span>" : "<span></span>") +
    dataSourceBadge(item.data_source) + "</div></div>" +
    '<div class="rcard-body">' +
    (meta.length ? '<div class="rcard-meta">' + UI.esc(meta.join(" \u00b7 ")) + "</div>" : "") +
    '<h3 class="rcard-title">' + UI.esc(UI.label(ISSUE_LABELS, item.suspected_issue)) + "</h3>" +
    (item.decision ? '<div class="rcard-sub">' + UI.esc(UI.label(DECISION_LABELS, item.decision)) + "</div>" : "") +
    (lvl ? '<div class="conf conf-' + UI.esc(item.confidence_band) + '" title="Model self-reported, not calibrated">' +
           '<span class="conf-bars">' + bars + "</span>" + UI.esc(UI.label(CONFIDENCE_LABELS, item.confidence_band)) + "</div>" : "") +
    ((item.rain_expected === true || item.escalation_reason) ?
      '<div class="row" style="gap:8px">' +
      (item.rain_expected === true ? '<span class="chip chip-lime">Rain expected</span>' : "") +
      (item.escalation_reason ? '<span class="chip chip-warn" title="Escalation reason">' + UI.esc(item.escalation_reason) + "</span>" : "") +
      "</div>" : "") +
    (item.expert_guidance ? '<div class="rcard-quote">' + UI.esc(UI.truncate(item.expert_guidance, 140)) + "</div>" : "") +
    '<div class="rcard-foot"><span>' + UI.esc(UI.formatDateTime(item.created_at)) + "</span><span>View \u2192</span></div>" +
    "</div></" + tag + ">";
  return html;
}