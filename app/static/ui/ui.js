"use strict";
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const SS = sessionStorage;
try { localStorage.removeItem("reviewer"); } catch {}
const toast = (m, ms = 2600, undo = false) => { const t = $("#toast"); t.textContent = m;
  if (undo) { const b = document.createElement("button"); b.className = "toastbtn"; b.textContent = "Undo"; b.onclick = () => doUndo(); t.append(b); ms = Math.max(ms, 6000); }
  t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms); refreshUndo(); };
const csrf = () => (document.cookie.match(/(?:^|; )gac_csrf=([^;]*)/) || [])[1] || "";
function saveDraft() { if (dirty && cur) try { SS.draft = JSON.stringify({id: cur.id, vals: dirtyVals()}); } catch {} }
async function call(u, o = {}) {
  if (o.method && o.method !== "GET") o.headers = {...(o.headers || {}), "X-CSRF-Token": csrf()};
  const r = await fetch(u, o); let j = null; try { j = await r.json(); } catch {}
  const uid = r.headers.get("X-GAC-User");
  if (ME && uid && uid !== String(ME.id) && !$("#swapWarn")) {   // another tab signed this browser in as someone else
    document.body.insertAdjacentHTML("afterbegin", `<div id="swapWarn" class="alert bad" role="alert">This browser is now signed in as a <b>different person</b> (someone signed in in another tab or window). Your next actions would be recorded under their name. <a href="/ui">Reload</a> to continue as them, or sign out and sign in again. Tip: use a separate browser profile per person.</div>`);
  }
  if (r.status === 401) { saveDraft(); dirty = false; location.href = "/login?next=" + encodeURIComponent("/ui" + location.hash); throw new Error("Please sign in."); }
  if (!r.ok) { const e = new Error((j && (j.error || j.detail)) || ("Server error " + r.status)); e.status = r.status; e.data = j || {}; throw e; }
  return j;
}
const post = (u, b) => call(u, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(b)});
async function busy(btn, label, fn) {
  if (btn.getAttribute("aria-busy") === "true") return;
  const old = btn.innerHTML; btn._old = old; btn.setAttribute("aria-busy", "true"); btn.disabled = true; btn.innerHTML = label;
  try { return await fn(); } finally { btn.removeAttribute("aria-busy"); btn.disabled = false; btn.innerHTML = old; }
}
const LABEL = {name: "Name", title: "Job title", company: "Company", emails: "Email", phones: "Phone", website: "Website", address: "Address", department: "Department", other_address: "Other address", credentials: "Credentials (e.g. CPA, PhD)"};
const when = t => t ? new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "";

/* ---------- dialog helper ---------- */
function ask({title, html = "", input = null, buttons}) {
  $$('[aria-busy="true"]').forEach(b => { if (b._old !== undefined) { b.innerHTML = b._old; b.removeAttribute("aria-busy"); } });   // no spinner behind a question
  const d = $("#dlg"); $("#dlgTitle").textContent = title; $("#dlgBody").innerHTML = html; $("#dlgErr").textContent = "";
  $("#dlgInputWrap").hidden = !input;
  if (input) { $("#dlgInputLabel").textContent = input.label; $("#dlgInput").value = input.value || ""; $("#dlgInput").placeholder = input.placeholder || ""; $("#dlgInput").maxLength = input.max || 200; $("#dlgInput").type = input.type || "text"; }
  $("#dlgBtns").innerHTML = buttons.map((b, i) => `<button type="button" class="btn ${b.cls || ""}" data-i="${i}">${esc(b.label)}</button>`).join("");
  return new Promise(res => {
    const done = v => { d.close(); res(v); };
    $$("#dlgBtns button").forEach(el => el.onclick = () => {
      const b = buttons[+el.dataset.i], val = $("#dlgInput").value.trim();
      if (b.needInput && input && !val) { $("#dlgErr").textContent = input.required || "Please fill this in."; $("#dlgInput").focus(); return; }
      done({value: b.value, input: val});
    });
    d.oncancel = e => { e.preventDefault(); done({value: null}); };
    $("#dlgForm").onsubmit = e => { e.preventDefault(); const p = buttons.find(b => b.primary); if (p) $(`#dlgBtns [data-i="${buttons.indexOf(p)}"]`).click(); };
    d.showModal(); (input ? $("#dlgInput") : $("#dlgBtns button")).focus();
  });
}

