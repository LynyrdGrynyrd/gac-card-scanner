// v0.4.3 #8 / v0.4.4 #11 (part-timer): the app menu is not in the page at all; it is added only when you are signed in.
// The version shown is the one the server is running.
fetch("/health", {credentials: "same-origin"}).then(r => r.ok ? r.json() : null).then(h => {
  if (h && h.version) document.querySelectorAll("[data-ver]").forEach(e => { e.textContent = h.version; });
}).catch(() => {});
fetch("/api/me", {credentials: "same-origin"}).then(r => {
  if (!r.ok) return;
  const slot = document.getElementById("helpNavSlot"), b = document.getElementById("helpBack");
  if (slot) {
    const n = document.createElement("nav"); n.setAttribute("aria-label", "Main"); n.id = "helpNav";
    for (const [h, t] of [["/ui#upload", "Scan cards"], ["/ui#queue", "Review queue"], ["/ui#export", "Export"], ["/static/ui/help.html", "Help"]]) {
      const a = document.createElement("a"); a.href = h; a.textContent = t; if (t === "Help") a.setAttribute("aria-current", "page"); n.appendChild(a);
    }
    slot.replaceWith(n);
  }
  if (b) b.textContent = "← Back to the scanner";
}).catch(() => {});
