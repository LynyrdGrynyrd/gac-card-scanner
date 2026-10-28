// Header: signed-in user, password, sign-out, Undo, the pending badge, the AI badge and the update banner.
import {S} from "./core/state.js";
import {$, $$, SS, esc, fmtEta, plural} from "./core/dom.js";
import {call, post} from "./core/api.js";
import {clearDrafts, keepDraft} from "./core/store.js";
import {toast} from "./ui/toast.js";
import {ask} from "./ui/dialog.js";
import {parseHash} from "./router.js";
import {Q, loadQueue} from "./views/queue.js";
import {dirtyVals, openCard} from "./views/review.js";
import {exportInfo} from "./views/export.js";

/* ---------- signed-in user ---------- */
const who = () => S.ME ? S.ME.initials : "";
async function loadMe() {
  S.ME = await call("/api/me");
  // v0.4.2 #2 (part-timer blocker): who is signed in, on every screen
  { const w = document.getElementById("youAre"); if (w && S.ME) { w.innerHTML = `You are: <b>${esc(S.ME.display || S.ME.username)}</b> · <button type="button" class="link" id="notMe">Not you?</button>`; $("#notMe").onclick = () => $("#logout").click(); } }
  idleStart(S.ME.idle_minutes);
  $("#whoText").innerHTML = `<b>${esc(S.ME.display)}</b> (${esc(S.ME.initials)})`;
  $("#fNaL").hidden = false;   // v0.4.7 #4: reviewers filter their own flagged cards; admins see every batch's
  { const a_ = S.ME.role === "admin"; for (const id of ["exHistEveryoneL"]) { const el = document.getElementById(id); if (el) el.hidden = !a_; } }   // v0.4.7 #8
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
// v0.4.2 #2: sign out after a period with no click, key or touch (a shared event computer). Photos still uploading keep you in.
let idleT = null, idleLast = Date.now(), idleWarned = false;
function idleStart(min) {
  if (!min || idleT) return;
  const bump = () => { idleLast = Date.now(); };
  ["pointerdown", "keydown", "wheel", "touchstart"].forEach(e => addEventListener(e, bump, {passive: true, capture: true}));
  idleT = setInterval(async () => {
    if (window.gacBusy && window.gacBusy()) { idleLast = Date.now(); return; }
    const idle = (Date.now() - idleLast) / 60000;
    if (idle < min - 1 || idleWarned) return;
    idleWarned = true; const t0 = idleLast;
    // v0.4.3 #2 (skeptic L1): unsaved edits are named and kept as YOUR draft (restored when you open the card again)
    const ed_ = S.dirty && S.cur && !$("#v-review").hidden ? S.cur.id : null;
    const a = await ask({title: "Still there?", html: `<p>You will be signed out in 1 minute.</p>${ed_ ? `<p>Card #${ed_} has unsaved changes. They are kept as your draft.</p>` : ""}`, timeout: 60000,
      buttons: [{label: "Stay signed in", cls: "primary", value: 1, primary: true, focus: true}]});
    idleWarned = false;
    if (!a.timedOut || idleLast !== t0) { idleLast = Date.now(); return; }
    // v0.4.4 #10 (skeptic L3): the draft goes to the SERVER (yours only); the browser copy is cleared at sign-out
    if (ed_) { try { await post(`/api/cards/${ed_}/draft`, {vals: dirtyVals(), version: S.cur.version}); } catch {} }
    S.dirty = false; window.gacIdleOut = true; $("#logout").click();
  }, 15000);
}
$("#logout").onclick = async () => {
  if (S.dirty && S.cur && !$("#v-review").hidden) {
    const a = await ask({title: `Sign out and discard the changes to card #${S.cur.id}?`, html: "<p>Unsaved changes are lost when you sign out.</p>",
                         buttons: [{label: "Stay", cls: "primary", value: null, primary: true, focus: true}, {label: "Sign out", cls: "danger", value: 1}]});
    if (!a.value) return; S.dirty = false; }
  S.SIGNING_OUT = true; S.dirty = false; clearTimeout(keepDraft.t);
  clearDrafts();   // reviewer r8/r9, v0.4.4 #10: no draft stays in the browser after any sign-out (an idle one keeps it on the server)
  const back = location.hash && !location.hash.startsWith("#upload") ? location.hash.replace(/^#queue\?.*$/, "#queue") : "#queue";   // reviewer r7: signing back in returns here (newcomer r9: without a remembered batch)
  ["lastBatch", "lastBatchUid", "lastBatchAt", "batchChosen", "batchChosenUid", "queueHash", "order", "draft", "batch"].forEach(k => { try { delete SS[k]; } catch {} });
  // v0.4.8 #12 (newcomer: a blank sign-in page after sign-out): the sign-in page says why
  await post("/api/auth/logout", {}); location.href = "/login?out=" + (window.gacIdleOut ? "idle" : "1") + "&next=" + encodeURIComponent("/ui" + back); };
/* ---------- undo ---------- */
// v0.4.5 #6: Undo works on the batch you are in, from the last 2 hours, and says what it will undo
const undoBatch = () => (S.cur && !$("#v-review").hidden && S.cur.batch) || ($("#fBatch") && !$("#v-queue").hidden && $("#fBatch").value) || (S.B && S.B.id) || "";
// v0.4.6 #2: the server answers with the SAME rule the click uses (this batch, last 2 hours); nothing undoable = no button
async function refreshUndo() { try { const b = undoBatch(), u = await call("/api/undo" + (b ? "?batch=" + encodeURIComponent(b) : "")); const btn = $("#undoBtn"); btn.hidden = !u.id;
  clearTimeout(refreshUndo.t); if (u.id) refreshUndo.t = setTimeout(refreshUndo, 60000);
  // v0.4.8 #11: the action and a short batch name on the button; the hover gives the true minutes and the 2-hour limit
  btn.textContent = u.id ? `↶ Undo ${u.short || u.label}${u.batch_short ? " (" + u.batch_short + ")" : ""}` : "↶ Undo";
  btn.dataset.ts = u.ts || ""; btn.dataset.what = u.id ? `${u.label}${u.batch_label ? " · " + u.batch_label : ""}` : ""; btn.dataset.win = u.window_min || 120;
  undoTitle(); btn.setAttribute("aria-label", u.id ? "Undo: " + btn.dataset.what : "Undo"); btn.dataset.label = u.label || ""; btn.dataset.id = u.id || ""; } catch { $("#undoBtn").hidden = true; $("#undoBtn").dataset.id = ""; } }
function undoTitle() { const btn = $("#undoBtn"), ts = Number(btn.dataset.ts); if (!ts) { btn.title = ""; return; }
  const m = Math.max(0, Math.floor((Date.now() / 1000 - ts) / 60)), h = Math.round(Number(btn.dataset.win) / 60);
  btn.title = `Undo: ${btn.dataset.what} · ${m < 1 ? "less than a minute ago" : m + " min ago"}. Works for ${h} hours, in this batch only. (U)`; }
$("#undoBtn").addEventListener("mouseenter", undoTitle);
async function doUndo() {
  try { const id_ = Number($("#undoBtn").dataset.id) || null, b = undoBatch(); const r = await post("/api/undo", {...(id_ ? {id: id_} : {}), ...(b ? {batch: b} : {})}); refreshCounts();
    // v0.4.3 #8 (newcomer): a short "Undone" that survives the move to the card (a route change clears the message)
    const msg = "Undone: " + r.undone + "." + (r.notice ? " " + r.notice : ""), show = () => toast(msg, r.notice ? 8000 : 4500);
    const {v, id} = parseHash(); if (v === "review" && r.cards.includes(+id)) { await openCard(+id); show(); } else if (v === "review" && r.cards.length) { location.hash = "review/" + r.cards[0]; setTimeout(show, 500); } else { if (v === "queue") loadQueue(); else if (v === "export") exportInfo(); show(); }
    refreshUndo();
  } catch (e) { toast(e.message); refreshUndo(); }   // v0.4.4 #10: a refused action is closed; the button moves on
}
$("#undoBtn").onclick = doUndo;
async function refreshCounts() {
  // round 15 (part-timer r14): the badge counts YOUR pending cards (batches you scanned), from a cheap server count; it never
  // touches the queue's tabs (those always come from the batch shown, see renderQueue)
  try {
    const c = await call("/api/counts" + (Q.batch ? "?batch=" + encodeURIComponent(Q.batch) : ""));
    const rd = S.B && S.B.uid === (S.ME && S.ME.id) ? S.B.rows.filter(r => ["wait", "up", "queued", "reading"].includes(r.state)).length : 0;
    const pb = $("#pendingBadge"); pb.hidden = !c.mine_pending && !rd;
    pb.textContent = String(c.mine_pending) + (rd ? ` · ${rd} reading` : "");   // v0.4.4 #9 (coordinator): plain words, not "63 +4"
    // v0.4.8 #7: a reviewer's badge is the batch the queue shows (same number as the list)
    const lbl = `${c.mine_pending} to review in ${"badge_batch" in c ? (c.badge_label ? c.badge_label : "this batch") : "your batches"}` + (rd ? `, ${rd} still being read` : "");
    pb.setAttribute("aria-label", lbl); pb.title = lbl;
    const na = $("#naBadge"); if (na) { na.hidden = !c.needs_admin; na.textContent = `${c.needs_admin || 0} ${c.needs_admin === 1 ? "needs" : "need"} admin`; }   // v0.4.6 #3 (admins only)
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
// v0.4 #8: light/dark. Follows the system unless the person picked one with the light/dark button (kept on this computer).
{ const r = document.documentElement, k = "gacTheme";
  try { const t = localStorage.getItem(k); if (t === "dark" || t === "light") r.dataset.theme = t; } catch {}
  const b = document.getElementById("themeBtn");
  if (b) b.onclick = () => { const dark = r.dataset.theme === "dark" || (!r.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    r.dataset.theme = dark ? "light" : "dark"; try { localStorage.setItem(k, r.dataset.theme); } catch {} }; }
