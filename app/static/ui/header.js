// Header: signed-in user, password, sign-out, Undo, the pending badge, the AI badge and the update banner.
import {S} from "./core/state.js";
import {$, $$, SS, esc, fmtEta, plural} from "./core/dom.js";
import {call, post} from "./core/api.js";
import {clearDrafts, keepDraft} from "./core/store.js";
import {toast} from "./ui/toast.js";
import {ask} from "./ui/dialog.js";
import {parseHash} from "./router.js";
import {Q, loadQueue} from "./views/queue.js";
import {openCard} from "./views/review.js";
import {exportInfo} from "./views/export.js";

/* ---------- signed-in user ---------- */
const who = () => S.ME ? S.ME.initials : "";
async function loadMe() {
  S.ME = await call("/api/me");
  { const w = document.getElementById("scanWho"); if (w && S.ME) w.innerHTML = `Scanning as <b>${esc(S.ME.display || S.ME.username)}</b> (${esc(S.ME.initials || "")}). Not you? <a href="/login">Sign in as yourself</a>.`; }   // round 15 (coordinator r14 #4)
  $("#whoText").innerHTML = `<b>${esc(S.ME.display)}</b> (${esc(S.ME.initials)})`;
  $("#navAdmin").hidden = S.ME.role !== "admin"; $("#archiveAll").hidden = S.ME.role !== "admin"; $("#archiveBatch").hidden = S.ME.role !== "admin";
  if (S.ME.role !== "admin") $$("#exStatus option[value=all], #exStatus option[value=pending], #exStatus option[value=rejected]").forEach(o => o.remove());
  if (S.ME.must_change) setTimeout(() => changePw("Please choose your own password (the one you were given is temporary)."), 400);
}
async function changePw(reason) {
  const a = await ask({title: "Change password", html: `<p>${esc(reason || "")}</p><label for="pwOld">Current password</label><input id="pwOld" type="password" autocomplete="current-password">`,
    input: {label: "New password (10+ characters)", required: "Enter a new password.", type: "password"}, buttons: [{label: "Change password", cls: "primary", value: 1, needInput: true, primary: true}, {label: "Later", value: null}]});
  if (!a.value) return;
  try { await post("/api/me/password", {old: $("#pwOld").value, new: a.input}); toast("Password changed."); S.ME.must_change = 0; }
  catch (e) { await ask({title: "Password not changed", html: `<p>${esc(e.message)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); changePw(reason); }
}
$("#pwChange").onclick = () => changePw();
$("#logout").onclick = async () => {
  if (S.dirty && S.cur && !$("#v-review").hidden) {
    const a = await ask({title: `Sign out and discard the changes to card #${S.cur.id}?`, html: "<p>Unsaved changes are lost when you sign out.</p>",
                         buttons: [{label: "Stay", cls: "primary", value: null, primary: true, focus: true}, {label: "Sign out", cls: "danger", value: 1}]});
    if (!a.value) return; S.dirty = false; }
  S.SIGNING_OUT = true; S.dirty = false; clearTimeout(keepDraft.t); clearDrafts();   // reviewer r8/r9: drafts don't survive sign-out (shared computers)
  const back = location.hash && !location.hash.startsWith("#upload") ? location.hash.replace(/^#queue\?.*$/, "#queue") : "#queue";   // reviewer r7: signing back in returns here (newcomer r9: without a remembered batch)
  ["lastBatch", "lastBatchUid", "lastBatchAt", "batchChosen", "batchChosenUid", "queueHash", "order", "draft", "batch"].forEach(k => { try { delete SS[k]; } catch {} });
  await post("/api/auth/logout", {}); location.href = "/login?next=" + encodeURIComponent("/ui" + back); };
/* ---------- undo ---------- */
async function refreshUndo() { try { const u = await call("/api/undo"); $("#undoBtn").hidden = !u.id; $("#undoBtn").title = u.id ? "Undo: " + u.label + " (U)" : ""; $("#undoBtn").dataset.label = u.label || ""; } catch {} }
async function doUndo() {
  try { const r = await post("/api/undo", {}); toast("Undone: " + r.undone + (r.notice ? ". " + r.notice : ""), r.notice ? 8000 : 4500); refreshCounts();
    const {v, id} = parseHash(); if (v === "review" && r.cards.includes(+id)) openCard(+id); else if (v === "review" && r.cards.length) location.hash = "review/" + r.cards[0]; else if (v === "queue") loadQueue(); else if (v === "export") exportInfo();
    refreshUndo();
  } catch (e) { toast(e.message); }
}
$("#undoBtn").onclick = doUndo;
async function refreshCounts() {
  // round 15 (part-timer r14): the badge counts YOUR pending cards (batches you scanned), from a cheap server count; it never
  // touches the queue's tabs (those always come from the batch shown, see renderQueue)
  try {
    const c = await call("/api/counts" + (Q.batch ? "?batch=" + encodeURIComponent(Q.batch) : ""));
    const rd = S.B && S.B.uid === (S.ME && S.ME.id) ? S.B.rows.filter(r => ["wait", "up", "queued", "reading"].includes(r.state)).length : 0;
    const pb = $("#pendingBadge"); pb.hidden = !c.mine_pending && !rd;
    pb.textContent = String(c.mine_pending) + (rd ? ` +${rd}` : "");
    const lbl = `${c.mine_pending} waiting in your batches` + (rd ? `, ${rd} still being read` : "");
    pb.setAttribute("aria-label", lbl); pb.title = lbl;
    if ($("#v-queue").hidden) $$("#statusTabs button span").forEach(x => x.textContent = "");
    return c;
  } catch { return null; }
}
/* ---------- AI line indicator + update banner ---------- */
// round 20 (datamanager/newcomer r19): ONE wording for the AI state, used by the header AND Admin → Settings
function aiWord(a) { return !a.enabled ? "AI check: off" : a.available ? "AI check: on" : "AI check paused"; }
function aiHeader(a) { const el = $("#aiQueue"); if (!el) return; el.hidden = false; el.textContent = aiWord(a);
  el.title = !a.enabled ? "AI check is off (Admin → Settings)." : a.available ? "AI check is on: unclear cards get a later typo check." : "The AI isn't answering right now. Scanning still works. See Help."; }
async function aiQueueTick() {
  if (document.hidden) { setTimeout(aiQueueTick, 20000); return; }   // audit 2026-10: no work while the tab is hidden
  try { const a = await call("/api/ai/status"), q = a.queue || {}, n = (q.waiting || 0) + (q.running || 0);
    // round 16 (coordinator r15 #2): everyone sees whether the AI double-check is on (read-only; an admin changes it in Settings)
    $("#aiQueue").hidden = false;
    if (!n) aiHeader(a);
    if (n) { $("#aiQueue").textContent = "AI check: busy"; $("#aiQueue").classList.remove("warn");
      $("#aiQueue").title = `AI check: ${plural(n, "card")} ahead, about ${fmtEta(q.eta_seconds || 0)}. You can review them now.`; }
    setTimeout(aiQueueTick, n ? 5000 : 20000);
  } catch { setTimeout(aiQueueTick, 30000); }
}
async function updateCheck() { try { const u = await call("/api/update");
  if (u.update_available && u.show_banner && S.ME && S.ME.role === "admin" && localStorage.getItem("gacUpdDismiss") !== u.latest) {   // round 20 (e)
    const b = $("#updBanner"); b.hidden = false;
    b.innerHTML = `A new version (${esc(u.latest)}) is available; you have ${esc(u.current)}. <a href="${esc(u.url)}" target="_blank" rel="noopener noreferrer">Release notes &amp; download</a> <button class="link" id="updX">Dismiss</button>`;
    $("#updX").onclick = () => { localStorage.setItem("gacUpdDismiss", u.latest); b.hidden = true; };
  } } catch {} }
export {aiHeader, aiQueueTick, aiWord, doUndo, loadMe, refreshCounts, refreshUndo, updateCheck, who};
// v0.4 #8: light/dark. Follows the system unless the person picked one with the ◐ button (kept on this computer).
{ const r = document.documentElement, k = "gacTheme";
  try { const t = localStorage.getItem(k); if (t === "dark" || t === "light") r.dataset.theme = t; } catch {}
  const b = document.getElementById("themeBtn");
  if (b) b.onclick = () => { const dark = r.dataset.theme === "dark" || (!r.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    r.dataset.theme = dark ? "light" : "dark"; try { localStorage.setItem(k, r.dataset.theme); } catch {} }; }
