(function () {
  var pollInterval = null;

  function render(state) {
    var bar = document.getElementById("progress-fill");
    var pct = state.phase_total > 0
      ? Math.round((state.phase_current / state.phase_total) * 100)
      : 0;
    if (bar) bar.style.width = pct + "%";

    var phaseEl = document.getElementById("run-phase");
    if (phaseEl) phaseEl.textContent = state.phase;

    var progressEl = document.getElementById("run-progress-text");
    if (progressEl) progressEl.textContent = state.phase_current + " / " + state.phase_total;

    var candidatesEl = document.getElementById("run-candidates");
    if (candidatesEl) candidatesEl.textContent = state.candidates_found;

    var logEl = document.getElementById("run-log");
    if (logEl) {
      logEl.innerHTML = state.log.map(function (line) {
        return "<div>" + line.replace(/</g, "&lt;") + "</div>";
      }).join("");
    }

    if (state.phase === "done" || state.phase === "failed") {
      window.clearInterval(pollInterval);
      window.location.reload();
    }
  }

  function poll() {
    fetch("/api/run/status")
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () { /* transient network hiccup -- next poll retries */ });
  }

  var runContainer = document.getElementById("run-live");
  if (runContainer) {
    poll();
    pollInterval = window.setInterval(poll, 1500);
  }
})();
