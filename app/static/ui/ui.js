"use strict";
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const SS = sessionStorage;
const ASSET_V = ((document.currentScript && document.currentScript.src.match(/[?&]v=([0-9a-f]+)/)) || [])[1] || "";
try { localStorage.removeItem("reviewer"); } catch {}
const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;
const hideToast = re_ => { const t = $("#toast"); if (!re_ || re_.test(t.textContent)) { t.classList.remove("show"); clearTimeout(t._h); } };
const toast = (m, ms = 4500, undo = false) => { const t = $("#toast"); t.textContent = m;   /* round 15 (reviewer r14): 2.6 s was too quick */   // undo: true = the card Undo, or a function = its own undo
  if (undo) { const b = document.createElement("button"); b.className = "toastbtn"; b.textContent = "Undo"; b.onclick = () => typeof undo === "function" ? undo() : doUndo(); t.append(b); ms = Math.max(ms, 6000); }
  t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms); refreshUndo();
  t.onmouseenter = () => clearTimeout(t._h); t.onmouseleave = () => { clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2500); }; };   // round 17 (reviewer r16 N5)
const csrf = () => (document.cookie.match(/(?:^|; )gac_csrf=([^;]*)/) || [])[1] || "";
let SIGNING_OUT = false;   // reviewer r9: nothing may write a draft once sign-out started (beforeunload ran saveDraft after clearDrafts)
function saveDraft() { if (SIGNING_OUT) return; if (dirty && cur) try { SS.draft = JSON.stringify({id: cur.id, uid: ME && ME.id, vals: dirtyVals()}); } catch {} keepDraft(); }
// round 7 (advice): a per-card draft in localStorage, restored when the card is opened again (after leaving, a crash, sign-out)
const draftKey = id => `gac-draft-${(ME && ME.id) || "x"}-${id}`;
function keepDraft() { if (SIGNING_OUT) return; if (cur && !dirty) { dropDraft(cur.id); return; } if (dirty && cur) try { localStorage.setItem(draftKey(cur.id), JSON.stringify({ts: Date.now(), version: cur.version, vals: dirtyVals()})); } catch {} }
function dropDraft(id) { try { localStorage.removeItem(draftKey(id)); } catch {} }
function clearDrafts() { try { Object.keys(localStorage).filter(k => k.startsWith("gac-draft-")).forEach(k => localStorage.removeItem(k)); delete SS.draft; } catch {} }
async function call(u, o = {}) {
  if (o.method && o.method !== "GET") o.headers = {...(o.headers || {}), "X-CSRF-Token": csrf()};
  const r = await fetch(u, o); let j = null; try { j = await r.json(); } catch {}
  const av = r.headers.get("X-GAC-Asset");   // round 9: the app was updated while this tab was open
  if (av && ASSET_V && av !== ASSET_V && !$("#verWarn")) {
    if (!dirty && !SAVING && !$("#dlg").open && !$$('[aria-busy="true"]').length) { saveDraft(); location.reload(); }   // round 11 (newcomer r10): never mid-action
    else { document.body.insertAdjacentHTML("afterbegin", `<div id="verWarn" class="alert" role="alert">The scanner was updated. Save your work, then <button type="button" class="link" id="verReload">reload the page</button>.</div>`);
      $("#verReload").onclick = () => location.reload(); }   // audit 2026-10: a javascript: URL is blocked by the CSP
  }
  const uid = r.headers.get("X-GAC-User");
  if (ME && uid && uid !== String(ME.id) && !$("#swapWarn")) {   // another tab signed this browser in as someone else
    document.body.insertAdjacentHTML("afterbegin", `<div id="swapWarn" class="alert bad" role="alert">Someone else signed in on this browser in another tab, so your actions would be saved under <b>their name</b>. <a href="/ui">Reload</a> or sign in again.</div>`);
  }
  if (r.status === 401) { const e = new Error(handleAuth(401, j)); e.status = 401; e.data = j || {}; throw e; }
  if (!r.ok) { const e = new Error((j && (j.error || j.detail)) || ("Server error " + r.status)); e.status = r.status; e.data = j || {}; throw e; }
  const sm = o.method === "POST" && u.match(/^\/api\/cards\/(\d+)$/); if (sm) dropDraft(+sm[1]);   // saved: the draft is no longer needed
  return j;
}
// audit 2026-10: ONE place for an expired session, used by call(), the downloads (fetchOk) and the uploads. While photos are
// still waiting to upload, a 401 pauses the uploads (the photos stay in this tab) instead of leaving the page for /login.
function handleAuth(status, j) {
  if (status !== 401) return (j && (j.error || j.detail)) || null;
  if (upPending()) { authPause(); return "Your sign-in expired. Sign in again: the waiting photos upload after that."; }
  saveDraft(); dirty = false; location.href = "/login?next=" + encodeURIComponent("/ui" + location.hash); return "Please sign in.";
}
async function fetchOk(u) {   // audit 2026-10: downloads need the raw Response (a Blob), but errors are handled like call()'s
  const r = await fetch(u, {credentials: "same-origin"}); if (r.ok) return r;
  let j = {}; try { j = await r.json(); } catch {}
  const e = new Error(handleAuth(r.status, j) || r.statusText || ("Server error " + r.status)); e.status = r.status; e.data = j; throw e;
}
const post = (u, b) => call(u, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(b)});
async function busy(btn, label, fn) {
  if (btn.getAttribute("aria-busy") === "true") return;
  const old = btn.innerHTML; btn._old = old; btn.setAttribute("aria-busy", "true"); btn.disabled = true; btn.innerHTML = label;
  const t0 = Date.now();   // round 16 (part-timer r15): the busy label stays at least 0.5 s, so "Saving…" is seen even on a fast save
  try { return await fn(); } finally { const w = 500 - (Date.now() - t0); if (w > 0) await new Promise(r => setTimeout(r, w)); btn.removeAttribute("aria-busy"); btn.disabled = ["bApprove", "bReject", "bSave", "bPending"].includes(btn.id) && !CARD_READY; btn.innerHTML = old; }
}
const LABEL = {name: "Name", title: "Job title", company: "Company", emails: "Email", phones: "Phone", website: "Website", address: "Address", first_name: "First name", last_name: "Last name", social: "Social profiles", note: "Note", department: "Department", other_address: "Other address", credentials: "Credentials (e.g. CPA, PhD)"};
const when = t => t ? new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "";

/* ---------- dialog helper ---------- */
let DLG_DONE = null;   // round 11: a dialog is cancelled when the page moves to another card underneath it
function ask({title, html = "", input = null, buttons, wide = false, check = null}) {
  $$('[aria-busy="true"]').forEach(b => { if (b._old !== undefined) { b.innerHTML = b._old; b.removeAttribute("aria-busy"); } });   // no spinner behind a question
  const d = $("#dlg"); d.classList.toggle("wide", !!wide); $("#dlgTitle").textContent = title; $("#dlgBody").innerHTML = html; $("#dlgErr").textContent = "";
  $("#dlgInputWrap").hidden = !input;
  if (input) { $("#dlgInputLabel").textContent = input.label; $("#dlgInput").value = input.value || ""; $("#dlgInput").placeholder = input.placeholder || ""; $("#dlgInput").maxLength = input.max || 200; $("#dlgInput").type = input.type || "text"; }
  $("#dlgBtns").innerHTML = buttons.map((b, i) => `<button type="button" class="btn ${b.cls || ""}${b.focus ? " dfocus" : ""}" data-i="${i}">${esc(b.label)}</button>`).join("");
  if (DLG_DONE) DLG_DONE({value: null, cancelled: true});   // round 14: a question replaced by another one is answered "cancelled", never left hanging
  return new Promise(res => {
    const done = v => { DLG_DONE = null; d.close(); res(v); };
    DLG_DONE = done;
    $$("#dlgBtns button").forEach(el => el.onclick = () => {
      const b = buttons[+el.dataset.i], val = $("#dlgInput").value.trim();
      if (b.needInput && input && !val) { $("#dlgErr").textContent = input.required || "Please fill this in."; $("#dlgInput").focus(); return; }
      if (b.needInput && check) { const ce = check(val); if (ce) { $("#dlgErr").textContent = ce; $("#dlgInput").focus(); return; } }   // round 24: the dialog stays open on a bad input
      done({value: b.value, input: val});
    });
    d.oncancel = e => { e.preventDefault(); done({value: null}); };
    $("#dlgForm").onsubmit = e => { e.preventDefault(); const p = buttons.find(b => b.primary); if (p) $(`#dlgBtns [data-i="${buttons.indexOf(p)}"]`).click(); };
    d.showModal(); (input ? $("#dlgInput") : ($("#dlgBtns button.dfocus") || $("#dlgBtns button"))).focus();   // reviewer r8: a destructive dialog focuses Cancel
  });
}

/* ---------- signed-in user ---------- */
let ME = null;
const who = () => ME ? ME.initials : "";
const needWho = async () => true;
async function loadMe() {
  ME = await call("/api/me");
  { const w = document.getElementById("scanWho"); if (w && ME) w.innerHTML = `Scanning as <b>${esc(ME.display || ME.username)}</b> (${esc(ME.initials || "")}). Not you? <a href="/login">Sign in as yourself</a>.`; }   // round 15 (coordinator r14 #4)
  $("#whoText").innerHTML = `<b>${esc(ME.display)}</b> (${esc(ME.initials)})`;
  $("#navAdmin").hidden = ME.role !== "admin"; $("#archiveAll").hidden = ME.role !== "admin"; $("#archiveBatch").hidden = ME.role !== "admin";
  if (ME.role !== "admin") $$("#exStatus option[value=all], #exStatus option[value=pending], #exStatus option[value=rejected]").forEach(o => o.remove());
  if (ME.must_change) setTimeout(() => changePw("Please choose your own password (the one you were given is temporary)."), 400);
}
async function changePw(reason) {
  const a = await ask({title: "Change password", html: `<p>${esc(reason || "")}</p><label for="pwOld">Current password</label><input id="pwOld" type="password" autocomplete="current-password">`,
    input: {label: "New password (10+ characters)", required: "Enter a new password.", type: "password"}, buttons: [{label: "Change password", cls: "primary", value: 1, needInput: true, primary: true}, {label: "Later", value: null}]});
  if (!a.value) return;
  try { await post("/api/me/password", {old: $("#pwOld").value, new: a.input}); toast("Password changed."); ME.must_change = 0; }
  catch (e) { await ask({title: "Password not changed", html: `<p>${esc(e.message)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); changePw(reason); }
}
$("#pwChange").onclick = () => changePw();
$("#logout").onclick = async () => {
  if (dirty && cur && !$("#v-review").hidden) {
    const a = await ask({title: `Sign out and discard the changes to card #${cur.id}?`, html: "<p>Unsaved changes are lost when you sign out.</p>",
                         buttons: [{label: "Stay", cls: "primary", value: null, primary: true, focus: true}, {label: "Sign out", cls: "danger", value: 1}]});
    if (!a.value) return; dirty = false; }
  SIGNING_OUT = true; dirty = false; clearTimeout(keepDraft.t); clearDrafts();   // reviewer r8/r9: drafts don't survive sign-out (shared computers)
  const back = location.hash && !location.hash.startsWith("#upload") ? location.hash.replace(/^#queue\?.*$/, "#queue") : "#queue";   // reviewer r7: signing back in returns here (newcomer r9: without a remembered batch)
  ["lastBatch", "lastBatchUid", "lastBatchAt", "batchChosen", "batchChosenUid", "queueHash", "order", "draft", "batch"].forEach(k => { try { delete SS[k]; } catch {} });
  await post("/api/auth/logout", {}); location.href = "/login?next=" + encodeURIComponent("/ui" + back); };
$("#dlgInput").type = "text";
/* ---------- undo ---------- */
async function refreshUndo() { try { const u = await call("/api/undo"); $("#undoBtn").hidden = !u.id; $("#undoBtn").title = u.id ? "Undo: " + u.label + " (U)" : ""; $("#undoBtn").dataset.label = u.label || ""; } catch {} }
async function doUndo() {
  try { const r = await post("/api/undo", {}); toast("Undone: " + r.undone + (r.notice ? ". " + r.notice : ""), r.notice ? 8000 : 4500); refreshCounts();
    const {v, id} = parseHash(); if (v === "review" && r.cards.includes(+id)) openCard(+id); else if (v === "review" && r.cards.length) location.hash = "review/" + r.cards[0]; else if (v === "queue") loadQueue(); else if (v === "export") exportInfo();
    refreshUndo();
  } catch (e) { toast(e.message); }
}
$("#undoBtn").onclick = doUndo;
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
  if (view === "export") { if (!SS.exportFrom) { const pv = route.prev, fb = pv === "upload" ? (B && B.id) : pv === "review" ? (cur && cur.batch) : pv === "queue" ? Q.batch : null; if (fb && fb !== "__none__") SS.exportFrom = fb; } exportInfo.picked = false; exportInfo.more = false; exportInfo(); }   // round 21: export the batch you came from
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
  if (DLG_DONE && location.hash !== lastHash) DLG_DONE({value: null, cancelled: true});   // round 11 (part-timer r4 CRITICAL): never answer a question about the previous card
  const wasReview = /^#review\//.test(lastHash);
  if (wasReview && dirty && cur && location.hash !== lastHash && !(location.hash === "#review/" + cur.id)) {
    keepDraft();
    // round 20 (reviewer r19): our own Leave / Stay question instead of the browser's OK / Cancel box
    const to = location.hash; history.replaceState(null, "", lastHash);
    ask({title: `Leave card #${cur.id}?`, html: "<p>You have unsaved changes. Leave anyway?</p><p class=\"small\">They are kept as a draft on this browser.</p>",
         buttons: [{label: "Stay", cls: "primary", value: null, primary: true, focus: true}, {label: "Leave", value: 1}]})
      .then(a => { if (a && a.value) { dirty = false; location.hash = to; } });
    return;
  }
  lastHash = location.hash; route();
});

