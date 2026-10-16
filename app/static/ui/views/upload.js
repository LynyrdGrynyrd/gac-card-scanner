// Scan page: picking/dropping photos, the upload queue (pause on sign-in expiry, retry), the batch list.
import {S} from "../core/state.js";
import {$, SS, esc, plural} from "../core/dom.js";
import {call, csrf, post} from "../core/api.js";
import {toast} from "../ui/toast.js";
import {ask} from "../ui/dialog.js";
import {refreshCounts} from "../header.js";
import {Q, loadQueue} from "./queue.js";

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

S.B = JSON.parse(SS.batch || "null");   // {id,label,rows:[{key,file,state,msg,job,card,thumb}]}
const saveB = () => { if (S.B) SS.batch = JSON.stringify({...S.B, rows: S.B.rows.map(r => ({...r, thumb: undefined, blob: undefined}))}); };
let uploading = 0; const UPCONC = 3, upq = [];
const upPending = () => !!(upq.length || uploading || (S.B && S.B.rows.some(r => r.state === "wait" && r.blob)));
// audit 2026-10: a 401 while uploading used to mark every photo "Not added: Please sign in" and the files were lost. Now the
// queue pauses, the photos stay "waiting", one message offers a sign-in in a new tab, and the uploads resume by themselves.
let AUTH_PAUSED = false, authT = null;
function authPause() {
  AUTH_PAUSED = true;
  let el = $("#authPause"); if (!el) { document.body.insertAdjacentHTML("afterbegin", `<div id="authPause" class="alert bad" role="alert"></div>`); el = $("#authPause"); }
  const n = S.B ? S.B.rows.filter(r => r.state === "wait").length : 0;
  el.innerHTML = `<b>Your sign-in expired, so uploading is paused.</b> ${n ? plural(n, "photo") + " waiting; nothing is lost. " : ""}Keep this tab open, <a href="/login?next=%2Fui%23upload" target="_blank" rel="noopener">sign in again</a> (opens a new tab), then come back: the upload carries on by itself.`;
  el.hidden = false; if (!authT) authT = setInterval(authCheck, 3000); renderBatch();
}
async function authCheck() {   // runs while this tab is hidden too: the person is signing in in the other tab
  if (!AUTH_PAUSED) return;
  let s = null; try { s = await (await fetch("/api/auth/state", {credentials: "same-origin"})).json(); } catch { return; }
  if (!s || !s.user || !AUTH_PAUSED) return;
  if (S.ME && s.user.id !== S.ME.id) { $("#authPause").innerHTML = `This browser is now signed in as <b>${esc(s.user.display)}</b>, not <b>${esc(S.ME.display)}</b>, so uploading stays paused (the photos would be saved under their name). Sign in as ${esc(S.ME.display)} in the other tab.`; return; }
  AUTH_PAUSED = false; clearInterval(authT); authT = null; $("#authPause").hidden = true;
  toast("Signed in again: uploading carries on.", 4000); renderBatch(); pumpUploads(); poll();
}
addEventListener("focus", () => { if (AUTH_PAUSED) authCheck(); });
function newBatch() {
  // round 8 (newcomer r8 N2): the batch name is kept exactly as typed (only spaces tidied, control characters and < > dropped);
  // nothing is appended. Your own batch with the same name from the last 12 h is reused; if someone else (or an older batch)
  // already uses the name, a visible " (2)" is added and you are told.
  if (S.B) S.B.rows.forEach(dropThumb);   // audit 2026-10: the previous batch's rows are gone from the page
  const d = new Date(), id = "B" + d.toISOString().replace(/\D/g, "").slice(0, 14) + "-" + Math.random().toString(16).slice(2, 6);   // round 13: unique even when two people start in the same second
  const name = $("#batchName").value.replace(/[\u0000-\u001f\u007f<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 120);
  const norm = x => (x || "").replace(/\s+/g, " ").trim().toLowerCase();
  const all = S.BATCHES || [];
  // v0.4.2 #5 (reviewer/newcomer: "(2) (1)"): the name always carries the date and the owner, so it is readable and unique
  // without a counter: "After Hours · Oct 16 · RR". Your own batch with the same name today is reused.
  const day = d.toLocaleDateString([], {month: "short", day: "numeric"}), who = (S.ME && (S.ME.initials || S.ME.display)) || "";
  let label = [name, day, who].filter(Boolean).join(" · ");
  const same = all.find(b => b.own && norm(b.batch_label) === norm(label) && b.started > Date.now() / 1000 - 12 * 3600);
  if (same) { S.B = {id: same.batch, label: same.batch_label, rows: [], t0: Date.now() / 1000, uid: S.ME && S.ME.id}; saveB(); toast(`Added to your batch “${label}”.`); return; }
  if (!name || all.some(b => norm(b.batch_label) === norm(label))) label += " " + d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  S.B = {id, label, rows: [], t0: Date.now() / 1000, uid: S.ME && S.ME.id}; saveB();
}
const isImg = f => /^image\//.test(f.type) || /\.(jpe?g|png|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name) || isPdf(f);
const isPdf = f => f.type === "application/pdf" || /\.pdf$/i.test(f.name);   // round 18: each page / card on a page becomes a card
// round 15 (coordinator r14 #4): a sign-in left over on this browser silently acted as someone else. Before the first upload
// in a tab, ask who is scanning; "someone else" signs out.
async function confirmWho() {
  if (!S.ME || SS.whoOk === String(S.ME.id) || SS.whoSigned === "1") return true;   // signed in in this tab: it is you
  const r = await ask({title: "Who is scanning?", html: `<p>This browser is signed in as <b>${esc(S.ME.display || S.ME.username)}</b> (${esc(S.ME.initials || "")}). Cards you upload are recorded under this name.</p>`,
    buttons: [{label: `Yes, I am ${S.ME.display || S.ME.username}`, cls: "primary", value: "me", primary: true}, {label: "No, sign out so I can sign in", value: "out"}, {label: "Cancel", value: null}]});
  if (r.value === "me") { SS.whoOk = String(S.ME.id); return true; }
  if (r.value === "out") { try { await post("/api/auth/logout", {}); } catch {} location.href = "/login"; }
  return false;
}
async function enqueue(files) {
  if (!files.length) { toast("Nothing was selected."); return; }
  if (!await confirmWho()) return;
  // coordinator r2 N1: a different name typed in "Name this batch", or a batch left over from hours ago, starts a NEW batch
  const typed = $("#batchName").value.replace(/\s+/g, " ").trim().toLowerCase();
  const fresh = !S.B || S.B.rows.every(r => ["done", "rej", "err", "cancel"].includes(r.state)) && $("#clearBatch").dataset.fresh === "1";
  // v0.4.2 #5: a saved current batch from another day (or another person) is never reused
  const oldDay = S.B && S.B.t0 && new Date(S.B.t0 * 1000).toDateString() !== new Date().toDateString(), notYou = S.B && S.B.uid && S.ME && S.B.uid !== S.ME.id;
  const renamed = S.B && !fresh && (oldDay || notYou || (typed && !(S.B.label || "").toLowerCase().startsWith(typed)) || (!typed && S.B.t0 && Date.now() / 1000 - S.B.t0 > 4 * 3600));
  // audit 2026-10 P0-14: photos of the current batch still waiting to upload would be filed under the NEW batch (and no longer
  // tracked); finish (or cancel) this batch's uploads first
  if ((fresh || renamed) && S.B && (upq.length || uploading)) { toast(`Photos of “${S.B.label}” are still uploading. Wait until they are done (or cancel them), then start the new batch.`, 7000); return; }
  if (fresh && S.B) newBatch();
  else if (renamed) { const old = S.B.label; newBatch(); toast(`Started a new batch “${S.B.label}” (the previous one was “${old}”).`, 6000); }
  if (!S.B) newBatch();
  $("#clearBatch").dataset.fresh = "0";
  S.B.rows = S.B.rows.filter(r => r.state !== "cancel" || dropThumb(r));   // round 21 (reviewer r20): no stale cancelled rows on the next upload
  for (const f of files) {
    const row = {key: Math.random().toString(36).slice(2), file: f.webkitRelativePath || f.name, state: "wait"};
    if (/(^|\/)\./.test(row.file)) continue;              // hidden system files in folders
    if (!isImg(f)) { row.state = "rej"; row.msg = "Can't scan this file. Use JPG, PNG, HEIC or PDF."; }
    else if (!f.size) { row.state = "rej"; row.msg = "File is empty."; }
    else { row.blob = f; row.thumb = null; if (!isPdf(f) && !/\.hei[cf]$/i.test(f.name)) thq.push(row); upq.push(row); }
    ROWB.set(row, S.B); S.B.rows.push(row);
  }
  S.B.stopped = false; saveB(); renderBatch(); pumpUploads(); pumpThumbs();
}
// audit 2026-10: upload thumbnails were full-resolution blob URLs that were never revoked (hundreds of decoded 12 MP photos
// on a big batch). Now one ~96 px thumbnail per photo, made one at a time; its URL is revoked when the row goes.
const thq = []; let thBusy = false;
function dropThumb(r) { if (r && r.thumb && r.thumb.startsWith("blob:")) URL.revokeObjectURL(r.thumb); if (r) r.thumb = null; return false; }
async function pumpThumbs() {
  if (thBusy) return; thBusy = true;
  try { while (thq.length) {
    const r = thq.shift(), live = () => S.B && S.B.rows.includes(r) && r.blob; if (!live() || r.thumb) continue;
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
  const bb = ROWB.get(row) || S.B;
  return new Promise(res => { try {
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
      // v0.4.3 #8 (reviewer: Scan showed two batches with one name): Scan shows the name the server stored, " (2)" included
      if (j.batch_label && j.batch_label !== bb.label && (!j.batch || j.batch === bb.id)) { bb.label = j.batch_label; if (S.B === bb) { saveB(); renderBatch(); } }
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
      row.backoff = true; if (!row.stop) setTimeout(() => { row.backoff = false; if (row.state === "wait" && bb.rows.includes(row)) { upq.push(row); pumpUploads(); } }, Math.min(15000, 2000 * row.tries)); };
    x.timeout = 180000; x.ontimeout = x.onerror;   // v0.4.2 #12: a request that never answers no longer holds an upload slot forever
    x.send(fd);
    // v0.4.2 #12 (newcomer: first upload stuck on "Waiting to upload"): anything thrown before the send left the row waiting
    // with no request and no retry. Now it says so and offers Retry.
  } catch (e) { delete row.xhr; row.state = "rej"; row.retry = true; row.msg = "Not sent. Press Retry."; saveB(); renderBatch(); res(); } });
}
// round 20 (b): one calm line while the scanner can't be reached; everything retries by itself
function conn(ok) {
  let el = $("#reconn");
  if (!el) { document.body.insertAdjacentHTML("afterbegin", `<div id="reconn" class="alert" role="status" hidden>Reconnecting… your cards are safe.</div>`); el = $("#reconn"); }
  // v0.4.3 #8 (part-timer): only a REAL disconnect: two failures in a row, 4 s apart, and not while the page is closing
  if (ok) { conn.f = 0; conn.t = 0; el.hidden = true; return; }
  if (conn.leaving) return;
  conn.f = (conn.f || 0) + 1; conn.t = conn.t || Date.now();
  el.hidden = !(conn.f >= 2 && Date.now() - conn.t >= 4000);
}
addEventListener("pagehide", () => { conn.leaving = true; });
function addKids(row, job) {   // round 20: cards of a PDF appear as each page is read
  row.kids = row.kids || 0;
  const dir = row.file.includes("/") ? row.file.slice(0, row.file.lastIndexOf("/") + 1) : "";
  const fresh = (job.children || []).slice(row.kids); if (!fresh.length) return;
  row.kids += fresh.length;
  const rows = fresh.map(x => ({key: Math.random().toString(36).slice(2), file: dir + x.file, state: x.job ? "queued" : (x.status === 409 ? "dup" : "rej"),
    job: x.job, msg: x.job ? "" : x.error, dupOf: x.duplicate_of, src: row.file}));
  const at = S.B.rows.indexOf(row); S.B.rows.splice(at, 0, ...rows);
}
function splitRow(row, j, bb = S.B) {
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
  if (!S.B || AUTH_PAUSED) return;   // audit 2026-10: resumed by authCheck()
  const live = S.B.rows.filter(r => ["queued", "reading", "splitting"].includes(r.state) && r.job);
  if (!live.length) return;
  try {
    const j = await call("/api/jobs?ids=" + live.map(r => r.job).join(","));
    const byJob = new Map(S.B.rows.filter(x => x.job).map(x => [x.job, x]));   // audit 2026-10: no O(n²) find on big batches
    for (const job of j.jobs) {
      const r = byJob.get(job.id); if (!r) continue;
      if (r.pdf) {
        addKids(r, job);
        if (job.state === "split") { S.B.rows.splice(S.B.rows.indexOf(r), 1); toast(`${r.file.split("/").pop()}: ${plural(r.kids || 0, "card")} found.` + (job.note ? " " + job.note : ""), 6000); }
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
    const fin = S.B.rows.filter(r => ["done", "err"].includes(r.state) && r.job).length;
    if (!S.B.t0) S.B.t0 = Date.now() / 1000;
    S.B.ahead = j.queue_ahead || 0;
    S.B.avg = fin ? (Date.now() / 1000 - S.B.t0) / fin : (j.avg_seconds ? j.avg_seconds * Math.max(1, S.B.rows.filter(r => r.state === "queued").length) / Math.max(1, S.B.rows.length) : null);
    saveB(); renderBatch();
    if (j.jobs.some(x => x.state === "done" || x.state === "error")) { refreshCounts(); if (!$("#v-queue").hidden && Q.batch && Q.batch === S.B.id) loadQueue(); }   // round 15: newly read cards of the batch shown appear without a reload
  } catch (e) { if (e instanceof TypeError) conn(false); }   // network error: say "Reconnecting…" and keep trying
  pollT = setTimeout(poll, document.hidden ? 5000 : 1200);   // audit 2026-10: slower while the tab is hidden
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
  if ($("#batchCur")) $("#batchCur").textContent = S.B && S.B.rows.length ? "Now: " + S.B.label : "";   // v0.4.2 #5: the batch name first, not under More
  if (!S.B || !S.B.rows.length) { $("#batch").hidden = true; return; }
  $("#batch").hidden = false; $("#batchTitle").textContent = "Batch: " + S.B.label;
  // audit 2026-10: the list was rebuilt on every 1.2 s poll (all images, focus lost); now only changed rows are touched
  { const ul = $("#batchList"), old = new Map([...ul.children].map(li => [li.dataset.k, li])); let prev = null;
    for (const r of S.B.rows) {
      let li = old.get(r.key); old.delete(r.key);
      if (!li) { li = document.createElement("li"); li.dataset.k = r.key; }
      const h = rowHTML(r), c = ["rej", "dup", "err", "cancel"].includes(r.state) ? "rej" : "";
      if (li._h !== h) { li.innerHTML = h; li._h = h; } if (li.className !== c) li.className = c;
      const at = prev ? prev.nextSibling : ul.firstChild; if (at !== li) ul.insertBefore(li, at); prev = li;
    }
    old.forEach(li => li.remove()); }
  // round 20 (d): cancelled cards are not "finished"; they are counted on their own
  const cn = S.B.rows.filter(r => r.state === "cancel").length, n = S.B.rows.length - cn, fin = S.B.rows.filter(r => ["done", "rej", "dup", "err"].includes(r.state)).length;
  const ok = S.B.rows.filter(r => r.state === "done").length, bad = fin - ok, chk = S.B.rows.filter(r => r.state === "done" && r.card.att.length).length;
  const p = n ? Math.round(100 * fin / n) : 100; $("#batchBar div").style.width = p + "%"; $("#batchBar").setAttribute("aria-valuenow", p);
  const sum_ = S.B.stopMsg ? S.B.stopMsg.replace(/\.$/, "") : (S.B.stopped && fin === n ? `Stopped. ${ok} kept, ${cn} not scanned` : `${fin} of ${n} finished · ${ok} added`) + (chk && !S.B.stopped ? ` (${chk} to check)` : "") + (bad ? ` · ${bad} not added` : "") + (cn && !(S.B.stopped && fin === n) ? ` · ${cn} not scanned` : "");
  if ($("#batchSummary").textContent !== sum_) $("#batchSummary").textContent = sum_;   // audit 2026-10: a live region: only real changes
  const left = n - fin;
  const qa = left ? (S.B.ahead || 0) : 0;   // round 14: other people's cards waiting ahead in the shared reading line count too
  const etaS = (left + qa) * (S.B.avg || 0), etaTxt = etaS < 60 ? "less than a minute left" : `about ${Math.round(etaS / 60)} min left`;   // round 15 (part-timer r14): no "1 min left (≈1 s per card)"
  // round 22: when other people's cards are in line, say how many are ahead instead of a time guess
  $("#batchEta").textContent = left && qa ? `Reading… ${qa} ahead of you.` : left && S.B.avg ? `Reading… ${etaTxt}.` : left ? "Reading photos…" : "";
  $("#batchLegend").hidden = !fin; $("#toQueue").hidden = !ok; $("#toQueue").href = `#queue?batch=${encodeURIComponent(S.B.id)}&s=pending`;
  $("#clearBatch").hidden = fin !== n; $("#cancelBatch").hidden = fin === n || !!S.B.stopped;
}
$("#batchList").addEventListener("click", e => { if (S.B && !S.B.t0) S.B.t0 = Date.now() / 1000;
  const rk = e.target.dataset.retry, rr = rk && S.B && S.B.rows.find(x => x.key === rk);   // audit 2026-10: send a failed photo again (it is still in this tab)
  if (rr && rr.blob) { Object.assign(rr, {state: "wait", msg: "", retry: false, job: undefined, tries: 0, csrfTry: 0}); S.B.stopped = false; S.B.stopMsg = ""; upq.push(rr); saveB(); renderBatch(); pumpUploads(); return; }
  const k = e.target.dataset.again; if (!k) return; const r = S.B.rows.find(x => x.key === k); r.msg = ""; upload(r, true); });
// round 19: Cancel stops the cards still waiting (not yet uploaded or in line to be read); cards already added stay.
async function cancelJobs(rows) {
  const ids = rows.filter(r => ["queued", "splitting", "reading"].includes(r.state) && r.job).map(r => r.job); if (!ids.length) return 0;
  try { await post("/api/jobs/cancel", {ids, batch: S.B.id, batch_label: S.B.label}); } catch {}
  await poll(); return ids.length;
}
$("#cancelBatch").onclick = async () => {
  if (!S.B) return;
  for (let i = upq.length - 1; i >= 0; i--) if (S.B.rows.includes(upq[i])) { upq[i].state = "cancel"; upq.splice(i, 1); }
  S.B.rows.filter(r => r.state === "up").forEach(r => { r.stop = true; try { r.xhr && r.xhr.abort(); } catch {} });   // round 21 (part-timer r20): truthful Cancel
  S.B.rows.filter(r => r.state === "wait").forEach(r => { r.state = "cancel"; r.msg = ""; });
  await cancelJobs(S.B.rows); S.B.stopped = true;
  let kept = null;
  // round 23 (skeptic/part-timer r22): the server waits until nothing of THIS upload is still being read, then counts the
  // cards this upload made (not the whole batch). That one number is the final truth for the toast and the list.
  const sess = S.B.rows.map(r => r.job).filter(Boolean);
  try { const x = await post("/api/jobs/cancel", {ids: [], session: sess, batch: S.B.id, batch_label: S.B.label, all_waiting: true}); kept = x.kept; await poll(); } catch {}
  for (let i = 0; i < 20 && S.B.rows.some(r => r.state === "reading"); i++) { await new Promise(res => setTimeout(res, 500)); await poll(); }
  S.B.rows.filter(r => r.state === "cancel").forEach(r => r.msg = "");   // round 20 (d): no leftover status text
  saveB(); renderBatch();
  const ok = typeof kept === "number" ? kept : S.B.rows.filter(r => r.state === "done").length;
  S.B.rows.filter(r => !["done", "cancel", "error", "dup", "skip"].includes(r.state)).forEach(r => { r.state = "cancel"; r.msg = ""; });   // nothing is left 'reading' on screen
  const cn = S.B.rows.filter(r => r.state === "cancel").length; S.B.stopMsg = `Stopped. ${ok} kept, ${cn} not scanned.`; saveB(); renderBatch();
  toast(S.B.stopMsg, 4500);
};
$("#clearBatch").onclick = () => { if (S.B) S.B.rows.forEach(dropThumb); S.B = null; SS.removeItem("batch"); $("#batchName").value = ""; renderBatch(); $("#clearBatch").dataset.fresh = "1"; toast("Ready for a new batch."); };
function restoreBatch() {
  // v0.4.2 #12: after a reload a photo that was still waiting is no longer in the page (its file is gone): say so, never "Waiting" forever
  if (S.B) S.B.rows.forEach(r => { if (r.state === "wait" && !r.blob) { r.state = "rej"; r.msg = "Not sent before the page reloaded. Add this photo again."; } });
  renderBatch(); poll(); refreshBatchCards(); }
// v0.4.2 #12: a watchdog: a photo waiting with nothing uploading and nothing queued is sent again
setInterval(() => { if (AUTH_PAUSED || uploading || upq.length || !S.B) return;
  const w = S.B.rows.filter(r => r.state === "wait" && r.blob && !r.stop && !r.backoff); if (w.length) { upq.push(...w); pumpUploads(); } }, 5000);
async function refreshBatchCards() {   // reviewer r9: the upload list shows each card's CURRENT state, not the one at scan time
  try { const rows = (S.B.rows || []).filter(r => r.state === "done" && r.card); if (!rows.length) return;
    const by = new Map((await call("/api/cards?batch=" + encodeURIComponent(S.B.id))).map(c => [c.id, c]));   // round 15: only this batch (fast)
    const before = JSON.stringify(rows.map(r => r.card));
    rows.forEach(r => { const c = by.get(r.card.id); if (!c) return; r.card.att = (c.attention || []).map(a => a.text); r.card.status = c.status; r.card.blocked = !!c.blocked; r.card.name = c.name || r.card.name; });
    if (JSON.stringify(rows.map(r => r.card)) !== before) { saveB(); renderBatch(); } } catch {}
}
window.gacBusy = upPending;   // v0.4.2 #2: no idle sign-out while photos are still uploading
export {authPause, enqueue, refreshBatchCards, restoreBatch, upPending};
