// Hash routing (#upload, #queue?…, #review/ID, #export, #admin) and the leave-with-unsaved-edits guard.
import {S} from "./core/state.js";
import {$, $$, SS} from "./core/dom.js";
import {keepDraft} from "./core/store.js";
import {ask} from "./ui/dialog.js";
import {restoreBatch} from "./views/upload.js";
import {Q, applyQueueState, loadQueue} from "./views/queue.js";
import {openCard} from "./views/review.js";
import {exportInfo} from "./views/export.js";
import {loadAdmin} from "./views/admin.js";

/* ---------- routing ---------- */
function parseHash() { const h = location.hash.slice(1) || "upload"; const [path, qs] = h.split("?"); const [v, id] = path.split("/"); return {v, id, q: new URLSearchParams(qs || "")}; }
let routed = false;   // first route() after page load leaves focus alone (first Tab = skip link)
function route() {
  const {v, id, q} = parseHash();
  const t = $("#toast"); t.classList.remove("show"); t.textContent = "";   // no stale message on another page (Undo stays in the header)
  const view = ["upload", "queue", "review", "export", "admin"].includes(v) ? v : "upload";
  $$(".view").forEach(s => s.hidden = s.id !== "v-" + view);
  $$("nav a").forEach(a => { if (a.dataset.nav === (view === "review" ? "queue" : view)) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  if (view === "queue") { const before = Q.batch; applyQueueState(q); if (!(Q.loading && Q.loadingFor === (Q.batch ?? before) && before === Q.batch && Q.cardsFor === Q.batch)) loadQueue(); }   // round 15: a re-click of Review queue while this batch is already loading/shown is a no-op
  if (view === "review") openCard(+id);
  if (view === "export") { if (!SS.exportFrom) { const pv = route.prev, fb = pv === "upload" ? (S.B && S.B.id) : pv === "review" ? (S.cur && S.cur.batch) : pv === "queue" ? Q.batch : null; if (fb && fb !== "__none__") SS.exportFrom = fb; } exportInfo.picked = false; exportInfo.more = false; exportInfo(); }   // round 21: export the batch you came from
  if (view === "upload") restoreBatch();
  route.prev = view;
  if (view === "admin") loadAdmin();
  // Keyboard users: if focus was left on something in the view that just got hidden (or on <body>), the browser's next
  // Tab would start from that hidden spot (it landed on the footer link). Put focus on the new view's heading instead.
  const ae = document.activeElement;
  if (routed && (!ae || ae === document.body || (ae.closest(".view") && ae.closest(".view").hidden))) {
    const h = $("#v-" + view + " h1"); if (h) { h.setAttribute("tabindex", "-1"); h.focus({preventScroll: true}); }
  }
  routed = true;
  document.title = ({upload: "Scan", queue: "Review queue", review: "Review card", export: "Export", admin: "Admin"})[view] + " · GAC Card Scanner";
}
// round 7 (reviewer r7): leaving a card with unsaved edits inside the app asks first (Queue link, URL change, J/K, Next)
let lastHash = location.hash;
addEventListener("hashchange", () => {
  if (S.DLG_DONE && location.hash !== lastHash) S.DLG_DONE({value: null, cancelled: true});   // round 11 (part-timer r4 CRITICAL): never answer a question about the previous card
  const wasReview = /^#review\//.test(lastHash);
  if (wasReview && S.dirty && S.cur && location.hash !== lastHash && !(location.hash === "#review/" + S.cur.id)) {
    keepDraft();
    // round 20 (reviewer r19): our own Leave / Stay question instead of the browser's OK / Cancel box
    const to = location.hash; history.replaceState(null, "", lastHash);
    ask({title: `Leave card #${S.cur.id}?`, html: "<p>You have unsaved changes. Leave anyway?</p><p class=\"small\">They are kept as a draft on this browser.</p>",
         buttons: [{label: "Stay", cls: "primary", value: null, primary: true, focus: true}, {label: "Leave", value: 1}]})
      .then(a => { if (a && a.value) { S.dirty = false; location.hash = to; } });
    return;
  }
  lastHash = location.hash; route();
});
export {parseHash, route};