/* ---------- upload / batch ---------- */
const drop = $("#drop");
if (matchMedia("(pointer: coarse)").matches && !matchMedia("(hover: hover)").matches) {   // phones/tablets: there is no drag and drop
  $("#dropHead").textContent = "Add card photos"; $("#dropHelp").textContent = "Take or choose photos or PDFs.";
}
["dragenter", "dragover"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(e => drop.addEventListener(e, () => drop.classList.remove("over")));
drop.addEventListener("drop", async ev => { ev.preventDefault(); enqueue(await filesFromDrop(ev.dataTransfer)); });
$("#bPhotos").onclick = () => $("#fPhotos").click(); $("#bFolder").onclick = () => $("#fFolder").click(); $("#bCam").onclick = () => $("#fCam").click();
["#fPhotos", "#fFolder", "#fCam"].forEach(s => $(s).addEventListener("change", e => { enqueue([...e.target.files]); e.target.value = ""; }));
document.addEventListener("dragover", e => e.preventDefault()); document.addEventListener("drop", e => e.preventDefault());
async function filesFromDrop(dt) {
  const items = [...(dt.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (!items.length) return [...dt.files];
  const out = [];
  const walk = ent => new Promise(res => {
    if (ent.isFile) ent.file(f => { out.push(f); res(); }, () => res());
    else if (ent.isDirectory) { const r = ent.createReader(); const all = [];
      const rd = () => r.readEntries(async es => { if (!es.length) { for (const x of all) await walk(x); res(); } else { all.push(...es); rd(); } }, () => res()); rd(); }
    else res();
  });
  for (const e of items) await walk(e);
  return out;
}

let B = JSON.parse(SS.batch || "null");   // {id,label,rows:[{key,file,state,msg,job,card,thumb}]}
const saveB = () => { if (B) SS.batch = JSON.stringify({...B, rows: B.rows.map(r => ({...r, thumb: undefined, blob: undefined}))}); };
let BATCHES = []; call("/api/batches").then(b => BATCHES = b).catch(() => {});
let uploading = 0; const UPCONC = 3, upq = [];
const upPending = () => !!(upq.length || uploading || (B && B.rows.some(r => r.state === "wait" && r.blob)));
// audit 2026-10: a 401 while uploading used to mark every photo "Not added: Please sign in" and the files were lost. Now the
// queue pauses, the photos stay "waiting", one message offers a sign-in in a new tab, and the uploads resume by themselves.
let AUTH_PAUSED = false, authT = null;
function authPause() {
  AUTH_PAUSED = true;
  let el = $("#authPause"); if (!el) { document.body.insertAdjacentHTML("afterbegin", `<div id="authPause" class="alert bad" role="alert"></div>`); el = $("#authPause"); }
  const n = B ? B.rows.filter(r => r.state === "wait").length : 0;
  el.innerHTML = `<b>Your sign-in expired, so uploading is paused.</b> ${n ? plural(n, "photo") + " waiting; nothing is lost. " : ""}Keep this tab open, <a href="/login?next=%2Fui%23upload" target="_blank" rel="noopener">sign in again</a> (opens a new tab), then come back: the upload carries on by itself.`;
  el.hidden = false; if (!authT) authT = setInterval(authCheck, 3000); renderBatch();
}
async function authCheck() {   // runs while this tab is hidden too: the person is signing in in the other tab
  if (!AUTH_PAUSED) return;
  let s = null; try { s = await (await fetch("/api/auth/state", {credentials: "same-origin"})).json(); } catch { return; }
  if (!s || !s.user || !AUTH_PAUSED) return;
  if (ME && s.user.id !== ME.id) { $("#authPause").innerHTML = `This browser is now signed in as <b>${esc(s.user.display)}</b>, not <b>${esc(ME.display)}</b>, so uploading stays paused (the photos would be saved under their name). Sign in as ${esc(ME.display)} in the other tab.`; return; }
  AUTH_PAUSED = false; clearInterval(authT); authT = null; $("#authPause").hidden = true;
  toast("Signed in again: uploading carries on.", 4000); renderBatch(); pumpUploads(); poll();
}
addEventListener("focus", () => { if (AUTH_PAUSED) authCheck(); });
function newBatch() {
  // round 8 (newcomer r8 N2): the batch name is kept exactly as typed (only spaces tidied, control characters and < > dropped);
  // nothing is appended. Your own batch with the same name from the last 12 h is reused; if someone else (or an older batch)
  // already uses the name, a visible " (2)" is added and you are told.
  if (B) B.rows.forEach(dropThumb);   // audit 2026-10: the previous batch's rows are gone from the page
  const d = new Date(), id = "B" + d.toISOString().replace(/\D/g, "").slice(0, 14) + "-" + Math.random().toString(16).slice(2, 6);   // round 13: unique even when two people start in the same second
  const name = $("#batchName").value.replace(/[\u0000-\u001f\u007f<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 120);
  const norm = x => (x || "").replace(/\s+/g, " ").trim().toLowerCase();
  const all = BATCHES || [];
  const same = name && all.find(b => b.mine && norm(b.batch_label) === norm(name) && b.started > Date.now() / 1000 - 12 * 3600);
  if (same) { B = {id: same.batch, label: same.batch_label, rows: [], t0: Date.now() / 1000, uid: ME && ME.id}; saveB(); toast(`Added to your existing batch “${name}”.`); return; }
  let label = name || ("Untitled batch, " + d.toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}));
  if (all.some(b => norm(b.batch_label) === norm(label))) {
    let k = 2; while (all.some(b => norm(b.batch_label) === norm(`${label} (${k})`))) k++;
    toast(`A batch called “${label}” already exists, so this one is saved as “${label} (${k})”.`, 7000); label = `${label} (${k})`;
  }
  B = {id, label, rows: [], t0: Date.now() / 1000, uid: ME && ME.id}; saveB();
}
const isImg = f => /^image\//.test(f.type) || /\.(jpe?g|png|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name) || isPdf(f);
const isPdf = f => f.type === "application/pdf" || /\.pdf$/i.test(f.name);   // round 18: each page / card on a page becomes a card
// round 15 (coordinator r14 #4): a sign-in left over on this browser silently acted as someone else. Before the first upload
// in a tab, ask who is scanning; "someone else" signs out.
async function confirmWho() {
  if (!ME || SS.whoOk === String(ME.id) || SS.whoSigned === "1") return true;   // signed in in this tab: it is you
  const r = await ask({title: "Who is scanning?", html: `<p>This browser is signed in as <b>${esc(ME.display || ME.username)}</b> (${esc(ME.initials || "")}). Cards you upload are recorded under this name.</p>`,
    buttons: [{label: `Yes, I am ${ME.display || ME.username}`, cls: "primary", value: "me", primary: true}, {label: "No, sign out so I can sign in", value: "out"}, {label: "Cancel", value: null}]});
  if (r.value === "me") { SS.whoOk = String(ME.id); return true; }
  if (r.value === "out") { try { await post("/api/auth/logout", {}); } catch {} location.href = "/login"; }
  return false;
}
async function enqueue(files) {
  if (!files.length) { toast("Nothing was selected."); return; }
  if (!await confirmWho()) return;
  // coordinator r2 N1: a different name typed in "Name this batch", or a batch left over from hours ago, starts a NEW batch
  const typed = $("#batchName").value.replace(/\s+/g, " ").trim().toLowerCase();
  const fresh = !B || B.rows.every(r => ["done", "rej", "err", "cancel"].includes(r.state)) && $("#clearBatch").dataset.fresh === "1";
  const renamed = B && !fresh && ((typed && !(B.label || "").toLowerCase().startsWith(typed)) || (!typed && B.t0 && Date.now() / 1000 - B.t0 > 4 * 3600));
  // audit 2026-10 P0-14: photos of the current batch still waiting to upload would be filed under the NEW batch (and no longer
  // tracked); finish (or cancel) this batch's uploads first
  if ((fresh || renamed) && B && (upq.length || uploading)) { toast(`Photos of “${B.label}” are still uploading. Wait until they are done (or cancel them), then start the new batch.`, 7000); return; }
  if (fresh && B) newBatch();
  else if (renamed) { const old = B.label; newBatch(); toast(`Started a new batch “${B.label}” (the previous one was “${old}”).`, 6000); }
  if (!B) newBatch();
  $("#clearBatch").dataset.fresh = "0";
  B.rows = B.rows.filter(r => r.state !== "cancel" || dropThumb(r));   // round 21 (reviewer r20): no stale cancelled rows on the next upload
  for (const f of files) {
    const row = {key: Math.random().toString(36).slice(2), file: f.webkitRelativePath || f.name, state: "wait"};
    if (/(^|\/)\./.test(row.file)) continue;              // hidden system files in folders
    if (!isImg(f)) { row.state = "rej"; row.msg = "Can't scan this file. Use JPG, PNG, HEIC or PDF."; }
    else if (!f.size) { row.state = "rej"; row.msg = "File is empty."; }
    else { row.blob = f; row.thumb = null; if (!isPdf(f) && !/\.hei[cf]$/i.test(f.name)) thq.push(row); upq.push(row); }
    ROWB.set(row, B); B.rows.push(row);
  }
  B.stopped = false; saveB(); renderBatch(); pumpUploads(); pumpThumbs();
}
// audit 2026-10: upload thumbnails were full-resolution blob URLs that were never revoked (hundreds of decoded 12 MP photos
// on a big batch). Now one ~96 px thumbnail per photo, made one at a time; its URL is revoked when the row goes.
const thq = []; let thBusy = false;
function dropThumb(r) { if (r && r.thumb && r.thumb.startsWith("blob:")) URL.revokeObjectURL(r.thumb); if (r) r.thumb = null; return false; }
async function pumpThumbs() {
  if (thBusy) return; thBusy = true;
  try { while (thq.length) {
    const r = thq.shift(), live = () => B && B.rows.includes(r) && r.blob; if (!live() || r.thumb) continue;
    let u = null;
    try { const bm = await createImageBitmap(r.blob, {resizeWidth: 96, resizeQuality: "low"}), c = document.createElement("canvas");
      c.width = bm.width; c.height = bm.height; c.getContext("2d").drawImage(bm, 0, 0); if (bm.close) bm.close();
      const tb = await new Promise(res => c.toBlob(res, "image/jpeg", 0.7)); if (tb) u = URL.createObjectURL(tb); } catch {}
    if (!u) u = URL.createObjectURL(r.blob);   // no resize support (older browsers): the photo itself, as before
    if (!live()) { URL.revokeObjectURL(u); continue; }
    r.thumb = u; renderRow(r);
  } } finally { thBusy = false; }
}
function pumpUploads() {
  if (AUTH_PAUSED) return;
  while (uploading < UPCONC && upq.length) { const r = upq.shift(); uploading++; upload(r).finally(() => { uploading--; pumpUploads(); }); }
}
const ROWB = new WeakMap();   // audit 2026-10 P0-14: row -> the batch it was added to (not whatever batch is current at send time)
function upload(row, allowDup = false) {
  const bb = ROWB.get(row) || B;
  return new Promise(res => {
    const fd = new FormData(); fd.append("image", row.blob, row.file.split("/").pop());
    fd.append("engine", $("#engine").value); fd.append("batch", bb.id); fd.append("batch_label", bb.label);
    if (allowDup) fd.append("allow_duplicate", "1");
    if ($("#skipAi") && $("#skipAi").checked) fd.append("skip_ai", "1");   // round 23: Skip AI for this scan
    const x = new XMLHttpRequest(); row.xhr = x; x.open("POST", "/api/jobs");
    x.onabort = () => { row.state = "cancel"; row.msg = ""; delete row.xhr; saveB(); renderBatch(); res(); };   // round 21: Cancel stops an upload in flight
    x.setRequestHeader("X-CSRF-Token", csrf());
    row.state = "up"; row.pct = 0; renderBatch();
    x.upload.onprogress = e => { if (e.lengthComputable) { row.pct = Math.round(100 * e.loaded / e.total); renderRow(row); } };
    x.onload = () => {
      delete row.xhr; let j = {}; try { j = JSON.parse(x.responseText); } catch {}
      conn(true);
      if (x.status === 200 && j.pdf) { row.state = "queued"; row.job = j.job; row.pdf = true; row.pages = j.pages; if (j.batch && j.batch !== bb.id) bb.id = j.batch; }   // round 20: a PDF is read page by page in the background
      else if ([200, 409, 422].includes(x.status) && j.jobs && j.jobs.length) splitRow(row, j, bb);   // round 18: a PDF / sheet of cards came back as several cards
      else if (x.status === 200) { row.state = "queued"; row.job = j.job; if (j.batch && j.batch !== bb.id) bb.id = j.batch; }   // round 13: the server may give this batch its own id
      else if (x.status === 409 && j.cancelled) { row.state = "cancel"; row.msg = ""; }
      else if (x.status === 409) { row.state = "dup"; row.msg = j.error; row.dupOf = j.duplicate_of; }
      else if (x.status === 401) { row.state = "wait"; row.msg = ""; upq.unshift(row); authPause(); }   // audit 2026-10: kept, sent after signing in
      else if (x.status === 403 && j.need === "reload" && !row.csrfTry) {   // stale CSRF cookie: any signed-in GET renews it; send once more
        row.csrfTry = 1; row.state = "wait"; row.msg = ""; call("/api/me").catch(() => {}).finally(() => { upq.unshift(row); pumpUploads(); }); }
      else { row.state = "rej"; row.msg = j.error || "Upload failed (" + x.status + ")."; row.retry = x.status >= 500 || [403, 408, 429].includes(x.status); }   // audit 2026-10: Retry button
      if (row.stop) cancelJobs([row].concat(bb.rows.filter(r => r.src === row.file)));   // round 19: Cancel pressed while this photo was uploading
      saveB(); renderBatch(); poll(); res();
    };
    // round 20: the scanner restarting is not an error: the photo waits and is sent again by itself
    x.onerror = () => { conn(false); row.state = "wait"; row.msg = ""; row.tries = (row.tries || 0) + 1; saveB(); renderBatch(); res();
      if (!row.stop) setTimeout(() => { if (row.state === "wait" && bb.rows.includes(row)) { upq.push(row); pumpUploads(); } }, Math.min(15000, 2000 * row.tries)); };
    x.send(fd);
  });
}
// round 20 (b): one calm line while the scanner can't be reached; everything retries by itself
function conn(ok) {
  let el = $("#reconn");
  if (!el) { document.body.insertAdjacentHTML("afterbegin", `<div id="reconn" class="alert" role="status" hidden>Reconnecting… your cards are safe.</div>`); el = $("#reconn"); }
  el.hidden = !!ok;
}
function addKids(row, job) {   // round 20: cards of a PDF appear as each page is read
  row.kids = row.kids || 0;
  const dir = row.file.includes("/") ? row.file.slice(0, row.file.lastIndexOf("/") + 1) : "";
  const fresh = (job.children || []).slice(row.kids); if (!fresh.length) return;
  row.kids += fresh.length;
  const rows = fresh.map(x => ({key: Math.random().toString(36).slice(2), file: dir + x.file, state: x.job ? "queued" : (x.status === 409 ? "dup" : "rej"),
    job: x.job, msg: x.job ? "" : x.error, dupOf: x.duplicate_of, src: row.file}));
  const at = B.rows.indexOf(row); B.rows.splice(at, 0, ...rows);
}
function splitRow(row, j, bb = B) {
  // one row per card, named after the file and page it came from ("cards.pdf (page 2 of 5, card 3 of 8)")
  if (j.batch && j.batch !== bb.id) bb.id = j.batch;
  const dir = row.file.includes("/") ? row.file.slice(0, row.file.lastIndexOf("/") + 1) : "";
  const rows = j.jobs.map(x => ({key: Math.random().toString(36).slice(2), file: dir + x.file, state: x.job ? "queued" : (x.status === 409 ? "dup" : "rej"),
    job: x.job, msg: x.job ? "" : x.error, dupOf: x.duplicate_of, src: row.file}));
  bb.rows.splice(bb.rows.indexOf(row), 1, ...rows); dropThumb(row);
  toast(`${row.file.split("/").pop()}: ${j.jobs.length} cards found` + (j.back_skipped ? ". Back photo not used (single cards only)." : "."), 6000);
}
let pollT = null;
async function poll() {
  clearTimeout(pollT);
  if (!B || AUTH_PAUSED) return;   // audit 2026-10: resumed by authCheck()
  const live = B.rows.filter(r => ["queued", "reading", "splitting"].includes(r.state) && r.job);
  if (!live.length) return;
  try {
    const j = await call("/api/jobs?ids=" + live.map(r => r.job).join(","));
    const byJob = new Map(B.rows.filter(x => x.job).map(x => [x.job, x]));   // audit 2026-10: no O(n²) find on big batches
    for (const job of j.jobs) {
      const r = byJob.get(job.id); if (!r) continue;
      if (r.pdf) {
        addKids(r, job);
        if (job.state === "split") { B.rows.splice(B.rows.indexOf(r), 1); toast(`${r.file.split("/").pop()}: ${plural(r.kids || 0, "card")} found.` + (job.note ? " " + job.note : ""), 6000); }
        else if (job.state === "error") { r.state = "err"; r.msg = job.error; }
        else if (job.state === "cancelled") { r.state = "cancel"; r.msg = ""; }
        else { r.state = job.state; r.page = job.page; }
        continue;
      }
      if (job.state === "done") { delete r.blob; r.state = "done"; r.card = {id: job.card.id, img: job.card.image, name: job.card.name || (job.card.company ? "(no name) – " + job.card.company : "(no name)"), att: job.card.attention.map(a => a.text), blocked: !!job.card.blocked}; }
      else if (job.state === "error") { r.state = "err"; r.msg = job.error; }
      else if (job.state === "cancelled") r.state = "cancel";
      else { r.state = job.state; r.msg = job.waiting_memory ? (job.waiting_memory_msg || "Waiting for memory…") : ""; }   // round 22: calm memory-guard wait
    }
    const known = new Set(j.jobs.map(x => x.id));
    live.filter(r => !known.has(r.job)).forEach(r => { r.state = "err"; r.msg = "The scanner restarted. Add this photo again."; });
    conn(true);
    const fin = B.rows.filter(r => ["done", "err"].includes(r.state) && r.job).length;
    if (!B.t0) B.t0 = Date.now() / 1000;
    B.ahead = j.queue_ahead || 0;
    B.avg = fin ? (Date.now() / 1000 - B.t0) / fin : (j.avg_seconds ? j.avg_seconds * Math.max(1, B.rows.filter(r => r.state === "queued").length) / Math.max(1, B.rows.length) : null);
    saveB(); renderBatch();
    if (j.jobs.some(x => x.state === "done" || x.state === "error")) { refreshCounts(); if (!$("#v-queue").hidden && Q.batch && Q.batch === B.id) loadQueue(); }   // round 15: newly read cards of the batch shown appear without a reload
  } catch (e) { if (e instanceof TypeError) conn(false); }   // network error: say "Reconnecting…" and keep trying
  pollT = setTimeout(poll, 1200);
}
const ST = {splitting: "Reading PDF…", wait: "Waiting to upload", up: "Uploading…", queued: "In line to be read", reading: "Reading card…", done: "Added", rej: "Not added", dup: "Not added", err: "Failed", cancel: "Cancelled"};
function rowHTML(r) {
  const pct = {splitting: 20, wait: 0, up: Math.round((r.pct || 0) * .3), queued: 35, reading: 65, done: 100, rej: 100, dup: 100, err: 100, cancel: 100}[r.state];
  let st = esc(ST[r.state]), cls = {done: "done", rej: "err", dup: "err", err: "err", cancel: "err"}[r.state] || "work";
  if (r.state === "done") st = `<a href="#review/${r.card.id}">✓ ${esc(r.card.name)} (#${r.card.id})</a> ` + (r.card.status && r.card.status !== "pending" ? `<span class="pill ${esc(r.card.status)}">${esc(r.card.status)}</span>` : r.card.blocked ? `<span class="flag bad">Blocked</span>` : r.card.att.length ? `<span class="flag low" title="${esc(r.card.att.join("; "))}">Needs a look</span>` : `<span class="flag ok">Looks good</span>`);
  if (r.state === "splitting" && r.pages) st = esc(`Reading PDF: page ${r.page || 1} of ${r.pages}…`);
  if (r.state === "queued" && r.pdf) st = "PDF in line to be read";
  if (r.msg) st += `<span class="why">${esc(r.msg)}</span>`;
  if (r.state === "wait" && AUTH_PAUSED) st += `<span class="why">Paused until you sign in again</span>`;
  if (r.blob && (r.state === "err" || (r.state === "rej" && r.retry))) st += ` <button type="button" class="link" data-retry="${r.key}">Retry</button>`;   // audit 2026-10
  if (r.state === "dup") st += ` <span class="why">${r.dupOf ? `<a href="#review/${r.dupOf}">Open card #${r.dupOf}</a> · ` : ""}${r.blob ? `<button type="button" class="link" data-again="${r.key}">Scan it anyway</button>` : ""}</span>`;
  const tsrc = r.thumb || (r.card && r.card.img ? `/img/${encodeURIComponent(r.card.img)}?w=160` : null);   // round 20: PDF/HEIC cards get the server's thumbnail once read
  const th = tsrc && r.state !== "rej" ? `<img alt="" src="${tsrc}">` : `<span class="thumbph" aria-hidden="true">${r.state === "rej" ? "✕" : "▢"}</span>`;
  return `${th}<div><div class="nm">${esc(r.file)}</div><div class="progress mini" aria-hidden="true"><div style="width:${pct}%"></div></div></div><span class="st ${cls}">${st}</span>`;
}
function renderRow(r) { const li = document.querySelector(`li[data-k="${r.key}"]`); if (li) { const h = rowHTML(r); if (li._h !== h) { li.innerHTML = h; li._h = h; } } }
function renderBatch() {
  if (!B || !B.rows.length) { $("#batch").hidden = true; return; }
  $("#batch").hidden = false; $("#batchTitle").textContent = "Batch: " + B.label;
  // audit 2026-10: the list was rebuilt on every 1.2 s poll (all images, focus lost); now only changed rows are touched
  { const ul = $("#batchList"), old = new Map([...ul.children].map(li => [li.dataset.k, li])); let prev = null;
    for (const r of B.rows) {
      let li = old.get(r.key); old.delete(r.key);
      if (!li) { li = document.createElement("li"); li.dataset.k = r.key; }
      const h = rowHTML(r), c = ["rej", "dup", "err", "cancel"].includes(r.state) ? "rej" : "";
      if (li._h !== h) { li.innerHTML = h; li._h = h; } if (li.className !== c) li.className = c;
      const at = prev ? prev.nextSibling : ul.firstChild; if (at !== li) ul.insertBefore(li, at); prev = li;
    }
    old.forEach(li => li.remove()); }
  // round 20 (d): cancelled cards are not "finished"; they are counted on their own
  const cn = B.rows.filter(r => r.state === "cancel").length, n = B.rows.length - cn, fin = B.rows.filter(r => ["done", "rej", "dup", "err"].includes(r.state)).length;
  const ok = B.rows.filter(r => r.state === "done").length, bad = fin - ok, chk = B.rows.filter(r => r.state === "done" && r.card.att.length).length;
  const p = n ? Math.round(100 * fin / n) : 100; $("#batchBar div").style.width = p + "%"; $("#batchBar").setAttribute("aria-valuenow", p);
  const sum_ = B.stopMsg ? B.stopMsg.replace(/\.$/, "") : (B.stopped && fin === n ? `Stopped. ${ok} kept, ${cn} not scanned` : `${fin} of ${n} finished · ${ok} added`) + (chk && !B.stopped ? ` (${chk} to check)` : "") + (bad ? ` · ${bad} not added` : "") + (cn && !(B.stopped && fin === n) ? ` · ${cn} not scanned` : "");
  if ($("#batchSummary").textContent !== sum_) $("#batchSummary").textContent = sum_;   // audit 2026-10: a live region: only real changes
  const left = n - fin;
  const qa = left ? (B.ahead || 0) : 0;   // round 14: other people's cards waiting ahead in the shared reading line count too
  const etaS = (left + qa) * (B.avg || 0), etaTxt = etaS < 60 ? "less than a minute left" : `about ${Math.round(etaS / 60)} min left`;   // round 15 (part-timer r14): no "1 min left (≈1 s per card)"
  // round 22: when other people's cards are in line, say how many are ahead instead of a time guess
  $("#batchEta").textContent = left && qa ? `Reading… ${qa} ahead of you.` : left && B.avg ? `Reading… ${etaTxt}.` : left ? "Reading photos…" : "";
  $("#batchLegend").hidden = !fin; $("#toQueue").hidden = !ok; $("#toQueue").href = `#queue?batch=${encodeURIComponent(B.id)}&s=pending`;
  $("#clearBatch").hidden = fin !== n; $("#cancelBatch").hidden = fin === n || !!B.stopped;
}
$("#batchList").addEventListener("click", e => { if (B && !B.t0) B.t0 = Date.now() / 1000;
  const rk = e.target.dataset.retry, rr = rk && B && B.rows.find(x => x.key === rk);   // audit 2026-10: send a failed photo again (it is still in this tab)
  if (rr && rr.blob) { Object.assign(rr, {state: "wait", msg: "", retry: false, job: undefined, tries: 0, csrfTry: 0}); B.stopped = false; B.stopMsg = ""; upq.push(rr); saveB(); renderBatch(); pumpUploads(); return; }
  const k = e.target.dataset.again; if (!k) return; const r = B.rows.find(x => x.key === k); r.msg = ""; upload(r, true); });
// round 19: Cancel stops the cards still waiting (not yet uploaded or in line to be read); cards already added stay.
async function cancelJobs(rows) {
  const ids = rows.filter(r => ["queued", "splitting", "reading"].includes(r.state) && r.job).map(r => r.job); if (!ids.length) return 0;
  try { await post("/api/jobs/cancel", {ids, batch: B.id, batch_label: B.label}); } catch {}
  await poll(); return ids.length;
}
$("#cancelBatch").onclick = async () => {
  if (!B) return;
  for (let i = upq.length - 1; i >= 0; i--) if (B.rows.includes(upq[i])) { upq[i].state = "cancel"; upq.splice(i, 1); }
  B.rows.filter(r => r.state === "up").forEach(r => { r.stop = true; try { r.xhr && r.xhr.abort(); } catch {} });   // round 21 (part-timer r20): truthful Cancel
  B.rows.filter(r => r.state === "wait").forEach(r => { r.state = "cancel"; r.msg = ""; });
  await cancelJobs(B.rows); B.stopped = true;
  let kept = null;
  // round 23 (skeptic/part-timer r22): the server waits until nothing of THIS upload is still being read, then counts the
  // cards this upload made (not the whole batch). That one number is the final truth for the toast and the list.
  const sess = B.rows.map(r => r.job).filter(Boolean);
  try { const x = await post("/api/jobs/cancel", {ids: [], session: sess, batch: B.id, batch_label: B.label, all_waiting: true}); kept = x.kept; await poll(); } catch {}
  for (let i = 0; i < 20 && B.rows.some(r => r.state === "reading"); i++) { await new Promise(res => setTimeout(res, 500)); await poll(); }
  B.rows.filter(r => r.state === "cancel").forEach(r => r.msg = "");   // round 20 (d): no leftover status text
  saveB(); renderBatch();
  const ok = typeof kept === "number" ? kept : B.rows.filter(r => r.state === "done").length;
  B.rows.filter(r => !["done", "cancel", "error", "dup", "skip"].includes(r.state)).forEach(r => { r.state = "cancel"; r.msg = ""; });   // nothing is left 'reading' on screen
  const cn = B.rows.filter(r => r.state === "cancel").length; B.stopMsg = `Stopped. ${ok} kept, ${cn} not scanned.`; saveB(); renderBatch();
  toast(B.stopMsg, 4500);
};
$("#clearBatch").onclick = () => { if (B) B.rows.forEach(dropThumb); B = null; SS.removeItem("batch"); $("#batchName").value = ""; renderBatch(); $("#clearBatch").dataset.fresh = "1"; toast("Ready for a new batch."); };
function restoreBatch() { renderBatch(); poll(); refreshBatchCards(); }
async function refreshBatchCards() {   // reviewer r9: the upload list shows each card's CURRENT state, not the one at scan time
  try { const rows = (B.rows || []).filter(r => r.state === "done" && r.card); if (!rows.length) return;
    const by = new Map((await call("/api/cards?batch=" + encodeURIComponent(B.id))).map(c => [c.id, c]));   // round 15: only this batch (fast)
    const before = JSON.stringify(rows.map(r => r.card));
    rows.forEach(r => { const c = by.get(r.card.id); if (!c) return; r.card.att = (c.attention || []).map(a => a.text); r.card.status = c.status; r.card.blocked = !!c.blocked; r.card.name = c.name || r.card.name; });
    if (JSON.stringify(rows.map(r => r.card)) !== before) { saveB(); renderBatch(); } } catch {}
}

/* ---------- queue ---------- */
const Q = {s: "pending", batch: "", att: false, dup: false, nx: false, text: "", arch: false, cards: [], sel: new Set()};
function applyQueueState(q) {
  if (q.has("s")) Q.s = q.get("s") === "all" ? "" : q.get("s");
  // round 8 (newcomer r8 N1): the batch filter is kept when coming back (menu link, ↩ Queue, back button); 'all' = All batches.
  // With no batch remembered yet, the queue opens on YOUR most recent batch (chosen in loadQueue), not on everyone's cards.
  // round 11 (newcomer r10 N2): a remembered batch counts only for the person who chose it, and only until they start a newer batch
  // round 12 (newcomer r10 N2): only a batch the person CHOSE in the batch dropdown this session is remembered. Opening a
  // card of another batch, its ↩ Queue link or a look-alike link no longer changes what the top-bar "Review queue" shows.
  const remembered = SS.batchChosen !== undefined && ME && SS.batchChosenUid === String(ME.id) ? SS.batchChosen : null;
  Q.batch = q.has("batch") ? (q.get("batch") === "all" ? "" : q.get("batch")) : remembered;
  Q.batchFromMemory = !q.has("batch") && remembered !== null;   // round 24 (newcomer/datamanager r23): the queue always opens on your newest batch
  Q.att = q.get("att") === "1"; Q.nx = q.get("nx") === "1"; Q.dup = q.get("dup") === "1"; Q.text = q.get("q") || ""; Q.arch = q.get("arch") === "1";
  $$("#statusTabs button").forEach(x => x.setAttribute("aria-selected", x.dataset.s === Q.s));
  $("#fAtt").checked = Q.att; $("#fNew").checked = Q.nx; $("#fDup").checked = Q.dup; $("#fText").value = Q.text; $("#fArch").checked = Q.arch;
}
function pushQueueState() {
  const p = new URLSearchParams(); p.set("s", Q.s); p.set("batch", Q.batch || "all"); SS.lastBatch = Q.batch || ""; SS.lastBatchUid = ME ? String(ME.id) : ""; SS.lastBatchAt = String(Date.now() / 1000); if (Q.att) p.set("att", "1"); if (Q.nx) p.set("nx", "1"); if (Q.dup) p.set("dup", "1"); if (Q.text) p.set("q", Q.text); if (Q.arch) p.set("arch", "1");
  SS.queueHash = "#queue?" + p;
  if (location.hash.startsWith("#queue") && !$("#dlg").open) history.replaceState(null, "", "#queue?" + p);   // round 15: never rewrite the URL of another page or under an open question
}
$$("#statusTabs button").forEach(b => b.onclick = () => { Q.s = b.dataset.s; $$("#statusTabs button").forEach(x => x.setAttribute("aria-selected", x === b)); Q.sel.clear(); pushQueueState(); loadQueue(); });
$("#fAtt").onchange = e => { Q.att = e.target.checked; pushQueueState(); renderQueue(); };
$("#fNew").onchange = e => { Q.nx = e.target.checked; pushQueueState(); renderQueue(); };
$("#fDup").onchange = e => { Q.dup = e.target.checked; pushQueueState(); renderQueue(); };
$("#fArch").onchange = e => { Q.arch = e.target.checked; Q.sel.clear(); pushQueueState(); loadQueue(); };
let fTextT = null;   // audit 2026-10: no full re-render on every keystroke
$("#fText").oninput = e => { Q.text = e.target.value; clearTimeout(fTextT); fTextT = setTimeout(() => { pushQueueState(); renderQueue(); }, 150); };
// round 21 (part-timer/reviewer r20): ~130 batches in the drop-down. Recent ones (and the one in use) are listed; old and test batches behind "Show all"
let SHOWALLB = false;
const TESTB = /\b(qa|test|demo|e2e|skeptic|r\d{1,2})\b/i;
function trimB(list, keep) { if (SHOWALLB) return list;   // round 23 (r22 coordinator/skeptic): only the current batch until "More batches…"
  return list.filter(b => b.batch === keep); }
$("#fBatch").addEventListener("change", e => { if (e.target.value === "__showall__") { e.stopImmediatePropagation(); SHOWALLB = true; e.target.value = Q.batch || ""; loadQueue(); } }, true);
$("#fBatch").onchange = e => { Q.batch = e.target.value; SS.batchChosen = Q.batch; SS.batchChosenUid = ME ? String(ME.id) : ""; SS.lastBatch = Q.batch; SS.lastBatchUid = ME ? String(ME.id) : ""; SS.lastBatchAt = String(Date.now() / 1000); Q.sel.clear(); pushQueueState(); loadQueue(); };
function filterBatchOptions() {   // the batch list gets long: type to narrow it
  const t = ($("#fBatchQ") && $("#fBatchQ").value || "").toLowerCase().trim();
  $$("#fBatch option").forEach(o => o.hidden = (!!t && o.value !== "" && o.value !== Q.batch && !o.textContent.toLowerCase().includes(t)) || (!t && o.dataset.old === "1" && !SHOWALLB && o.value !== Q.batch));
}
$("#fBatchQ") && ($("#fBatchQ").oninput = filterBatchOptions);
async function refreshCounts() {
  // round 15 (part-timer r14): the badge counts YOUR pending cards (batches you scanned), from a cheap server count; it never
  // touches the queue's tabs (those always come from the batch shown, see renderQueue)
  try {
    const c = await call("/api/counts" + (Q.batch ? "?batch=" + encodeURIComponent(Q.batch) : ""));
    const rd = B && B.uid === (ME && ME.id) ? B.rows.filter(r => ["wait", "up", "queued", "reading"].includes(r.state)).length : 0;
    const pb = $("#pendingBadge"); pb.hidden = !c.mine_pending && !rd;
    pb.textContent = String(c.mine_pending) + (rd ? ` +${rd}` : "");
    const lbl = `${c.mine_pending} pending in your batches (the batches you scanned; ${c.everyone_pending} pending from everyone)` + (rd ? `; ${rd} more of yours still being read` : "");
    pb.setAttribute("aria-label", lbl); pb.title = lbl;
    if ($("#v-queue").hidden) $$("#statusTabs button span").forEach(x => x.textContent = "");
    return c;
  } catch { return null; }
}
let qSeq = 0, STATUS = {}, MINE = new Set();
function qBlank(msg) {   // round 15 (newcomer r14 BLOCKER): nothing of another batch is ever on screen while loading
  Q.cards = []; Q.cardsFor = undefined; Q.sel.clear(); $("#qBody").innerHTML = ""; $$("#statusTabs button span").forEach(x => x.textContent = "");
  $("#selAll").checked = false; $("#selNote").hidden = true; syncSel();
  if (msg) { $("#qEmpty").hidden = false; $("#qEmpty").innerHTML = msg; }
}
async function loadQueue(force) {
  // round 15 (newcomer r14 BLOCKER): the queue is STRICTLY scoped to one batch at all times. While loading, the old rows,
  // counts and selection are cleared (or kept ONLY if they already belong to the target), the batch is decided FIRST, and
  // only that batch's cards are asked for. An answer for another batch, or a late one, is dropped. A re-click of Review
  // queue while a load for the same target is already running is ignored (it used to restart forever and leave "Loading…").
  const myB = B && B.id && (!B.uid || (ME && B.uid === ME.id)) ? B : null;
  const reading = myB && myB.rows.some(r => ["wait", "up", "queued", "reading"].includes(r.state)) ? myB.id : null;
  if (reading && (Q.batch === null || Q.batchFromMemory || Q.batch === "")) Q.batch = reading;
  const target = Q.batch;
  if (Q.loading && Q.loadingFor === target && target !== undefined) { if (force) Q.again = true; return; }   // round 20: a forced reload runs after the one in flight
  const seq = ++qSeq; Q.loading = true; Q.loadingFor = target; $("#qLoading").hidden = false; $("#qEmpty").hidden = true;
  if (Q.cardsFor !== target) {
    const lab = (reading && target === reading ? (myB.label || "Newest batch") + " (being read…)" : (target ? "Loading this batch…" : "Loading…"));
    $("#fBatch").innerHTML = `<option value="${esc(target || "")}">${esc(lab)}</option>`; $("#fBatch").disabled = true; qBlank(reading && target === reading ? `<span class="spin" aria-hidden="true"></span> Reading your newest batch. Cards appear as they finish.` : "");
  }
  try {
    const batches = await call("/api/batches");
    if (seq !== qSeq || $("#v-queue").hidden) return;
    // round 20 (coordinator r19): your batches first, newest first; everyone else's under their own heading
    const bOpt = b => `<option value="${esc(b.batch)}">${esc(b.batch_label || b.batch)} (${b.n}${reading && b.batch === reading ? ", being read…" : ""})</option>`;
    const bNew = (a, b) => (b.started || 0) - (a.started || 0), bMine = batches.filter(b => b.mine || b.own).sort(bNew), bOth = batches.filter(b => !(b.mine || b.own)).sort(bNew);
    const buildB = () => { const tM = new Set(trimB(bMine, Q.batch)), tO = new Set(trimB(bOth, Q.batch)), hid = bMine.length - tM.size + bOth.length - tO.size;
    const hOpt = keep => b => keep.has(b) ? bOpt(b) : "";   // round 22: old/test batches are really left out (<option hidden> is ignored by some browsers); links and Show all still reach them
    $("#fBatch").innerHTML = (tM.size ? `<optgroup label="My batches">${bMine.map(hOpt(tM)).join("")}</optgroup>` : "") +
      (tO.size ? `<optgroup label="Other people's batches">${bOth.map(hOpt(tO)).join("")}</optgroup>` : "") + (SHOWALLB || Q.batch === "" ? `<option value="">All batches (everyone's)</option>` : "") +
      (hid ? `<option value="__showall__">More batches…</option>` : ""); }; // round 16 (coordinator r15 #1); round 21: old/test batches behind "Show all"
    BATCHES = batches; MINE = new Set(batches.filter(b => b.mine).map(b => b.batch));
    const byNew = (a, b) => (b.started || 0) - (a.started || 0);
    const newest = batches.filter(b => b.own).sort(byNew)[0] || batches.filter(b => b.mine).sort(byNew)[0];
    Q.reading = reading;
    if (Q.reading && (Q.batch === null || Q.batchFromMemory || Q.batch === "") && Q.batch !== Q.reading) Q.batch = Q.reading;
    if (Q.batchFromMemory && newest && newest.batch !== Q.batch) Q.batch = null;   // round 22 (part-timer r21): the queue opens on your newest batch
    Q.batchFromMemory = false;
    if (Q.batch === null) Q.batch = newest ? newest.batch : "";
    buildB();
    if (Q.reading && Q.batch === Q.reading && !batches.some(b => b.batch === Q.reading)) $("#fBatch").insertAdjacentHTML("beforeend", `<option value="${esc(Q.reading)}">${esc(myB.label || "Newest batch")} (being read…)</option>`);
    if (Q.batch && Q.batch !== "__none__" && Q.batch !== Q.reading && !batches.some(b => b.batch === Q.batch))
      $("#fBatch").insertAdjacentHTML("beforeend", `<option value="${esc(Q.batch)}">(selected batch)</option>`);
    $("#fBatch").value = Q.batch || "";
    if (($("#fBatch").value || "") !== (Q.batch || "")) { $("#fBatch").insertAdjacentHTML("beforeend", `<option value="${esc(Q.batch)}">(selected batch)</option>`); $("#fBatch").value = Q.batch; }
    pushQueueState(); filterBatchOptions();
    const want = Q.batch, qs = new URLSearchParams(); if (want) qs.set("batch", want); else qs.set("limit", "0"); if (Q.arch) qs.set("archived", "true");
    if (Q.cardsFor !== want) { $$("#statusTabs button span").forEach(x => x.textContent = ""); $("#qBody").innerHTML = ""; }   // never show another batch's counts under this name
    const cards = await call("/api/cards" + (qs.toString() ? "?" + qs : ""));
    if (seq !== qSeq || $("#v-queue").hidden || want !== Q.batch) return;
    Q.cards = want ? cards.filter(c => inBatch(c, want)) : cards; Q.cardsFor = want;
    Q.loaded = true; $("#fBatch").disabled = false;
    renderQueue(); refreshCounts();
    // round 20 (coordinator r19): the list once showed Pending (0) / All (0) for a batch that has cards, until a reload.
    // If the batch list says it has cards but none came back, load it once more.
    const bn = (batches.find(b => b.batch === want) || {}).n || 0;
    if (want && !Q.cards.length && bn > 0 && Q.retryFor !== want) { Q.retryFor = want; Q.cardsFor = undefined; setTimeout(() => { if (Q.batch === want) loadQueue(); }, 600); }
    else if (Q.cards.length) Q.retryFor = null;
  } catch (e) { if (seq === qSeq) { $("#qEmpty").hidden = false; $("#qEmpty").textContent = "Couldn't load cards: " + e.message + ". Is the scanner window still open?"; } }
  finally { if (seq === qSeq) { $("#qLoading").hidden = true; Q.loading = false; if (Q.again) { Q.again = false; setTimeout(() => loadQueue(), 0); } } }
}
const inBatch = (c, b) => !b || (b === "__none__" ? !c.batch : c.batch === b);
function filtered() {
  const raw = Q.text.toLowerCase().trim(), idOnly = /^#\d+$/.test(raw), q = raw.replace(/^#/, "");
  if (Q.cardsFor !== Q.batch) return [];   // round 15: rows are only shown for the batch they were loaded for
  return Q.cards.filter(c => (!Q.s || c.status === Q.s) && inBatch(c, Q.batch) &&
    (!Q.att || c.needs_attention) && (!Q.nx || !c.exported) && (!Q.dup || c.dup) &&
    (!q || String(c.id) === q || !idOnly && [c.name, c.company, c.email, c.filename].join(" ").toLowerCase().includes(q)));
}
function confBar(v, blocked) { if (blocked) return `<span class="chip bad" title="Fix before approving">Blocked</span>`; if (v == null) return "–"; const p = Math.round(v * 100), col = v < .6 ? "#e8a33a" : v < .8 ? "#388a9c" : "#1e7a3c";
  const w = v < .6 ? ["low", "Unclear"] : v < .8 ? ["mid", "OK"] : ["ok", "Clear"]; return `<span class="chip ${w[0]}" title="${p}%">${w[1]}</span>`; }
function aiBadge(c) {
  const s = c.ai_status, d = c.ai_detail || {};
  if (s === "queued" || s === "checking") return ' <span class="pill ai busy">AI checking…</span>';
  if (s === "checked") return ` <span class="pill ai" title="${d.changed && d.changed.length ? "AI corrected: " + esc(d.changed.map(k => LABEL[k] || k).join(", ")) : (Object.keys(d.diff || {}).length ? "AI made suggestions; all were decided" : "AI found nothing to change")}">AI-checked${d.changed && d.changed.length ? " ✎" + d.changed.length : ""}</span>`;
  if (s === "suggested") return ' <span class="pill ai">AI suggestions</span>';
  return "";
}
let qPoll = null;
function scheduleQueuePoll() {
  clearTimeout(qPoll);
  if (Q.cards.some(c => c.ai_status === "queued" || c.ai_status === "checking"))
    qPoll = setTimeout(async () => { if ($("#v-queue").hidden) return; const want = Q.batch, s0 = qSeq;
      try { const qs = new URLSearchParams(); if (want) qs.set("batch", want); else qs.set("limit", "0"); if (Q.arch) qs.set("archived", "true");   // round 16 (skeptic r15 M1): never the 200-card default page
        const cs = await call("/api/cards" + (qs.toString() ? "?" + qs : "")); if (want !== Q.batch || s0 !== qSeq || $("#v-queue").hidden) return;
        const fresh = cs.filter(c => inBatch(c, want));
        if (Q.cardsFor === want && JSON.stringify(fresh) === JSON.stringify(Q.cards)) { scheduleQueuePoll(); return; }   // audit 2026-10: nothing changed
        Q.cards = fresh; Q.cardsFor = want; renderQueue(); } catch {} }, 5000);
}
function renderQueue() {
  const ae = document.activeElement, fTr = ae && ae !== document.body && $("#qBody").contains(ae) ? ae.closest("tr") : null;   // audit 2026-10: focus survives a re-render
  const fId = fTr && fTr.dataset.id, fSel = ae && ae.classList && ae.classList.contains("sel") ? ".sel" : "a";
  const rows = filtered(); Q.cards.forEach(c => { STATUS[c.id] = c.status; }); SS.order = JSON.stringify(rows.map(c => c.id)); SS.queueHash = location.hash.startsWith("#queue") ? location.hash : (SS.queueHash || "#queue");
  $("#qBody").innerHTML = rows.map(c => `<tr data-id="${c.id}">
    <td><input type="checkbox" class="sel" aria-label="Select card #${c.id} ${esc(c.name)}" ${Q.sel.has(c.id) ? "checked" : ""}></td>
    <td><img src="/img/${esc(c.image)}?w=160" alt="" loading="lazy" decoding="async"></td>
    <td><a href="#review/${c.id}">${esc(c.name) || "<em>(no name)</em>"}</a><div class="sub">#${c.id}${c.qr ? ' <span class="src qr">QR</span>' : ""}${c.batch_label ? " · " + esc(c.batch_label) : ""}</div></td>
    <td>${esc(c.company)}</td><td>${esc(c.email)}</td><td>${confBar(c.conf, c.blocked)}</td>
    <td class="att">${c.attention.length ? `<ul class="reasons">${c.attention.map(a => `<li><span class="flag ${a.code.startsWith("dup") ? "dup" : a.code === "invalid" ? "bad" : "low"}">${esc(a.text)}</span></li>`).join("")}</ul>` : `<span class="flag ok">Looks good</span>`}</td>
    <td><span class="pill ${c.status}">${c.status}</span>${c.archived ? ' <span class="pill archived">archived</span>' : ""}${c.exported ? ` <span class="pill archived" title="First exported ${esc(when(c.exported))}">exported</span>` : ""}${aiBadge(c)}${c.reviewer ? `<div class="sub">by ${esc(c.reviewer)}</div>` : ""}</td></tr>`).join("");
  if (fId) { const tr = $(`#qBody tr[data-id="${+fId}"]`), el = tr && (tr.querySelector(fSel) || tr.querySelector("a")); if (el) el.focus({preventScroll: true}); }
  const anyFilter = Q.att || Q.nx || Q.dup || Q.text || Q.batch;
  $("#qEmpty").hidden = rows.length > 0;
  $("#qEmpty").textContent = Q.cards.length ? (anyFilter ? "No cards match. Clear the filters or search." : `No ${({pending: "pending", approved: "approved", rejected: "rejected"})[Q.s] || ""} cards in this batch. ` + (Q.s === "pending" ? "See “All”, or go to Export." : "See “Pending” or “All”.")) : "No cards yet. Go to “Scan cards” to add some.";
  if (!rows.length && Q.batch && Q.s === "pending" && !Q.att && !Q.nx && !Q.dup && !Q.text && Q.cards.length && Q.cardsFor === Q.batch && !(Q.reading && Q.batch === Q.reading))
    $("#qEmpty").innerHTML = `<b>✓ All done:</b> no pending cards in ${esc(($("#fBatch").selectedOptions[0] || {}).textContent || "this batch")}.` + (Q.cards.some(c => c.status === "approved") ? ` <a href="#export" data-export-from="${esc(Q.batch || "")}">Export it</a>` : " Nothing to export: no card was approved.");   // round 20   // round 15 (part-timer r14)
  if (!rows.length && Q.reading && Q.batch === Q.reading) $("#qEmpty").innerHTML = `<span class="spin" aria-hidden="true"></span> Reading your newest batch. Cards appear as they finish.`;
  $("#archiveBatch").disabled = !Q.batch || Q.arch; { const vis = new Set(rows.map(c => c.id)); [...Q.sel].forEach(i => { if (!vis.has(i)) Q.sel.delete(i); }); $("#selAll").checked = Q.sel.size > 0; if (!Q.sel.size) $("#selNote").hidden = true; syncSel(); } syncSel(); scheduleQueuePoll();   // newcomer r9 N3: the header box, the note and the button count always agree; audit 2026-10: a Set, not O(n²) (a shown card always has the shown status)
  const inB = Q.cardsFor === Q.batch ? Q.cards.filter(c => inBatch(c, Q.batch)) : [], cnt = {pending: 0, approved: 0, rejected: 0, "": inB.length};
  inB.forEach(c => cnt[c.status]++); $$("#statusTabs button").forEach(b => b.querySelector("span").textContent = `(${cnt[b.dataset.s]})`);

}
$("#qBody").addEventListener("click", e => {
  const tr = e.target.closest("tr"); if (!tr) return; const id = +tr.dataset.id;
  if (e.target.classList.contains("sel")) { e.target.checked ? Q.sel.add(id) : Q.sel.delete(id); syncSel(); return; }
  if (e.target.tagName !== "A") location.hash = "review/" + id;
});
// audit 2026-10 C9: "Export it" used an inline onclick, which the CSP (script-src 'self') blocks; one delegated listener instead
$("#qEmpty").addEventListener("click", e => { const a = e.target.closest("a[data-export-from]"); if (a) SS.exportFrom = a.dataset.exportFrom; });
// round 8 (newcomer r8 N1): the header box selects YOUR cards (cards in batches you scanned); other people's cards only on request
$("#selAll").onchange = e => { const rows = filtered().filter(c => inBatch(c, Q.batch)), mine = rows.filter(c => MINE.has(c.batch)), others = rows.filter(c => !MINE.has(c.batch));
  Q.sel.clear(); if (e.target.checked) mine.forEach(c => Q.sel.add(c.id));
  $$("#qBody tr").forEach(tr => { const x = tr.querySelector(".sel"); if (x) x.checked = Q.sel.has(+tr.dataset.id); });
  const n = $("#selNote");
  if (e.target.checked && others.length) { n.hidden = false; n.innerHTML = `Selected <b>${mine.length}</b> of <b>your</b> cards. ${others.length} from other people were <b>not</b> selected. <button type="button" class="link" id="selOthers">Select theirs too</button>`;
    $("#selOthers").onclick = () => { others.forEach(c => Q.sel.add(c.id)); $$("#qBody tr").forEach(tr => { const x = tr.querySelector(".sel"); if (x) x.checked = Q.sel.has(+tr.dataset.id); }); n.textContent = `Selected ${plural(Q.sel.size, "card")}, including ${others.length} from other people's batches.`; syncSel(); }; }
  else if (e.target.checked) { n.hidden = false; n.textContent = `${mine.length} selected.`; }
  else n.hidden = true;
  syncSel(); };
function syncSel() { const n = Q.sel.size; $("#bulkApprove").disabled = $("#bulkReject").disabled = !n;
  // round 12 (newcomer r10 N3): the "Selected N" note is recounted from the real selection every time (it said 29 while the
  // button said 24 once other people's cards changed under "All batches")
  { const nt = $("#selNote"); if (nt && !nt.hidden && !$("#selOthers")) { const sc = Q.cards.filter(c => Q.sel.has(c.id)), om = sc.filter(c => !MINE.has(c.batch)).length;
      nt.textContent = n ? `${n} selected` + (om ? `, ${om} from other people's batches.` : ".") : ""; if (!n) nt.hidden = true; }
    else if (nt && !nt.hidden && $("#selOthers")) { const b_ = nt.querySelector("b"); if (b_) b_.textContent = String(n); } }
  $("#bulkApprove").textContent = n ? `Approve ${n} selected card${n > 1 ? "s" : ""}` : "Approve selected"; $("#bulkReject").textContent = n ? `Reject ${n} selected card${n > 1 ? "s" : ""}` : "Reject selected"; }
async function bulk(status, btn) {
  const ids = [...Q.sel]; if (!ids.length || !await needWho()) return;
  $("#bulkApprove").disabled = $("#bulkReject").disabled = true;   // round 15 (reviewer r14): both off while one runs
  try { return await bulk_(status, btn, ids); } finally { syncSel(); }
}
// round 17 (newcomer r16 #2): "Approve all 1" read oddly: natural wording for 1 and 2
const allN17 = (n, tail) => `Approve ${n}`;   // round 21 (newcomer r20): one approve label
const cap17 = (xs, f, n = 10) => xs.slice(0, n).map(f).join("") + (xs.length > n ? `<li>…and ${xs.length - n} more (open the cards from the queue)</li>` : "");
const ids17 = (xs, n = 10) => xs.slice(0, n).map(i => `<a href="#review/${i}">#${i}</a>`).join(", ") + (xs.length > n ? ` …and ${xs.length - n} more` : "");
async function bulk_(status, btn, ids) {
  const sel = Q.cards.filter(c => Q.sel.has(c.id)), decided = sel.filter(c => c.status !== "pending" && c.status !== status);
  const verb = status === "approved" ? "Approve" : "Reject";
  const mineSel = sel.filter(c => MINE.has(c.batch)), oth = sel.filter(c => !MINE.has(c.batch));
  const byB = {}; oth.forEach(c => { const k = c.batch_label || c.batch || "no batch"; byB[k] = (byB[k] || 0) + 1; });
  const whose = `<p>Whose cards: <b>${mineSel.length}</b> from your batches` + (oth.length ? `, <b>${oth.length}</b> from <b>other people's</b> batches (${esc(Object.entries(byB).map(([k, n]) => `${k}: ${n}`).join("; "))})` : "") + ".</p>";
  // round 14 (coordinator r6): ONE question for an approve: the server's dry run lists what would be skipped (with the
  // field), the cross-batch look-alikes and the cards whose AI check hasn't finished, before anything changes
  let pre = null;
  if (status === "approved") {
    await busy(btn, "Checking…", async () => { try { pre = await post("/api/cards-bulk", {ids, status, confirm_redecide: true, dry_run: true, batch: Q.batch || "all", versions: Object.fromEntries(sel.map(c => [c.id, c.version]))}); } catch (e) { toast("Couldn't check the cards: " + e.message, 6000); } });
    if (!pre) { syncSel(); return; }
  }
  const lk0 = pre ? pre.lookalikes || [] : [], ai0 = pre ? pre.ai_pending || [] : [], sk0 = pre ? pre.skipped || [] : [];
  // round 16 (reviewer r15 N2, coordinator r15 #6): words instead of raw scores, and long lists are capped
  const why16 = w => String(w || "").replace(/\bname~[\d.]+/g, "similar name").replace(/\borg~[\d.]+/g, "similar company").replace(/\bemail exact\b/g, "same email").replace(/\bphone exact\b/g, "same phone");
  const cap16 = (xs, f) => xs.slice(0, 10).map(f).join("") + (xs.length > 10 ? `<li>…and ${xs.length - 10} more (open the cards from the queue)</li>` : "");
  // round 21 (r20 bots): about 5 short lines; ids and reasons behind "Show" / More
  const show = (n, inner) => `<details class="more small"><summary>Show ${n}</summary><ul>${inner}</ul></details>`;
  const line = [];
  if (sk0.length) line.push(`<li><b>${plural(sk0.length, "card")}</b> can't be approved yet. ${show(sk0.length, cap16(sk0, x => `<li><a href="#review/${x.id}">#${x.id}</a>: ${esc(why16(x.why))}</li>`))}</li>`);
  if (ai0.length) line.push(`<li>${plural(ai0.length, "card")}: AI check not finished (approving cancels it).</li>`);
  if (lk0.length) line.push(`<li>${plural(lk0.length, "card")} may already be in MC Trade. ${show(lk0.length, cap16(lk0, w => `<li><a href="#review/${w.id}">#${w.id}</a>: ${esc(why16(w.why))}</li>`))}</li>`);
  if (decided.length) line.push(`<li>${plural(decided.length, "card")} already decided.</li>`);
  const preHtml = line.length ? `<ul>${line.join("")}</ul>` : "";
  const restN = pre ? (pre.would_approve || []).filter(i => !lk0.some(w => w.id === i)).length : 0;
  const goN = pre ? (pre.would_approve || []).length : ids.length;   // round 16 (newcomer r15 #1): the button counts what really happens
  const r = await ask({title: pre && !goN ? `None of the ${plural(ids.length, "card")} can be approved yet` : `${verb} ${plural(pre ? goN : ids.length, "card")}?`, html: preHtml +
      `<details class="more small"><summary>More</summary><p>As reviewer <b>${esc(who())}</b>.</p>${whose}</details>`,
    buttons: [...(lk0.length ? [...(restN ? [{label: `Approve the other ${restN}, leave the look-alikes pending`, cls: "ok", value: "rest"}] : []), {label: allN17(goN, "the look-alikes too"), value: "goxb"}] : goN ? [{label: `${verb} ${goN}`, cls: status === "approved" ? "ok" : "danger", value: "go"}] : []), ...(oth.length && mineSel.length ? [{label: `${verb} only my ${mineSel.length}`, value: "mine"}] : []), ...(decided.length ? [{label: `${verb}, but leave already-decided cards alone`, value: "pendingonly"}] : []), {label: "Cancel", value: null, primary: true, focus: true}]});
  if (!r.value) { syncSel(); return; }
  if (r.value === "mine") { ids.splice(0, ids.length, ...mineSel.map(c => c.id)); sel.splice(0, sel.length, ...mineSel); }
  let res = null, xbOk = r.value === "goxb", ids_ = r.value === "rest" ? ids.filter(i => !lk0.some(w => w.id === i)) : ids;
  if (r.value === "goxb" || r.value === "rest") r.value = "go";
  for (let round = 0; round < 3; round++) {   // round 9 (coordinator N7): cross-batch look-alikes are asked about BEFORE approving
    let ask_ = null;
    await busy(btn, "Working…", async () => {
      try {
        const versions = Object.fromEntries(sel.filter(c => ids_.includes(c.id)).map(c => [c.id, c.version]));
        res = await post("/api/cards-bulk", {ids: ids_, status, reviewer: who(), confirm_redecide: r.value !== "pendingonly", confirm_cross_batch: xbOk, versions, batch: Q.batch || "all"});
        // round 20 (datamanager r19): the list shows the new status at once (it showed Pending until a reload)
        const upd_ = new Set((res.updated || []).map(x => +(x.id ?? x))); Q.cards.forEach(c => { if (upd_.has(c.id)) c.status = status; }); renderQueue();
        Q.sel.clear(); $("#selNote").hidden = true; await loadQueue(true);
      } catch (e) { if (e.data?.need === "confirm_cross_batch") ask_ = e.data; else toast("Not saved: " + e.message, 5000); }
    });
    if (!ask_) break;
    const lk = ask_.lookalikes || [], rest = ids_.filter(i => !lk.some(w => w.id === i));
    const a = await ask({title: "Same person already approved in another batch?", html: `<p>${esc(ask_.error)}</p><ul>${cap17(lk, w => `<li><a href="#review/${w.id}">#${w.id}</a>: ${esc(w.why)}</li>`)}</ul><p class="small">The same person may go to MC Trade twice. Approving anyway is noted in history.</p>`,
      buttons: [...(rest.length ? [{label: `Approve the other ${rest.length}, leave these pending`, cls: "ok", value: "rest"}] : []), {label: allN17(ids_.length, "these too"), value: "all"}, {label: "Cancel (nothing changes)", value: null, primary: true, focus: true}]});
    if (!a.value) { res = null; break; }
    if (a.value === "all") xbOk = true; else ids_ = rest;
  }
  syncSel();   // newcomer r8 N7: the result dialog no longer sits inside busy(), so no stale "(3)" label behind it
  if (res) {
      const warn = res.warnings || [];
      const msg = `Done: ${plural(res.updated.length, "card")} ${status}.` + (res.skipped.length ? ` ${res.skipped.length} skipped (still pending: open them from the queue).` : "") + (warn.length ? ` ${plural(warn.length, "card")} may already be in MC Trade.` : "");   // round 21: no second dialog repeating the list
      toast(msg, res.skipped.length || warn.length ? 7000 : 4500, res.updated.length > 0); refreshUndo(); refreshCounts.t = 0; refreshCounts();   // round 12 (reviewer r10): nav badge follows a bulk decision
  }
  syncSel(); setTimeout(syncSel, 0);   // busy() restored the old label ("… (3)"); show the real count
}
$("#bulkApprove").onclick = e => bulk("approved", e.currentTarget); $("#bulkReject").onclick = e => bulk("rejected", e.currentTarget);
$("#archiveBatch").onclick = async e => { const btn = e.currentTarget;
  const opt = $("#fBatch").selectedOptions[0]; if (!Q.batch || !await needWho()) return;
  const r = await ask({title: "Archive this batch?", html: `<p><b>${esc(opt.textContent)}</b> will be hidden from the queue and exports. Nothing is deleted. Tick “Show archived” to see it.</p>`,
    buttons: [{label: "Archive batch", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return;
  await busy(btn, "Archiving…", async () => { const x = await post("/api/batches/archive", {batch: Q.batch, reviewer: who()}); Q.batch = ""; pushQueueState(); toast(`${plural(x.archived, "card")} archived.`, 4500, x.archived > 0); await loadQueue(); });
};
$("#archiveAll").onclick = async e => { const btn = e.currentTarget;
  if (!await needWho()) return;
  const r = await ask({title: "Archive all test data?", html: "<p>Hides every card in the queue from the queue and exports. Nothing is deleted. Undo brings them back.</p>",
    input: {label: "Type CLEAR to confirm", required: "Type CLEAR to confirm."}, buttons: [{label: "Archive everything", cls: "danger", value: 1, needInput: true, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return; if (r.input.trim() !== "CLEAR") { toast("Not cleared: you didn't type CLEAR."); return; }
  await busy(btn, "Clearing…", async () => { const x = await post("/api/batches/archive", {batch: "__all__", confirm: "CLEAR", reviewer: who()}); toast(`${plural(x.archived, "card")} archived. The review queue is now empty.`, 4500, x.archived > 0); await loadQueue(); });
};

/* ---------- review ---------- */
let cur = null;
const order = () => { try { return JSON.parse(SS.order || "[]"); } catch { return []; } };
// round 16 (newcomer r15 #6): on a PENDING card, the counter and Prev/Next go through the cards still pending (decided ones are skipped)
const navOrder = id => { const o = order(); if ((cur && cur.id === id ? cur.status : STATUS[id]) !== "pending") return o;
  return o.filter(x => x === id || (STATUS[x] ?? "pending") === "pending"); };
function dirtyVals() { const o = {}; dirtyIds.forEach(i => { const el = document.getElementById(i); if (el) o[i] = el.value; }); return o; }
let openSeq = 0;
let CARD_READY = false;   // round 15 (part-timer): Save/Approve stay off until the card has finished loading (a blank form must never be saved)
async function openCard(id, opts = {}) {
  const tok = ++openSeq, switching = !cur || cur.id !== id;
  if (switching) {   // round 6 (newcomer F1): never show the previous card's values under the new card's number
    CARD_READY = false; cur = null; $("#rForm").inert = true; $("#rForm").classList.add("loading");
    $$("#rForm input, #rForm textarea").forEach(el => { if (!el.readOnly) { el.readOnly = true; el.dataset.ro16 = "1"; } });   // round 16 (part-timer r15): nothing typed into the empty form while it loads
    $$("#rForm input, #rForm textarea").forEach(el => el.value = ""); $("#rDupBox").hidden = true; ["#rExported", "#rDupQ", "#rDupC", "#rAI", "#rCons"].forEach(q => { const e = $(q); if (e) { e.hidden = true; e.innerHTML = ""; } });
    $("#h-r").textContent = `Loading card #${id}…`; $$(".decide button, #bApprove, #bReject, #bSave, #bPending").forEach(b => b.disabled = true);
  }
  let d; try { d = await call("/api/cards/" + id); } catch { if (tok === openSeq) { toast("Card not found."); location.hash = SS.queueHash || "queue"; } return; }
  if (tok !== openSeq) return;   // the person already moved on to another card: drop this late answer
  // round 14 (LOST SAVE): what the person typed WHILE the card was loading is kept too (it used to be read before the fetch)
  if (opts.keep && cur && cur.id === id) recomputeDirty();
  const keep = opts.keep && cur && cur.id === id && dirty ? dirtyVals() : null;
  $("#rForm").inert = false; $("#rForm").classList.remove("loading"); $$("#rForm [data-ro16]").forEach(el => { el.readOnly = false; delete el.dataset.ro16; }); $$(".decide button, #bApprove, #bReject, #bSave, #bPending").forEach(b => b.disabled = b.getAttribute("aria-busy") === "true"); CARD_READY = true;   // round 17 (part-timer r16 #4): never re-enabled while it still reads "Saving…"
  if (!cur || cur.id !== d.id) scrollTo(0, 0);
  cur = d; const c = d.card, f = c.fields, k = f.confidence || {};
  $("#rImg").src = $("#zImg").src = "/img/" + c.image; $("#rawLink").href = "/img/" + c.image;
  $("#rRaw").textContent = c.raw_text || "";
  $("#rImg").alt = d.image_deleted ? "Photo deleted by the retention policy" : "Photo of the business card";
  $("#rBatch").textContent = [d.batch_label ? "Batch: " + d.batch_label : "", (/ \((page \d+ of \d+|card \d+ of \d+)/.test(d.filename || "") || /\.(hei[cf]|pdf)(\.jpg)?$/i.test(d.filename || "")) ? "From: " + d.filename.replace(/\.jpg$/i, "") : ""].filter(Boolean).join(" · ");   // round 18: which file/page
  $("#h-r").textContent = `Review card #${c.id}`;
  { const qh = new URLSearchParams(((SS.queueHash || "#queue?").split("?")[1]) || ""); qh.set("batch", d.batch || "__none__"); if (!qh.has("s")) qh.set("s", "pending");
    $$(".pager a.ghost").forEach(a => a.href = "#queue?" + qh); }   // reviewer r8: back to THIS card's batch, with the other filters kept
  if (!opts.keep) { $("#h-r").tabIndex = -1; $("#h-r").focus({preventScroll: true}); }   // keys (J/K/A/R) work right after a link jump
  $("#rStatus").className = "pill " + c.status; $("#rStatus").textContent = c.status + (d.archived ? " · archived" : "");
  $("#rDecided").textContent = c.status !== "pending" ? `${c.status[0].toUpperCase() + c.status.slice(1)} by ${c.reviewer || "?"} on ${when(c.decided)}` + (c.note ? ` · Note: ${c.note}` : "") : "";
  { const xe = d.exported_elsewhere || [], el = $("#rExported");   // round 11 (part-timer r4): warn before Approve, not only on it
    // round 21 (all r20 bots): ONE duplicate box. 'Already exported' is a line in it, only on pending cards, and gone after a decision
    el.hidden = !xe.length || c.status !== "pending";
    if (xe.length) el.innerHTML = `<b>Already exported:</b> ${plural(xe.length, "card")} in another batch. Merge it, or approve only if it's an update. ` +
      `<details class="more small"><summary>Show ${xe.length}</summary><ul>${xe.map(x => `<li><a href="#review/${x.card_id}">#${x.card_id}</a> (${esc(x.why.join(", "))}; exported ${x.times}×)</li>`).join("")}</ul></details>`; }
  $("#rConf").innerHTML = "Read quality " + confBar(d.conf ?? f.overall_confidence, d.status === "pending" && Object.keys(d.hard || {}).length > 0);   // newcomer r9 N5: same number as the queue
  ["first_name", "last_name", "title", "company", "website", "address"].forEach(x => $("#" + x).value = f[x] || "");
  $("#emails").value = (f.emails || []).join(", "); $("#social").value = (f.social || []).join(" ");
  $("#phones").value = (f.phones || []).map(p => `${p.type}: ${p.number}`).join("\n"); $("#note").value = c.note || "";
  const KNOWN = ["first_name","last_name","title","company","website","address","emails","phones","social","confidence","overall_confidence","ocr_conf","fallback_reason","edited"];
  $$("#fields .f.extra").forEach(e => e.remove());
  Object.entries(f).filter(([key, val]) => !KNOWN.includes(key) && typeof val === "string").forEach(([key, val]) => {
    $("#addrBox").insertAdjacentHTML("beforebegin", `<div class="f extra"><label for="x_${esc(key)}">${esc(LABEL[key] || key.replace(/_/g, " "))}</label><input id="x_${esc(key)}" data-extra="${esc(key)}" data-c="${esc(key)}" value="${esc(val)}"></div>`); });
  $$("#fields [data-c]").forEach(el => { const box = el.closest(".f"); box.querySelector(".cf")?.remove();
    const low = d.low.includes(el.dataset.c), v = k[el.dataset.c]; box.classList.toggle("low", low);
    if (low) box.querySelector("label").insertAdjacentHTML("afterbegin", `<span class="cf">Please check${v != null ? " · " + Math.round(v * 100) + "%" : ""}</span>`); });
  $("#legend").hidden = !d.low.length;
  const SRCK = {first_name: "first_name", last_name: "last_name", title: "title", company: "company", emails: "emails", phones: "phones", website: "website", address: "address", social: "social"};
  $$("#fields .src").forEach(x => x.remove());
  $$("#fields input[id], #fields textarea[id]").forEach(el => { const key = el.dataset.extra || SRCK[el.id]; const sv = key && d.sources[key]; if (!sv) return;
    const [kind, by] = sv.split(":"), lab = el.closest(".f")?.querySelector("label"); if (!lab) return;
    lab.insertAdjacentHTML("beforeend", kind === "qr" ? ' <span class="src qr" title="Read from the QR code on the card: very reliable">from QR code</span>' : kind === "ai" ? ' <span class="src ai" title="Corrected by the local AI double-check: please confirm">corrected by AI</span>' : kind === "back" ? ' <span class="src ocr">from the back of the card</span>' : kind === "edited" ? ` <span class="src edited">edited by ${esc(by)}</span>` : ""); });   // plain "read from text" is the default: not tagged (see #srcLegend)
  Object.entries(d.confirmed || {}).forEach(([k, c_]) => { const el = document.getElementById(k) || $(`[data-extra="${k}"]`), lab = el && el.closest(".f")?.querySelector("label");
    if (lab) lab.insertAdjacentHTML("beforeend", ` <span class="src confirmed" title="${esc(c_.reason || "")}">✓ confirmed by ${esc(c_.by || "?")}</span>`); });   // round 23 (skeptic r22 L5)
  showErrors(Object.keys(d.hard || {}).length ? {...(d.errors || {}), ...d.hard} : d.errors, false); confirmBtn(d.overridable, d.id);   // round 22: blocks + override visible on open
  renderDupes(d);
  { const kids = ["#rExported", "#rDupQ", "#rDupC"].map(q => $(q)); if (!kids[1].hidden && !kids[0].hidden) { kids[0].hidden = true; const sb = $("#rDupQ b"); const qs = new Set((d.dupes.queue || []).map(x => x.card_id)), nx = (d.exported_elsewhere || []).filter(x => qs.has(x.card_id)).length;   // round 22: counted from the same list as '+N'
      const ln = $("#rDupQ > a"); if (ln && nx) { const sp = document.createElement("span"); sp.className = "small"; sp.textContent = ` · ${nx} already exported`;
        (ln.nextSibling && ln.nextSibling.nodeType === 3 ? ln.nextSibling : ln).after(sp); } }
    $("#rDupBox").hidden = kids.every(k => k.hidden); }
  $("#rWarn").hidden = !f.fallback_reason; $("#rWarn").textContent = f.fallback_reason ? "Note: " + f.fallback_reason : "";
  $("#bPending").hidden = c.status === "pending"; $("#bPending").className = "btn " + (c.status === "rejected" ? "primary" : "ghost");
  $("#bPending").textContent = c.status === "rejected" ? "↩ Move back to pending (un-reject)" : "Move back to pending"; $("#bApprove").hidden = c.status !== "pending"; $("#bDelete").hidden = !ME || ME.role !== "admin"; $("#bReject").hidden = c.status === "rejected";
  dirty = false; dirtyIds.clear();
  ORIG = {}; $$("#rForm input[id], #rForm textarea[id]").forEach(el => { if (el.type !== "file") ORIG[el.id] = el.value; });
  let restore = keep;
  if (!restore) { try { const ld = JSON.parse(localStorage.getItem(draftKey(c.id)) || "null");
    // reviewer r8: a draft whose values equal the saved card (e.g. saved just before) is a ghost: drop it, say nothing
    // coordinator r3 #2: compare the way the server stores values (spacing, separators, email/website case), so a save the server tidied isn't "unsaved"
    const nv = normV;
    const real = ld && ld.vals ? Object.fromEntries(Object.entries(ld.vals).filter(([i, v]) => i in ORIG && nv(i, ORIG[i]) !== nv(i, v))) : {};
    if (ld && !Object.keys(real).length) dropDraft(c.id);
    if (Object.keys(real).length) { restore = real; toast(`Restored your unsaved edits on card #${c.id}` + (ld.version && ld.version !== d.version ? " (the card changed since: check them)" : "") + ". Save to keep them.", 6000);
      setTimeout(async () => { try { const r = await post("/api/validate", {fields: collect(), card_id: c.id}); showErrors({...r.errors, ...r.hard}, true); } catch {} }, 60); } } catch {} }   // round 15 (reviewer r14): inline errors for a restored draft
  if (!restore && SS.draft) { try { const dr = JSON.parse(SS.draft); if (dr.id === c.id && ME && dr.uid === ME.id) { restore = dr.vals; toast("Restored your unsaved edits. Check them and save.", 6000); } } catch {} delete SS.draft; }
  if (restore) Object.entries(restore).forEach(([i, v]) => { const el = document.getElementById(i); if (el && normV(i, v) !== normV(i, el.value)) el.value = v; });
  recomputeDirty();
  renderAI(d); markRisks(d);
  const hk_ = Object.keys(d.hard || {}), cons = d.attention.filter(a => a.code === "consistency" && !(a.field && (hk_.includes(a.field) || (["emails", "website"].includes(a.field) && (hk_.includes("emails") || hk_.includes("website"))))));
  $("#rCons").hidden = !cons.length; $("#rCons").innerHTML = cons.length ? `<b>Details that don't agree with each other:</b><ul>${cons.map(a => `<li>${esc(a.text)}</li>`).join("")}</ul>` : "";
  const bi = (d.back_image || ""); $("#backLink").hidden = !bi; $("#backLink").href = bi ? "/img/" + bi : "#";
  $("#rHist").innerHTML = d.history.map(h => `<li>${esc(when(h.ts))} · <b>${esc(h.reviewer || "system")}</b> ${esc(histText(h))}</li>`).join("") || "<li>No history yet.</li>";
  // round 17 (reviewer r16 N2, part-timer r16 #2, newcomer r16 #3): the counter and Prev/Next/J/K use the cards' REAL
  // statuses. STATUS used to hold only decisions made in this tab, so K reached a card rejected in the queue (bulk reject)
  // and "2 of 2 pending" was shown with 1 (or 3) left. The batch's pending list is asked from the server on every open.
  STATUS[c.id] = c.status;
  const showPos = (pendN) => { if (!cur || cur.id !== c.id) return; const o = navOrder(c.id), i = o.indexOf(c.id);
    $("#pos").textContent = i < 0 ? "" : c.status === "pending" ? `${i + 1} of ${o.length} pending` : `${i + 1} of ${o.length}` + (pendN != null ? ` · ${pendN} pending left` : "");
    $("#prev").disabled = i <= 0; $("#next").disabled = i < 0 || i >= o.length - 1; };
  showPos(null);
  { const b_ = d.batch || c.batch || "", seq_ = openSeq;
    call("/api/cards?status=pending&limit=0" + (b_ ? "&batch=" + encodeURIComponent(b_) : "")).then(cs => {
      if (seq_ !== openSeq || !cur || cur.id !== c.id) return;
      const pend = new Set((cs || []).map(x => x.id)); let o = order();
      o.forEach(x => { if (pend.has(x)) STATUS[x] = "pending"; else if ((STATUS[x] ?? "pending") === "pending" && x !== c.id) STATUS[x] = "decided"; });
      if (!o.includes(c.id)) { o = (cs || []).map(x => x.id).concat(pend.has(c.id) ? [] : [c.id]); SS.order = JSON.stringify(o); }   // opened by link: this batch's pending cards
      showPos(pend.size); }).catch(() => {});
  }
}
let dirty = false, rPoll = null, ORIG = {}, SAVING = false, LASTOK = {}; const dirtyIds = new Set();
// round 10 (coordinator r3 #2): compare values the way the server stores them (spacing, separators, "&" spacing, email/website
// case), so a value the server tidied on save never counts as "unsaved" and never comes back as a "restored edit"
const normV = (i, v) => { let x = String(v ?? "").replace(/\s*&\s*/g, " & ");
  // round 15 (part-timer): commas in an address are real punctuation (never stripped for comparison); only runs of spaces collapse
  x = (i === "address" || i === "other_address" ? x.replace(/[ \t\r\n]+/g, " ") : x.replace(/[\s,;]+/g, " ")).trim();
  return ["emails", "website"].includes(i) ? x.toLowerCase() : x; };
// round 8 (reviewer r8): 'unsaved' = a field differs from the saved card (typing the original value back clears it)
// round 12 (coordinator r4 #2) ROOT CAUSE of the "Unsaved changes" badge after a successful save: after the save answered,
// the form still held the typed values and ORIG the OLD ones until the card was re-read (seconds on a busy machine). Any
// recomputeDirty() in that window (leaving the page = beforeunload, the AI box, a click) compared them again, so the badge
// and the leave prompt came back and a stale draft was written. Now the saved values become the baseline the moment the
// server says "saved".
function formSnap() { const o = {}; $$("#rForm input[id], #rForm textarea[id]").forEach(el => { if (el.type !== "file") o[el.id] = el.value; }); return o; }
function markSaved(sid, sent) {
  // round 14 (LOST SAVE, reviewer r12 #325): the baseline is what was SENT, not what the form holds now. Typing that
  // happened while the save was in flight stays "unsaved" (and is kept by the reload) instead of being silently dropped.
  if (cur && cur.id === sid) { ORIG = sent ? {...sent} : formSnap(); }
  dirty = false; dirtyIds.clear(); recomputeDirty(); if (!dirty) dropDraft(sid);
}
async function waitSaveIdle(ms = 60000) { const t0 = Date.now(); while (SAVING && Date.now() - t0 < ms) await new Promise(r => setTimeout(r, 100)); return !SAVING; }
function recomputeDirty() {
  dirtyIds.clear(); Object.keys(ORIG).forEach(i => { const el = document.getElementById(i); if (el && normV(i, el.value) !== normV(i, ORIG[i])) dirtyIds.add(i); });
  dirty = dirtyIds.size > 0;
  $$("#fields .f.unsaved").forEach(x => x.classList.remove("unsaved"));   // reviewer r9: mark each unsaved field
  dirtyIds.forEach(i => { const f_ = document.getElementById(i)?.closest(".f"); if (f_) f_.classList.add("unsaved"); });
  const ab = $("#rAI"); if (ab) { $("#rAIStale")?.remove(); if (dirty && /AI-checked/.test(ab.textContent)) ab.insertAdjacentHTML("beforeend", '<div id="rAIStale" class="small" style="color:#b45309"><b>This AI result covers the SAVED values only.</b> You have unsaved changes; save, then run the check again if needed.</div>'); }
  const b = $("#rDirty"); if (b) { b.hidden = !dirty; b.textContent = dirty ? (SAVING ? "Saving…" : `Unsaved changes: ${[...dirtyIds].map(i => String(LABEL[i] || LABEL[i.replace(/^x_/, "")] || i.replace(/^x_/, "").replace(/_/g, " ")).toLowerCase()).join(", ")}`) : ""; }
  const x = $("#bDiscard"); if (x) x.hidden = !dirty;
  if (!dirty && cur) dropDraft(cur.id);
  return dirty;
}
// reviewer/part-timer r8: the reasons a card needs checking are shown ON the fields, not only as a tooltip in the list
function markRisks(d) {
  $$("#fields .fhint").forEach(x => x.remove()); $$("#fields .f.hinted").forEach(x => x.classList.remove("hinted"));
  const FID = {name: "first_name", emails: "emails", phones: "phones", title: "title", company: "company", website: "website", address: "address", first_name: "first_name", last_name: "last_name"};
  // round 21: duplicates live in the one duplicate box, but only while that box shows them (a rejected card, or a rejected twin, keeps its hint here)
  const rej_ = d.status === "rejected", dupQShown = !rej_ && ((d.dupes || {}).queue || []).length, dupCShown = !rej_ && ((d.dupes || {}).crm || []).length;
  // round 23 (coordinator r22): a field that already has a red block shows no extra soft line about the same thing
  const hk = Object.keys(d.hard || {}).map(k => k === "name" ? "first_name" : k), hardF = new Set(hk.concat(hk.some(k => k === "emails" || k === "website") ? ["emails", "website"] : []));
  const items = (d.attention || []).filter(a => !(a.field && hardF.has(a.field === "name" ? "first_name" : a.field))).filter(a => !["invalid", "hard", "dup_queue", "override", "reexport"].includes(a.code) && !(a.code === "dup_other" && dupQShown && !/rejected/.test(a.text || "")) && !(a.code === "dup_crm" && dupCShown));
  items.forEach(a => { const el = a.field && document.getElementById(FID[a.field] || a.field); const box = el && el.closest(".f"); if (!box) return;
    box.classList.add("hinted"); box.insertAdjacentHTML("beforeend", `<p class="fhint">⚠ ${esc(a.text)}</p>`); });
  const r = $("#rRisk"); r.hidden = !items.length;
  r.innerHTML = items.length ? `<b>To check (${items.length}):</b><ul>${items.map(a => `<li${a.field && FID[a.field] ? ` data-f="${esc(FID[a.field])}"` : ""}>${esc(a.text)}</li>`).join("")}</ul>` : "";
}
$("#bDiscard") && ($("#bDiscard").onclick = async () => { if (!cur) return;
  const r = await ask({title: "Discard your edits?", html: `<p>The form goes back to the saved card #${cur.id}. Your typed changes (${esc([...dirtyIds].map(i => LABEL[i.replace(/^x_/, "")] || i.replace(/^x_/, "")).join(", "))}) are thrown away.</p>`,
    buttons: [{label: "Discard my edits", cls: "danger", value: 1}, {label: "Cancel", value: null, primary: true, focus: true}]});
  if (!r.value) return; clearTimeout(keepDraft.t); dropDraft(cur.id); dirty = false; dirtyIds.clear(); delete SS.draft; await openCard(cur.id); toast("Edits discarded."); });
addEventListener("beforeunload", e => { if (SIGNING_OUT) return; if (!$("#v-review").hidden && Object.keys(ORIG).length && recomputeDirty()) { saveDraft(); e.preventDefault(); e.returnValue = ""; } });
addEventListener("pageshow", e => { if (e.persisted) location.reload(); });   // never show a cached page after sign-out
let vT = null;
$("#rForm").addEventListener("input", e => {
  // round 17 (part-timer r16 #5): a field's own warning (e.g. "StSuite looks like two words") is about the OLD value: it goes
  // as soon as the field is edited; Save re-checks the card and shows it again only if it still applies
  { const f_ = e.target.closest && e.target.closest(".f"); if (f_ && f_.querySelector(".fhint")) { f_.querySelectorAll(".fhint").forEach(x => x.remove()); f_.classList.remove("hinted");
      const lab = (f_.querySelector("label")?.getAttribute("for")) || ""; $$("#rRisk li[data-f]").forEach(li => { if (li.dataset.f === lab) li.remove(); });
      const n_ = $$("#rRisk li").length, b_ = $("#rRisk b"); if (!n_) $("#rRisk").hidden = true; else if (b_) b_.textContent = `To check (${n_}):`; } }
  recomputeDirty(); clearTimeout(keepDraft.t); keepDraft.t = setTimeout(keepDraft, 400); clearTimeout(vT);
  if (cur) { const b = $("#rAI .flag.bad"); if (b && !dirty) b.remove(); }
  if (!$$("#fields .f.err").length && $("#rErr").hidden) return;      // only re-check while problems are shown
  vT = setTimeout(async () => { try { const r = await post("/api/validate", {fields: collect(), card_id: cur && cur.id}); showErrors({...r.errors, ...r.hard}, !$("#rErr").hidden); } catch {} }, 300); });
function fmtEta(s) { s = Math.max(1, Math.round(s)); return s < 90 ? `${s} s` : `${Math.round(s / 60)} min`; }
function renderAI(d) {
  const s = d.ai_status, x = d.ai_detail || {}, box = $("#rAI"); clearTimeout(rPoll);
  const canAsk = d.status === "pending" && !d.image_deleted && s !== "checking";   // reviewer r7: also while waiting in line (moves it up)
  let h = "";
  if ((s === "queued" || s === "checking") && d.status !== "pending") h = "";
  else if (s === "queued" || s === "checking") {
    const p = d.ai_progress || {}, t0 = s === "checking" ? x.started : x.queued_at, secs = t0 ? Math.max(0, Math.round(Date.now() / 1000 - t0)) : 0;
    const typ = p.busy ? "the AI is busy, so this may take a while"
              : p.typical_seconds ? `recent checks took about ${p.typical_seconds} s each` : "about a minute per card";
    // round 21 (all r20 bots): ONE plain sentence
    h = `<b role="status">${p.eta_seconds ? `AI check in ~${fmtEta(p.eta_seconds)}` : s === "checking" ? "AI check running…" : "AI check soon"}.</b> Keep working.` +
        `<div class="progress mini" aria-hidden="true"><div style="width:${s === "queued" ? 5 : Math.min(95, Math.round(100 * secs / (p.typical_seconds || 60)))}%"></div></div>`;
  }
  const ruleHints = (d.attention || []).filter(a => ["hint", "consistency"].includes(a.code));
  if (s === "checked" && !(x.changed && x.changed.length) && !Object.keys(x.decided || {}).length && ruleHints.length)   // reviewer r8 (Rnbber/Mian)
    h = `<b>AI-checked:</b> no AI changes, but ${plural(ruleHints.length, "thing")} still to check: <ul>${ruleHints.map(a => `<li>${esc(a.text)}</li>`).join("")}</ul>Check those fields against the photo.`;
  else if (s === "checked") h = x.changed && x.changed.length ? `<b>AI-checked:</b> corrected ${esc(x.changed.map(k => LABEL[k] || k).join(", "))} . Check the photo.` : (Object.keys(x.decided || {}).length ? "<b>AI-checked:</b> all suggestions decided." : "<b>AI-checked:</b> no changes needed.");
  else if (s === "suggested") h = "<b>AI suggestions</b> (nothing changes until you choose):";
  else if (s === "skipped") h = /skipped at scan/i.test(x.note || "") ? "AI skipped at scan." : "AI skipped: " + esc((x.note || "a person reviewed this card first").replace(/^AI check skipped\s*/i, "")) + ".";   // round 24 (coordinator r23): said "AI check skipped" twice
  else if (s === "failed" && x.offline) h = "AI check is off right now. Scanning still works.";   // round 20 (a)
  else if (s === "failed") h = "The AI check didn't finish" + (/timeout|timed out/i.test(x.error || "") ? " in time (the computer was busy)" : "") + ". Check the fields against the photo, or try again." + (x.error && !/errno|urlerror|refused|exception/i.test(x.error) ? ` <span class="small">(${esc(x.error)})</span>` : "");
  else if (s === "busy") h = "<b>AI busy:</b> " + esc(x.error || "the AI model didn't answer in time") + "";
  if (canAsk) h += ` <button type="button" class="link" id="aiAsk" title="Checks the saved card">${s === "checked" || s === "suggested" ? "Check again with AI" : "Check with AI"}</button>`;
  const diff = x.diff || {}, dec = x.decided || {}, open = Object.keys(diff).filter(k => !dec[k]);
  if (open.length && (s === "suggested" || s === "checked")) {
    const v = val => esc(Array.isArray(val) ? val.map(p => typeof p === "object" ? `${p.type}: ${p.number}` : p).join(", ") : (val ?? ""));
    h += `<table class="aidiff"><thead><tr><th scope="col">Field</th><th scope="col">${x.applied ? "Before AI" : "Now"}</th><th scope="col">${x.applied ? "AI changed it to" : "AI suggests"}</th><th scope="col">Choice</th></tr></thead><tbody>` +
      open.map(k => `<tr><th scope="row">${esc(LABEL[k] || k)}</th><td>${v(diff[k].from)}</td><td>${v(diff[k].to)}</td><td><button type="button" class="btn small ok" data-aik="${esc(k)}" data-aic="accept" aria-label="Use AI value for ${esc(LABEL[k] || k)}">${x.applied ? "Keep AI value" : "Use AI value"}</button> <button type="button" class="btn small" data-aik="${esc(k)}" data-aic="reject" aria-label="Keep current ${esc(LABEL[k] || k)}">${x.applied ? "Undo AI change" : "Keep current"}</button></td></tr>`).join("") + "</tbody></table>";
  }
  if (h && dirty && dirtyIds.size) h = `<p class="flag bad">Not saved yet: ${esc([...dirtyIds].map(i => LABEL[i.replace(/^x_/, "")] || i.replace(/^x_/, "")).join(", "))}. AI checks the saved card. Save, then check again.</p>` + h;   // reviewer r7
  // round 11 (reviewer r10 blocker 1): the AI is labelled plainly. It is a spelling/typo double-check, advisory only.
  if (h) h += `<p class="small aiNote">AI suggestions can be wrong. Check the photo.</p>`;
  box.hidden = !h; box.innerHTML = h;
  box.querySelectorAll("[data-aik]").forEach(b => b.onclick = async () => {
    const k = b.dataset.aik, ch = b.dataset.aic;
    // round 12 (coordinator r4 #4): a second AI choice clicked while the first one was still reloading the card used the old
    // card version, was refused, and "Keep current" was lost. Now the buttons are locked until the card is re-read, and the
    // choice is sent with the version on screen right now (retried once if the card changed meanwhile).
    if (!cur || cur.id !== d.id) return;
    box.querySelectorAll("[data-aik]").forEach(x => x.disabled = true);
    const send = async (extra) => { try { return await post(`/api/cards/${d.id}/ai-decide`, {choices: {[k]: ch}, version: cur.version, ...extra}); }
      catch (e) { if (e.data && e.data.need === "stale") { const n = await call("/api/cards/" + d.id); cur.version = n.version; return await post(`/api/cards/${d.id}/ai-decide`, {choices: {[k]: ch}, version: n.version, ...extra}); } throw e; } };
    if (dirty) {   // unsaved typing on the form: merge here in the browser, never on the server
      if (ch === "accept" && !setFormField(k, diff[k].to)) { toast("Save your edits first, then choose.", 4000); return; }
      try { await send({record_only: true}); toast(ch === "accept" ? `AI value put in ${LABEL[k] || k}. Save to keep it.` : "Kept the current value.", 4000); await openCard(d.id, {keep: true}); }
      catch (e) { toast("Not saved: " + e.message, 5000); box.querySelectorAll("[data-aik]").forEach(x => x.disabled = false); }
      return;
    }
    try { await send({}); toast(ch === "accept" ? "AI value used." : "Kept the current value.", 4500, true); await openCard(d.id); }
    catch (e) { toast("Not saved: " + e.message, 5000); box.querySelectorAll("[data-aik]").forEach(x => x.disabled = false); } });
  if ($("#aiAsk")) $("#aiAsk").onclick = async () => { const typed = dirty; try { const r = await post(`/api/cards/${d.id}/ai-check`, {}); toast("AI double-check started" + (r.ahead ? ` (${r.ahead} ahead of it)` : "") + (typed ? ". It checks the saved card, not unsaved edits." : "."), typed ? 7000 : 3500); openCard(d.id, {keep: true}); } catch (e) { toast(e.message, 5000); } };
  if (s === "queued" || s === "checking") rPoll = setTimeout(async () => {
    if (!$("#v-review").hidden && cur && cur.id === d.id && ($("#dlg").open || DECIDING)) { renderAI(d); return; }   // round 15 (part-timer r14): never reload the card under an open question (the merge dialog vanished); try again later
    if ($("#v-review").hidden || !cur || cur.id !== d.id || SAVING) return;   // round 10: root cause of the ghost "unsaved" badge: this
    const n = await call("/api/cards/" + d.id);                                 // poll re-opened the card with the TYPED values while a save was in flight
    if (SAVING || !cur || cur.id !== d.id) return;
    if ($("#dlg").open || DECIDING) { renderAI(d); return; }   // round 17 (part-timer r16 #1): a question opened while this poll waited stays open; try again later
    if (n.ai_status === s) return renderAI(n);
    const kept = dirty; await openCard(d.id, {keep: true});
    const rh = (n.attention || []).some(a => ["hint", "consistency"].includes(a.code));
    toast((n.ai_status === "suggested" ? "AI double-check finished: suggestions below." : n.ai_status === "checked" ? (rh ? "AI check done: no changes, but some fields still need a look." : "AI double-check finished: no changes needed.") : "AI double-check: " + n.ai_status) + (kept ? " Your unsaved edits were kept." : ""), 4000);
  }, 4000);
}
function setFormField(k, val) {
  const el = k === "emails" ? $("#emails") : k === "phones" ? $("#phones") : k === "social" ? $("#social") : (document.getElementById(k) || $(`[data-extra="${k}"]`));
  if (!el) return false;
  if (typeof val === "string" && /address/.test(k)) val = val.replace(/\s*[\r\n]+\s*/g, ", ");   // a line break is a separator, never glue
  el.value = k === "emails" ? (val || []).join(", ") : k === "phones" ? (val || []).map(p => `${p.type}: ${p.number}`).join("\n") : k === "social" ? (val || []).join(" ") : (val ?? "");
  recomputeDirty(); return true;
}
function histText(h) {
  if (h.text) return h.text;
  if (h.action === "decision") return `${h.from_status} → ${h.to_status}` + (h.detail && h.detail.override ? ` (approved despite problems: "${h.detail.override}")` : "") + (h.detail && h.detail.bulk ? " (bulk)" : "");
  if (h.action === "edited") return "edited " + Object.keys(h.detail || {}).map(x => LABEL[x] || x).join(", ");
  if (h.action === "scanned") return "scanned" + (h.detail && h.detail.file ? ` from ${h.detail.file}` : "");
  if (h.action === "merged_from") return `merged details from card #${h.detail.card}`;
  if (h.action === "mc_trade_choice") return h.detail === "update_existing" ? "chose: update existing MC Trade contact" : "chose: add as new MC Trade contact";
  if (h.action === "duplicate_kept_both") return "marked as a different person (keep both)";
  if (h.action === "ai_checked") return "AI double-check: " + (Object.keys((h.detail || {}).changed || {}).length ? "corrected " + Object.keys(h.detail.changed).map(x => LABEL[x] || x).join(", ") : "no changes");
  if (h.action === "undo") return "undid: " + (h.detail && h.detail.undid);
  if (h.action === "photo_deleted") return `photo deleted (retention: ${h.detail && h.detail.after_days} days)`;
  if (h.action === "hard_check_override") return `confirmed ${LABEL[(h.detail || {}).field] || "a value"} as correct` + ((h.detail || {}).reason ? ` (reason: ${h.detail.reason})` : "");
  if (h.action === "exported") return "exported to " + (h.detail && h.detail.file || "file");
  return h.action;
}
function showErrors(errs, loud) {
  ["name", "emails", "phones"].forEach(k => { $("#e_" + k).textContent = (errs && errs[k]) || ""; });
  $$("#fields .f").forEach(b => b.classList.remove("err"));
  if (errs) { if (errs.name) $("#first_name").closest(".f").classList.add("err"); if (errs.emails) $("#emails").closest(".f").classList.add("err"); if (errs.phones) $("#phones").closest(".f").classList.add("err"); }
  if (errs) Object.keys(errs).forEach(k => { const el = document.getElementById(k === "name" ? "first_name" : k) || $(`[data-extra="${k}"]`); el && el.closest(".f")?.classList.add("err"); });   // round 15: every problem field
  ["first_name", "emails", "phones"].forEach(id => $("#" + id).setAttribute("aria-invalid", errs && errs[{first_name: "name", emails: "emails", phones: "phones"}[id]] ? "true" : "false"));
  // round 22 (reviewer/newcomer r21): every block message shows ONCE, in ONE box (fields get a red border, no second text)
  ["name", "emails", "phones"].forEach(k => { $("#e_" + k).textContent = ""; });
  const n = errs ? Object.keys(errs).length : 0;
  $("#rErr").hidden = !n; $("#rErr").innerHTML = n ? `<b>Fix before approving:</b><ul>${Object.values(errs).map(m => `<li>${esc(m)}</li>`).join("")}</ul>` : "";
}
// round 23 (datamanager/coordinator/newcomer r22): 'This is correct' confirms ONE field at a time, shows the value and needs a
// reason. Phones are never confirmable. A reviewer who meets an admin-only block gets an 'Ask an admin' hint.
const CONF_ADMIN = ["emails", "website", "address", "other_address"];
function confirmBtn(ov, sid, hardNow) {
  if (!$("#rErr") || $("#rErr").hidden || $("#rErr .conf")) return;
  const adm = ME && ME.role === "admin", all = (ov || []).filter(k => k !== "phones");
  const mine = all.filter(k => adm || !((cur && cur.admin_override) || CONF_ADMIN).includes(k));
  const hard = Object.keys(hardNow || (cur && cur.hard) || {}), askAdm = !adm && hard.some(k => CONF_ADMIN.includes(k));
  if (!mine.length && !askAdm) return;
  const lab = k => LABEL[k === "name" ? "first_name" : k] || k;
  $("#rErr").insertAdjacentHTML("beforeend", `<p class="small conf">${mine.length ? "Photo agrees? " + mine.map((k, i) => `<button type="button" class="btn small" data-confirm="${esc(k)}"${i ? "" : ' id="bConfirmOk"'}>Confirm ${esc(lab(k))}</button>`).join(" ") : ""}${askAdm ? `${mine.length ? " " : ""}<span id="askAdmin">Card really says this? Ask an admin to confirm it.</span>` : ""}</p>`);
  $$("#rErr [data-confirm]").forEach(b => b.onclick = async () => {
    if (recomputeDirty()) { toast("Save first, then confirm the saved value.", 4000); return; }
    const k = b.dataset.confirm, fk = k === "name" ? "first_name" : k, v = cur.card.fields[fk], vs = Array.isArray(v) ? v.join(", ") : (v || "");
    const r = await ask({title: `Confirm ${lab(k)}?`, html: `<p><b>${esc(vs)}</b></p>`, input: {label: "Why is it correct? (at least 3 letters)", placeholder: "e.g. printed like this on the card", required: "A reason is needed.", max: 300},
      check: t => (t.replace(/[\u200b-\u200d\ufeff]/g, "").match(/[\p{L}\p{N}_]/gu) || []).length < 3 ? "Write a short reason (at least 3 letters)." : /^[=+\-@]/.test(t) || /<\s*[a-z\/!]|&#|javascript:/i.test(t) ? "The reason can't contain formulas or HTML code." : null,
      buttons: [{label: "Confirm", cls: "primary", value: 1, primary: true, needInput: true}, {label: "Cancel", value: null}]});
    if (!r.value) return;
    if (!(r.input || "").trim()) { toast("A reason is needed.", 4000); return; }
    try { const r1 = await post(`/api/cards/${sid}/confirm-correct`, {field: k, value: v, version: cur.version, reason: r.input}); cur.version = r1.version || cur.version;
      toast(`${lab(k)} confirmed.`, 3000, true); openCard(sid, {keep: true}); } catch (x) { toast("Not changed: " + x.message, 5000); } });
}
// round 14 (parttimer r6): a long look-alike list shows the first 3 and a count you can expand
const capList = (items, n = 3) => items.length <= n + 1 ? items.join("") : items.slice(0, n).join("") +
  `<li class="more"><details><summary>${items.length - n} more look-alike${items.length - n > 1 ? "s" : ""} (click to show)</summary><ul>${items.slice(n).join("")}</ul></details></li>`;
function renderDupes(d) {
  const rejected = d.status === "rejected", all = rejected ? [] : d.dupes.queue, crm = rejected ? [] : d.dupes.crm;
  const decided = d.dup_decided || d.status !== "pending";   // round 21: after 'Different person' (or a decision) no merge buttons
  const q = decided ? [] : all.filter(x => !x.kept_apart), kept = decided ? all : all.filter(x => x.kept_apart), res = q.length ? null : "keep_both";
  $("#rDupQ").hidden = !all.length;
  if (all.length) {
    // round 22 (datamanager r21): a STABLE merge target (no #354/#127 flipping): same tiers, then the lowest card number
    const byId = l => [...l].sort((a, b) => a.card_id - b.card_id);
    const o = q[0] || all[0], bestQ = [...byId(q.filter(x => x.strong)), ...byId(q.filter(x => x.same_batch && !x.strong)), ...byId(q.filter(x => !x.same_batch && !x.strong))][0] || o;
    $("#rDupQ").innerHTML = res === "keep_both" ? (d.status !== "pending" && !d.dup_decided ? `<b>Seen before:</b> similar to ${plural(all.length, "other card")}.` : `<b>Checked:</b> marked as a different person from ${kept.length > 3 ? plural(kept.length, "card") + ": " : "card" + (kept.length > 1 ? "s " : " ")}${kept.slice(0, 3).map(x => `<a href="#review/${x.card_id}">#${x.card_id}</a>`).join(", ")}${kept.length > 3 ? ` and ${kept.length - 3} more` : ""}.`)
      // round 8 (newcomer r8 N5): ONE decision per card instead of two buttons per look-alike (18 buttons for 9 look-alikes)
      // round 20 (reviewer r19): ONE 'Seen before' box: the best match, Same / Different person buttons, the rest under More
      : `<b>Seen before:</b> <a href="#review/${bestQ.card_id}">#${bestQ.card_id} ${esc(bestQ.name || "(no name)")}</a>${q.length > 1 ? ` +${q.length - 1}` : ""}${bestQ.strong ? ` <span class="small"><b>Duplicate scan</b>: merge or reject one.</span>` : ""}` +
        `<div class="btns"><button type="button" class="btn small" id="dSame">Same person (merge into #${bestQ.card_id})</button>${q.some(x => !x.strong) ? ` <button type="button" class="btn small" id="dDiff">Different person</button>` : ""}</div>` +
        `<details class="more small"><summary>Details</summary><ul>${capList(q.map(x => `<li><a href="#review/${x.card_id}">#${x.card_id} ${esc(x.name || "(no name)")}</a>${x.organization ? ", " + esc(x.organization) : ""} (${esc(x.status || "")}): ${esc(x.why_text || x.why.join(", "))}${x.strong ? ` <span class="small"><b>Duplicate scan</b> (${x.why.includes("same photo") ? "same photo" : "same email/phone in the same batch"}): merge or reject one of them.</span>` : ""}</li>`))}</ul>` +
      `<div class="btns"><label for="dDecide" class="small">Decision:</label> <select id="dDecide"><option value="">Choose…</option>` +
        (() => { const opt = x => `<option value="merge:${x.card_id}">Same person as #${x.card_id}${x.name ? " (" + esc(x.name) + ")" : ""} [${x.same_batch ? "this batch" : "other batch" + (x.status ? ", " + esc(x.status) : "")}]: merge into #${x.card_id}</option>`;
          // round 12 (coordinator r4 #5): ALWAYS grouped under headings, and every option says which batch it is in
          const a_ = q.filter(x => x.same_batch), b_ = q.filter(x => !x.same_batch);
          // round 20 (reviewer r19): the best few only (duplicate scans first), not 25-38 options
          const best = l => [...l.filter(x => x.strong), ...l.filter(x => !x.strong)].slice(0, 4);
          return (a_.length ? `<optgroup label="── In this batch ──">${best(a_).map(opt).join("")}</optgroup>` : "") +
                 (b_.length ? `<optgroup label="── Earlier batches ──">${best(b_).map(opt).join("")}</optgroup>` : ""); })() +
        (q.some(x => !x.strong) ? `<optgroup label="── Not the same person ──"><option value="keep">Different person from ${q.filter(x => !x.strong).length === 1 ? "#" + q.find(x => !x.strong).card_id : (q.some(x => x.strong) ? "the other " : "all ") + q.filter(x => !x.strong).length + " listed cards"}${q.some(x => x.strong) ? ` (all ${q.length} except the ${plural(q.filter(x => x.strong).length, "duplicate scan")})` : ""}: keep both</option></optgroup>` : "") +
        `</select> <button type="button" class="btn small" id="dApply" disabled>Save decision</button></div></details>` +
      `<details class="more small"><summary>More</summary>Merging adds this card's new details to the other card and removes this card. Where both have a value, the other card's is kept, so some values can be dropped.` +
      (q.some(x => !x.blocking) ? ` Other batches don't block approval.` : "") + `</details>` +
      (kept.length ? `<p class="small">Already marked as different people: ${kept.map(x => `<a href="#review/${x.card_id}">#${x.card_id}</a>`).join(", ")}.</p>` : "") +
      `<span id="dMerge" hidden></span>`;
    const doMerge = async (btn, tid) => {   // round 7: preview what merging does (no silent drop); round 8: same pick rule as the server
      const sid = cur.id; if (tid === sid) { toast("A card can't be merged into itself.", 5000); return; }
      let t, pv = {rows: []};
      try { t = (await call("/api/cards/" + tid)).card.fields; pv = await post(`/api/cards/${sid}/merge-preview`, {into: tid, fields: collect()}); } catch (x) { toast("Couldn't open #" + tid + ": " + x.message, 5000); return; }
      const me = collect(), F = {first_name: "First name", last_name: "Last name", title: "Job title", company: "Company", website: "Website", address: "Address", department: "Department"};
      const str = v => Array.isArray(v) ? v.map(p => typeof p === "object" ? p.number : p).join(", ") : (v || "");
      const rows = pv.rows.map(x => `<tr><th scope="row">${F[x.field] || x.field}</th><td>${esc(x.target) || "<i>empty</i>"}</td><td>${esc(x.this)}</td><td>${!x.target ? "added to #" + tid : x.keep === "src" ? "<b>this card's value is used</b>" + (x.why === "fails_check" ? " (#" + tid + "'s value fails a check)" : x.why === "fuller" ? " (it is the fuller version)" : "") : (x.why === "spacing" ? "<b>kept: #" + tid + "'s value</b> (only spacing or capitals differ)" : x.to_note ? "<b>kept: #" + tid + "'s value</b> (this card's title goes into the note)" : "<b>kept: #" + tid + "'s value</b> (this card's value is dropped)")}</td></tr>`).join("") +
        ["emails", "phones", "social"].map(k => { const have = new Set((t[k] || []).map(x => (typeof x === "object" ? x.number : x).replace(/\D/g, k === "phones" ? "" : "$&").toLowerCase()));
          const add = (me[k] || []).filter(x => k !== "phones" || (x.number || "").replace(/\s*(x|ext\.?)\s*\d+$/i, "").replace(/\D/g, "").length >= ((x.number || "").trim().startsWith("+") ? 8 : 10)).filter(x => ![...have].some(h => k === "phones" && h.endsWith((x.number || "").replace(/\D/g, ""))) && !have.has((typeof x === "object" ? x.number : x).replace(/\D/g, k === "phones" ? "" : "$&").toLowerCase()));
          const rep = k === "emails" ? (pv.email_replace || []) : [];   // round 11 (part-timer r4): a misread email is REPLACED, and the preview says so
          const repNew = new Set(rep.map(x => x.new.toLowerCase()));
          const drop = k === "emails" ? new Set((pv.email_drop || []).map(x => x.toLowerCase())) : new Set();
          const plain = add.filter(x => !repNew.has(String(x).toLowerCase()) && !drop.has(String(x).toLowerCase()));
          const dropRows = [...drop].map(x => `<tr><th scope="row">${LABEL[k] || k}</th><td>${esc(str(t[k]))}</td><td>${esc(x)}</td><td>not added (${(pv.email_drop_why || {})[x] === "misread" ? `looks like a misread copy of #${tid}'s email` : "it fails the email check (misread?): type the right address if needed"})</td></tr>`).join("");
          return rep.map(x => `<tr><th scope="row">${LABEL[k] || k}</th><td>${esc(x.old)}</td><td>${esc(x.new)}</td><td><b>replace:</b> #${tid}'s misread ${esc(x.old)} is replaced by ${esc(x.new)}</td></tr>`).join("") +
            dropRows + (plain.length ? `<tr><th scope="row">${LABEL[k] || k}</th><td>${esc(str(t[k])) || "<i>empty</i>"}</td><td>${esc(str(plain))}</td><td>${k === "phones" && plain.some(x => [...(t[k] || [])].some(h => { const hd = String(h.number || h).replace(/\D/g, ""), xd = String(x.number || x).replace(/\D/g, ""); return hd.length >= 7 && xd !== hd && xd.endsWith(hd); })) ? "<b>replaces</b> #" + tid + "'s shorter (truncated) number" : "added to #" + tid}</td></tr>` : ""); }).join("");   // round 15 (coordinator r14 #5)
      const r = await ask({title: `Merge this card into #${tid}?`, html: (rows ? `<table class="aidiff"><thead><tr><th>Field</th><th>#${tid} has</th><th>This card has</th><th>After merging</th></tr></thead><tbody>${rows}</tbody></table>` : "<p>No different values: nothing is lost.</p>") +
          `<p class="small">This card is then rejected as a duplicate. Undo reverses the merge.</p>`,
        wide: true, buttons: [{label: "Merge", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
      if (r.cancelled) { await ask({title: "Not merged", html: `<p>The question closed before you answered. <b>Nothing was merged or saved.</b> Your edits are still on the form.</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return; }   // round 15 (part-timer r14)
      if (r.value) act(btn, {merge_into: tid}, `Merged #${sid} into #${tid}; #${sid} was rejected as a duplicate.`, sid); };
    const sel = $("#dDecide"), ap = $("#dApply");
    if (sel) { sel.onchange = () => ap.disabled = !sel.value;
      ap.onclick = e => { const v = sel.value; if (!v) return;
        if (v.startsWith("merge:")) return doMerge(e.currentTarget, +v.slice(6));
        const ids = q.filter(x => !x.strong).map(x => x.card_id);
        act(e.currentTarget, {keep_apart: ids.length === 1 ? ids : "all"}, ids.length === 1 ? `Marked as a different person from #${ids[0]}.` : `Marked as a different person from ${ids.length} look-alike cards.`); };
      const ds = $("#dSame"), dd = $("#dDiff");
      if (ds) ds.onclick = e => doMerge(e.currentTarget, bestQ.card_id);
      if (dd) dd.onclick = e => { sel.value = "keep"; ap.disabled = false; ap.onclick({currentTarget: e.currentTarget}); }; }
  }
  $("#rDupC").hidden = !crm.length;
  if (crm.length) {
    const m = crm[0], ch = d.dupes.crm_action;
    $("#rDupC").innerHTML = `<b>${ch ? "MC Trade:" : "May already be in MC Trade:"}</b> <b>${esc(m.name)}</b>, ${esc(m.organization)} (profile #${esc(m.profile_id)}): ${esc(m.why_text)}.
      ${m.sample ? `<p class="small"><b>SAMPLE data:</b> test contacts, not GAC's real MC Trade list. No Profile ID is used.</p>` : `<p class="small">Checked against GAC's uploaded MC Trade contacts export.</p>`}` +
      (d.status !== "pending" ? "" : ch ? `<p>Decision: <b>${ch === "update_existing" ? "update the existing contact" : "add as a new contact"}</b>. <button type="button" class="link" id="cChange">Change</button></p>`
          : d.dup_decided ? `<div class="btns"><button type="button" class="btn small" id="cNew">Add as new contact</button> <button type="button" class="link" id="cChange">Other choice</button></div>`   // round 22: after 'Different person' one button, not a second same/different pair
          : `<div class="btns">${d.dupes.updates_enabled ? `<button type="button" class="btn small" id="cUpd">Same person: update their existing MC Trade contact</button>` : ""}<button type="button" class="btn small" id="cNew">Different person: add as new contact</button></div>` +
            (d.dupes.updates_enabled ? "" : `<p class="small">Updating existing contacts is off. If it's the same person, reject or leave pending and tell the data team.</p>`));
    const set = (v, msg) => e => act(e.currentTarget, {crm_action: v}, msg + (v === "create_new" && m.why.includes("email exact") && !m.sample ? " It is exported as a new row and listed under 'possible existing member' in the READ-ME (same email as profile #" + m.profile_id + ")." : v === "update_existing" && m.sample ? " (Sample data: it will be listed for checking in MC Trade, not exported.)" : ""));
    $("#cUpd") && ($("#cUpd").onclick = set("update_existing", "Will update the existing MC Trade contact."));
    $("#cNew") && ($("#cNew").onclick = set("create_new", "Will be added as a new contact."));
    $("#cChange") && ($("#cChange").onclick = () => { ($("#rDupC").querySelector(".btns") || $("#rDupC").querySelector("p:last-child")).outerHTML = `<div class="btns"><button type="button" class="btn small" id="cUpd">Update existing contact</button><button type="button" class="btn small" id="cNew">Add as new contact</button></div>`;
      $("#cUpd").onclick = set("update_existing", "Will update the existing MC Trade contact."); $("#cNew").onclick = set("create_new", "Will be added as a new contact."); });
  }
}
function collect() {
  const v = id => $("#" + id).value.trim();
  const phones = v("phones").split("\n").map(l => l.trim()).filter(Boolean).map(l => {
    const m = l.match(/^(work|mobile|cell|fax|office|main|direct|phone|tel)\s*[:.]?\s*(.+)$/i);
    return m ? {type: ({cell: "mobile", office: "work", main: "work", direct: "work", phone: "work", tel: "work"})[m[1].toLowerCase()] || m[1].toLowerCase(), number: m[2].trim()} : {type: "work", number: l}; });
  const extra = {}; $$("[data-extra]").forEach(e => extra[e.dataset.extra] = e.value.trim());
  return {...extra, first_name: v("first_name"), last_name: v("last_name"), title: v("title"), company: v("company"), website: v("website"), address: v("address"),
    emails: v("emails").split(/[,;\s]+/).filter(Boolean), social: v("social").split(/\s+/).filter(Boolean), phones};
}
async function act(btn, extra, okMsg, sid = cur && cur.id) {
  if (!CARD_READY || !cur) { toast("Wait for the card to finish loading before saving.", 4000); return; }
  if (!await needWho()) return;
  if (SAVING && !await waitSaveIdle()) { toast("Not saved: the last save is still running. Try again in a moment.", 6000); return; }   // round 14
  // round 11 (part-timer r4 CRITICAL): the card is fixed when the action starts. If the page moved to another card meanwhile
  // (e.g. while the merge dialog was open), nothing is saved: before, the merge was sent for the card now on screen, so the
  // TARGET was merged into itself and rejected.
  if (!cur || cur.id !== sid) { toast(`Not saved: you moved from card #${sid} to another card. Open #${sid} and try again.`, 7000); return; }
  $$("#rDupQ button, #rDupC button").forEach(b => { if (b !== btn) b.disabled = true; });
  clearTimeout(rPoll); SAVING = true; try {
  await busy(btn, "Saving…", async () => {
    try { const sent_ = formSnap(); const r = await post("/api/cards/" + sid, {fields: collect(), reviewer: who(), note: $("#note").value, card_id: sid, version: cur.version, ...extra}); clearTimeout(keepDraft.t); markSaved(sid, sent_); toast(r.notice || okMsg, r.notice ? 7000 : 4500, true); await openCard(cur.id, {keep: true}); refreshCounts(); }
    catch (e) { toast("Not saved: " + e.message, 5000); }
  }); } finally { SAVING = false; recomputeDirty(); }   // round 21: never a stuck 'Saving…' after a refused save
}
const dlgStopped = r => { if (r && r.cancelled) toast("Not saved: the question closed first. Your edits are still on the form.", 8000); };   // round 14
let DECIDING = 0;   // round 17 (reviewer r16 N3, part-timer r16 #1): one decision at a time; the AI poll never re-renders under it
async function decide(status, btn) {
  if (!cur || $("#dlg").open) return;
  if (DECIDING && status) return;   // a double-click on Approve: the second click is ignored (no "question was closed" toast)
  DECIDING++; try { return await decide_(status, btn); } finally { DECIDING--; }
}
async function decide_(status, btn) {
  if (!CARD_READY) { toast("Wait for the card to finish loading before saving.", 4000); return; }
  const sid = cur.id;   // round 11 (part-timer r4): the card is fixed when the action starts (see act())
  if (status && !await needWho()) return;
  // round 14 (LOST SAVE): a click while the previous save is still running used to be ignored without a word (busy button).
  // It now waits for that save, then saves what is on the form at that moment.
  if (SAVING || btn.getAttribute("aria-busy") === "true") {
    toast("Saving your previous change first…", 2500);
    if (!await waitSaveIdle()) { await ask({title: "Not saved", html: "<p>The last save is still running. Your edits are still here. Save again in a moment.</p>", buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return; }
    if (!cur || cur.id !== sid) { toast(`Not saved: you moved from card #${sid} to another card.`, 6000); return; }
  }
  const sent = formSnap();
  const body = {fields: collect(), status, reviewer: who(), note: $("#note").value, card_id: sid, version: cur.version};
  // round 13 (part-timer r5): the AI status on screen can be out of date (queued or started after the page loaded): ask the
  // server first, so the "AI check hasn't finished" prompt always shows, and an AI-only change never gives a silent 409
  clearTimeout(rPoll);   // round 14: no AI-poll reload while this decision is being prepared
  let fr0 = null; if (status === "approved" || status === "rejected") { try { fr0 = await call("/api/cards/" + sid); } catch {} }
  if (fr0 && cur && cur.id === sid && JSON.stringify([fr0.card.fields, fr0.card.status, fr0.card.note || ""]) === JSON.stringify([cur.card.fields, cur.card.status, cur.card.note || ""])) body.version = fr0.version;
  // round 16 (reviewer r15 N1/#7): check the form FIRST, so nobody confirms the "already exported?" dialog only to be refused;
  // the refusal lists every problem at once
  let soft0 = {};   // round 22: soft problems known up front, so the reason is asked in the SAME dialog (at most one dialog)
  if (status === "approved") { let goOn = false; try { const v_ = await post("/api/validate", {fields: collect(), card_id: sid}), hard_ = v_.hard || {}; soft0 = v_.errors || {};
    if (Object.keys(hard_).length) { const all_ = {...(v_.errors || {}), ...hard_}; showErrors(all_, true);
      // round 21 (mctrade-admin r20): a 'looks misread' check can be wrong. When every blocker is that kind and the form is saved, the reviewer may confirm it
      const ov = v_.overridable || [], canOv = ov.length && Object.keys(hard_).every(k => ov.includes(k)) && !recomputeDirty();
      // round 22: the refusal shows once (inline + one summary line), no dialog; 'This is correct' sends field + exact value + version
      if (!recomputeDirty()) confirmBtn(ov, sid, hard_);   // the button covers the overridable blocks; others still need fixing
      { const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); return; }
      try { const fr_ = await call("/api/cards/" + sid); body.version = fr_.version; cur.version = fr_.version; } catch {} } } catch {} }
  const aiWas = fr0 ? fr0.ai_status : cur.ai_status;   // approving doesn't wait for the AI; a queued check is cancelled, a running one leaves suggestions
  // round 15 (part-timer): ONE dialog for AI-not-finished + already-known cross-batch look-alikes (no two questions in a row)
  // round 20 (reviewer r19): cards already marked "Different person" don't bring back the 'may send twice' warning
  const keptIds = new Set(((cur.dupes || {}).queue || []).filter(x => x.kept_apart).map(x => x.card_id));
  const xe0 = status === "approved" && !cur.dup_decided ? (cur.exported_elsewhere || []).filter(x => (x.times || 0) > 0 && !keptIds.has(x.card_id)) : [];
  // round 23 (newcomer r22): a choice already made on the card (or 'Different person' when adding as new is the only choice) is sent, so it is not asked again
  if (status === "approved" && cur.dupes && !body.crm_action) { if (cur.dupes.crm_action) body.crm_action = cur.dupes.crm_action; else if (cur.dup_decided && (cur.dupes.crm || []).length && !cur.dupes.updates_enabled) body.crm_action = "create_new"; }
  const aiBusy = (status === "approved" || status === "rejected") && ["queued", "checking"].includes(aiWas) && cur.status === "pending";
  if (aiBusy || (status === "approved" && xe0.length && !body.confirm_cross_batch)) {
    const bits = [];
    if (aiBusy) bits.push(`<p>${aiWas === "queued" ? "AI check not done yet. Deciding now <b>cancels</b> it." : "AI still checking. Its suggestions appear later, for information."}</p>`);
    if (status === "approved" && xe0.length) bits.push(`<p>This person was exported before (${xe0.slice(0, 3).map(x => "#" + x.card_id).join(", ")}). Approve anyway?</p>`);   // round 23 (datamanager/reviewer r22): asked even while the AI is checking
    const needWhy = status === "approved" && Object.keys(soft0).length > 0;
    if (needWhy) bits.push(`<ul>${Object.values(soft0).map(m => `<li>${esc(m)}</li>`).join("")}</ul><p>Fix them on the form, or approve anyway and say why.</p>`);
    const r0 = await ask({title: status === "rejected" ? "Reject before the AI check?" : aiBusy && xe0.length ? "Before you approve" : aiBusy ? "The AI check hasn't finished" : "Same person already exported?", html: bits.join(""),
      input: needWhy ? {label: "Reason for approving anyway", placeholder: "e.g. card has no email, phone confirmed by hand", required: "A reason is needed to approve anyway.", max: 300} : null,
      buttons: [{label: status === "approved" ? (xe0.length ? "Approve it anyway" : "Approve now") : "Reject now", cls: "primary", value: 1, primary: true}, {label: aiBusy ? "Wait for the AI" : "Cancel", value: null}]});
    if (!r0.value) { dlgStopped(r0); return; }
    if (needWhy) { if (!(r0.input || "").trim()) { toast("A reason is needed to approve anyway.", 4000); return; } body.override_reason = r0.input; }
    if (xe0.length && status === "approved") body.confirm_cross_batch = true;
    clearTimeout(rPoll);
    try { const fr = await call("/api/cards/" + sid); if (JSON.stringify([fr.card.fields, fr.card.status, fr.card.note || ""]) === JSON.stringify([cur.card.fields, cur.card.status, cur.card.note || ""])) body.version = fr.version; } catch {}
  }
  clearTimeout(rPoll); SAVING = true; recomputeDirty();
  try { await busy(btn, status === "approved" ? "Approving…" : status === "rejected" ? "Rejecting…" : "Saving…", async () => {
    for (let tries = 0; tries < 5; tries++) {
      try {
        if (!cur || cur.id !== sid) { toast(`Not saved: you moved from card #${sid} to another card. Your edits on #${sid} are kept as a draft.`, 7000); return; }
        // round 15 (part-timer): values typed WHILE the save/approve was waiting (dialogs, network) are included, not lost
        body.fields = collect(); body.note = $("#note").value;
        const saved = await post("/api/cards/" + sid, body);
        if (saved && saved.version && cur && cur.id === sid) cur.version = saved.version;   // round 14: the next quick save uses the new version at once
        if (saved && saved.card) LASTOK[sid] = JSON.stringify([saved.card.fields, saved.card.status, saved.card.note || ""]);
        clearTimeout(keepDraft.t); delete SS.draft; markSaved(sid, sent);   // reviewer r8 / round 12 / round 14: no ghost draft or badge after a save
        await refreshCounts(); STATUS[sid] = saved.status;
        if (status === "approved" || status === "rejected") {
          toast(`✓ Card #${sid} ${status} by ${who()}.` + (["queued", "checking"].includes(aiWas) ? (aiWas === "queued" ? " The waiting AI check was cancelled." : " Any AI suggestions will appear on the card later.") : ""), 3500, true);
          // round 8 (part-timer r2): 'Next' stays inside THIS card's batch, asked from the server (also when the card was opened
          // by a direct link); "All done" only when that batch has no pending card left at all
          const myB = cur.batch || null, o = order(), i = o.indexOf(sid);
          let pl = null; try { const qs = new URLSearchParams({status: "pending"}); if (myB) qs.set("batch", myB); else qs.set("limit", "0"); pl = (await call("/api/cards?" + qs)).filter(x => x.id !== sid); } catch {}
          let nx2;
          if (pl) { const ids = new Set(pl.map(x => x.id));
            nx2 = (i >= 0 ? (o.slice(i + 1).find(x => ids.has(x)) ?? o.slice(0, i).find(x => ids.has(x))) : undefined) ?? (pl.find(x => x.id > sid) || pl[0] || {}).id; }
          else { const pend = x => x !== sid && STATUS[x] === "pending"; nx2 = i >= 0 ? (o.slice(i + 1).find(pend) ?? o.slice(0, i).find(pend)) : undefined; }
          const bq = "#queue?s=pending&batch=" + encodeURIComponent(myB || "__none__");
          if (nx2 !== undefined) { if (pl && pl.length > 1) toast(`✓ Card #${sid} ${status}. ${plural(pl.length, "card")} still pending in this batch.`, 3000, true); location.hash = "review/" + nx2; }
          else if (pl) { try { if (cur && cur.id === sid) await openCard(sid, {keep: true}); } catch {}   // round 15 (newcomer r14): the card behind the dialog shows its new status
            const msg_ = `All done: no pending cards are left in ${cur.batch_label || "this batch"}.`; location.hash = bq; setTimeout(() => toast(msg_, 6000), 400); }   // after the route change (it clears toasts)   // round 22: a toast, not one more dialog
          else { toast("Couldn't check what is still pending: back to the queue.", 4000); location.hash = bq; }
        } else {
          const sp = saved.save_problems || {};
          toast(saved.notice || (status === "pending" ? `Card #${sid} moved back to pending.` : Object.keys(sp).length ? "Saved, but it can't be approved yet: " + Object.values(sp).join(" ") : "Changes saved."), saved.notice || Object.keys(sp).length ? 7000 : 4500, true);
          if (cur && cur.id === sid && location.hash === "#review/" + sid) await openCard(sid, {keep: true});   // round 12; round 14: keep typing done during the save: never pull the view back to a card the person already left
          if (Object.keys(sp).length) { showErrors(sp, true); const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); }   // reviewer r7
        }
        return;
      } catch (e) {
        const need = e.data && e.data.need;
        
        if (need === "confirm_redecide") {
          const r = await ask({title: "Change an earlier decision?", html: `<p>${esc(e.message)}</p><p class="small">The earlier decision stays in the card's history.</p>`,
            buttons: [{label: `Yes, mark it ${status}`, cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
          if (!r.value) { dlgStopped(r); return; } body.confirm_redecide = true; continue;
        }
        if (need === "stale" && !body._selfRetry) {   // round 14: stale only because of OUR OWN previous save -> send again, no dialog
          try { const fr = await call("/api/cards/" + sid);
            if (LASTOK[sid] && LASTOK[sid] === JSON.stringify([fr.card.fields, fr.card.status, fr.card.note || ""])) { body.version = fr.version; body._selfRetry = 1; continue; } } catch {}
        }
        if (need === "stale" || need === "wrong_card") {
          await ask({title: "The card changed", html: `<p>${esc(e.message)}</p><p class="small">Your edits are still here. Check them and save again.</p>`, buttons: [{label: "Reload the card", cls: "primary", value: 1, primary: true}]});
          await openCard(sid, {keep: true}); return;
        }
        if (need === "confirm_cross_batch") {
          const r = await ask({title: "Same person already approved in another batch?", html: `<p>${esc(e.message)}</p>` + ((e.data.others || []).length > 1 ? `<p>Open: ${e.data.others.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}</p>` : "") + `<p class="small">“Approve this one too” doesn't change the other cards.</p>`,
            buttons: [{label: (e.data.others || []).length > 1 ? `Open the first of these ${e.data.others.length} cards` : "Open that card", value: "open"}, {label: "Different person (or a deliberate update): approve this one too", cls: "primary", value: "go", primary: true}, {label: "Cancel", value: null}]});
          if (r.value === "open") { location.hash = "review/" + e.data.other; return; }
          if (!r.value) { dlgStopped(r); return; } body.confirm_cross_batch = true; continue;
        }
        if (need === "true_duplicate") { await ask({title: "Duplicate scan", html: `<p>${esc(e.message)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return; }
        if (need === "fix" && !status) {   // reviewer r9: a refused SAVE says so, lists every problem, and keeps the unsaved markers
          let all_ = {...(e.data.errors || {})};
          try { const v_ = await post("/api/validate", {fields: collect(), card_id: sid}); all_ = {...v_.errors, ...v_.hard, ...all_}; } catch {}
          showErrors(all_, true);
          await ask({title: "Not saved: fix these first", html: `<ul>${Object.entries(all_).map(([k, m]) => `<li>${esc(m)}${(e.data.errors || {})[k] ? " <b>(blocks saving)</b>" : " (blocks approving later)"}</li>`).join("")}</ul><p>Nothing was saved. Fix the values marked “blocks saving”, then save again.</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]});
          recomputeDirty(); const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); return;
        }
        if (need === "fix") {
          try { const v_ = await post("/api/validate", {fields: collect(), card_id: sid}); e.data.errors = {...(v_.errors || {}), ...(v_.hard || {}), ...(e.data.errors || {})}; } catch {}   // round 16: every problem
          showErrors(e.data.errors, true);
          await ask({title: "These values can't be approved", html: `<ul>${Object.values(e.data.errors).map(m => `<li>${esc(m)}</li>`).join("")}</ul><p>Fix them, then approve. A card needs a first name, a full email (like name@company.com) and phones with 7+ digits.</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]});
          const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); return;
        }
        if (need === "fix_or_override") {
          showErrors(e.data.errors, true);
          const r = await ask({title: "Some details are missing or look wrong", html: `<ul>${Object.values(e.data.errors).map(m => `<li>${esc(m)}</li>`).join("")}</ul><p>Fix them on the form (recommended), or approve anyway and say why.</p>`,
            buttons: [{label: "Fix the fields", cls: "primary", value: null, primary: true}, {label: "Approve anyway", value: "override", needInput: true}], input: {label: "Reason for approving anyway (at least 3 letters)", placeholder: "e.g. card has no email, phone confirmed by hand", required: "A reason is needed to approve anyway.", max: 300}});
          if (r.value !== "override") { const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); return; }
          body.override_reason = r.input; continue;
        }
        if (need === "resolve_duplicate") {
          await ask({title: "Possible duplicate", html: `<p>${esc(e.message)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]});
          $("#rDupQ").scrollIntoView({block: "center"}); return;
        }
        if (need === "crm_choice") {
          const r = await ask({title: "Already in MC Trade?", html: `<p><b>${esc(e.data.match.name)}</b>, ${esc(e.data.match.organization)} looks like this person (${esc(e.data.match.why_text || "")}).</p>` + (e.data.match.sample ? `<p class="small"><b>SAMPLE data:</b> test contacts only. The card is exported as a <b>new</b> profile.</p>` : ""),
            buttons: [...(cur.dupes.updates_enabled ? [{label: "Same person: update their contact", cls: "primary", value: "update_existing", primary: true}] : []), {label: "Different person: add as new", value: "create_new", ...(cur.dupes.updates_enabled ? {} : {cls: "primary", primary: true})}, {label: "Cancel", value: null}]});
          if (!r.value) { dlgStopped(r); return; } body.crm_action = r.value; continue;
        }
        // round 13 (part-timer r5): never fail silently: say why in a dialog, not only a short toast
        await ask({title: status === "approved" ? "Not approved" : status === "rejected" ? "Not rejected" : "Not saved", html: `<p>${esc(e.message)}</p><p class="small">Nothing changed. Your edits are still here.</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return;
      }
    }
  }); } finally { SAVING = false; recomputeDirty(); }   // round 21: never a stuck 'Saving…' after a refused save
}
$("#bApprove").onclick = e => decide("approved", e.currentTarget); $("#bReject").onclick = e => decide("rejected", e.currentTarget);
$("#bSave").onclick = e => decide(null, e.currentTarget); $("#bPending").onclick = e => decide("pending", e.currentTarget);
const step = d => { const o = cur ? navOrder(cur.id) : order(), i = o.indexOf(cur?.id);
  // opened from a link (not in the current queue list): J/K go to the nearest card of the list by number
  const n = i >= 0 ? o[i + d] : (d > 0 ? o.filter(x => x > cur.id).sort((a, b) => a - b)[0] : o.filter(x => x < cur.id).sort((a, b) => b - a)[0]);
  if (n !== undefined) location.hash = "review/" + n; else toast(d > 0 ? "No next card in the queue list." : "No previous card in the queue list."); };
$("#backFile").onchange = async e => {
  const file = e.target.files[0]; e.target.value = ""; if (!file || !cur) return;
  if (dirty) { toast("Save your edits first, then add the back.", 4000); return; }
  const send = confirm => { const fd = new FormData(); fd.append("image", file); if (confirm) fd.append("confirm_other_person", "1"); return call(`/api/cards/${cur.id}/back`, {method: "POST", body: fd}); };
  toast("Reading the back of the card…", 15000);
  try { let r;
    try { r = await send(false); }
    catch (x) {
      if (x.data?.need !== "confirm_other_person") throw x;
      hideToast(/^Reading the back/);
      const a = await ask({title: "This looks like a different person's card", html: `<p>${esc(x.message)}</p>`,
        buttons: [{label: "Don't add it", value: null, primary: true}, {label: "It IS the back of this card: add it", value: 1}]});
      if (!a.value) { toast("Nothing was added.", 3000); return; }
      toast("Reading the back of the card…", 15000); r = await send(true);
    }
    hideToast(/^Reading the back/); toast((r.filled.length ? "Back added. Filled: " + r.filled.map(k => LABEL[k] || k).join(", ") : "Back added. Nothing new found on it.") +
      (r.not_added && Object.keys(r.not_added).length ? " Not added (not clearly printed, or doesn't match the card's email): " + Object.entries(r.not_added).map(([k, v]) => (LABEL[k] || k) + " " + [].concat(v).join(", ")).join("; ") + ". Type it in if it is right." : ""), r.not_added && Object.keys(r.not_added).length ? 9000 : 4000, true); openCard(cur.id); }
  catch (x) { hideToast(/^Reading the back/); toast("Not added: " + x.message, 5000); }
  finally { hideToast(/^Reading the back/); }
};
$("#bDelete").onclick = async () => {
  const r = await ask({title: `Delete card #${cur.id} permanently?`, html: "<p>For removal requests. Deletes the photo, details and stored export copies. This can't be undone. The audit log keeps who did what and when, with personal details removed. Files already in MC Trade must be removed there.</p><details class=\"more small\"><summary>More</summary>Export files already downloaded to a computer must be deleted there too.</details>",
    buttons: [{label: "Delete permanently", cls: "danger", value: 1}, {label: "Cancel", value: null, primary: true}]});
  if (!r.value) return;
  try { const x = await post(`/api/admin/cards/${cur.id}/delete`, {confirm: cur.id}); toast(`Card #${x.deleted} deleted.`); location.hash = SS.queueHash || "queue"; refreshCounts(); }
  catch (e) { toast("Not deleted: " + e.message, 5000); }
};
$("#prev").onclick = () => step(-1); $("#next").onclick = () => step(1);
$("#zoom").onclick = $("#rImg").onclick = () => $("#zoomDlg").showModal();
document.addEventListener("keydown", e => {
  if ($("#v-review").hidden || e.ctrlKey || e.metaKey || e.altKey || $("#dlg").open || $("#zoomDlg").open) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) { if (e.key === "Escape") document.activeElement.blur(); return; }
  const k = e.key.toLowerCase();
  if (k === "a") decide("approved", $("#bApprove")); else if (k === "r") decide("rejected", $("#bReject")); else if (k === "j") step(1); else if (k === "k") step(-1); else if (k === "u") doUndo(); else return;
  e.preventDefault();
});

/* ---------- export ---------- */
async function exportInfo() {
  const st = $("#exStatus").value, eb = $("#exBatch").value; $("#exInfo").textContent = "Checking…";
  try {
    if (!exportInfo.busyList) {   // refreshed every time (manager L-new3: a new batch showed only after a reload)
      exportInfo.busyList = true; let bs; try { bs = await call("/api/batches"); exportInfo.list = bs; } finally { exportInfo.busyList = false; }
      let keepB = exportInfo.picked ? $("#exBatch").value : "";   // round 22: a fresh visit picks the default below (never a stale empty batch)   // the person may have picked a batch while the list was loading (r15int: "All batches" = "" is a real pick too)
      // round 7 (part-timer r1): your own batches first, and the default is your most recent batch, not "All batches"
      const cnt = b => st === "approved_new" ? `${b.ready ?? b.n} ready to export` : st === "approved" ? `${b.approved ?? b.n} approved` : `${plural(b.n, "card")}`;
      const opt = b => `<option value="${esc(b.batch)}">${esc(b.batch_label || b.batch)} (${cnt(b)})</option>`;
      const mine = bs.filter(b => b.mine), others = bs.filter(b => !b.mine);
      // round 8 (part-timer r2): your batches first; other people's only with "Show other people's batches too"
      const showAll = ($("#exShowAll") && $("#exShowAll").checked) || exportInfo.more, othShown = showAll ? others : others.filter(b => b.batch === keepB);
      const rdy = b => (st === "approved_new" ? (b.ready ?? b.n) : st === "approved" ? (b.approved ?? b.n) : b.n) > 0;
      if (SS.exportFrom) { const fb_ = bs.find(b => b.batch === SS.exportFrom); if (fb_ && fb_.mine && rdy(fb_) && !exportInfo.picked) keepB = SS.exportFrom; delete SS.exportFrom; }   // round 23: only your own   // round 22 (newcomer r21 HIGH): only when it has cards ready   // round 21 (newcomer r20 HIGH): the batch you came from / just finished
      // round 23 (mctrade-admin/reviewer r22 M2): the default is YOUR OWN newest batch from TODAY, or nothing ("Choose a batch");
      // never another tester's or an old batch. The list shows only that batch plus "More batches…" until More is chosen.
      if (!exportInfo.picked && !keepB) {
        const nw = (a, b) => (b.started || 0) - (a.started || 0), d0 = new Date(); d0.setHours(0, 0, 0, 0);
        const today = mine.filter(b => b.own && (b.started || 0) >= d0 / 1000).sort(nw);
        const def = today[0] || mine.filter(b => b.own).sort(nw)[0]; keepB = def ? def.batch : "__choose__"; }   // round 24: the newest batch, not an older one with ready cards
      const cur_ = bs.find(b => b.batch === keepB);
      $("#exBatch").innerHTML = (keepB === "__choose__" ? `<option value="__choose__">Choose a batch…</option>` : "") +
        (showAll ? (mine.length ? `<optgroup label="Your batches">${mine.map(opt).join("")}</optgroup>` : "") + (others.length ? `<optgroup label="Other people's batches">${others.map(opt).join("")}</optgroup>` : "") + `<option value="">All batches (everyone's)</option>`
                 : (cur_ ? opt(cur_) : keepB === "" ? `<option value="">All batches (everyone's)</option>` : "") + `<option value="__more__">More batches…</option>`);
      if ($("#exShowAll")) $("#exShowAll").nextElementSibling.textContent = " Show all batches";
      $("#exBatch").value = [...$("#exBatch").options].some(o => o.value === keepB) ? keepB : ($("#exBatch").options[0] || {}).value || ""; filterExBatch(); }
    if ($("#exBatch").value !== "__more__") exportInfo.last = $("#exBatch").value;
    if ($("#exBatch").value === "__choose__") {   // nothing chosen: nothing to export, no check
      $("#exInfo").textContent = "Choose a batch."; $("#exDup").hidden = true; $$(".tile").forEach(t => t.disabled = true); loadExportHistory(); return {count: 0}; }
    if ($("#exBatch").value !== eb) { if (!exportInfo.depth) { exportInfo.depth = 1; try { return await exportInfo(); } finally { exportInfo.depth = 0; } } }   // selection changed meanwhile: check the batch actually shown
    const r = await call(`/api/export/check?status=${st}&batch=${encodeURIComponent(eb)}`);
    $("#exInfo").innerHTML = `${r.count ? `<b>${plural(r.count, "card")}</b> will be exported.` : "Nothing to export yet. Approve some cards first."}` +
      (r.flagged && r.flagged.length ? ` <span class="flag bad">${r.flagged.length === 1 ? "1 card has" : r.flagged.length + " cards have"} a warning (${r.flagged.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}). See the READ-ME.</span>` : "");   // round 23: no '1 were approved'

    $("#exDup").hidden = !r.duplicates.length;
    // round 7: no button per pair (part-timer/newcomer: a flood of buttons that write onto other people's cards). The pairs are
    // a review list of links; open a card to decide. Only an admin gets "mark all", behind a confirm that lists the pairs.
    const pairsAll = r.duplicates.flatMap(p => p.with.filter(w => !(p.strong || []).includes(w)).map(w => [p.id, w]));
    $("#exDup").innerHTML = r.duplicates.length ? `<b>Export is blocked: some cards look like the same person.</b> ${eb ? "Open each card to merge, or mark them as different people there." : "<b>Tip:</b> choose your own batch; other people's look-alikes don't block it."}` +
      (!eb && r.ok_batches && r.ok_batches.length ? `<p>These batches can be exported now: ${r.ok_batches.map(b => `<a href="#" data-xbatch="${esc(b.batch)}">${esc(b.label)}</a> (${b.count})`).join(", ")}</p>` : "") +
      `<details${eb ? " open" : ""}><summary>Review list: ${plural(r.duplicates.length, "card")} with look-alikes</summary><ul>${r.duplicates.map(p => `<li><a href="#review/${p.id}">Card #${p.id}</a>${p.batch ? ` <span class="sub">(${esc(p.batch)})</span>` : ""} may duplicate ${p.with.map(w => `<a href="#review/${w}">#${w}</a>` + ((p.strong || []).includes(w) ? ` <span class="sub">(duplicate scan: merge or reject one)</span>` : "")).join(", ")}</li>`).join("")}</ul></details>` : "";
    const pairs = ME.role === "admin" ? pairsAll : [];
    if (pairs.length > 1) {
      $("#exDup").insertAdjacentHTML("beforeend", `<p class="small">Admin only: <button class="btn small" id="xKeepAll">Mark all ${pairs.length} listed pairs as different people…</button> (check the list first)</p>`);
      $("#xKeepAll").onclick = async () => {
        const r = await ask({title: `Mark ${pairs.length} pairs as different people?`, html: `<p>This saves a “different person” link on each listed card for the card next to it (${esc(pairs.slice(0, 12).map(([a, w]) => `#${a}↔#${w}`).join(", "))}${pairs.length > 12 ? "…" : ""}). Duplicate scans aren't included. Undo is available.</p>`,
          buttons: [{label: "Mark them all", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
        if (!r.value || !await needWho()) return; let ok = 0, bad = 0;
        for (const [a, w] of pairs) { try { const cv = (await call(`/api/cards/${a}`)).version; await post(`/api/cards/${a}`, {keep_apart: [w], card_id: a, version: cv}); ok++; } catch { bad++; } }
        toast(`${ok} pair(s) marked as different people` + (bad ? `, ${bad} not changed (open them)` : "") + ".", 4000, ok > 0); exportInfo(); };
    }
    $("#exDup").querySelectorAll("[data-xbatch]").forEach(a => a.onclick = e => { e.preventDefault(); $("#exBatch").value = a.dataset.xbatch; exportInfo(); });
    $$(".tile").forEach(t => t.disabled = !r.count || r.duplicates.length > 0); loadExportHistory();
    return r;
  } catch (e) { $("#exInfo").textContent = "Couldn't check: " + e.message; }
}
// audit 2026-10: say what was really saved. In the desktop app each file goes through a native Save dialog that can be
// cancelled (desktop.js gacSaveBlob answers {saved} | {cancelled} | {error}); a browser only takes the download over.
async function saveBlob(blob, name) {
  const d = window.gacSaveBlob && window.gacSaveBlob(blob, name); if (d) return await d;
  const a = document.createElement("a"), u = URL.createObjectURL(blob); a.href = u; a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 60000); return {name, started: true};
}
const lostFiles = outs => outs.filter(o => !o.saved && !o.started);
function savedText(outs) {
  if (outs.every(o => o.started)) return `Your browser is downloading ${plural(outs.length, "file")}.`;
  const ok = outs.filter(o => o.saved), no = lostFiles(outs);
  return ((ok.length ? `Saved ${ok.length === 1 ? ok[0].saved : plural(ok.length, "file") + " to " + ok[0].saved.replace(/[\\/][^\\/]*$/, "")}.` : "") +
    (no.length ? ` Not saved: ${no.map(o => `${o.name} (${o.cancelled ? "cancelled" : o.error || "failed"})`).join(", ")}.` : "")).trim();
}
async function dl(url) {   // fetch + save, so several files can be downloaded from one click
  const r = await fetchOk(url);
  const nm = (r.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || "file";
  return {r, out: await saveBlob(await r.blob(), decodeURIComponent(nm))};
}
$("#exPreview").onclick = async () => {
  // round 20 (coordinator r19): Preview shows the files ON SCREEN only; downloading the PREVIEW- copies is a separate button
  const q = `/api/export/xlsx?preview=1&status=${encodeURIComponent($("#exStatus").value)}&batch=${encodeURIComponent($("#exBatch").value)}`;
  try { const v = await call(q + "&view=1"), cell = x => `<td>${esc(x ?? "")}</td>`;
        if (!v || !v.rows) { toast("No preview available.", 4000); return; }
        const tbl = (h, rows) => `<div style="overflow:auto;max-height:40vh"><table class="aidiff"><thead><tr>${h.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.map(r_ => `<tr>${r_.map(cell).join("")}</tr>`).join("") || `<tr><td colspan="${h.length}">none</td></tr>`}</tbody></table></div>`;
        const a = await ask({title: "Preview of the MC Trade files", html: `<p class="small">Nothing is downloaded or marked as exported.</p><p>${esc(v.source_text)}</p><p><b>New profiles (${plural(v.rows.length, "row")})</b></p>` + tbl(v.headers, v.rows) +
          (v.updates.length ? `<p><b>UPDATES file (${v.updates.length})</b></p>` + tbl(v.headers, v.updates) : "") +
          `<p><b>Left out / to check (${v.left.length})</b></p>` + tbl(["Card", "Why"], v.left.map(x => ["#" + x[0], x[1]])) +
          ((v.warnings || []).length ? `<details class="more"><summary>In the file, with a warning (${v.warnings.length})</summary><ul>${v.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""),
          wide: true, buttons: [{label: "Close", cls: "primary", value: null, primary: true}, {label: "Download preview files (not for import)", value: "dl"}]});
        if (a.value !== "dl") return;
        const {r, out} = await dl(q), comp = (r.headers.get("X-Companions") || "").split(",").filter(Boolean), outs = [out];
        for (const c of comp) outs.push((await dl(q + "&companion=" + c)).out);
        toast(savedText(outs) + " These are PREVIEW files, not for import.", lostFiles(outs).length ? 8000 : 5000); }
  catch (e) { toast("Preview not made: " + e.message, 5000); }
};
$("#exDryrun").onclick = () => { window.open(`/api/export/dryrun?status=${encodeURIComponent($("#exStatus").value)}&batch=${encodeURIComponent($("#exBatch").value)}`, "_blank", "noopener"); };
$("#exShowAll") && ($("#exShowAll").onchange = () => exportInfo());
$("#exStatus").onchange = exportInfo;
$("#exBatch").onchange = () => { if ($("#exDone").dataset.batch !== $("#exBatch").value) $("#exDone").hidden = true;   // round 23 (newcomer r22): no stale success box for another batch
 if ($("#exBatch").value === "__more__") { if ($("#exShowAll")) $("#exShowAll").checked = true; exportInfo.more = true; $("#exBatch").value = exportInfo.last ?? ""; exportInfo.picked = true; exportInfo(); return; } exportInfo.picked = true; exportInfo(); };
function filterExBatch() { const t = ($("#exBatchQ")?.value || "").toLowerCase().trim();
  [...$("#exBatch").options].forEach(o => { o.hidden = !!t && o.value !== "" && !o.textContent.toLowerCase().includes(t); }); }
$("#exBatchQ") && ($("#exBatchQ").oninput = filterExBatch);
let exHistShow = 10;
$("#exHistMoreBtn").onclick = () => { exHistShow += 10; loadExportHistory(); };
$("#exHistAllBtn").onclick = () => { exHistShow = Infinity; loadExportHistory(); };
async function loadExportHistory() {
  const every = await call("/api/exports"), everyone = $("#exHistEveryone") && $("#exHistEveryone").checked;   // part-timer r3: yours by default
  const all = everyone ? every : every.filter(x => x.own), h = all.slice(0, exHistShow);
  $("#exHistMore").hidden = all.length <= h.length; $("#exHistCount").textContent = `Showing ${h.length} of ${all.length}` + (everyone ? " (everyone's)." : ` of your exports (${every.length - all.length} by other people hidden).`);
  $("#exHist").innerHTML = h.map(x => `<tr><td>${esc(when(x.ts))}</td><td>${esc(x.initials)}</td><td>${esc(x.kind.toUpperCase())}<div class="sub">${esc(x.filter_text)}${x.batch_label ? " · batch " + esc(x.batch_label) : ""}</div></td><td>${x.count}</td>
    <td>${x.available ? `<a href="/api/exports/${x.id}/download">${esc(x.filename)}</a>` + (x.companions || []).map(c => ` · <a href="/api/exports/${x.id}/companion/${c}">${c === "readme.txt" ? "READ ME" : c === "updates.xlsx" ? "UPDATES file" : "extra columns"}</a>`).join("") : `${esc(x.filename)} <span class="sub">(${x.mine ? "copy deleted" : "only " + esc(x.initials) + " or an admin can download it"})</span>`}</td></tr>`).join("") || `<tr><td colspan="5">No exports yet.</td></tr>`;
}
$("#exHistEveryone") && ($("#exHistEveryone").onchange = () => loadExportHistory());
const KIND_ = 0; const KIND = {xlsx: "MC Trade import (Excel)", csv: "Spreadsheet (CSV)", vcf: "Contacts (vCard)"};
$$(".tile").forEach(t => t.onclick = async () => {   // round 14 (parttimer r6): busy at once, one click only, checks in parallel
  if (t.getAttribute("aria-busy") === "true") return;
  t.setAttribute("aria-busy", "true"); const lbl0 = t.style.cursor; t.style.cursor = "progress"; toast("Preparing the export…", 1500);
  try { await tileExport(t); } finally { t.removeAttribute("aria-busy"); t.style.cursor = lbl0; }
});
async function tileExport(t) {
  const kind = t.dataset.ex, st = $("#exStatus").value;
  const pre = kind === "xlsx" ? call(`/api/export/xlsx?preview=1&view=1&status=${st}&batch=${encodeURIComponent($("#exBatch").value)}`).catch(e => ({__err: e})) : null;
  const info = await exportInfo(); if (!info || !info.count || info.duplicates.length) return;
  if (!await needWho()) return;
  { const eb_ = $("#exBatch").value, bo = (BATCHES || []).find(b => b.batch === eb_) || (exportInfo.list || []).find(b => b.batch === eb_);   // round 24 (reviewer r23): warn before exporting someone else's batch
    if (eb_ === "" || (bo && !bo.own)) { const who_ = bo && bo.owner ? bo.owner : "other people";
      const a_ = await ask({title: eb_ === "" ? "Export everyone's batches?" : `This batch belongs to ${who_}`, html: `<p>${eb_ === "" ? "You chose All batches: cards other people scanned are included." : `“${esc(bo.batch_label || bo.batch)}” was scanned by ${esc(who_)}, not you.`} Export it anyway?</p>`,
        buttons: [{label: "Cancel", cls: "primary", value: null, primary: true, focus: true}, {label: "Export anyway", value: 1}]});
      if (!a_.value) return; } }
  let so = "", seenV = info.versions || null, nUpd = 0;
  const shw = (n, html) => n ? ` <details class="more small" style="display:inline"><summary>Show</summary>${html}</details>` : "";   // round 21: a count + Show, not an id wall   // round 16: what the sign-off was made from; the export is refused if it changed
  // round 7: 'ready to export' sign-off: what goes in which file, and what still needs a decision
  if (kind === "xlsx") { try { const v = await pre; if (v && v.__err) throw v.__err; if (v && v.versions) seenV = v.versions; nUpd = (v && v.updates || []).length;
    if (v && v.rows) { const nm = r_ => [r_[v.headers.indexOf("IndFirstName")], r_[v.headers.indexOf("IndLastName")]].filter(Boolean).join(" ");
      so = `<div class="alert"><ul><li><b>${info.count}</b> approved card${(info.count) === 1 ? "" : "s"} checked</li>` +
        `<li><b>${v.rows.length}</b> new-profile row${(v.rows.length) === 1 ? "" : "s"} in the import file${shw(v.rows.length, esc(v.rows.map(nm).join(", ")))}</li>` +
        (v.updates.length ? `<li><b>${v.updates.length}</b> update row${(v.updates.length) === 1 ? "" : "s"} in the UPDATES file: ${esc(v.updates.map(nm).join(", "))}</li>` : "") +
        ((v.update_diff || []).length ? `<li><b>What the updates change in MC Trade</b> (an import overwrites non-blank cells and can't be undone):<div style="overflow:auto;max-height:30vh"><table class="aidiff" data-updiff="1"><thead><tr><th>Card</th><th>Profile</th><th>Field</th><th>Now in MC Trade</th><th>After import</th></tr></thead><tbody>${v.update_diff.map(u => u.fields.map(x => `<tr${x.changes ? ' class="chg"' : ""}><td><a href="#review/${u.card}">#${u.card}</a></td><td>${esc(u.profile_id)}</td><td>${esc(x.field)}</td><td>${x.old === null ? "<i>not in the contacts export: check in MC Trade</i>" : esc(x.old)}</td><td>${x.changes || x.changes === null ? "<b>" + esc(x.new) + "</b>" : esc(x.new)}</td></tr>`).join("")).join("")}</tbody></table></div></li>` : "") +
        ((v.sample_email_matches || []).length ? `<li>${v.sample_email_matches.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")} match test contacts. Included anyway.</li>` : "") +
        (() => { const dz = v.decisions || {}, rv = v.left.filter(x => dz[x[0]] === "review"), lo = v.left.filter(x => dz[x[0]] !== "review");   // same classification as the export + dry run
          return (rv.length ? `<li><b>${rv.length}</b> card${(rv.length) === 1 ? "" : "s"} to review (in neither file)${shw(rv.length, rv.map(x => `<a href="#review/${x[0]}" title="${esc(x[1])}">#${x[0]}</a>`).join(", "))}</li>` : "") +
                 (lo.length ? `<li><b>${lo.length}</b> card${(lo.length) === 1 ? "" : "s"} left out (merged into another row, or to fix first)${shw(lo.length, lo.map(x => `<a href="#review/${x[0]}" title="${esc(x[1])}">#${x[0]}</a>`).join(", "))}</li>` : ""); })() +
        (info.pending_count ? `<li><b>${info.pending_count}</b> card${(info.pending_count) === 1 ? "" : "s"} still <b>pending</b>${shw(info.pending_count, info.pending.slice(0, 30).map(x => `<a href="#review/${x.id}">#${x.id} ${esc(x.name)}</a>`).join(", "))}</li>` : "") +
        `</ul></div>`; } } catch {} }
  const r = await ask({title: `Export ${plural(info.count, "card")}?`, html: so + `<p>Format: <b>${KIND[kind]}</b><br>Cards: <b>${esc($("#exStatus").selectedOptions[0].textContent)}</b><br>Batch: <b>${esc($("#exBatch").selectedOptions[0]?.textContent || "All batches")}</b></p><p class="small">${kind === "xlsx" ? `<b>You'll get ${nUpd ? 4 : 3} files. Import only the .xlsx${nUpd ? " (and the UPDATES .xlsx as a separate import)" : ""}.</b> <details class="more"><summary>More</summary>The READ-ME.txt and extra-columns.csv are for reading, not for import.</details>` : "You'll get one file."}</p>`,
    buttons: [{label: "Export", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return;
  t.setAttribute("aria-busy", "true");
  try {
    const sv = seenV ? Object.entries(seenV).map(([k, x]) => `&seen_${k}=${encodeURIComponent(x)}`).join("") : "";
    const res = await fetchOk(`/api/export/${kind}?status=${st}&batch=${encodeURIComponent($("#exBatch").value)}` + sv);
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || "export." + kind, n = res.headers.get("X-Card-Count");
    const outs = [await saveBlob(await res.blob(), name)];
    $("#exDone").hidden = false;
    const eid = res.headers.get("X-Export-Id"), comp = (res.headers.get("X-Companions") || "").split(",").filter(Boolean);
    for (const c of comp) { let r2; try { r2 = await fetchOk(`/api/exports/${eid}/companion/${c}`); } catch (x) { if (x.status === 401) throw x; outs.push({name: c, error: x.message}); continue; }
      const nm = (r2.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || c;
      outs.push(await saveBlob(await r2.blob(), decodeURIComponent(nm))); }
    $("#exDone").className = "alert ok"; $("#exDone").hidden = false;
    let sm = null; try { sm = JSON.parse(res.headers.get("X-Summary") || "null"); } catch {}
    // round 23 (coordinator/newcomer r22): one short line, plus only what needs action
    $("#exDone").innerHTML = (sm ? `<b>✓ ${plural(sm.cards, "card")} saved: ${plural(sm.new_rows, "new row")}` + (sm.update_rows ? `, ${plural(sm.update_rows, "update")}` : "") + (sm.crm_real ? "" : " (test data, no Profile IDs)") + `.</b>` +
        (sm.left_ids.length ? ` <span class="flag bad">Not imported: ${sm.left_ids.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}.</span>` : "") +
        (sm.possible.length ? ` <span class="flag low">Maybe in MC Trade: ${sm.possible.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}.</span>` : "")
      : `<b>✓ Exported ${plural(n, "card")}</b>.`) + (kind === "xlsx" ? `<br>Import only the .xlsx${comp.includes("updates.xlsx") ? " (updates separately)" : ""}. Read the READ-ME and try 2 rows first.` : "");
    const lost = lostFiles(outs);   // audit 2026-10: a cancelled Save dialog (desktop app) is said, never claimed as saved
    if (lost.length) $("#exDone").insertAdjacentHTML("beforeend", `<br><span class="flag bad">Not saved: ${esc(lost.map(o => o.name).join(", "))}.</span> Download ${lost.length === 1 ? "it" : "them"} again from Export history below.`);
    $("#exDone").dataset.batch = $("#exBatch").value;
    toast(savedText(outs) + (kind === "xlsx" && !lost.length ? " Read the READ-ME first." : ""), lost.length ? 9000 : 5000); exportInfo.picked = true; exportInfo(); refreshCounts();   // round 24 (newcomer r23): stay on the exported batch   // round 20 (newcomer r19)
  } catch (e) { $("#exDone").hidden = false; $("#exDone").className = "alert bad"; $("#exDone").textContent = "Export failed: " + e.message; }
  finally { t.removeAttribute("aria-busy"); }
}

/* ---------- admin ---------- */
let adminTab = "users";
$$("#adminTabs button").forEach(b => b.onclick = () => { adminTab = b.dataset.t; loadAdmin(); });
const ADMV = {};   // round 15: versions of the shared admin state as shown on this page
async function loadAdmin() {
  if (!ME) return;   // route() runs again once the signed-in user is known
  if (ME.role !== "admin") { ["users", "settings", "audit"].forEach(t => $("#t-" + t).hidden = true); $("#adminTabs").hidden = true; toast("Only admins can open the Admin page."); return; }
  $$("#adminTabs button").forEach(x => x.setAttribute("aria-selected", x.dataset.t === adminTab));
  ["users", "settings", "audit"].forEach(t => $("#t-" + t).hidden = t !== adminTab);
  if (adminTab === "users") {
    const us = await call("/api/admin/users");
    $("#uBody").innerHTML = us.map(u => `<tr data-u="${u.id}"><td>${esc(u.display)}</td><td>${esc(u.username)}${/^qa[-_]/i.test(u.username) ? '<div class="sub" style="color:#b45309">Shared test login: deactivate before go-live</div>' : ""}</td><td>${esc(u.initials)}</td><td>${u.role === "admin" ? "Admin" : "Reviewer"}</td><td>${u.active ? "Active" : "Deactivated"}${u.must_change ? '<div class="sub">temporary password</div>' : ""}</td>
      <td>${u.id === ME.id ? '<span class="sub">(you)</span>' : `<button class="link" data-act="pw">Reset password</button> · <button class="link" data-act="active">${u.active ? "Deactivate" : "Reactivate"}</button> · <button class="link" data-act="role">${u.role === "admin" ? "Make reviewer" : "Make admin"}</button>`}</td></tr>`).join("");
    $("#uBody").onclick = async e => {
      const act = e.target.dataset.act; if (!act) return; const id = +e.target.closest("tr").dataset.u, u = us.find(x => x.id === id);
      let body = null;
      if (act === "pw") { const r = await ask({title: `Reset password for ${u.display}`, html: "<p>They will be asked to change it when they sign in. Their open sessions are signed out.</p>", input: {label: "Temporary password (10+ characters)", required: "Enter a password."}, buttons: [{label: "Reset", cls: "primary", value: 1, needInput: true, primary: true}, {label: "Cancel", value: null}]}); if (!r.value) return; body = {password: r.input}; }
      if (act === "active") { const r = await ask({title: `${u.active ? "Deactivate" : "Reactivate"} ${u.display}?`, html: u.active ? "<p>They can no longer sign in. Their past reviews stay in the audit log.</p>" : "", buttons: [{label: u.active ? "Deactivate" : "Reactivate", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]}); if (!r.value) return; body = {active: !u.active}; }
      if (act === "role") body = {role: u.role === "admin" ? "reviewer" : "admin"};
      try { await post("/api/admin/users/" + id, body); toast("Saved."); loadAdmin(); } catch (x) { toast(x.message, 5000); }
    };
  }
  if (adminTab === "settings") {
    const st = await call("/api/admin/settings"), pv = await call("/api/admin/retention/preview");
    ADMV.seen = st;   // round 15 (manager r14): optimistic locking: the values shown are sent back with every save
    call("/api/admin/backup-status").then(b => { const w = $("#sBackupWarn"); w.hidden = !b.same_disk;
      if (b.same_disk) w.innerHTML = `<b>Backups are on this computer only.</b> Ask IT to set a backup drive. <details class="more"><summary>More</summary>If this disk fails, the cards and backups are lost together. Backup folder: ${esc(b.dir)}. IT: see the admin guide, section 2.5.</details>`; }).catch(() => {});
    $("#sOn").checked = st.retention_enabled === "1"; $("#sAI").checked = st.ai_check_enabled === "1"; $("#sUpd").checked = st.mctrade_updates_enabled === "1"; $("#sCorr").checked = st.corrections_enabled === "1"; $("#sAff").value = st.mctrade_affcode || ""; $("#sPh").value = st.phone_format || "gac"; $("#sPhone").checked = st.phone_mode_allowed === "1"; $("#sUpdChk").checked = st.update_check_enabled === "1";
    call("/api/admin/mctrade-template").then(t => { ADMV.tpl = t.version; return t; }).then(t => $("#sTpl").innerHTML = (t.present ? `<span class="chip ok">GAC template</span> ${t.columns.filter(Boolean).length} columns${t.unknown.length ? " · left blank: " + esc(t.unknown.join(", ")) : ""}` : `<span class="chip low">Default columns</span> Upload GAC's template before the first real import.`) + ` <span title="Version ${esc(t.version)}">` + (t.last_change ? `· changed by ${esc(t.last_change.by)}, ${esc(t.last_change.at)}` : "") + "</span>").catch(() => {});
    $("#sTplFile").onchange = async e => { const f = e.target.files[0]; e.target.value = ""; if (!f) return; const fd = new FormData(); fd.append("image", f); fd.append("expected_version", ADMV.tpl || "");
      try { const r = await call("/api/admin/mctrade-template", {method: "POST", body: fd}); loadAdmin();
            const undoTpl = async () => { try { await call("/api/admin/mctrade-template/revert?expected_version=" + encodeURIComponent(r.version || "") + (r.had_previous ? "" : "&to_none=1"), {method: "POST"}); toast("Template upload undone."); loadAdmin(); } catch (x) { toast("Couldn't undo: " + x.message, 5000); } };
            toast(`Template saved: ${r.columns.filter(Boolean).length} columns.`, 6000, undoTpl); } catch (x) { toast("Not saved: " + x.message, 5000); } };
    let tplNone = false;   // manager r8 L-r8-1: with no earlier file, the button removes the (first) template
    call("/api/admin/mctrade-template").then(t => { tplNone = t.present && !t.can_revert; $("#sTplRevert").hidden = !t.present;
      $("#sTplRevert").textContent = t.can_revert ? `Use previous template` : "Remove template"; }).catch(() => {});
    $("#sTplRevert").onclick = async () => { const r = await ask({title: tplNone ? "Remove the template?" : "Go back to the previous template?", html: tplNone ? "<p>There is no earlier template. Exports go back to the default columns, which may not match MC Trade.</p>" : "<p>The current template is replaced by the one before it.</p>", buttons: [{label: tplNone ? "Remove it" : "Go back", cls: "primary", value: 1}, {label: "Cancel", value: null, primary: true, focus: true}]});
      if (!r.value) return; try { await call("/api/admin/mctrade-template/revert?expected_version=" + encodeURIComponent(ADMV.tpl || "") + (tplNone ? "&to_none=1" : ""), {method: "POST"}); toast(tplNone ? "Template removed: default columns are used." : "Previous template restored."); loadAdmin(); } catch (x) { toast(x.message, 5000); } };
    call("/api/admin/mctrade-contacts").then(c => { ADMV.crm = c.version; $("#sCrm").innerHTML = (c.real ? `<span class="chip ok">Real contacts</span> ` + esc(c.source) : `<span class="chip low">SAMPLE data</span> Test contacts only. No Profile IDs.`) +
      (c.last_change ? ` · changed by <b>${esc(c.last_change.by)}</b>, ${esc(c.last_change.at)}. Ask them before replacing it.` : "");
      $("#sCrmRemove").hidden = !c.real; }).catch(() => {});
    $("#sCrmFile").onchange = async e => { const f = e.target.files[0]; e.target.value = ""; if (!f) return; const fd = new FormData(); fd.append("image", f); fd.append("expected_version", ADMV.crm || "");
      try { const r = await call("/api/admin/mctrade-contacts", {method: "POST", body: fd}); toast("MC Trade contacts loaded: " + r.people + " people." + (r.skipped_sample_rows ? ` Skipped ${r.skipped_sample_rows} SAMPLE row(s).` : ""), 6000); loadAdmin(); } catch (x) { toast("Not loaded: " + x.message, 6000); } };
    $("#sCrmRemove").onclick = async () => { const a = await ask({title: "Remove the MC Trade contacts export?", html: "<p>The file is deleted from this computer. Exports go back to SAMPLE data, with no Profile IDs.</p>", buttons: [{label: "Remove and delete it", cls: "danger", value: 1}, {label: "Cancel", value: null, primary: true, focus: true}]});
      if (!a.value) return; try { await call("/api/admin/mctrade-contacts/remove?expected_version=" + encodeURIComponent(ADMV.crm || ""), {method: "POST"}); toast("Contacts file deleted. Back to SAMPLE data: no Profile IDs."); loadAdmin(); } catch (x) { toast(x.message, 5000); } };
    aiHelperRefresh(); call("/api/ai/status").then(a => { $("#sAIStatus").innerHTML = `<span class="chip ${a.available ? "ok" : "low"}">${esc(aiWord(a))}</span>` + (a.available ? "" : " See Help to start it."); if (!((a.queue || {}).waiting || (a.queue || {}).running)) aiHeader(a); }); $("#sImg").value = st.image_retention_days; $("#sExp").value = st.export_retention_days;
    $("#sPrev").textContent = `${pv.photos_stored} photos stored · ${pv.would_delete} older than ${pv.days} days${pv.enabled ? " (deleted at next check)" : " (auto-delete off)"}`;
  }
  if (adminTab === "audit") loadAudit();
}
$("#uForm").onsubmit = async e => { e.preventDefault(); $("#uErr").textContent = "";
  await busy($("#uAdd"), "Adding…", async () => { try {
    await post("/api/admin/users", {display: $("#uDisplay").value.trim(), username: $("#uName").value.trim(), initials: $("#uIni").value.trim(), role: $("#uRole").value, password: $("#uPw").value});
    toast(`Added ${$("#uDisplay").value}. Send them their username and password.`, 5000); $("#uForm").reset(); loadAdmin();
  } catch (x) { $("#uErr").textContent = x.message; } }); };
$("#uDisplay").oninput = () => { if (!$("#uName").dataset.touched) $("#uName").value = $("#uDisplay").value.trim().toLowerCase().replace(/\s+/g, ".").replace(/[^a-z0-9._-]/g, ""); };
$("#uName").oninput = () => $("#uName").dataset.touched = "1";
$("#sAISkip").onclick = e => busy(e.currentTarget, "Skipping…", async () => { try { const r = await post("/api/admin/ai/skip-waiting", {}); toast(`AI check skipped for ${plural(r.skipped, "waiting card")}.`, 4000, true); } catch (x) { toast(x.message, 5000); } });   // round 22
$("#sSave").onclick = e => busy(e.currentTarget, "Saving…", async () => { try { const r = await post("/api/admin/settings", {ai_check_enabled: $("#sAI").checked ? "1" : "0", corrections_enabled: $("#sCorr").checked ? "1" : "0", mctrade_updates_enabled: $("#sUpd").checked ? "1" : "0", retention_enabled: $("#sOn").checked ? "1" : "0", image_retention_days: $("#sImg").value, export_retention_days: $("#sExp").value, mctrade_affcode: $("#sAff").value, phone_format: $("#sPh").value, phone_mode_allowed: $("#sPhone").checked ? "1" : "0", update_check_enabled: $("#sUpdChk").checked ? "1" : "0", _seen: ADMV.seen || {}}); toast(r._changed && !r._changed.length ? "Nothing changed, so nothing was saved." : "Settings saved."); loadAdmin(); } catch (x) { toast(x.message, 5000); } });
$("#sRun").onclick = async e => { const btn = e.currentTarget;
  const pv = await call("/api/admin/retention/preview");
  const r = await ask({title: "Delete old photos now?", html: `<p>${pv.would_delete} card photo(s) older than ${pv.days} days will be permanently deleted. Contact details stay. This can't be undone.</p>`, buttons: [{label: "Delete now", cls: "danger", value: 1, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return;
  await busy(btn, "Deleting…", async () => { const x = await post("/api/admin/retention/run", {}); toast(`Deleted ${x.images} photo(s) and ${x.exports} export copy(ies).`); loadAdmin(); });
};
let aT; $("#aQ").oninput = () => { clearTimeout(aT); aT = setTimeout(loadAudit, 250); };
async function loadAudit() {
  const q = $("#aQ").value.trim(), rows = await call("/api/admin/audit?limit=300&q=" + encodeURIComponent(q));
  $("#aCsv").href = "/api/admin/audit?fmt=csv&limit=5000&q=" + encodeURIComponent(q);
  $("#aBody").innerHTML = rows.map(r => `<tr><td>${esc(when(r.ts))}</td><td>${esc(r.who)}</td><td>${esc(r.kind)}</td><td>${r.card ? `<a href="#review/${r.card}">#${r.card}</a>` : ""}</td><td>${esc(r.what)}</td></tr>`).join("") || `<tr><td colspan="5">Nothing found.</td></tr>`;
}

(async () => { await loadMe(); route(); refreshCounts(); refreshUndo(); })();
fetch("/health").then(r => r.json()).then(h => { const el = $("#appVer"); if (el) el.textContent = `v${h.version || "?"}` + (h.commit && h.commit !== "unknown" && h.commit !== "?" ? ` (${h.commit})` : ""); }).catch(() => {});   // round 11
setInterval(() => { if (!document.hidden) refreshCounts(); }, 15000);
// round 10 (newcomer r9): the upload list updates by itself (a card approved, rejected or merged elsewhere shows its new state)
setInterval(() => { if (!document.hidden && B && (location.hash || "#upload").startsWith("#upload")) refreshBatchCards(); }, 15000);
window.addEventListener("focus", () => { if (B && (location.hash || "#upload").startsWith("#upload")) refreshBatchCards(); });
$(".skip").onclick = e => { e.preventDefault(); $("#main").focus(); };   // the hash is the router: don't navigate to "#main"

/* ---------- phone mode (Scan with phone) ---------- */
let phT = null;
async function phoneRefresh() {
  clearTimeout(phT);
  try { const st = await call("/api/phone/status"); $("#bPhone").hidden = !st.allowed;
    if (!st.active) { $("#phonePanel").hidden = true; return; }
    $("#phoneCount").textContent = st.uploads || 0; const m = Math.max(0, Math.round((st.expires - Date.now() / 1000) / 60));
    $("#phoneExp").textContent = m ? `Code works for ${m} more min` : "Code expiring";
    phT = setTimeout(phoneRefresh, 5000);
  } catch {}
}
async function phoneStart() {
  try { const r = await post("/api/phone/start", {batch_label: $("#batchName").value.trim()});
    $("#phoneQr").src = r.qr; $("#phoneUrl").textContent = r.url.replace(/\?t=.*/, "?t=…"); $("#phonePanel").hidden = false;
    if (!r.lan_only) toast("No Wi-Fi connection found. Connect this computer to Wi-Fi.", 6000);
    const cand = r.candidates || [];   // part-timer r2: say which address the QR uses when the computer has several
    let cn = $("#phoneCand"); if (!cn) { $("#phoneUrl").insertAdjacentHTML("afterend", `<p id="phoneCand" class="small"></p>`); cn = $("#phoneCand"); }
    cn.textContent = cand.length > 1 ? `If the phone can't open the page, ask IT to set the phone address (now ${r.host}).` : "";
    phoneRefresh();
  } catch (e) { toast(e.message, 6000); }
}
$("#bPhone").onclick = phoneStart; $("#phoneNew").onclick = phoneStart;
$("#phoneStop").onclick = async () => { await post("/api/phone/stop", {}); $("#phonePanel").hidden = true; toast("Phone scanning stopped."); };
phoneRefresh();
/* ---------- AI line indicator + update banner ---------- */
// round 20 (datamanager/newcomer r19): ONE wording for the AI state, used by the header AND Admin → Settings
function aiWord(a) { return !a.enabled ? "AI check: off" : a.available ? "AI check: on" : "AI check paused"; }
function aiHeader(a) { const el = $("#aiQueue"); if (!el) return; el.hidden = false; el.textContent = aiWord(a);
  el.title = !a.enabled ? "AI check is off (Admin → Settings)." : a.available ? "AI check is on: unclear cards get a later typo check." : "The AI isn't answering right now. Scanning still works. See Help."; }
async function aiQueueTick() {
  try { const a = await call("/api/ai/status"), q = a.queue || {}, n = (q.waiting || 0) + (q.running || 0);
    // round 16 (coordinator r15 #2): everyone sees whether the AI double-check is on (read-only; an admin changes it in Settings)
    $("#aiQueue").hidden = false;
    if (!n) aiHeader(a);
    if (n) { $("#aiQueue").textContent = "AI check: busy"; $("#aiQueue").classList.remove("warn");
      $("#aiQueue").title = `AI check: ${plural(n, "card")} ahead, about ${fmtEta(q.eta_seconds || 0)}. You can review them now.`; }
    setTimeout(aiQueueTick, n ? 5000 : 20000);
  } catch { setTimeout(aiQueueTick, 30000); }
}
aiQueueTick();
setTimeout(async () => { try { const u = await call("/api/update");
  if (u.update_available && u.show_banner && ME && ME.role === "admin" && localStorage.getItem("gacUpdDismiss") !== u.latest) {   // round 20 (e)
    const b = $("#updBanner"); b.hidden = false;
    b.innerHTML = `A new version (${esc(u.latest)}) is available; you have ${esc(u.current)}. <a href="${esc(u.url)}" target="_blank" rel="noopener noreferrer">Release notes &amp; download</a> <button class="link" id="updX">Dismiss</button>`;
    $("#updX").onclick = () => { localStorage.setItem("gacUpdDismiss", u.latest); b.hidden = true; };
  } } catch {} }, 6000);
// ---- Desktop "AI helper" download/start/stop (Admin > Settings). Shown only in the packaged desktop app.
var aiHelperTimer = null;
async function aiHelperRefresh() {
  let s; try { s = await call("/api/admin/ai-helper"); } catch (e) { return; }
  const box = $("#aiHelper"); if (!box) return;
  box.hidden = !(s.desktop || s.installed) || !s.supported;
  const busyNow = s.phase === "downloading" || s.phase === "verifying";
  const pct = s.total ? Math.floor(100 * s.done / s.total) : 0;
  $("#aiHelperMsg").textContent = s.phase === "error" ? "Download failed: " + s.error :
    busyNow ? (s.phase === "verifying" ? "Checking " : "Downloading ") + (s.file || "") + (s.total ? ` (${pct}%, ${(s.done / 1e9).toFixed(2)} of ${(s.total / 1e9).toFixed(2)} GB)` : "…") :
    s.installed ? (s.running ? "AI helper installed and running (it can take a minute to load)." : "AI helper installed but stopped.") :
    `Optional: download the local AI helper (about ${s.size_gb} GB, runs only on this computer). Scanning works without it.`;
  $("#aiHelperBar").hidden = !busyNow; $("#aiHelperBar").value = pct;
  $("#aiHelperDl").hidden = s.installed || busyNow; $("#aiHelperStart").hidden = !s.installed || s.running;
  $("#aiHelperStop").hidden = !s.running; $("#aiHelperRm").hidden = !s.installed || busyNow;
  clearTimeout(aiHelperTimer); if (busyNow || (s.running && !box.hidden)) aiHelperTimer = setTimeout(aiHelperRefresh, busyNow ? 1500 : 8000);
}
for (const [id, path] of [["#aiHelperDl", "download"], ["#aiHelperStart", "start"], ["#aiHelperStop", "stop"], ["#aiHelperRm", "remove"]])
  if ($(id)) $(id).onclick = async () => { if (path === "remove" && !confirm("Delete the downloaded AI helper files?")) return;
    try { await post("/api/admin/ai-helper/" + path, {}); } catch (e) { toast(e.message, 5000); } aiHelperRefresh(); };