/* ---------- signed-in user ---------- */
let ME = null;
const who = () => ME ? ME.initials : "";
const needWho = async () => true;
async function loadMe() {
  ME = await call("/api/me");
  $("#whoText").innerHTML = `Signed in as <b>${esc(ME.display)}</b> (${esc(ME.initials)})`;
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
$("#logout").onclick = async () => { await post("/api/auth/logout", {}); location.href = "/login"; };
$("#dlgInput").type = "text";
/* ---------- undo ---------- */
async function refreshUndo() { try { const u = await call("/api/undo"); $("#undoBtn").hidden = !u.id; $("#undoBtn").title = u.id ? "Undo: " + u.label + " (U)" : ""; $("#undoBtn").dataset.label = u.label || ""; } catch {} }
async function doUndo() {
  try { const r = await post("/api/undo", {}); toast("Undone: " + r.undone); refreshCounts();
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
  if (view === "queue") { applyQueueState(q); loadQueue(); }
  if (view === "review") openCard(+id);
  if (view === "export") exportInfo();
  if (view === "upload") restoreBatch();
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
addEventListener("hashchange", route);

/* ---------- upload / batch ---------- */
const drop = $("#drop");
if (matchMedia("(pointer: coarse)").matches && !matchMedia("(hover: hover)").matches) {   // phones/tablets: there is no drag and drop
  $("#dropHead").textContent = "Add card photos"; $("#dropHelp").textContent = "Take a photo or choose photos below. JPG or PNG, one card per photo.";
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
function newBatch() {
  const d = new Date(), id = "B" + d.toISOString().replace(/\D/g, "").slice(0, 14);
  const name = $("#batchName").value.trim();
  const mon = d.toLocaleString([], {month: "short"}), hasDate = name && new RegExp(`\\b${mon}\\w*\\.?\\s*${d.getDate()}\\b|\\b${d.getMonth() + 1}/${d.getDate()}\\b`, "i").test(name);
  const stamp = d.toLocaleString([], hasDate ? {hour: "numeric", minute: "2-digit"} : {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  const same = name && (BATCHES || []).find(b => (b.batch_label || "").split(" · ")[0].toLowerCase() === name.toLowerCase() && b.started > Date.now() / 1000 - 12 * 3600);
  if (same) { B = {id: same.batch, label: same.batch_label, rows: [], t0: Date.now() / 1000}; saveB(); toast(`Added to your existing batch “${name}”.`); return; }
  const label = (name ? name + " · " : "") + stamp + (who() ? " · " + who() : "");
  B = {id, label, rows: [], t0: Date.now() / 1000}; saveB();
}
const isImg = f => /^image\//.test(f.type) || /\.(jpe?g|png|webp|gif|bmp|tiff?)$/i.test(f.name);
function enqueue(files) {
  if (!files.length) { toast("Nothing was selected."); return; }
  if (!B || B.rows.every(r => ["done", "rej", "err"].includes(r.state)) && $("#clearBatch").dataset.fresh === "1") newBatch();
  if (!B) newBatch();
  $("#clearBatch").dataset.fresh = "0";
  for (const f of files) {
    const row = {key: Math.random().toString(36).slice(2), file: f.webkitRelativePath || f.name, state: "wait"};
    if (/(^|\/)\./.test(row.file)) continue;              // hidden system files in folders
    if (!isImg(f)) { row.state = "rej"; row.msg = "Not a photo (only JPG/PNG images can be scanned)."; }
    else if (!f.size) { row.state = "rej"; row.msg = "File is empty."; }
    else { row.blob = f; row.thumb = URL.createObjectURL(f); upq.push(row); }
    B.rows.push(row);
  }
  saveB(); renderBatch(); pumpUploads();
}
function pumpUploads() {
  while (uploading < UPCONC && upq.length) { const r = upq.shift(); uploading++; upload(r).finally(() => { uploading--; pumpUploads(); }); }
}
function upload(row, allowDup = false) {
  return new Promise(res => {
    const fd = new FormData(); fd.append("image", row.blob, row.file.split("/").pop());
    fd.append("engine", $("#engine").value); fd.append("batch", B.id); fd.append("batch_label", B.label);
    if (allowDup) fd.append("allow_duplicate", "1");
    const x = new XMLHttpRequest(); x.open("POST", "/api/jobs"); x.setRequestHeader("X-CSRF-Token", csrf());
    row.state = "up"; row.pct = 0; renderBatch();
    x.upload.onprogress = e => { if (e.lengthComputable) { row.pct = Math.round(100 * e.loaded / e.total); renderRow(row); } };
    x.onload = () => {
      let j = {}; try { j = JSON.parse(x.responseText); } catch {}
      if (x.status === 200) { row.state = "queued"; row.job = j.job; }
      else if (x.status === 409) { row.state = "dup"; row.msg = j.error; row.dupOf = j.duplicate_of; }
      else { row.state = "rej"; row.msg = j.error || "Upload failed (" + x.status + ")."; if (x.status === 401) saveB(); }
      saveB(); renderBatch(); poll(); res();
    };
    x.onerror = () => { row.state = "err"; row.msg = "Connection to the scanner was lost. Is the scanner window still open?"; saveB(); renderBatch(); res(); };
    x.send(fd);
  });
}
let pollT = null;
async function poll() {
  clearTimeout(pollT);
  if (!B) return;
  const live = B.rows.filter(r => ["queued", "reading"].includes(r.state) && r.job);
  if (!live.length) return;
  try {
    const j = await call("/api/jobs?ids=" + live.map(r => r.job).join(","));
    for (const job of j.jobs) {
      const r = B.rows.find(x => x.job === job.id); if (!r) continue;
      if (job.state === "done") { r.state = "done"; r.card = {id: job.card.id, name: job.card.name || job.card.company || "(no name)", att: job.card.attention.map(a => a.text)}; }
      else if (job.state === "error") { r.state = "err"; r.msg = job.error; }
      else r.state = job.state;
    }
    const known = new Set(j.jobs.map(x => x.id));
    live.filter(r => !known.has(r.job)).forEach(r => { r.state = "err"; r.msg = "Lost track of this upload (the scanner was restarted). Please add it again."; });
    const fin = B.rows.filter(r => ["done", "err"].includes(r.state) && r.job).length;
    if (!B.t0) B.t0 = Date.now() / 1000;
    B.avg = fin ? (Date.now() / 1000 - B.t0) / fin : (j.avg_seconds ? j.avg_seconds * Math.max(1, B.rows.filter(r => r.state === "queued").length) / Math.max(1, B.rows.length) : null);
    saveB(); renderBatch();
    if (j.jobs.some(x => x.state === "done" || x.state === "error")) refreshCounts();
  } catch {}
  pollT = setTimeout(poll, 1200);
}
const ST = {wait: "Waiting to upload", up: "Uploading…", queued: "In line to be read", reading: "Reading card…", done: "Added", rej: "Not added", dup: "Not added", err: "Failed"};
function rowHTML(r) {
  const pct = {wait: 0, up: Math.round((r.pct || 0) * .3), queued: 35, reading: 65, done: 100, rej: 100, dup: 100, err: 100}[r.state];
  let st = esc(ST[r.state]), cls = {done: "done", rej: "err", dup: "err", err: "err"}[r.state] || "work";
  if (r.state === "done") st = `<a href="#review/${r.card.id}">✓ ${esc(r.card.name)} (#${r.card.id})</a> ` + (r.card.att.length ? `<span class="flag low" title="${esc(r.card.att.join("; "))}">Check</span>` : `<span class="flag ok">Looks good</span>`);
  if (r.msg) st += `<span class="why">${esc(r.msg)}</span>`;
  if (r.state === "dup") st += ` <span class="why">${r.dupOf ? `<a href="#review/${r.dupOf}">Open card #${r.dupOf}</a> · ` : ""}${r.blob ? `<button type="button" class="link" data-again="${r.key}">Scan it anyway</button>` : ""}</span>`;
  const th = r.thumb && r.state !== "rej" ? `<img alt="" src="${r.thumb}">` : `<span class="thumbph" aria-hidden="true">${r.state === "rej" ? "✕" : "▢"}</span>`;
  return `${th}<div><div class="nm">${esc(r.file)}</div><div class="progress mini" aria-hidden="true"><div style="width:${pct}%"></div></div></div><span class="st ${cls}">${st}</span>`;
}
function renderRow(r) { const li = document.querySelector(`li[data-k="${r.key}"]`); if (li) li.innerHTML = rowHTML(r); }
function renderBatch() {
  if (!B || !B.rows.length) { $("#batch").hidden = true; return; }
  $("#batch").hidden = false; $("#batchTitle").textContent = "Batch: " + B.label;
  $("#batchList").innerHTML = B.rows.map(r => `<li data-k="${r.key}" class="${["rej", "dup", "err"].includes(r.state) ? "rej" : ""}">${rowHTML(r)}</li>`).join("");
  const n = B.rows.length, fin = B.rows.filter(r => ["done", "rej", "dup", "err"].includes(r.state)).length;
  const ok = B.rows.filter(r => r.state === "done").length, bad = fin - ok, chk = B.rows.filter(r => r.state === "done" && r.card.att.length).length;
  const p = Math.round(100 * fin / n); $("#batchBar div").style.width = p + "%"; $("#batchBar").setAttribute("aria-valuenow", p);
  $("#batchSummary").textContent = `${fin} of ${n} finished · ${ok} added` + (chk ? ` (${chk} to check)` : "") + (bad ? ` · ${bad} not added` : "");
  const left = n - fin;
  $("#batchEta").textContent = left && B.avg ? `About ${Math.max(1, Math.round(left * B.avg / 60))} min left (≈${Math.round(B.avg)} s per card). You can keep reviewing other cards meanwhile.` : left ? "Working it out… (cards are read one at a time; with other people scanning it can take 5–30 s per card)." : "";
  $("#batchLegend").hidden = !fin; $("#toQueue").hidden = !ok; $("#toQueue").href = `#queue?batch=${encodeURIComponent(B.id)}&s=pending`;
  $("#clearBatch").hidden = fin !== n;
}
$("#batchList").addEventListener("click", e => { if (B && !B.t0) B.t0 = Date.now() / 1000; const k = e.target.dataset.again; if (!k) return; const r = B.rows.find(x => x.key === k); r.msg = ""; upload(r, true); });
$("#clearBatch").onclick = () => { B = null; SS.removeItem("batch"); $("#batchName").value = ""; renderBatch(); $("#clearBatch").dataset.fresh = "1"; toast("Ready for a new batch."); };
function restoreBatch() { renderBatch(); poll(); }

/* ---------- queue ---------- */
const Q = {s: "pending", batch: "", att: false, dup: false, nx: false, text: "", arch: false, cards: [], sel: new Set()};
function applyQueueState(q) {
  if (q.has("s")) Q.s = q.get("s") === "all" ? "" : q.get("s");
  Q.batch = q.get("batch") || "";   // the batch filter applies only when the link asks for it (Queue in the menu shows everything)
  Q.att = q.get("att") === "1"; Q.nx = q.get("nx") === "1"; Q.dup = q.get("dup") === "1"; Q.text = q.get("q") || ""; Q.arch = q.get("arch") === "1";
  $$("#statusTabs button").forEach(x => x.setAttribute("aria-selected", x.dataset.s === Q.s));
  $("#fAtt").checked = Q.att; $("#fNew").checked = Q.nx; $("#fDup").checked = Q.dup; $("#fText").value = Q.text; $("#fArch").checked = Q.arch;
}
function pushQueueState() {
  const p = new URLSearchParams(); p.set("s", Q.s); if (Q.batch) p.set("batch", Q.batch); if (Q.att) p.set("att", "1"); if (Q.nx) p.set("nx", "1"); if (Q.dup) p.set("dup", "1"); if (Q.text) p.set("q", Q.text); if (Q.arch) p.set("arch", "1");
  history.replaceState(null, "", "#queue?" + p); SS.queueHash = "#queue?" + p;
}
$$("#statusTabs button").forEach(b => b.onclick = () => { Q.s = b.dataset.s; $$("#statusTabs button").forEach(x => x.setAttribute("aria-selected", x === b)); Q.sel.clear(); pushQueueState(); loadQueue(); });
$("#fAtt").onchange = e => { Q.att = e.target.checked; pushQueueState(); renderQueue(); };
$("#fNew").onchange = e => { Q.nx = e.target.checked; pushQueueState(); renderQueue(); };
$("#fDup").onchange = e => { Q.dup = e.target.checked; pushQueueState(); renderQueue(); };
$("#fArch").onchange = e => { Q.arch = e.target.checked; Q.sel.clear(); pushQueueState(); loadQueue(); };
$("#fText").oninput = e => { Q.text = e.target.value; pushQueueState(); renderQueue(); };
$("#fBatch").onchange = e => { Q.batch = e.target.value; SS.lastBatch = Q.batch; Q.sel.clear(); pushQueueState(); renderQueue(); };
function filterBatchOptions() {   // the batch list gets long: type to narrow it
  const t = ($("#fBatchQ") && $("#fBatchQ").value || "").toLowerCase().trim();
  $$("#fBatch option").forEach(o => o.hidden = !!t && o.value !== "" && o.value !== Q.batch && !o.textContent.toLowerCase().includes(t));
}
$("#fBatchQ") && ($("#fBatchQ").oninput = filterBatchOptions);
async function refreshCounts() {
  try {
    const all = await call("/api/cards"); const c = {pending: 0, approved: 0, rejected: 0, "": all.length};
    all.forEach(x => c[x.status]++);
    if ($("#v-queue").hidden || !Q.batch) $$("#statusTabs button").forEach(b => b.querySelector("span").textContent = `(${c[b.dataset.s]})`);
    const inB = Q.batch ? all.filter(x => Q.batch === "__none__" ? !x.batch : x.batch === Q.batch) : all, np = inB.filter(x => x.status === "pending").length;
    const pb = $("#pendingBadge"); pb.hidden = !c.pending; pb.textContent = c.pending;
    pb.setAttribute("aria-label", c.pending + " pending (all users)" + (Q.batch ? `, ${np} in the selected batch` : "")); pb.title = "Pending cards from everyone" + (Q.batch ? ` (${np} in the selected batch)` : "");
    STATUS = Object.fromEntries(all.map(x => [x.id, x.status]));
    return all;
  } catch { return []; }
}
let qSeq = 0, STATUS = {};
async function loadQueue() {
  const seq = ++qSeq; $("#qLoading").hidden = false; $("#qEmpty").hidden = true;
  try {
    const [cards, batches] = await Promise.all([call("/api/cards" + (Q.arch ? "?archived=true" : "")), call("/api/batches")]);
    if (seq !== qSeq) return;
    Q.cards = cards;
    $("#fBatch").innerHTML = `<option value="">All batches</option>` + batches.map(b => `<option value="${esc(b.batch)}">${esc(b.batch_label || b.batch)} (${b.n})</option>`).join("");
    BATCHES = batches;
    if (Q.batch && !batches.some(b => b.batch === Q.batch)) $("#fBatch").insertAdjacentHTML("beforeend", `<option value="${esc(Q.batch)}">(selected batch, now empty)</option>`);
    $("#fBatch").value = Q.batch; filterBatchOptions();
    renderQueue(); refreshCounts();
  } catch (e) { $("#qEmpty").hidden = false; $("#qEmpty").textContent = "Couldn't load cards: " + e.message + ". Is the scanner window still open?"; }
  finally { if (seq === qSeq) $("#qLoading").hidden = true; }
}
function filtered() {
  const raw = Q.text.toLowerCase().trim(), idOnly = /^#\d+$/.test(raw), q = raw.replace(/^#/, "");
  return Q.cards.filter(c => (!Q.s || c.status === Q.s) && (!Q.batch || (Q.batch === "__none__" ? !c.batch : c.batch === Q.batch)) &&
    (!Q.att || c.needs_attention) && (!Q.nx || !c.exported) && (!Q.dup || c.dup) &&
    (!q || String(c.id) === q || !idOnly && [c.name, c.company, c.email, c.filename].join(" ").toLowerCase().includes(q)));
}
function confBar(v) { if (v == null) return "–"; const p = Math.round(v * 100), col = v < .6 ? "#e8a33a" : v < .8 ? "#388a9c" : "#1e7a3c";
  return `<span class="cbar" aria-hidden="true"><i style="width:${p}%;background:${col}"></i></span>${p}%`; }
function aiBadge(c) {
  const s = c.ai_status, d = c.ai_detail || {};
  if (s === "queued" || s === "checking") return ' <span class="pill ai busy">AI checking…</span>';
  if (s === "checked") return ` <span class="pill ai" title="${d.changed && d.changed.length ? "AI corrected: " + esc(d.changed.map(k => LABEL[k] || k).join(", ")) : "AI found nothing to change"}">AI-checked${d.changed && d.changed.length ? " ✎" + d.changed.length : ""}</span>`;
  if (s === "suggested") return ' <span class="pill ai">AI suggestions</span>';
  return "";
}
let qPoll = null;
function scheduleQueuePoll() {
  clearTimeout(qPoll);
  if (Q.cards.some(c => c.ai_status === "queued" || c.ai_status === "checking"))
    qPoll = setTimeout(async () => { if ($("#v-queue").hidden) return; try { const cs = await call("/api/cards" + (Q.arch ? "?archived=true" : "")); Q.cards = cs; renderQueue(); } catch {} }, 5000);
}
function renderQueue() {
  const rows = filtered(); SS.order = JSON.stringify(rows.map(c => c.id)); SS.queueHash = location.hash.startsWith("#queue") ? location.hash : (SS.queueHash || "#queue");
  $("#qBody").innerHTML = rows.map(c => `<tr data-id="${c.id}">
    <td><input type="checkbox" class="sel" aria-label="Select card #${c.id} ${esc(c.name)}" ${Q.sel.has(c.id) ? "checked" : ""}></td>
    <td><img src="/img/${esc(c.image)}?w=160" alt="" loading="lazy" decoding="async"></td>
    <td><a href="#review/${c.id}">${esc(c.name) || "<em>(no name)</em>"}</a><div class="sub">#${c.id}${c.qr ? ' <span class="src qr">QR</span>' : ""}${c.batch_label ? " · " + esc(c.batch_label) : ""}</div></td>
    <td>${esc(c.company)}</td><td>${esc(c.email)}</td><td>${confBar(c.conf)}</td>
    <td class="att">${c.attention.length ? `<ul class="reasons">${c.attention.map(a => `<li><span class="flag ${a.code.startsWith("dup") ? "dup" : a.code === "invalid" ? "bad" : "low"}">${esc(a.text)}</span></li>`).join("")}</ul>` : `<span class="flag ok">Looks good</span>`}</td>
    <td><span class="pill ${c.status}">${c.status}</span>${c.archived ? ' <span class="pill archived">archived</span>' : ""}${c.exported ? ` <span class="pill archived" title="First exported ${esc(when(c.exported))}">exported</span>` : ""}${aiBadge(c)}${c.reviewer ? `<div class="sub">by ${esc(c.reviewer)}</div>` : ""}</td></tr>`).join("");
  const anyFilter = Q.att || Q.nx || Q.dup || Q.text || Q.batch;
  $("#qEmpty").hidden = rows.length > 0;
  $("#qEmpty").textContent = Q.cards.length ? (anyFilter ? "No cards match these filters. " : `No ${({pending: "pending", approved: "approved", rejected: "rejected"})[Q.s] || ""} cards. `.replace("  ", " ")) + "Try the “All” tab or clear the filters." : "No cards yet. Go to “Scan cards” to add some.";
  $("#archiveBatch").disabled = !Q.batch || Q.arch; $("#selAll").checked = false; syncSel(); scheduleQueuePoll();
  const inB = Q.cards.filter(c => !Q.batch || (Q.batch === "__none__" ? !c.batch : c.batch === Q.batch)), cnt = {pending: 0, approved: 0, rejected: 0, "": inB.length};
  inB.forEach(c => cnt[c.status]++); $$("#statusTabs button").forEach(b => b.querySelector("span").textContent = `(${cnt[b.dataset.s]})`);

}
$("#qBody").addEventListener("click", e => {
  const tr = e.target.closest("tr"); if (!tr) return; const id = +tr.dataset.id;
  if (e.target.classList.contains("sel")) { e.target.checked ? Q.sel.add(id) : Q.sel.delete(id); syncSel(); return; }
  if (e.target.tagName !== "A") location.hash = "review/" + id;
});
$("#selAll").onchange = e => { filtered().forEach(c => e.target.checked ? Q.sel.add(c.id) : Q.sel.delete(c.id)); $$("#qBody .sel").forEach(x => x.checked = e.target.checked); syncSel(); };
function syncSel() { const n = Q.sel.size; $("#bulkApprove").disabled = $("#bulkReject").disabled = !n;
  $("#bulkApprove").textContent = n ? `Approve selected (${n})` : "Approve selected"; $("#bulkReject").textContent = n ? `Reject selected (${n})` : "Reject selected"; }
async function bulk(status, btn) {
  const ids = [...Q.sel]; if (!ids.length || !await needWho()) return;
  const sel = Q.cards.filter(c => Q.sel.has(c.id)), decided = sel.filter(c => c.status !== "pending" && c.status !== status);
  const verb = status === "approved" ? "Approve" : "Reject";
  const r = await ask({title: `${verb} ${ids.length} card(s)?`, html: `<p>As reviewer <b>${esc(who())}</b>.</p>` +
      (status === "approved" ? "<p class='small'>Cards with missing/invalid fields or possible duplicates are skipped; open them to resolve.</p>" : "") +
      (decided.length ? `<p class="alert">${decided.length} of these were already decided (${decided.map(c => "#" + c.id + " " + c.status).join(", ")}). Change them too?</p>` : ""),
    buttons: [{label: verb, cls: status === "approved" ? "ok" : "danger", value: "go", primary: true}, ...(decided.length ? [{label: `${verb}, but leave already-decided cards alone`, value: "pendingonly"}] : []), {label: "Cancel", value: null}]});
  if (!r.value) return;
  await busy(btn, "Working…", async () => {
    try {
      const res = await post("/api/cards-bulk", {ids, status, reviewer: who(), confirm_redecide: r.value === "go"});
      Q.sel.clear(); await loadQueue();
      const msg = `${res.updated.length} card(s) ${status}.` + (res.skipped.length ? ` ${res.skipped.length} skipped: ` + res.skipped.map(s => `#${s.id} (${s.why})`).join(", ") : "");
      res.skipped.length ? await ask({title: "Done, with some cards skipped", html: `<p>${esc(msg)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}) : toast(msg, 2600, res.updated.length > 0); refreshUndo();
    } catch (e) { toast("Not saved: " + e.message, 5000); }
  });
  syncSel();   // busy() restored the old label ("… (3)"); show the real count
}
$("#bulkApprove").onclick = e => bulk("approved", e.currentTarget); $("#bulkReject").onclick = e => bulk("rejected", e.currentTarget);
$("#archiveBatch").onclick = async e => { const btn = e.currentTarget;
  const opt = $("#fBatch").selectedOptions[0]; if (!Q.batch || !await needWho()) return;
  const r = await ask({title: "Archive this batch?", html: `<p><b>${esc(opt.textContent)}</b> will be hidden from the queue and from exports. Nothing is deleted; tick “Show archived cards” to see it again.</p>`,
    buttons: [{label: "Archive batch", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return;
  await busy(btn, "Archiving…", async () => { const x = await post("/api/batches/archive", {batch: Q.batch, reviewer: who()}); Q.batch = ""; pushQueueState(); toast(`${x.archived} card(s) archived.`, 2600, x.archived > 0); await loadQueue(); });
};
$("#archiveAll").onclick = async e => { const btn = e.currentTarget;
  if (!await needWho()) return;
  const r = await ask({title: "Archive all test data?", html: "<p>This <b>archives</b> (it does not delete) every card currently in the queue, all statuses: they are hidden from the queue and exports but kept in the database, and Undo brings them back.</p>",
    input: {label: "Type CLEAR to confirm", required: "Type CLEAR to confirm."}, buttons: [{label: "Archive everything", cls: "danger", value: 1, needInput: true, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return; if (r.input.trim() !== "CLEAR") { toast("Not cleared: you didn't type CLEAR."); return; }
  await busy(btn, "Clearing…", async () => { const x = await post("/api/batches/archive", {batch: "__all__", confirm: "CLEAR", reviewer: who()}); toast(`${x.archived} card(s) archived. The review queue is now empty.`, 2600, x.archived > 0); await loadQueue(); });
};

/* ---------- review ---------- */
let cur = null;
const order = () => { try { return JSON.parse(SS.order || "[]"); } catch { return []; } };
function dirtyVals() { const o = {}; dirtyIds.forEach(i => { const el = document.getElementById(i); if (el) o[i] = el.value; }); return o; }
async function openCard(id, opts = {}) {
  const keep = opts.keep && cur && cur.id === id && dirty ? dirtyVals() : null;
  let d; try { d = await call("/api/cards/" + id); } catch { toast("Card not found."); location.hash = SS.queueHash || "queue"; return; }
  if (!cur || cur.id !== d.id) scrollTo(0, 0);
  cur = d; const c = d.card, f = c.fields, k = f.confidence || {};
  $("#rImg").src = $("#zImg").src = "/img/" + c.image; $("#rawLink").href = "/img/" + c.image;
  $("#rRaw").textContent = c.raw_text || "";
  $("#rImg").alt = d.image_deleted ? "Photo deleted by the retention policy" : "Photo of the business card";
  $("#rBatch").textContent = d.batch_label ? "Batch: " + d.batch_label : "";
  $("#h-r").textContent = `Review card #${c.id}`;
  $$(".pager a.ghost").forEach(a => a.href = SS.queueHash || "#queue");   // back to the queue WITH its batch/status filters
  if (!opts.keep) { $("#h-r").tabIndex = -1; $("#h-r").focus({preventScroll: true}); }   // keys (J/K/A/R) work right after a link jump
  $("#rStatus").className = "pill " + c.status; $("#rStatus").textContent = c.status + (d.archived ? " · archived" : "");
  $("#rDecided").textContent = c.status !== "pending" ? `${c.status[0].toUpperCase() + c.status.slice(1)} by ${c.reviewer || "?"} on ${when(c.decided)}` + (c.note ? ` · Note: ${c.note}` : "") : "";
  $("#rConf").innerHTML = "Read confidence " + confBar(f.overall_confidence);
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
  showErrors(d.errors, false);
  renderDupes(d);
  $("#rWarn").hidden = !f.fallback_reason; $("#rWarn").textContent = f.fallback_reason ? "Note: " + f.fallback_reason : "";
  $("#bPending").hidden = c.status === "pending"; $("#bApprove").hidden = c.status !== "pending"; $("#bDelete").hidden = !ME || ME.role !== "admin"; $("#bReject").hidden = c.status === "rejected";
  dirty = false; dirtyIds.clear();
  let restore = keep;
  if (!restore && SS.draft) { try { const dr = JSON.parse(SS.draft); if (dr.id === c.id) { restore = dr.vals; toast("Restored the edits you hadn't saved before you were signed out. Check them and save.", 6000); } } catch {} delete SS.draft; }
  if (restore) Object.entries(restore).forEach(([i, v]) => { const el = document.getElementById(i); if (el) { el.value = v; dirtyIds.add(i); dirty = true; } });
  renderAI(d);
  const cons = d.attention.filter(a => a.code === "consistency");
  $("#rCons").hidden = !cons.length; $("#rCons").innerHTML = cons.length ? `<b>Details that don't agree with each other:</b><ul>${cons.map(a => `<li>${esc(a.text)}</li>`).join("")}</ul>` : "";
  const bi = (d.back_image || ""); $("#backLink").hidden = !bi; $("#backLink").href = bi ? "/img/" + bi : "#";
  $("#rHist").innerHTML = d.history.map(h => `<li>${esc(when(h.ts))} · <b>${esc(h.reviewer || "system")}</b> ${esc(histText(h))}</li>`).join("") || "<li>No history yet.</li>";
  const o = order(), i = o.indexOf(c.id);
  $("#pos").textContent = i >= 0 ? `${i + 1} of ${o.length}` : "";
  $("#prev").disabled = i <= 0; $("#next").disabled = i < 0 || i >= o.length - 1;
}
let dirty = false, rPoll = null; const dirtyIds = new Set();
addEventListener("beforeunload", e => { if (dirty && !$("#v-review").hidden) { saveDraft(); e.preventDefault(); e.returnValue = ""; } });
addEventListener("pageshow", e => { if (e.persisted) location.reload(); });   // never show a cached page after sign-out
let vT = null;
$("#rForm").addEventListener("input", e => { dirty = true; if (e.target.id) dirtyIds.add(e.target.id); clearTimeout(vT);
  if (!$$("#fields .f.err").length && $("#rErr").hidden) return;      // only re-check while problems are shown
  vT = setTimeout(async () => { try { const r = await post("/api/validate", {fields: collect()}); showErrors({...r.errors, ...r.hard}, !$("#rErr").hidden); } catch {} }, 300); });
function renderAI(d) {
  const s = d.ai_status, x = d.ai_detail || {}, box = $("#rAI"); clearTimeout(rPoll);
  const canAsk = d.status === "pending" && !d.image_deleted && !["queued", "checking"].includes(s);
  let h = "";
  if ((s === "queued" || s === "checking") && d.status !== "pending") h = "";
  else if (s === "queued" || s === "checking") {
    const p = d.ai_progress || {}, t0 = s === "checking" ? x.started : x.queued_at, secs = t0 ? Math.max(0, Math.round(Date.now() / 1000 - t0)) : 0;
    const typ = p.busy ? "the AI model is busy with other work right now, so this may take several minutes or time out; you don't need to wait"
              : p.typical_seconds ? `recent checks took about ${p.typical_seconds} s` : "usually under a minute when the model is free";
    h = `<b role="status">AI checking… ${s === "queued" ? (p.ahead ? `waiting: ${p.ahead} card(s) ahead` : "starting") : `running for ${secs} s`} (${typ}).</b> ` +
        `It is double-checking ${esc((x.why || []).map(k => LABEL[k] || k).join(", ") || "this card")}. You can keep working: nothing on the form is changed; you get suggestions to accept or ignore.` +
        `<div class="progress mini" aria-hidden="true"><div style="width:${s === "queued" ? 5 : Math.min(95, Math.round(100 * secs / (p.typical_seconds || 60)))}%"></div></div>`;
  }
  else if (s === "checked") h = x.changed && x.changed.length ? `<b>AI-checked:</b> corrected ${esc(x.changed.map(k => LABEL[k] || k).join(", "))} (please confirm against the photo).` : (Object.keys(x.decided || {}).length ? "<b>AI-checked:</b> all suggestions decided." : "<b>AI-checked:</b> no changes needed.");
  else if (s === "suggested") h = "<b>AI suggestions</b> (nothing on the card is changed until you choose):";
  else if (s === "skipped") h = "AI double-check skipped: " + esc(x.note || "a person reviewed this card first") + ".";
  else if (s === "failed") h = "The AI double-check didn't finish" + (/timeout|timed out/i.test(x.error || "") ? " in time (the computer was busy)" : "") + ". The card is still readable as is; check the fields against the photo, or try again." + (x.error ? ` <span class="small">(${esc(x.error)})</span>` : "");
  else if (s === "busy") h = "<b>AI busy:</b> " + esc(x.error || "the AI model didn't answer in time") + "";
  if (canAsk) h += ` <button type="button" class="link" id="aiAsk">${s === "checked" || s === "suggested" ? "Ask AI to check again" : "Ask AI to double-check"}</button>`;
  const diff = x.diff || {}, dec = x.decided || {}, open = Object.keys(diff).filter(k => !dec[k]);
  if (open.length && (s === "suggested" || s === "checked")) {
    const v = val => esc(Array.isArray(val) ? val.map(p => typeof p === "object" ? `${p.type}: ${p.number}` : p).join(", ") : (val ?? ""));
    h += `<table class="aidiff"><thead><tr><th scope="col">Field</th><th scope="col">${x.applied ? "Before AI" : "Now"}</th><th scope="col">${x.applied ? "AI changed it to" : "AI suggests"}</th><th scope="col">Choice</th></tr></thead><tbody>` +
      open.map(k => `<tr><th scope="row">${esc(LABEL[k] || k)}</th><td>${v(diff[k].from)}</td><td>${v(diff[k].to)}</td><td><button type="button" class="btn small ok" data-aik="${esc(k)}" data-aic="accept" aria-label="Use AI value for ${esc(LABEL[k] || k)}">${x.applied ? "Keep AI value" : "Use AI value"}</button> <button type="button" class="btn small" data-aik="${esc(k)}" data-aic="reject" aria-label="Keep current ${esc(LABEL[k] || k)}">${x.applied ? "Undo AI change" : "Keep current"}</button></td></tr>`).join("") + "</tbody></table>";
  }
  box.hidden = !h; box.innerHTML = h;
  box.querySelectorAll("[data-aik]").forEach(b => b.onclick = async () => {
    const k = b.dataset.aik, ch = b.dataset.aic;
    if (dirty) {   // unsaved typing on the form: merge here in the browser, never on the server
      if (ch === "accept" && !setFormField(k, diff[k].to)) { toast("Save your edits first, then choose.", 4000); return; }
      try { await post(`/api/cards/${d.id}/ai-decide`, {choices: {[k]: ch}, record_only: true}); toast(ch === "accept" ? `AI value put in ${LABEL[k] || k}. Save to keep it.` : "Kept the current value.", 4000); openCard(d.id, {keep: true}); }
      catch (e) { toast("Not saved: " + e.message, 5000); }
      return;
    }
    try { await post(`/api/cards/${d.id}/ai-decide`, {choices: {[k]: ch}}); toast(ch === "accept" ? "AI value used." : "Kept the current value.", 2600, true); openCard(d.id); }
    catch (e) { toast("Not saved: " + e.message, 5000); } });
  if ($("#aiAsk")) $("#aiAsk").onclick = async () => { try { const r = await post(`/api/cards/${d.id}/ai-check`, {}); toast("AI double-check started" + (r.ahead ? ` (${r.ahead} ahead of it)` : "") + ". Your edits stay as they are."); openCard(d.id, {keep: true}); } catch (e) { toast(e.message, 5000); } };
  if (s === "queued" || s === "checking") rPoll = setTimeout(async () => {
    if ($("#v-review").hidden || !cur || cur.id !== d.id) return;
    const n = await call("/api/cards/" + d.id);
    if (n.ai_status === s) return renderAI(n);
    const kept = dirty; await openCard(d.id, {keep: true});
    toast((n.ai_status === "suggested" ? "AI double-check finished: suggestions below." : n.ai_status === "checked" ? "AI double-check finished: no changes needed." : "AI double-check: " + n.ai_status) + (kept ? " Your unsaved edits were kept." : ""), 4000);
  }, 4000);
}
function setFormField(k, val) {
  const el = k === "emails" ? $("#emails") : k === "phones" ? $("#phones") : k === "social" ? $("#social") : (document.getElementById(k) || $(`[data-extra="${k}"]`));
  if (!el) return false;
  el.value = k === "emails" ? (val || []).join(", ") : k === "phones" ? (val || []).map(p => `${p.type}: ${p.number}`).join("\n") : k === "social" ? (val || []).join(" ") : (val ?? "");
  dirty = true; if (el.id) dirtyIds.add(el.id); return true;
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
  if (h.action === "exported") return "exported to " + (h.detail && h.detail.file || "file");
  return h.action;
}
function showErrors(errs, loud) {
  ["name", "emails", "phones"].forEach(k => { $("#e_" + k).textContent = (errs && errs[k]) || ""; });
  $$("#fields .f").forEach(b => b.classList.remove("err"));
  if (errs) { if (errs.name) $("#first_name").closest(".f").classList.add("err"); if (errs.emails) $("#emails").closest(".f").classList.add("err"); if (errs.phones) $("#phones").closest(".f").classList.add("err"); }
  ["first_name", "emails", "phones"].forEach(id => $("#" + id).setAttribute("aria-invalid", errs && errs[{first_name: "name", emails: "emails", phones: "phones"}[id]] ? "true" : "false"));
  const n = errs ? Object.keys(errs).length : 0;
  $("#rErr").hidden = !n; $("#rErr").innerHTML = n ? `<b>${loud ? "Can't approve yet." : "Fix before approving:"}</b><ul>${Object.values(errs).map(m => `<li>${esc(m)}</li>`).join("")}</ul>` : "";
}
function renderDupes(d) {
  const rejected = d.status === "rejected", all = rejected ? [] : d.dupes.queue, crm = rejected ? [] : d.dupes.crm;
  const q = all.filter(x => !x.kept_apart), kept = all.filter(x => x.kept_apart), res = q.length ? null : "keep_both";
  $("#rDupQ").hidden = !all.length;
  if (all.length) {
    const o = q[0] || all[0];
    $("#rDupQ").innerHTML = res === "keep_both" ? `<b>Checked:</b> marked as a different person from card${kept.length > 1 ? "s" : ""} ${kept.map(x => `<a href="#review/${x.card_id}">#${x.card_id}</a>`).join(", ")}.`
      : `<b>Possible duplicate: this may be the same person as another scanned card.</b><ul>${q.map(x => `<li><a href="#review/${x.card_id}">#${x.card_id} ${esc(x.name || "(no name)")}</a>${x.organization ? ", " + esc(x.organization) : ""} (${esc(x.status || "")}): ${esc(x.why_text || x.why.join(", "))}
        <div class="btns"><button type="button" class="btn small" data-merge="${x.card_id}">Same person: add any new details to #${x.card_id} and drop this card</button>
        ${x.strong ? `<span class="small"><b>Duplicate scan</b> (${x.why.includes("same photo") ? "same photo" : "same email/phone in the same batch"}): merge or reject one of them.</span>`
                   : `<button type="button" class="btn small" data-keep="${x.card_id}" ${x.card_id === o.card_id ? 'id="dKeep"' : ""}>Different person from #${x.card_id}: keep both</button>`}</div></li>`).join("")}</ul>` +
      (q.filter(x => !x.strong).length > 1 ? `<div class="btns"><button type="button" class="btn small" id="dKeepAll">None of these are the same person: keep all ${q.filter(x => !x.strong).length}</button></div>` : "") +
      (q.some(x => !x.blocking) ? `<p class="small">Look-alikes in <b>other batches</b> only warn: they don't stop you approving this card.</p>` : "") +
      (kept.length ? `<p class="small">Already marked as different people: ${kept.map(x => `<a href="#review/${x.card_id}">#${x.card_id}</a>`).join(", ")}.</p>` : "") +
      `<span id="dMerge" hidden></span>`;
    $("#rDupQ").querySelectorAll("[data-merge]").forEach(b => b.onclick = e => act(e.currentTarget, {merge_into: +b.dataset.merge}, `Merged into #${b.dataset.merge}; this card was rejected as a duplicate.`));
    $("#rDupQ").querySelectorAll("[data-keep]").forEach(b => b.onclick = e => act(e.currentTarget, {keep_apart: [+b.dataset.keep]}, `Marked as a different person from #${b.dataset.keep}.`));
    $("#dKeepAll") && ($("#dKeepAll").onclick = e => act(e.currentTarget, {keep_apart: "all"}, "Marked as different people from all the look-alike cards."));
  }
  $("#rDupC").hidden = !crm.length;
  if (crm.length) {
    const m = crm[0], ch = d.dupes.crm_action;
    $("#rDupC").innerHTML = `<b>${ch ? "MC Trade:" : "Possible duplicate: this person may already be in MC Trade."}</b> Closest match: <b>${esc(m.name)}</b>, ${esc(m.organization)} (MC Trade profile #${esc(m.profile_id)}), ${esc(m.why_text)}.
      <p class="small">Matches are checked against a sample copy of MC Trade contacts until live access is set up.</p>` +
      (ch ? `<p>Decision: <b>${ch === "update_existing" ? "update the existing contact" : "add as a new contact"}</b>. <button type="button" class="link" id="cChange">Change</button></p>`
          : `<div class="btns"><button type="button" class="btn small" id="cUpd">Same person: update their existing MC Trade contact</button><button type="button" class="btn small" id="cNew">Different person: add as new contact</button></div>`);
    const set = (v, msg) => e => act(e.currentTarget, {crm_action: v}, msg);
    $("#cUpd") && ($("#cUpd").onclick = set("update_existing", "Will update the existing MC Trade contact."));
    $("#cNew") && ($("#cNew").onclick = set("create_new", "Will be added as a new contact."));
    $("#cChange") && ($("#cChange").onclick = () => { $("#rDupC").querySelector("p:last-child").outerHTML = `<div class="btns"><button type="button" class="btn small" id="cUpd">Update existing contact</button><button type="button" class="btn small" id="cNew">Add as new contact</button></div>`;
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
async function act(btn, extra, okMsg) {
  if (!await needWho()) return;
  $$("#rDupQ button, #rDupC button").forEach(b => { if (b !== btn) b.disabled = true; });
  await busy(btn, "Saving…", async () => {
    try { const r = await post("/api/cards/" + cur.id, {fields: collect(), reviewer: who(), note: $("#note").value, ...extra}); toast(r.notice || okMsg, r.notice ? 7000 : 2600, true); await openCard(cur.id); refreshCounts(); }
    catch (e) { toast("Not saved: " + e.message, 5000); }
  });
}
async function decide(status, btn) {
  if (!cur || $("#dlg").open) return;
  if (status && !await needWho()) return;
  const body = {fields: collect(), status, reviewer: who(), note: $("#note").value};
  const aiWas = cur.ai_status;   // approving doesn't wait for the AI; a queued check is cancelled, a running one leaves suggestions
  await busy(btn, status === "approved" ? "Approving…" : status === "rejected" ? "Rejecting…" : "Saving…", async () => {
    for (let tries = 0; tries < 5; tries++) {
      try {
        const saved = await post("/api/cards/" + cur.id, body);
        await refreshCounts(); STATUS[cur.id] = saved.status;
        if (status === "approved" || status === "rejected") {
          toast(`✓ Card #${cur.id} ${status} by ${who()}.` + (["queued", "checking"].includes(aiWas) ? (aiWas === "queued" ? " The waiting AI check was cancelled." : " Any AI suggestions will appear on the card later.") : ""), 3500, true);
          // next still-pending card after this one in the list; then wrap to earlier pending ones; only then "all done"
          const o = order(), i = o.indexOf(cur.id), pend = x => x !== cur.id && (STATUS[x] === undefined || STATUS[x] === "pending");
          const nxt = i >= 0 ? (o.slice(i + 1).find(pend) ?? o.slice(0, i).find(pend)) : undefined;
          if (nxt !== undefined) { location.hash = "review/" + nxt; }
          else { await ask({title: "All done in this list", html: "<p>There are no pending cards left in the list you were reviewing.</p>", buttons: [{label: "Back to the queue", cls: "primary", value: 1, primary: true}]}); location.hash = SS.queueHash || "queue"; }
        } else { toast(saved.notice || (status === "pending" ? `Card #${cur.id} moved back to pending.` : "Changes saved."), saved.notice ? 7000 : 2600, true); await openCard(cur.id); }
        return;
      } catch (e) {
        const need = e.data && e.data.need;
        
        if (need === "confirm_redecide") {
          const r = await ask({title: "Change an earlier decision?", html: `<p>${esc(e.message)}</p><p class="small">The earlier decision stays in the card's history.</p>`,
            buttons: [{label: `Yes, mark it ${status}`, cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
          if (!r.value) return; body.confirm_redecide = true; continue;
        }
        if (need === "true_duplicate") { await ask({title: "Duplicate scan", html: `<p>${esc(e.message)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return; }
        if (need === "fix") {
          showErrors(e.data.errors, true);
          await ask({title: "These values can't be approved", html: `<ul>${Object.values(e.data.errors).map(m => `<li>${esc(m)}</li>`).join("")}</ul><p>Fix or delete them on the form, then approve. (A missing first name, an email without “@” and a phone number with fewer than 7 digits can't be approved anyway.)</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]});
          const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); return;
        }
        if (need === "fix_or_override") {
          showErrors(e.data.errors, true);
          const r = await ask({title: "Some details are missing or look wrong", html: `<ul>${Object.values(e.data.errors).map(m => `<li>${esc(m)}</li>`).join("")}</ul><p>Fix them on the form (recommended), or approve anyway and say why.</p>`,
            input: {label: "Reason for approving anyway", placeholder: "e.g. card has no email, phone confirmed by hand", required: "A reason is needed to approve anyway."},
            buttons: [{label: "Fix the fields", cls: "primary", value: null, primary: true}, {label: "Approve anyway", value: "override", needInput: true}]});
          if (r.value !== "override") { const first = $("#fields .f.err input, #fields .f.err textarea"); first && first.focus(); return; }
          body.override_reason = r.input; continue;
        }
        if (need === "resolve_duplicate") {
          await ask({title: "Possible duplicate", html: `<p>${esc(e.message)}</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]});
          $("#rDupQ").scrollIntoView({block: "center"}); return;
        }
        if (need === "crm_choice") {
          const r = await ask({title: "Already in MC Trade?", html: `<p><b>${esc(e.data.match.name)}</b>, ${esc(e.data.match.organization)} looks like this person (${esc(e.data.match.why_text || "")}).</p>`,
            buttons: [{label: "Same person: update their contact", cls: "primary", value: "update_existing", primary: true}, {label: "Different person: add as new", value: "create_new"}, {label: "Cancel", value: null}]});
          if (!r.value) return; body.crm_action = r.value; continue;
        }
        toast("Not saved: " + e.message, 5000); return;
      }
    }
  });
}
$("#bApprove").onclick = e => decide("approved", e.currentTarget); $("#bReject").onclick = e => decide("rejected", e.currentTarget);
$("#bSave").onclick = e => decide(null, e.currentTarget); $("#bPending").onclick = e => decide("pending", e.currentTarget);
const step = d => { const o = order(), i = o.indexOf(cur?.id);
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
      const a = await ask({title: "This looks like a different person's card", html: `<p>${esc(x.message)}</p>`,
        buttons: [{label: "Don't add it", value: null, primary: true}, {label: "It IS the back of this card: add it", value: 1}]});
      if (!a.value) { toast("Nothing was added.", 3000); return; }
      r = await send(true);
    }
    toast(r.filled.length ? "Back added. Filled: " + r.filled.map(k => LABEL[k] || k).join(", ") : "Back added. Nothing new found on it.", 4000, true); openCard(cur.id); }
  catch (x) { toast("Not added: " + x.message, 5000); }
};
$("#bDelete").onclick = async () => {
  const r = await ask({title: `Delete card #${cur.id} permanently?`, html: "<p>For a removal request. The photo, the contact details and any stored export copies that contain it are deleted and can't be undone. The audit log keeps who scanned, approved and exported it and when, with the personal details removed. Files already downloaded or imported into MC Trade must be cleaned up there.</p>",
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
    if (!$("#exBatch").dataset.loaded) { const bs = await call("/api/batches"); $("#exBatch").dataset.loaded = 1;
      $("#exBatch").innerHTML = `<option value="">All batches</option>` + bs.map(b => `<option value="${esc(b.batch)}">${esc(b.batch_label || b.batch)} (${b.n})</option>`).join(""); }
    const r = await call(`/api/export/check?status=${st}&batch=${encodeURIComponent(eb)}`);
    $("#exInfo").innerHTML = `<b>${r.count}</b> card(s) will be exported.` + (r.count ? "" : " Approve some cards in the review queue first.") +
      (r.flagged && r.flagged.length ? ` <span class="flag bad">${r.flagged.length} were approved anyway or still fail a check (${r.flagged.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}); they are listed in NeedsAttention (CSV) / the companion file (MC Trade Excel).</span>` : "");
    $("#exDup").hidden = !r.duplicates.length;
    $("#exDup").innerHTML = r.duplicates.length ? `<b>Export is blocked: some cards look like the same person.</b> For each pair, open the card to merge, or if they really are different people choose “Different people (keep both)”:<ul>${r.duplicates.map(p => `<li><a href="#review/${p.id}">Card #${p.id}</a>${p.batch ? ` <span class="sub">(${esc(p.batch)})</span>` : ""} may duplicate ${p.with.map(w => `<a href="#review/${w}">#${w}</a>` + ((p.strong || []).includes(w) ? ` <span class="sub">(same photo or same batch: merge or reject one)</span>` : ` <button class="btn small" data-xkeep="${p.id}:${w}">Different people (keep both)</button>`)).join(", ")} <a class="btn small" href="#review/${p.id}">Open to merge</a></li>`).join("")}</ul>` +
      (!eb && r.ok_batches && r.ok_batches.length ? `<p>These batches can be exported now (choose one under <b>Which batch</b>): ${r.ok_batches.map(b => `<a href="#" data-xbatch="${esc(b.batch)}">${esc(b.label)}</a> (${b.count})`).join(", ")}</p>` : "") : "";
    $("#exDup").querySelectorAll("[data-xkeep]").forEach(b => b.onclick = async () => { const [a, w] = b.dataset.xkeep.split(":").map(Number);
      if (!await needWho()) return;
      try { await post(`/api/cards/${a}`, {keep_apart: [w]}); toast(`Marked #${a} and #${w} as different people.`); exportInfo(); }
      catch (e) { toast("Couldn't keep both: " + e.message); } });
    $("#exDup").querySelectorAll("[data-xbatch]").forEach(a => a.onclick = e => { e.preventDefault(); $("#exBatch").value = a.dataset.xbatch; exportInfo(); });
    $$(".tile").forEach(t => t.disabled = !r.count || r.duplicates.length > 0); loadExportHistory();
    return r;
  } catch (e) { $("#exInfo").textContent = "Couldn't check: " + e.message; }
}
$("#exPreview").onclick = () => { (window.gacDownload || (u => location.href = u))(`/api/export/xlsx?preview=1&status=${encodeURIComponent($("#exStatus").value)}&batch=${encodeURIComponent($("#exBatch").value)}`); };
$("#exStatus").onchange = exportInfo; $("#exBatch").onchange = exportInfo;
let exHistShow = 10;
$("#exHistMoreBtn").onclick = () => { exHistShow += 10; loadExportHistory(); };
$("#exHistAllBtn").onclick = () => { exHistShow = Infinity; loadExportHistory(); };
async function loadExportHistory() {
  const all = await call("/api/exports"), h = all.slice(0, exHistShow);
  $("#exHistMore").hidden = all.length <= h.length; $("#exHistCount").textContent = `Showing ${h.length} of ${all.length}.`;
  $("#exHist").innerHTML = h.map(x => `<tr><td>${esc(when(x.ts))}</td><td>${esc(x.initials)}</td><td>${esc(x.kind.toUpperCase())}<div class="sub">${esc(x.filter_text)}${x.batch_label ? " · batch " + esc(x.batch_label) : ""}</div></td><td>${x.count}</td>
    <td>${x.available ? `<a href="/api/exports/${x.id}/download">${esc(x.filename)}</a>` + (x.companions || []).map(c => ` · <a href="/api/exports/${x.id}/companion/${c}">${c === "readme.txt" ? "READ ME" : c === "updates.xlsx" ? "UPDATES file" : "extra columns"}</a>`).join("") : `${esc(x.filename)} <span class="sub">(${x.mine ? "copy deleted" : "only " + esc(x.initials) + " or an admin can download it"})</span>`}</td></tr>`).join("") || `<tr><td colspan="5">No exports yet.</td></tr>`;
}
const KIND_ = 0; const KIND = {xlsx: "MC Trade import (Excel)", csv: "Spreadsheet (CSV)", vcf: "Contacts (vCard)"};
$$(".tile").forEach(t => t.onclick = async () => {
  const kind = t.dataset.ex, st = $("#exStatus").value, info = await exportInfo(); if (!info || !info.count || info.duplicates.length) return;
  if (!await needWho()) return;
  const r = await ask({title: `Export ${info.count} card(s)?`, html: `<p>Format: <b>${KIND[kind]}</b><br>Cards: <b>${esc($("#exStatus").selectedOptions[0].textContent)}</b><br>Batch: <b>${esc($("#exBatch").selectedOptions[0]?.textContent || "All batches")}</b></p><p class="small">The file goes to your Downloads folder.</p>`,
    buttons: [{label: "Export", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return;
  t.setAttribute("aria-busy", "true");
  try {
    const res = await fetch(`/api/export/${kind}?status=${st}&batch=${encodeURIComponent($("#exBatch").value)}`);
    if (!res.ok) { let j = {}; try { j = await res.json(); } catch {} throw new Error(j.error || res.statusText); }
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || "export." + kind, n = res.headers.get("X-Card-Count");
    const blob = await res.blob(), a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
    $("#exDone").hidden = false;
    const eid = res.headers.get("X-Export-Id"), comp = (res.headers.get("X-Companions") || "").split(",").filter(Boolean);
    for (const c of comp) { const r2 = await fetch(`/api/exports/${eid}/companion/${c}`); if (!r2.ok) continue;
      const nm = (r2.headers.get("Content-Disposition") || "").match(/filename="?([^"]+)"?/)?.[1] || c, a2 = document.createElement("a");
      a2.href = URL.createObjectURL(await r2.blob()); a2.download = decodeURIComponent(nm); document.body.append(a2); a2.click(); a2.remove(); }
    $("#exDone").className = "alert ok"; $("#exDone").hidden = false;
    $("#exDone").innerHTML = `<b>✓ Exported ${n} card(s)</b> to <b>${esc(name)}</b> in your Downloads folder.` + (kind === "xlsx" ? "<br>Three files: the <b>import file</b> (only MC Trade template columns, one row per person), a <b>…-extra-columns.csv</b> (audit details, notes, and any rows left out) and a <b>…-READ-ME.txt</b>. Read the READ ME, then import the .xlsx in MC Trade (Admin → Import Profiles), testing with two rows first." : "");
    toast("Export saved to Downloads."); exportInfo();
  } catch (e) { $("#exDone").hidden = false; $("#exDone").className = "alert bad"; $("#exDone").textContent = "Export failed: " + e.message; }
  finally { t.removeAttribute("aria-busy"); }
});

/* ---------- admin ---------- */
let adminTab = "users";
$$("#adminTabs button").forEach(b => b.onclick = () => { adminTab = b.dataset.t; loadAdmin(); });
async function loadAdmin() {
  if (!ME) return;   // route() runs again once the signed-in user is known
  if (ME.role !== "admin") { ["users", "settings", "audit"].forEach(t => $("#t-" + t).hidden = true); $("#adminTabs").hidden = true; toast("Only admins can open the Admin page."); return; }
  $$("#adminTabs button").forEach(x => x.setAttribute("aria-selected", x.dataset.t === adminTab));
  ["users", "settings", "audit"].forEach(t => $("#t-" + t).hidden = t !== adminTab);
  if (adminTab === "users") {
    const us = await call("/api/admin/users");
    $("#uBody").innerHTML = us.map(u => `<tr data-u="${u.id}"><td>${esc(u.display)}</td><td>${esc(u.username)}</td><td>${esc(u.initials)}</td><td>${u.role === "admin" ? "Admin" : "Reviewer"}</td><td>${u.active ? "Active" : "Deactivated"}${u.must_change ? '<div class="sub">temporary password</div>' : ""}</td>
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
    $("#sOn").checked = st.retention_enabled === "1"; $("#sAI").checked = st.ai_check_enabled === "1"; $("#sCorr").checked = st.corrections_enabled === "1"; $("#sAff").value = st.mctrade_affcode || ""; $("#sPh").value = st.phone_format || "gac";
    aiHelperRefresh(); call("/api/ai/status").then(a => $("#sAIStatus").textContent = a.available ? "✓ The AI model is running on this computer." : "The AI model is not running right now, so cards are only read the fast way. Use “Download AI helper” below (desktop app) or see HANDOFF.md → “AI double-check”."); $("#sImg").value = st.image_retention_days; $("#sExp").value = st.export_retention_days;
    $("#sPrev").textContent = `${pv.photos_stored} card photo(s) stored. ${pv.would_delete} are older than ${pv.days} days${pv.enabled ? " and will be deleted at the next check" : " (automatic deletion is off)"}.`;
  }
  if (adminTab === "audit") loadAudit();
}
$("#uForm").onsubmit = async e => { e.preventDefault(); $("#uErr").textContent = "";
  await busy($("#uAdd"), "Adding…", async () => { try {
    await post("/api/admin/users", {display: $("#uDisplay").value.trim(), username: $("#uName").value.trim(), initials: $("#uIni").value.trim(), role: $("#uRole").value, password: $("#uPw").value});
    toast(`Added ${$("#uDisplay").value}. Give them their username and temporary password.`, 5000); $("#uForm").reset(); loadAdmin();
  } catch (x) { $("#uErr").textContent = x.message; } }); };
$("#uDisplay").oninput = () => { if (!$("#uName").dataset.touched) $("#uName").value = $("#uDisplay").value.trim().toLowerCase().replace(/\s+/g, ".").replace(/[^a-z0-9._-]/g, ""); };
$("#uName").oninput = () => $("#uName").dataset.touched = "1";
$("#sSave").onclick = e => busy(e.currentTarget, "Saving…", async () => { try { const r = await post("/api/admin/settings", {ai_check_enabled: $("#sAI").checked ? "1" : "0", corrections_enabled: $("#sCorr").checked ? "1" : "0", retention_enabled: $("#sOn").checked ? "1" : "0", image_retention_days: $("#sImg").value, export_retention_days: $("#sExp").value, mctrade_affcode: $("#sAff").value, phone_format: $("#sPh").value}); toast(r._changed && !r._changed.length ? "Nothing changed, so nothing was saved or logged." : "Settings saved."); loadAdmin(); } catch (x) { toast(x.message, 5000); } });
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
setInterval(() => { if (!document.hidden) refreshCounts(); }, 15000);
$(".skip").onclick = e => { e.preventDefault(); $("#main").focus(); };   // the hash is the router: don't navigate to "#main"

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
