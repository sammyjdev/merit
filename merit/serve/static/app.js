// Keyboard navigation - the whole JS surface of MERIT serve (spec: ~50 lines).
(function () {
  "use strict";
  var VIEWS = { "1": "/vagas", "2": "/pipeline", "3": "/dossie", "4": "/evals" };

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
      if (e.target.matches("summary")) return; // native toggle already handles it
      var cur = selected();
      var link = cur && cur.querySelector("a[data-open]");
      if (link) { link.click(); return; }
      var det = cur && cur.querySelector("details");
      if (det) det.open = !det.open;
    }
    if (e.key === "?") {
      var el = document.getElementById("keys-help");
      if (el) el.hidden = !el.hidden;
    }
  });
})();

// Kanban drag-and-drop. Handlers are delegated on document because htmx
// swaps the whole #board out from under us on every move, which would drop
// any listener bound to a card. The drop reuses the same endpoint and swap
// contract the status <select> already uses - there is one way to move a card.
(function () {
  var dragging = null;

  document.addEventListener("dragstart", function (e) {
    var card = e.target.closest && e.target.closest(".pipeline-card[draggable]");
    if (!card) return;
    dragging = card;
    card.classList.add("card-dragging");
    e.dataTransfer.effectAllowed = "move";
    // Firefox refuses to start a drag without payload on the transfer.
    e.dataTransfer.setData("text/plain", card.dataset.appId || "");
  });

  document.addEventListener("dragend", function () {
    if (dragging) dragging.classList.remove("card-dragging");
    dragging = null;
  });

  document.addEventListener("dragover", function (e) {
    if (!dragging) return;
    var col = e.target.closest && e.target.closest("[data-drop-status]");
    if (!col) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  });

  document.addEventListener("drop", function (e) {
    if (!dragging) return;
    var col = e.target.closest && e.target.closest("[data-drop-status]");
    if (!col) return;
    e.preventDefault();
    var status = col.dataset.dropStatus;
    var appId = dragging.dataset.appId;
    // Dropping a card back on its own column is not a move. Sending it anyway
    // would bump updated_at, and the follow-up radar reads updated_at - a
    // no-op drag would silently reset a card's "going cold" timer.
    var from = dragging.closest("[data-drop-status]");
    if (!appId || (from && from.dataset.dropStatus === status)) return;
    htmx.ajax("POST", "/pipeline/" + appId + "/move", {
      target: "#board",
      swap: "outerHTML",
      values: { status: status }
    });
  });
})();
