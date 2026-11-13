/* dataSourceBadge(source, opts) -> HTML string
 * source: "live" | "cached" | "simulated" | "unverified" (DATA_SOURCES)
 * opts.large: bigger badge; for "simulated" it reads SIMULATED DATA.
 * Returns "" when the object has no data_source. Unknown values show as Unverified.
 */
function dataSourceBadge(source, opts) {
  opts = opts || {};
  if (source === undefined || source === null || source === "") return "";
  var key = DATA_SOURCES.indexOf(source) > -1 ? source : "unverified";
  var text = (opts.large && key === "simulated") ? "SIMULATED DATA" : DATA_SOURCE_LABELS[key];
  var hints = {
    live: "Fetched live from the service",
    cached: "Last saved result; the live service was not used",
    simulated: "Demo data, not from real farms",
    unverified: "Source could not be verified"
  };
  return '<span class="badge badge-' + key + (opts.large ? " badge-lg" : "") + '" title="' + UI.esc(hints[key]) + '">' +
         '<i class="badge-dot"></i>' + UI.esc(text) + "</span>";
}