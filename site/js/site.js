/* Tracklister website: theme toggle, language switch, live release line and screenshot viewer.
   SPDX-License-Identifier: GPL-3.0-or-later

   Loaded in <head> (not deferred) so the saved theme applies before the page paints. Everything else
   waits for DOMContentLoaded. No cookies and no analytics: the only request that leaves the site is
   one anonymous GET to api.github.com for the latest release (tag and zip size), cached for the tab
   session. If it fails, the page keeps its «Última versión en GitHub» / «Latest release on GitHub»
   and says nothing. Every text comes from the page itself (Spanish or English), never from here. */
(function () {
  "use strict";

  var THEMES = ["hormigon", "noche"];
  var THEME_KEY = "tracklister-tema";
  var RELEASE_KEY = "tracklister-release";
  var RELEASE_API = "https://api.github.com/repos/blessel-dev/tracklister/releases/latest";
  var root = document.documentElement;

  function storedTheme() {
    try {
      var t = window.localStorage.getItem(THEME_KEY);
      return THEMES.indexOf(t) >= 0 ? t : null;
    } catch (e) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch (e) {
      /* private mode or storage disabled: the choice lasts until the page closes */
    }
  }

  function applyTheme(theme) {
    if (THEMES.indexOf(theme) < 0) {
      theme = THEMES[0];
    }
    root.setAttribute("data-theme", theme);
    var buttons = document.querySelectorAll("[data-theme-choice]");
    for (var i = 0; i < buttons.length; i++) {
      var on = buttons[i].getAttribute("data-theme-choice") === theme;
      buttons[i].setAttribute("aria-pressed", on ? "true" : "false");
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta && window.getComputedStyle) {
      var bg = window.getComputedStyle(root).getPropertyValue("--bg").trim();
      if (bg) {
        meta.setAttribute("content", bg);
      }
    }
  }

  // Before the first paint: the saved theme, or Hormigón.
  applyTheme(storedTheme() || THEMES[0]);

  function initThemeToggle() {
    var group = document.querySelector(".theme-toggle");
    if (!group) {
      return;
    }
    group.hidden = false;
    applyTheme(root.getAttribute("data-theme"));
    group.addEventListener("click", function (ev) {
      var target = ev.target;
      var button = target && target.closest ? target.closest("[data-theme-choice]") : null;
      if (!button) {
        return;
      }
      var theme = button.getAttribute("data-theme-choice");
      applyTheme(theme);
      saveTheme(theme);
    });
  }

  // ---- language switch: plain links to the same page in the other language -------------------
  // With JS they keep the current #section: the URL's fragment (set by the section links, a shared
  // link or «Volver arriba»), if it names an element of this page. Both pages share their ids,
  // except the section in the other language, which names its twin with data-other-id.
  function sectionHash() {
    var id = window.location.hash.slice(1);
    if (!id) {
      return "";
    }
    try {
      id = decodeURIComponent(id);
    } catch (e) {
      return "";
    }
    var el = document.getElementById(id);
    if (!el) {
      return "";
    }
    var twin = el.closest ? el.closest("[data-other-id]") : null;
    return "#" + encodeURIComponent(twin ? twin.getAttribute("data-other-id") : id);
  }

  function initLangSwitch() {
    var links = document.querySelectorAll(".lang-switch a[hreflang]:not([aria-current])");
    if (!links.length) {
      return;
    }
    var bases = [];
    for (var i = 0; i < links.length; i++) {
      bases.push(links[i].getAttribute("href").split("#")[0]);
    }
    function update() {
      var hash = sectionHash();
      for (var j = 0; j < links.length; j++) {
        links[j].setAttribute("href", bases[j] + hash);
      }
    }
    window.addEventListener("hashchange", update);
    for (var k = 0; k < links.length; k++) {
      // and right before the browser follows the link, however it is opened
      links[k].addEventListener("focus", update);
      links[k].addEventListener("pointerdown", update);
      links[k].addEventListener("click", update);
    }
    update();
  }

  // ---- «Versión 1.0.0 · 132 MB» / «Version 1.0.0 · 132 MB» -------------------------------------
  function releaseInfo(data) {
    if (!data || typeof data.tag_name !== "string") {
      return null;
    }
    var m = /^v?(\d+\.\d+\.\d+)$/.exec(data.tag_name);
    if (!m) {
      return null;
    }
    var size = 0;
    var assets = Array.isArray(data.assets) ? data.assets : [];
    for (var i = 0; i < assets.length; i++) {
      var a = assets[i];
      if (a && typeof a.name === "string" && /^Tracklister-.+-win64\.zip$/.test(a.name) &&
          typeof a.size === "number" && a.size > 0) {
        size = a.size;
      }
    }
    return { version: m[1], size: size };
  }

  function releaseText(info, label) {
    var text = label + " " + info.version;
    if (info.size > 0) {
      text += " · " + Math.round(info.size / 1048576) + " MB";
    }
    return text;
  }

  function showRelease(info) {
    var el = document.getElementById("release-version");
    var label = el ? el.getAttribute("data-label") : "";
    if (el && info && label) {
      el.textContent = releaseText(info, label);
    }
  }

  function initRelease() {
    if (!document.getElementById("release-version")) {
      return;
    }
    var cached = null;
    try {
      cached = JSON.parse(window.sessionStorage.getItem(RELEASE_KEY) || "null");
    } catch (e) {
      cached = null;
    }
    if (cached && /^\d+\.\d+\.\d+$/.test(cached.version) && typeof cached.size === "number") {
      showRelease(cached);
      return;
    }
    if (!window.fetch) {
      return;
    }
    window.fetch(RELEASE_API, {
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: { "Accept": "application/vnd.github+json" }
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("HTTP " + response.status);
      }
      return response.json();
    }).then(function (data) {
      var info = releaseInfo(data);
      if (!info) {
        return;
      }
      showRelease(info);
      try {
        window.sessionStorage.setItem(RELEASE_KEY, JSON.stringify(info));
      } catch (e) {
        /* no session storage: it is asked again on the next visit */
      }
    }).catch(function () {
      /* offline, rate-limited or blocked: keep the page's fallback line, silently */
    });
  }

  // ---- screenshot viewer: the links open the PNG without JS; with JS, a modal <dialog> ----------
  function initViewer() {
    var dialog = document.getElementById("visor");
    if (!dialog || typeof dialog.showModal !== "function") {
      return;
    }
    var figure = dialog.querySelector(".viewer-figure");
    var caption = document.getElementById("visor-titulo");
    var close = dialog.querySelector(".viewer-close");
    var defaultTitle = caption.textContent;      // «Captura» / «Screenshot», from the page
    var opener = null;

    function clear() {
      while (figure.firstChild) {
        figure.removeChild(figure.firstChild);
      }
    }

    document.addEventListener("click", function (ev) {
      var target = ev.target;
      var link = target && target.closest ? target.closest("a.shot") : null;
      if (!link || ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
        return;
      }
      var thumb = link.querySelector("img");
      if (!thumb) {
        return;
      }
      ev.preventDefault();
      opener = link;
      clear();
      var big = document.createElement("img");
      big.src = link.getAttribute("href");
      big.alt = thumb.getAttribute("alt") || "";
      big.width = Number(thumb.getAttribute("width")) || 0;
      big.height = Number(thumb.getAttribute("height")) || 0;
      figure.appendChild(big);
      var fig = link.closest("figure");
      var title = fig ? fig.querySelector("figcaption strong") : null;
      caption.textContent = title ? title.textContent : defaultTitle;
      dialog.showModal();
      close.focus();
    });

    close.addEventListener("click", function () {
      dialog.close();
    });
    dialog.addEventListener("click", function (ev) {
      if (ev.target === dialog) {
        dialog.close();          // a click on the backdrop
      }
    });
    dialog.addEventListener("close", function () {
      clear();
      if (opener) {
        opener.focus();
        opener = null;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initThemeToggle();
    initLangSwitch();
    initRelease();
    initViewer();
  });
}());
