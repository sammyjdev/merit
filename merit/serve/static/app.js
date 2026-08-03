// Keyboard navigation - the whole JS surface of MERIT serve (spec: ~50 lines).
(function () {
  "use strict";
  var VIEWS = { "1": "/fila", "2": "/pipeline", "3": "/dossie", "4": "/evals" };

  function rows() { return Array.prototype.slice.call(document.querySelectorAll("[data-row]")); }

  function selected() { return document.querySelector("[data-row].selected"); }

  function select(next) {
    var cur = selected();
    if (cur) cur.classList.remove("selected");
    if (next) { next.classList.add("selected"); next.scrollIntoView({ block: "nearest" }); }
  }

  function move(delta) {
    var all = rows();
    if (!all.length) return;
    var idx = all.indexOf(selected());
    var next = all[Math.min(all.length - 1, Math.max(0, idx + delta))] || all[0];
    select(next);
  }

  document.addEventListener("keydown", function (e) {
    if (e.target.matches("input, textarea, select")) return;
    if (VIEWS[e.key]) { window.location.href = VIEWS[e.key]; return; }
    if (e.key === "j") move(1);
    if (e.key === "k") move(-1);
    if (e.key === "Enter") {
      var cur = selected();
      var link = cur && cur.querySelector("a[data-open]");
      if (link) link.click();
    }
    if (e.key === "?") {
      var el = document.getElementById("keys-help");
      if (el) el.hidden = !el.hidden;
    }
  });
})();
