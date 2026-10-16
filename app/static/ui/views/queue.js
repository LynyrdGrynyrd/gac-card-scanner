// Review queue: batch picker, filters, paged All batches, selection and bulk approve/reject.
import {S} from "../core/state.js";
import {$, $$, LABEL, SS, esc, plural, when} from "../core/dom.js";
import {call, post} from "../core/api.js";
import {toast} from "../ui/toast.js";
import {ask, busy} from "../ui/dialog.js";
import {refreshCounts, refreshUndo, who} from "../header.js";

/* ---------- queue ---------- */
const Q = {s: "pending", batch: "", att: false, dup: false, nx: false, text: "", arch: false, cards: [], sel: new Set()};
function applyQueueState(q) {
  if (q.has("s")) Q.s = q.get("s") === "all" ? "" : q.get("s");
  // round 8 (newcomer r8 N1): the batch filter is kept when coming back (menu link, ↩ Queue, back button); 'all' = All batches.
  // With no batch remembered yet, the queue opens on YOUR most recent batch (chosen in loadQueue), not on everyone's cards.
  // round 11 (newcomer r10 N2): a remembered batch counts only for the person who chose it, and only until they start a newer batch
  // round 12 (newcomer r10 N2): only a batch the person CHOSE in the batch dropdown this session is remembered. Opening a
  // card of another batch, its ↩ Queue link or a look-alike link no longer changes what the top-bar "Review queue" shows.
  const remembered = SS.batchChosen !== undefined && S.ME && SS.batchChosenUid === String(S.ME.id) ? SS.batchChosen : null;
  Q.batch = q.has("batch") ? (q.get("batch") === "all" ? "" : q.get("batch")) : remembered;
  Q.batchFromMemory = !q.has("batch") && remembered !== null;   // round 24 (newcomer/datamanager r23): the queue always opens on your newest batch
  Q.att = q.get("att") === "1"; Q.nx = q.get("nx") === "1"; Q.dup = q.get("dup") === "1"; Q.text = q.get("q") || ""; Q.arch = q.get("arch") === "1";
  $$("#statusTabs button").forEach(x => x.setAttribute("aria-pressed", x.dataset.s === Q.s));
  $("#fAtt").checked = Q.att; $("#fNew").checked = Q.nx; $("#fDup").checked = Q.dup; $("#fText").value = Q.text; $("#fArch").checked = Q.arch;
}
function pushQueueState() {
  const p = new URLSearchParams(); p.set("s", Q.s); p.set("batch", Q.batch || "all"); SS.lastBatch = Q.batch || ""; SS.lastBatchUid = S.ME ? String(S.ME.id) : ""; SS.lastBatchAt = String(Date.now() / 1000); if (Q.att) p.set("att", "1"); if (Q.nx) p.set("nx", "1"); if (Q.dup) p.set("dup", "1"); if (Q.text) p.set("q", Q.text); if (Q.arch) p.set("arch", "1");
  SS.queueHash = "#queue?" + p;
  if (location.hash.startsWith("#queue") && !$("#dlg").open) history.replaceState(null, "", "#queue?" + p);   // round 15: never rewrite the URL of another page or under an open question
}
$$("#statusTabs button").forEach(b => b.onclick = () => { Q.s = b.dataset.s; $$("#statusTabs button").forEach(x => x.setAttribute("aria-pressed", x === b));   // audit 2026-10: aria-pressed buttons, not tabs without tabpanels
 Q.sel.clear(); pushQueueState(); loadQueue(); });
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
$("#fBatch").onchange = e => { Q.batch = e.target.value; SS.batchChosen = Q.batch; SS.batchChosenUid = S.ME ? String(S.ME.id) : ""; SS.lastBatch = Q.batch; SS.lastBatchUid = S.ME ? String(S.ME.id) : ""; SS.lastBatchAt = String(Date.now() / 1000); Q.sel.clear(); pushQueueState(); loadQueue(); };
function filterBatchOptions() {   // the batch list gets long: type to narrow it
  const t = ($("#fBatchQ") && $("#fBatchQ").value || "").toLowerCase().trim();
  $$("#fBatch option").forEach(o => o.hidden = (!!t && o.value !== "" && o.value !== Q.batch && !o.textContent.toLowerCase().includes(t)) || (!t && o.dataset.old === "1" && !SHOWALLB && o.value !== Q.batch));
}
$("#fBatchQ") && ($("#fBatchQ").oninput = filterBatchOptions);
let qSeq = 0, MINE = new Set(); const STATUS = {};
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
  const myB = S.B && S.B.id && (!S.B.uid || (S.ME && S.B.uid === S.ME.id)) ? S.B : null;
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
    const bOpt = b => `<option value="${esc(b.batch)}">${esc(b.batch_label || b.batch)} · ${b.n}${reading && b.batch === reading ? ", being read…" : ""}</option>`;   // v0.4.2 #5: no "(2) (1)"
    const bNew = (a, b) => (b.started || 0) - (a.started || 0), bMine = batches.filter(b => b.mine || b.own).sort(bNew), bOth = batches.filter(b => !(b.mine || b.own)).sort(bNew);
    const buildB = () => { const tM = new Set(trimB(bMine, Q.batch)), tO = new Set(trimB(bOth, Q.batch)), hid = bMine.length - tM.size + bOth.length - tO.size;
    const hOpt = keep => b => keep.has(b) ? bOpt(b) : "";   // round 22: old/test batches are really left out (<option hidden> is ignored by some browsers); links and Show all still reach them
    $("#fBatch").innerHTML = (tM.size ? `<optgroup label="My batches">${bMine.map(hOpt(tM)).join("")}</optgroup>` : "") +
      (tO.size ? `<optgroup label="Other people's batches">${bOth.map(hOpt(tO)).join("")}</optgroup>` : "") + (SHOWALLB || Q.batch === "" ? `<option value="">All batches (everyone's)</option>` : "") +
      (hid ? `<option value="__showall__">More batches…</option>` : ""); }; // round 16 (coordinator r15 #1); round 21: old/test batches behind "Show all"
    S.BATCHES = batches; MINE = new Set(batches.filter(b => b.mine).map(b => b.batch));
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
    const want = Q.batch, qs = queueQs(want), key = qs.toString();
    if (Q.cardsFor !== want) { $$("#statusTabs button span").forEach(x => x.textContent = ""); $("#qBody").innerHTML = ""; }   // never show another batch's counts under this name
    // audit 2026-10: All batches is paged (a reload keeps the cards already loaded with "Load more")
    const pg = want ? null : await cardsUpTo(qs, Q.cardsFor === want && Q.qsKey === key ? Math.max(QPAGE, Q.cards.length) : QPAGE);
    const cards = pg ? pg.cs : await call("/api/cards?" + qs);
    if (seq !== qSeq || $("#v-queue").hidden || want !== Q.batch) return;
    Q.cards = want ? cards.filter(c => inBatch(c, want)) : cards; Q.cardsFor = want; Q.qsKey = key; Q.total = pg ? pg.total : null;
    $("#fBatch").disabled = false;
    renderQueue(); refreshCounts();
    // round 20 (coordinator r19): the list once showed Pending (0) / All (0) for a batch that has cards, until a reload.
    // If the batch list says it has cards but none came back, load it once more.
    const bn = (batches.find(b => b.batch === want) || {}).n || 0;
    if (want && !Q.cards.length && bn > 0 && Q.retryFor !== want) { Q.retryFor = want; Q.cardsFor = undefined; setTimeout(() => { if (Q.batch === want) loadQueue(); }, 600); }
    else if (Q.cards.length) Q.retryFor = null;
  } catch (e) { if (seq === qSeq) { $("#qEmpty").hidden = false; $("#qEmpty").textContent = "Couldn't load cards: " + e.message + ". Is the scanner window still open?"; } }
  finally { if (seq === qSeq) { $("#qLoading").hidden = true; Q.loading = false; if (Q.again) { Q.again = false; setTimeout(() => loadQueue(), 0); } } }
}
// audit 2026-10: "All batches" asked for every card (limit=0: ~9 s at 2,000 cards, each enriched by the server). It is
// paged now (the server's 200-card page; X-Total/X-Offset/X-Limit) with "Load more"; one-batch views stay unpaged.
const QPAGE = 200;
async function cardsPage(qs, off, lim) { const m = {}, p = new URLSearchParams(qs); p.set("limit", String(lim)); p.set("offset", String(off));
  const cs = await call("/api/cards?" + p, {meta: m}); const t = m.headers && m.headers.get("X-Total"); return {cs, total: t ? +t : off + cs.length}; }
