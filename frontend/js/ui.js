/* KhetLoop shared UI helpers (owner: P3)
 * Loaded in <head> after config.js and constants.js.
 * Exposes one global: UI
 */
document.documentElement.classList.add("js");

var UI = (function () {
  var IST = "Asia/Kolkata";
  var finePointer = !!(window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches);
  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var HOVER_SEL = "a, button, .btn, label, summary, [role='button'], [data-cursor], .card-hover, .leaflet-interactive, .leaflet-marker-icon";
  var TEXT_SEL = "input, textarea, select";

  /* ---------- text helpers ---------- */
  function esc(v) {
    if (v === null || v === undefined) return "";
    return String(v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Returns the RAW label (not escaped). Always wrap in esc() when printing. */
  function label(map, key) {
    if (key === null || key === undefined || key === "") return "\u2014";
    return (map && map[key]) ? map[key] : String(key);
  }

  function truncate(s, n) {
    s = s === null || s === undefined ? "" : String(s);
    return s.length > n ? s.slice(0, n - 1).trimEnd() + "\u2026" : s;
  }

  function getParam(name) {
    try { return new URLSearchParams(window.location.search).get(name); } catch (e) { return null; }
  }

  /* ---------- dates (API sends UTC, we show IST and say so) ---------- */
  function parseDate(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    return isNaN(d.getTime()) ? null : d;
  }

  function formatDateTime(iso) {
    var d = parseDate(iso);
    if (!d) return "Time unavailable";
    try {
      return new Intl.DateTimeFormat("en-IN", {
        day: "numeric", month: "short", year: "numeric",
        hour: "numeric", minute: "2-digit", hour12: true, timeZone: IST
      }).format(d) + " IST";
    } catch (e) { return d.toISOString(); }
  }

  function formatDate(iso) {
    var d = parseDate(iso);
    if (!d) return "Date unavailable";
    try {
      return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: IST }).format(d);
    } catch (e) { return String(iso); }
  }

  function timeAgo(iso) {
    var d = parseDate(iso);
    if (!d) return "";
    var s = Math.round((Date.now() - d.getTime()) / 1000);
    if (s < 0) return "just now";
    if (s < 60) return "just now";
    var m = Math.floor(s / 60); if (m < 60) return m + " min ago";
    var h = Math.floor(m / 60); if (h < 24) return h + " hr ago";
    var days = Math.floor(h / 24); return days + (days === 1 ? " day ago" : " days ago");
  }

  /* ---------- images ---------- */
  function img(url, alt, cls) {
    if (!url) return '<div class="img-fallback">No photo</div>';
    return '<img class="' + esc(cls || "") + '" src="' + esc(url) + '" alt="' + esc(alt || "") +
           '" loading="lazy" onerror="UI.imgFail(this)">';
  }

  function imgFail(node) {
    node.onerror = null;
    var d = document.createElement("div");
    d.className = "img-fallback";
    d.textContent = "Image unavailable";
    node.replaceWith(d);
  }

  /* ---------- loading, error, empty ---------- */
  function skeleton(kind, count) {
    var out = "";
    count = count || 1;
    for (var i = 0; i < count; i++) {
      if (kind === "card") {
        out += '<div class="card"><div class="skeleton sk-media"></div><div class="skeleton sk-line w60"></div>' +
               '<div class="skeleton sk-line"></div><div class="skeleton sk-line w40"></div></div>';
      } else {
        out += '<div class="skeleton sk-line"></div>';
      }
    }
    return out;
  }

  function showLoading(container, kind, count) {
    if (!container) return;
    container.setAttribute("aria-busy", "true");
    container.innerHTML = skeleton(kind || "lines", count || 3);
  }

  var ERROR_TITLES = {
    UNAUTHORIZED: "Expert access required",
    NOT_FOUND: "Not found",
    NETWORK_ERROR: "Can't reach the server",
    INVALID_REQUEST: "Invalid request",
    CONFLICT: "Already updated",
    DB_ERROR: "Database problem",
    INTERNAL_ERROR: "Server problem"
  };

  function showError(container, err, onRetry) {
    if (!container) return;
    container.removeAttribute("aria-busy");
    var code = (err && err.code) ? err.code : "INTERNAL_ERROR";
    var msg = (err && err.message) ? err.message : "Something went wrong. Please try again.";
    container.innerHTML =
      '<div class="error-box" role="alert"><div class="error-icon">!</div><div>' +
      "<strong>" + esc(ERROR_TITLES[code] || "Something went wrong") + "</strong>" +
      "<p>" + esc(msg) + "</p><small>Error code: " + esc(code) + "</small>" +
      (onRetry ? '<button type="button" class="btn btn-ghost btn-sm" data-retry>Try again</button>' : "") +
      "</div></div>";
    if (onRetry) {
      var b = container.querySelector("[data-retry]");
      if (b) b.addEventListener("click", onRetry);
    }
  }

  function showEmpty(container, title, text) {
    if (!container) return;
    container.removeAttribute("aria-busy");
    container.innerHTML = '<div class="empty"><strong>' + esc(title) + "</strong><p>" + esc(text || "") + "</p></div>";
  }

  function toast(message, type) {
    var wrap = document.querySelector(".toast-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "toast-wrap";
      document.body.appendChild(wrap);
    }
    var t = document.createElement("div");
    t.className = "toast is-" + (type || "info");
    t.setAttribute("role", "status");
    t.textContent = message;
    wrap.appendChild(t);
    setTimeout(function () {
      t.classList.add("out");
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 320);
    }, 4200);
  }

  /* ---------- navbar and footer ---------- */
  function mountNavbar(active) {
    var old = document.querySelector(".navbar");
    if (old) old.remove();
    var links = [
      ["index.html", "Home", "home"],
      ["dashboard.html", "Expert Dashboard", "dashboard"],
      ["radar.html", "Community Radar", "radar"]
    ];
    var items = links.map(function (l) {
      return '<a href="' + l[0] + '"' + (l[2] === active ? ' class="active" aria-current="page"' : "") + ">" + l[1] + "</a>";
    }).join("");
    var mock = (typeof USE_MOCK !== "undefined") ? USE_MOCK : false;
    var html =
      '<header class="navbar">' +
      '<a class="brand" href="index.html" aria-label="KhetLoop home">' +
      '<img class="brand-mark" src="assets/img/logo-icon.png" alt="" onerror="this.style.display=\'none\'">' +
      "<span>Khet<b>Loop</b></span></a>" +
      '<nav class="nav-links" id="navLinks">' + items + "</nav>" +
      '<div class="nav-right">' +
      '<span class="mode-pill ' + (mock ? "is-mock" : "is-live") + '">' + (mock ? "Mock data" : "Live API") + "</span>" +
      '<button class="nav-toggle" type="button" aria-label="Menu" aria-expanded="false">\u2630</button>' +
      "</div></header>";
    document.body.insertAdjacentHTML("afterbegin", html);

    var nav = document.querySelector(".navbar");
    var toggle = nav.querySelector(".nav-toggle");
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    var onScroll = function () { nav.classList.toggle("scrolled", window.scrollY > 24); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  function mountFooter() {
    var old = document.querySelector(".footer");
    if (old) old.remove();
    document.body.insertAdjacentHTML("beforeend",
      '<footer class="footer"><div class="container">' +
      "<p>KhetLoop gives preliminary assessments, not confirmed diagnoses. Confidence levels are reported by the model and are not calibrated. Always confirm treatment with your agriculture officer.</p>" +
      "<p>Team Code Stack \u00b7 Colossus 3.0</p></div></footer>");
  }

  /* ---------- number count-up ---------- */
  function animateNumber(el, to, opts) {
    if (!el) return;
    opts = opts || {};
    var decimals = opts.decimals || 0;
    var prefix = opts.prefix || "";
    var suffix = opts.suffix || "";
    var duration = opts.duration || 1400;
    var n = Number(to);
    function fmt(v) {
      return prefix + v.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
    }
    if (!isFinite(n)) { el.textContent = "\u2014"; return; }
    if (reduceMotion) { el.textContent = fmt(n); return; }
    var start = null;
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(n * eased);
      if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(n);
    }
    requestAnimationFrame(step);
  }

  /* ---------- scroll reveal ---------- */
  var revealObserver = null;
  function observeReveals(root) {
    var els = (root || document).querySelectorAll(".reveal:not(.in)");
    if (!els.length) return;
    if (!("IntersectionObserver" in window)) {
      els.forEach(function (e) { e.classList.add("in"); });
      return;
    }
    if (!revealObserver) {
      revealObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) { en.target.classList.add("in"); revealObserver.unobserve(en.target); }
        });
      }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    }
    els.forEach(function (e) { revealObserver.observe(e); });
  }

  /* ---------- cursor, magnetic buttons, card spotlight ---------- */
  function initCursor() {
    if (!finePointer || reduceMotion) return;
    var dot = document.createElement("div"); dot.className = "cursor-dot";
    var ring = document.createElement("div"); ring.className = "cursor-ring";
    document.body.appendChild(dot);
    document.body.appendChild(ring);
    var x = 0, y = 0, rx = 0, ry = 0, seen = false;

    document.addEventListener("mousemove", function (e) {
      x = e.clientX; y = e.clientY;
      if (!seen) {
        seen = true; rx = x; ry = y;
        document.body.classList.add("has-cursor", "cursor-on");
      }
      dot.style.transform = "translate3d(" + x + "px," + y + "px,0)";
      var t = e.target;
      var isText = !!(t && t.closest && t.closest(TEXT_SEL));
      var isHover = !!(t && t.closest && t.closest(HOVER_SEL));
      document.body.classList.toggle("cursor-text", isText);
      document.body.classList.toggle("cursor-hover", isHover && !isText);
    }, { passive: true });

    document.addEventListener("mousedown", function () { document.body.classList.add("cursor-down"); });
    document.addEventListener("mouseup", function () { document.body.classList.remove("cursor-down"); });
    document.documentElement.addEventListener("mouseleave", function () {
      seen = false; document.body.classList.remove("cursor-on");
    });

    (function loop() {
      rx += (x - rx) * 0.17;
      ry += (y - ry) * 0.17;
      ring.style.transform = "translate3d(" + rx.toFixed(1) + "px," + ry.toFixed(1) + "px,0)";
      requestAnimationFrame(loop);
    })();
  }

  function initMagnetic() {
    if (!finePointer || reduceMotion) return;
    var magnet = null;
    document.addEventListener("mousemove", function (e) {
      var t = (e.target && e.target.closest) ? e.target.closest(".btn, [data-magnetic]") : null;
      if (magnet && magnet !== t) {
        magnet.style.setProperty("--mx", "0px");
        magnet.style.setProperty("--my", "0px");
        magnet = null;
      }
      if (!t) return;
      var r = t.getBoundingClientRect();
      t.style.setProperty("--mx", ((e.clientX - r.left - r.width / 2) * 0.2).toFixed(1) + "px");
      t.style.setProperty("--my", ((e.clientY - r.top - r.height / 2) * 0.28).toFixed(1) + "px");
      magnet = t;
    }, { passive: true });
  }

  function initSpotlight() {
    document.addEventListener("mousemove", function (e) {
      var c = (e.target && e.target.closest) ? e.target.closest(".spot") : null;
      if (!c) return;
      var r = c.getBoundingClientRect();
      c.style.setProperty("--sx", (e.clientX - r.left) + "px");
      c.style.setProperty("--sy", (e.clientY - r.top) + "px");
    }, { passive: true });
  }

  function init() {
    initCursor();
    initMagnetic();
    initSpotlight();
    observeReveals(document);
    /* Auto-reveal anything inserted later by page scripts */
    if ("MutationObserver" in window) {
      var queued = false;
      new MutationObserver(function () {
        if (queued) return;
        queued = true;
        requestAnimationFrame(function () { queued = false; observeReveals(document); });
      }).observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  return {
    esc: esc, label: label, truncate: truncate, getParam: getParam,
    formatDateTime: formatDateTime, formatDate: formatDate, timeAgo: timeAgo,
    img: img, imgFail: imgFail,
    skeleton: skeleton, showLoading: showLoading, showError: showError, showEmpty: showEmpty, toast: toast,
    mountNavbar: mountNavbar, mountFooter: mountFooter,
    animateNumber: animateNumber, observeReveals: observeReveals
  };
})();