async function cardsUpTo(qs, n) {   // the first n cards of a paged list (the server sends at most 500 per request)
  let out = [], total = 0;
  do { const r = await cardsPage(qs, out.length, Math.min(500, n - out.length)); out = out.concat(r.cs); total = r.total; if (!r.cs.length) break; } while (out.length < Math.min(n, total));
  return {cs: out, total};
}
const queueQs = want => { const qs = new URLSearchParams(); if (want) qs.set("batch", want); else if (Q.s) qs.set("status", Q.s); if (Q.arch) qs.set("archived", "true"); return qs; };
$("#qMoreBtn").onclick = async e => {
  const b = e.currentTarget, want = Q.batch, s0 = qSeq, key = Q.qsKey; if (want !== "" || b.getAttribute("aria-busy") === "true") return;
  b.setAttribute("aria-busy", "true");   // not disabled: that would drop keyboard focus
  try { const r = await cardsPage(new URLSearchParams(key), Q.cards.length, QPAGE); if (s0 !== qSeq || Q.batch !== want || Q.qsKey !== key) return;
    const have = new Set(Q.cards.map(c => c.id)); Q.cards = Q.cards.concat(r.cs.filter(c => !have.has(c.id))); Q.total = r.total; renderQueue(); }
  catch (x) { toast("Couldn't load more cards: " + x.message, 5000); }
  finally { b.removeAttribute("aria-busy"); }
};
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
    qPoll = setTimeout(async () => { if ($("#v-queue").hidden) return; if (document.hidden) { scheduleQueuePoll(); return; } const want = Q.batch, s0 = qSeq;   // audit 2026-10: no work while hidden
      try { const qs = queueQs(want), key = qs.toString();   // round 16 (skeptic r15 M1): never the 200-card default page; audit 2026-10: All batches: the pages already loaded
        const pg = want ? null : await cardsUpTo(qs, Math.max(QPAGE, Q.cards.length)), cs = pg ? pg.cs : await call("/api/cards?" + qs);
        if (want !== Q.batch || s0 !== qSeq || $("#v-queue").hidden || (Q.qsKey && Q.qsKey !== key)) return;
        const fresh = cs.filter(c => inBatch(c, want)), total = pg ? pg.total : null;
        if (Q.cardsFor === want && total === Q.total && JSON.stringify(fresh) === JSON.stringify(Q.cards)) { scheduleQueuePoll(); return; }   // audit 2026-10: nothing changed
        Q.cards = fresh; Q.cardsFor = want; Q.total = total; renderQueue(); } catch {} }, 5000);
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
  inB.forEach(c => cnt[c.status]++);
  // audit 2026-10: a paged All batches list only knows the total of the status shown (X-Total)
  const paged = Q.batch === "" && Q.cardsFor === "" && Q.total != null;
  $$("#statusTabs button").forEach(b => b.querySelector("span").textContent = paged ? (b.dataset.s === Q.s ? `(${Q.total})` : "") : `(${cnt[b.dataset.s]})`);
  $("#qMore").hidden = !(paged && Q.total > Q.cards.length); if (!$("#qMore").hidden) $("#qMoreBtn").textContent = `Load more (${Q.cards.length} of ${Q.total} shown)`;

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
  const ids = [...Q.sel]; if (!ids.length) return;
  $("#bulkApprove").disabled = $("#bulkReject").disabled = true;   // round 15 (reviewer r14): both off while one runs
  try { return await bulk_(status, btn, ids); } finally { syncSel(); }
}
// round 17 (newcomer r16 #2): "Approve all 1" read oddly: natural wording for 1 and 2
const allN17 = (n, tail) => `Approve ${n}`;   // round 21 (newcomer r20): one approve label
const cap17 = (xs, f, n = 10) => xs.slice(0, n).map(f).join("") + (xs.length > n ? `<li>…and ${xs.length - n} more (open the cards from the queue)</li>` : "");
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
  // round 21 (r20 bots): about 5 short lines; ids and reasons behind "Show" / More
  const show = (n, inner) => `<details class="more small"><summary>Show ${n}</summary><ul>${inner}</ul></details>`;
  const line = [];
  if (sk0.length) line.push(`<li><b>${plural(sk0.length, "card")}</b> can't be approved yet. ${show(sk0.length, cap17(sk0, x => `<li><a href="#review/${x.id}">#${x.id}</a>: ${esc(why16(x.why))}</li>`))}</li>`);
  if (ai0.length) line.push(`<li>${plural(ai0.length, "card")}: AI check not finished (approving cancels it).</li>`);
  if (lk0.length) line.push(`<li>${plural(lk0.length, "card")} may already be in MC Trade. ${show(lk0.length, cap17(lk0, w => `<li><a href="#review/${w.id}">#${w.id}</a>: ${esc(why16(w.why))}</li>`))}</li>`);
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
      toast(msg, res.skipped.length || warn.length ? 7000 : 4500, res.updated.length > 0); refreshUndo(); refreshCounts();   // round 12 (reviewer r10): nav badge follows a bulk decision
  }
  syncSel(); setTimeout(syncSel, 0);   // busy() restored the old label ("… (3)"); show the real count
}
$("#bulkApprove").onclick = e => bulk("approved", e.currentTarget); $("#bulkReject").onclick = e => bulk("rejected", e.currentTarget);
$("#archiveBatch").onclick = async e => { const btn = e.currentTarget;
  const opt = $("#fBatch").selectedOptions[0]; if (!Q.batch) return;
  const r = await ask({title: "Archive this batch?", html: `<p><b>${esc(opt.textContent)}</b> will be hidden from the queue and exports. Nothing is deleted. Tick “Show archived” to see it.</p>`,
    buttons: [{label: "Archive batch", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return;
  await busy(btn, "Archiving…", async () => { const x = await post("/api/batches/archive", {batch: Q.batch, reviewer: who()}); Q.batch = ""; pushQueueState(); toast(`${plural(x.archived, "card")} archived.`, 4500, x.archived > 0); await loadQueue(); });
};
$("#archiveAll").onclick = async e => { const btn = e.currentTarget;
  const r = await ask({title: "Archive all test data?", html: "<p>Hides every card in the queue from the queue and exports. Nothing is deleted. Undo brings them back.</p>",
    input: {label: "Type CLEAR to confirm", required: "Type CLEAR to confirm."}, buttons: [{label: "Archive everything", cls: "danger", value: 1, needInput: true, primary: true}, {label: "Cancel", value: null}]});
  if (!r.value) return; if (r.input.trim() !== "CLEAR") { toast("Not cleared: you didn't type CLEAR."); return; }
  await busy(btn, "Clearing…", async () => { const x = await post("/api/batches/archive", {batch: "__all__", confirm: "CLEAR", reviewer: who()}); toast(`${plural(x.archived, "card")} archived. The review queue is now empty.`, 4500, x.archived > 0); await loadQueue(); });
};
export {Q, STATUS, applyQueueState, confBar, loadQueue};
