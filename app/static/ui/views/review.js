// Review card: the form, drafts, AI suggestions, duplicates, approve/reject/save, prev/next.
import {S} from "../core/state.js";
import {$, $$, LABEL, SS, esc, fmtEta, plural, when} from "../core/dom.js";
import {call, post} from "../core/api.js";
import {draftKey, dropDraft, keepDraft, saveDraft} from "../core/store.js";
import {hideToast, toast} from "../ui/toast.js";
import {ask, busy} from "../ui/dialog.js";
import {doUndo, refreshCounts, refreshUndo, who} from "../header.js";
import {STATUS, confBar} from "./queue.js";

/* ---------- review ---------- */
const order = () => { try { return JSON.parse(SS.order || "[]"); } catch { return []; } };
// round 16 (newcomer r15 #6): on a PENDING card, the counter and Prev/Next go through the cards still pending (decided ones are skipped)
const navOrder = id => { const o = order(); if ((S.cur && S.cur.id === id ? S.cur.status : STATUS[id]) !== "pending") return o;
  return o.filter(x => x === id || (STATUS[x] ?? "pending") === "pending"); };
function dirtyVals() { const o = {}; dirtyIds.forEach(i => { const el = document.getElementById(i); if (el) o[i] = el.value; }); return o; }
let openSeq = 0;
// round 15 (part-timer): Save/Approve stay off until the card has finished loading (a blank form must never be saved)
async function openCard(id, opts = {}) {
  const tok = ++openSeq, switching = !S.cur || S.cur.id !== id;
  if (switching) {   // round 6 (newcomer F1): never show the previous card's values under the new card's number
    S.CARD_READY = false; S.cur = null; $("#rForm").inert = true; $("#rForm").classList.add("loading");
    $$("#rForm input, #rForm textarea").forEach(el => { if (!el.readOnly) { el.readOnly = true; el.dataset.ro16 = "1"; } });   // round 16 (part-timer r15): nothing typed into the empty form while it loads
    $$("#rForm input, #rForm textarea").forEach(el => el.value = ""); $("#rDupBox").hidden = true; ["#rExported", "#rDupQ", "#rDupC", "#rAI", "#rCons"].forEach(q => { const e = $(q); if (e) { e.hidden = true; e.innerHTML = ""; e._h = null; } });
    $("#h-r").textContent = `Loading card #${id}…`; $$(".decide button, #bApprove, #bReject, #bSave, #bPending").forEach(b => b.disabled = true);
  }
  let d; try { d = await call("/api/cards/" + id); } catch { if (tok === openSeq) { toast("Card not found."); location.hash = SS.queueHash || "queue"; } return; }
  if (tok !== openSeq) return;   // the person already moved on to another card: drop this late answer
  // round 14 (LOST SAVE): what the person typed WHILE the card was loading is kept too (it used to be read before the fetch)
  if (opts.keep && S.cur && S.cur.id === id) recomputeDirty();
  const keep = opts.keep && S.cur && S.cur.id === id && S.dirty ? dirtyVals() : null;
  $("#rForm").inert = false; $("#rForm").classList.remove("loading"); $$("#rForm [data-ro16]").forEach(el => { el.readOnly = false; delete el.dataset.ro16; }); $$(".decide button, #bApprove, #bReject, #bSave, #bPending").forEach(b => b.disabled = b.getAttribute("aria-busy") === "true"); S.CARD_READY = true;   // round 17 (part-timer r16 #4): never re-enabled while it still reads "Saving…"
  if (!S.cur || S.cur.id !== d.id) scrollTo(0, 0);
  S.cur = d; const c = d.card, f = c.fields, k = f.confidence || {};
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
  $("#bPending").textContent = c.status === "rejected" ? "↩ Move back to pending (un-reject)" : "Move back to pending"; $("#bApprove").hidden = c.status !== "pending"; $("#bDelete").hidden = !S.ME || S.ME.role !== "admin"; $("#bReject").hidden = c.status === "rejected";
  S.dirty = false; dirtyIds.clear();
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
  if (!restore && SS.draft) { try { const dr = JSON.parse(SS.draft); if (dr.id === c.id && S.ME && dr.uid === S.ME.id) { restore = dr.vals; toast("Restored your unsaved edits. Check them and save.", 6000); } } catch {} delete SS.draft; }
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
  const showPos = (pendN) => { if (!S.cur || S.cur.id !== c.id) return; const o = navOrder(c.id), i = o.indexOf(c.id);
    $("#pos").textContent = i < 0 ? "" : c.status === "pending" ? `${i + 1} of ${o.length} pending` : `${i + 1} of ${o.length}` + (pendN != null ? ` · ${pendN} pending left` : "");
    $("#prev").disabled = i <= 0; $("#next").disabled = i < 0 || i >= o.length - 1; };
  showPos(null);
  { const b_ = d.batch || c.batch || "", seq_ = openSeq;
    call("/api/cards?status=pending" + (b_ ? "&limit=0&batch=" + encodeURIComponent(b_) : "&limit=500")).then(cs => {   // audit 2026-10: no batch: capped (only ids for Prev/Next)
      if (seq_ !== openSeq || !S.cur || S.cur.id !== c.id) return;
      const pend = new Set((cs || []).map(x => x.id)); let o = order();
      o.forEach(x => { if (pend.has(x)) STATUS[x] = "pending"; else if ((STATUS[x] ?? "pending") === "pending" && x !== c.id) STATUS[x] = "decided"; });
      if (!o.includes(c.id)) { o = (cs || []).map(x => x.id).concat(pend.has(c.id) ? [] : [c.id]); SS.order = JSON.stringify(o); }   // opened by link: this batch's pending cards
      showPos(pend.size); }).catch(() => {});
  }
}
let rPoll = null, ORIG = {}, LASTOK = {}; const dirtyIds = new Set();
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
  if (S.cur && S.cur.id === sid) { ORIG = sent ? {...sent} : formSnap(); }
  S.dirty = false; dirtyIds.clear(); recomputeDirty(); if (!S.dirty) dropDraft(sid);
}
async function waitSaveIdle(ms = 60000) { const t0 = Date.now(); while (S.SAVING && Date.now() - t0 < ms) await new Promise(r => setTimeout(r, 100)); return !S.SAVING; }
function recomputeDirty() {
  dirtyIds.clear(); Object.keys(ORIG).forEach(i => { const el = document.getElementById(i); if (el && normV(i, el.value) !== normV(i, ORIG[i])) dirtyIds.add(i); });
  S.dirty = dirtyIds.size > 0;
  $$("#fields .f.unsaved").forEach(x => x.classList.remove("unsaved"));   // reviewer r9: mark each unsaved field
  dirtyIds.forEach(i => { const f_ = document.getElementById(i)?.closest(".f"); if (f_) f_.classList.add("unsaved"); });
  const ab = $("#rAI"); if (ab) { $("#rAIStale")?.remove(); if (S.dirty && /AI-checked/.test(ab.textContent)) ab.insertAdjacentHTML("beforeend", '<div id="rAIStale" class="small" style="color:#b45309"><b>This AI result covers the SAVED values only.</b> You have unsaved changes; save, then run the check again if needed.</div>'); }
  const b = $("#rDirty"); if (b) { b.hidden = !S.dirty; b.textContent = S.dirty ? (S.SAVING ? "Saving…" : `Unsaved changes: ${[...dirtyIds].map(i => String(LABEL[i] || LABEL[i.replace(/^x_/, "")] || i.replace(/^x_/, "").replace(/_/g, " ")).toLowerCase()).join(", ")}`) : ""; }
  const x = $("#bDiscard"); if (x) x.hidden = !S.dirty;
  if (!S.dirty && S.cur) dropDraft(S.cur.id);
  return S.dirty;
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
$("#bDiscard") && ($("#bDiscard").onclick = async () => { if (!S.cur) return;
  const r = await ask({title: "Discard your edits?", html: `<p>The form goes back to the saved card #${S.cur.id}. Your typed changes (${esc([...dirtyIds].map(i => LABEL[i.replace(/^x_/, "")] || i.replace(/^x_/, "")).join(", "))}) are thrown away.</p>`,
    buttons: [{label: "Discard my edits", cls: "danger", value: 1}, {label: "Cancel", value: null, primary: true, focus: true}]});
  if (!r.value) return; clearTimeout(keepDraft.t); dropDraft(S.cur.id); S.dirty = false; dirtyIds.clear(); delete SS.draft; await openCard(S.cur.id); toast("Edits discarded."); });
addEventListener("beforeunload", e => { if (S.SIGNING_OUT) return; if (!$("#v-review").hidden && Object.keys(ORIG).length && recomputeDirty()) { saveDraft(); e.preventDefault(); e.returnValue = ""; } });
addEventListener("pageshow", e => { if (e.persisted) location.reload(); });   // never show a cached page after sign-out
let vT = null;
$("#rForm").addEventListener("input", e => {
  // round 17 (part-timer r16 #5): a field's own warning (e.g. "StSuite looks like two words") is about the OLD value: it goes
  // as soon as the field is edited; Save re-checks the card and shows it again only if it still applies
  { const f_ = e.target.closest && e.target.closest(".f"); if (f_ && f_.querySelector(".fhint")) { f_.querySelectorAll(".fhint").forEach(x => x.remove()); f_.classList.remove("hinted");
      const lab = (f_.querySelector("label")?.getAttribute("for")) || ""; $$("#rRisk li[data-f]").forEach(li => { if (li.dataset.f === lab) li.remove(); });
      const n_ = $$("#rRisk li").length, b_ = $("#rRisk b"); if (!n_) $("#rRisk").hidden = true; else if (b_) b_.textContent = `To check (${n_}):`; } }
  recomputeDirty(); clearTimeout(keepDraft.t); keepDraft.t = setTimeout(keepDraft, 400); clearTimeout(vT);
  if (S.cur) { const b = $("#rAI .flag.bad"); if (b && !S.dirty) b.remove(); }
  if (!$$("#fields .f.err").length && $("#rErr").hidden) return;      // only re-check while problems are shown
  vT = setTimeout(async () => { try { const r = await post("/api/validate", {fields: collect(), card_id: S.cur && S.cur.id}); showErrors({...r.errors, ...r.hard}, !$("#rErr").hidden); } catch {} }, 300); });
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
    h = `<b>${p.eta_seconds ? `AI check in ~${fmtEta(p.eta_seconds)}` : s === "checking" ? "AI check running…" : "AI check soon"}.</b> Keep working.` +
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
  if (h && S.dirty && dirtyIds.size) h = `<p class="flag bad">Not saved yet: ${esc([...dirtyIds].map(i => LABEL[i.replace(/^x_/, "")] || i.replace(/^x_/, "")).join(", "))}. AI checks the saved card. Save, then check again.</p>` + h;   // reviewer r7
  // round 11 (reviewer r10 blocker 1): the AI is labelled plainly. It is a spelling/typo double-check, advisory only.
  if (h) h += `<p class="small aiNote">AI suggestions can be wrong. Check the photo.</p>`;
  // audit 2026-10: #rAI is no longer a live region (it was replaced every 4 s and re-announced); a state change is announced
  // once by the toast. Unchanged content is not rewritten, so focus on its buttons survives the poll.
  box.hidden = !h; if (box._h !== h || box.dataset.cid !== String(d.id)) { box.innerHTML = h; box._h = h; box.dataset.cid = d.id; }
  box.querySelectorAll("[data-aik]").forEach(b => b.onclick = async () => {
    const k = b.dataset.aik, ch = b.dataset.aic;
    // round 12 (coordinator r4 #4): a second AI choice clicked while the first one was still reloading the card used the old
    // card version, was refused, and "Keep current" was lost. Now the buttons are locked until the card is re-read, and the
    // choice is sent with the version on screen right now (retried once if the card changed meanwhile).
    if (!S.cur || S.cur.id !== d.id) return;
    box.querySelectorAll("[data-aik]").forEach(x => x.disabled = true);
    const send = async (extra) => { try { return await post(`/api/cards/${d.id}/ai-decide`, {choices: {[k]: ch}, version: S.cur.version, ...extra}); }
      catch (e) { if (e.data && e.data.need === "stale") { const n = await call("/api/cards/" + d.id); S.cur.version = n.version; return await post(`/api/cards/${d.id}/ai-decide`, {choices: {[k]: ch}, version: n.version, ...extra}); } throw e; } };
    if (S.dirty) {   // unsaved typing on the form: merge here in the browser, never on the server
      if (ch === "accept" && !setFormField(k, diff[k].to)) { toast("Save your edits first, then choose.", 4000); return; }
      try { await send({record_only: true}); toast(ch === "accept" ? `AI value put in ${LABEL[k] || k}. Save to keep it.` : "Kept the current value.", 4000); refreshUndo(); await openCard(d.id, {keep: true}); }
      catch (e) { toast("Not saved: " + e.message, 5000); box.querySelectorAll("[data-aik]").forEach(x => x.disabled = false); }
      return;
    }
    try { await send({}); toast(ch === "accept" ? "AI value used." : "Kept the current value.", 4500, true); await openCard(d.id); }
    catch (e) { toast("Not saved: " + e.message, 5000); box.querySelectorAll("[data-aik]").forEach(x => x.disabled = false); } });
  if ($("#aiAsk")) $("#aiAsk").onclick = async () => { const typed = S.dirty; try { const r = await post(`/api/cards/${d.id}/ai-check`, {}); toast("AI double-check started" + (r.ahead ? ` (${r.ahead} ahead of it)` : "") + (typed ? ". It checks the saved card, not unsaved edits." : "."), typed ? 7000 : 3500); openCard(d.id, {keep: true}); } catch (e) { toast(e.message, 5000); } };
  if (s === "queued" || s === "checking") rPoll = setTimeout(async () => {
    if (document.hidden) { renderAI(d); return; }   // audit 2026-10: no polling while the tab is hidden
    if (!$("#v-review").hidden && S.cur && S.cur.id === d.id && ($("#dlg").open || DECIDING)) { renderAI(d); return; }   // round 15 (part-timer r14): never reload the card under an open question (the merge dialog vanished); try again later
    if ($("#v-review").hidden || !S.cur || S.cur.id !== d.id || S.SAVING) return;   // round 10: root cause of the ghost "unsaved" badge: this
    const n = await call("/api/cards/" + d.id);                                 // poll re-opened the card with the TYPED values while a save was in flight
    if (S.SAVING || !S.cur || S.cur.id !== d.id) return;
    if ($("#dlg").open || DECIDING) { renderAI(d); return; }   // round 17 (part-timer r16 #1): a question opened while this poll waited stays open; try again later
    if (n.ai_status === s) return renderAI(n);
    const kept = S.dirty; await openCard(d.id, {keep: true});
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
  const adm = S.ME && S.ME.role === "admin", all = (ov || []).filter(k => k !== "phones");
  const mine = all.filter(k => adm || !((S.cur && S.cur.admin_override) || CONF_ADMIN).includes(k));
  const hard = Object.keys(hardNow || (S.cur && S.cur.hard) || {}), askAdm = !adm && hard.some(k => CONF_ADMIN.includes(k));
  if (!mine.length && !askAdm) return;
  const lab = k => LABEL[k === "name" ? "first_name" : k] || k;
  $("#rErr").insertAdjacentHTML("beforeend", `<p class="small conf">${mine.length ? "Photo agrees? " + mine.map((k, i) => `<button type="button" class="btn small" data-confirm="${esc(k)}"${i ? "" : ' id="bConfirmOk"'}>Confirm ${esc(lab(k))}</button>`).join(" ") : ""}${askAdm ? `${mine.length ? " " : ""}<span id="askAdmin">Card really says this? Ask an admin to confirm it.</span>` : ""}</p>`);
  $$("#rErr [data-confirm]").forEach(b => b.onclick = async () => {
    if (recomputeDirty()) { toast("Save first, then confirm the saved value.", 4000); return; }
    const k = b.dataset.confirm, fk = k === "name" ? "first_name" : k, v = S.cur.card.fields[fk], vs = Array.isArray(v) ? v.join(", ") : (v || "");
    const r = await ask({title: `Confirm ${lab(k)}?`, html: `<p><b>${esc(vs)}</b></p>`, input: {label: "Why is it correct? (at least 3 letters)", placeholder: "e.g. printed like this on the card", required: "A reason is needed.", max: 300},
      check: t => (t.replace(/[\u200b-\u200d\ufeff]/g, "").match(/[\p{L}\p{N}_]/gu) || []).length < 3 ? "Write a short reason (at least 3 letters)." : /^[=+\-@]/.test(t) || /<\s*[a-z\/!]|&#|javascript:/i.test(t) ? "The reason can't contain formulas or HTML code." : null,
      buttons: [{label: "Confirm", cls: "primary", value: 1, primary: true, needInput: true}, {label: "Cancel", value: null}]});
    if (!r.value) return;
    if (!(r.input || "").trim()) { toast("A reason is needed.", 4000); return; }
    try { const r1 = await post(`/api/cards/${sid}/confirm-correct`, {field: k, value: v, version: S.cur.version, reason: r.input}); S.cur.version = r1.version || S.cur.version;
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
      const sid = S.cur.id; if (tid === sid) { toast("A card can't be merged into itself.", 5000); return; }
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
async function act(btn, extra, okMsg, sid = S.cur && S.cur.id) {
  if (!S.CARD_READY || !S.cur) { toast("Wait for the card to finish loading before saving.", 4000); return; }
  if (S.SAVING && !await waitSaveIdle()) { toast("Not saved: the last save is still running. Try again in a moment.", 6000); return; }   // round 14
  // round 11 (part-timer r4 CRITICAL): the card is fixed when the action starts. If the page moved to another card meanwhile
  // (e.g. while the merge dialog was open), nothing is saved: before, the merge was sent for the card now on screen, so the
  // TARGET was merged into itself and rejected.
  if (!S.cur || S.cur.id !== sid) { toast(`Not saved: you moved from card #${sid} to another card. Open #${sid} and try again.`, 7000); return; }
  $$("#rDupQ button, #rDupC button").forEach(b => { if (b !== btn) b.disabled = true; });
  clearTimeout(rPoll); S.SAVING = true; try {
  await busy(btn, "Saving…", async () => {
    try { const sent_ = formSnap(); const r = await post("/api/cards/" + sid, {fields: collect(), reviewer: who(), note: $("#note").value, card_id: sid, version: S.cur.version, ...extra}); clearTimeout(keepDraft.t); markSaved(sid, sent_); toast(r.notice || okMsg, r.notice ? 7000 : 4500, true); await openCard(S.cur.id, {keep: true}); refreshCounts(); }
    catch (e) { toast("Not saved: " + e.message, 5000); }
  }); } finally { S.SAVING = false; recomputeDirty(); }   // round 21: never a stuck 'Saving…' after a refused save
}
const dlgStopped = r => { if (r && r.cancelled) toast("Not saved: the question closed first. Your edits are still on the form.", 8000); };   // round 14
let DECIDING = 0;   // round 17 (reviewer r16 N3, part-timer r16 #1): one decision at a time; the AI poll never re-renders under it
async function decide(status, btn) {
  if (!S.cur || $("#dlg").open) return;
  if (DECIDING && status) return;   // a double-click on Approve: the second click is ignored (no "question was closed" toast)
  DECIDING++; try { return await decide_(status, btn); } finally { DECIDING--; }
}
async function decide_(status, btn) {
  if (!S.CARD_READY) { toast("Wait for the card to finish loading before saving.", 4000); return; }
  const sid = S.cur.id;   // round 11 (part-timer r4): the card is fixed when the action starts (see act())
  // round 14 (LOST SAVE): a click while the previous save is still running used to be ignored without a word (busy button).
  // It now waits for that save, then saves what is on the form at that moment.
  if (S.SAVING || btn.getAttribute("aria-busy") === "true") {
    toast("Saving your previous change first…", 2500);
    if (!await waitSaveIdle()) { await ask({title: "Not saved", html: "<p>The last save is still running. Your edits are still here. Save again in a moment.</p>", buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return; }
    if (!S.cur || S.cur.id !== sid) { toast(`Not saved: you moved from card #${sid} to another card.`, 6000); return; }
  }
  const sent = formSnap();
  const body = {fields: collect(), status, reviewer: who(), note: $("#note").value, card_id: sid, version: S.cur.version};
  // round 13 (part-timer r5): the AI status on screen can be out of date (queued or started after the page loaded): ask the
  // server first, so the "AI check hasn't finished" prompt always shows, and an AI-only change never gives a silent 409
  clearTimeout(rPoll);   // round 14: no AI-poll reload while this decision is being prepared
  let fr0 = null; if (status === "approved" || status === "rejected") { try { fr0 = await call("/api/cards/" + sid); } catch {} }
  if (fr0 && S.cur && S.cur.id === sid && JSON.stringify([fr0.card.fields, fr0.card.status, fr0.card.note || ""]) === JSON.stringify([S.cur.card.fields, S.cur.card.status, S.cur.card.note || ""])) body.version = fr0.version;
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
      try { const fr_ = await call("/api/cards/" + sid); body.version = fr_.version; S.cur.version = fr_.version; } catch {} } } catch {} }
  const aiWas = fr0 ? fr0.ai_status : S.cur.ai_status;   // approving doesn't wait for the AI; a queued check is cancelled, a running one leaves suggestions
  // round 15 (part-timer): ONE dialog for AI-not-finished + already-known cross-batch look-alikes (no two questions in a row)
  // round 20 (reviewer r19): cards already marked "Different person" don't bring back the 'may send twice' warning
  const keptIds = new Set(((S.cur.dupes || {}).queue || []).filter(x => x.kept_apart).map(x => x.card_id));
  const xe0 = status === "approved" && !S.cur.dup_decided ? (S.cur.exported_elsewhere || []).filter(x => (x.times || 0) > 0 && !keptIds.has(x.card_id)) : [];
  // round 23 (newcomer r22): a choice already made on the card (or 'Different person' when adding as new is the only choice) is sent, so it is not asked again
  if (status === "approved" && S.cur.dupes && !body.crm_action) { if (S.cur.dupes.crm_action) body.crm_action = S.cur.dupes.crm_action; else if (S.cur.dup_decided && (S.cur.dupes.crm || []).length && !S.cur.dupes.updates_enabled) body.crm_action = "create_new"; }
  const aiBusy = (status === "approved" || status === "rejected") && ["queued", "checking"].includes(aiWas) && S.cur.status === "pending";
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
    try { const fr = await call("/api/cards/" + sid); if (JSON.stringify([fr.card.fields, fr.card.status, fr.card.note || ""]) === JSON.stringify([S.cur.card.fields, S.cur.card.status, S.cur.card.note || ""])) body.version = fr.version; } catch {}
  }
  clearTimeout(rPoll); S.SAVING = true; recomputeDirty();
  try { await busy(btn, status === "approved" ? "Approving…" : status === "rejected" ? "Rejecting…" : "Saving…", async () => {
    for (let tries = 0; tries < 5; tries++) {
      try {
        if (!S.cur || S.cur.id !== sid) { toast(`Not saved: you moved from card #${sid} to another card. Your edits on #${sid} are kept as a draft.`, 7000); return; }
        // round 15 (part-timer): values typed WHILE the save/approve was waiting (dialogs, network) are included, not lost
        body.fields = collect(); body.note = $("#note").value;
        const saved = await post("/api/cards/" + sid, body);
        if (saved && saved.version && S.cur && S.cur.id === sid) S.cur.version = saved.version;   // round 14: the next quick save uses the new version at once
        if (saved && saved.card) LASTOK[sid] = JSON.stringify([saved.card.fields, saved.card.status, saved.card.note || ""]);
        clearTimeout(keepDraft.t); delete SS.draft; markSaved(sid, sent);   // reviewer r8 / round 12 / round 14: no ghost draft or badge after a save
        await refreshCounts(); STATUS[sid] = saved.status;
        if (status === "approved" || status === "rejected") {
          toast(`✓ Card #${sid} ${status} by ${who()}.` + (["queued", "checking"].includes(aiWas) ? (aiWas === "queued" ? " The waiting AI check was cancelled." : " Any AI suggestions will appear on the card later.") : ""), 3500, true);
          // round 8 (part-timer r2): 'Next' stays inside THIS card's batch, asked from the server (also when the card was opened
          // by a direct link); "All done" only when that batch has no pending card left at all
          const myB = S.cur.batch || null, o = order(), i = o.indexOf(sid);
          let pl = null; try { const qs = new URLSearchParams({status: "pending"}); if (myB) qs.set("batch", myB); else qs.set("limit", "500"); pl = (await call("/api/cards?" + qs)).filter(x => x.id !== sid); } catch {}   // audit 2026-10: capped without a batch
          let nx2;
          if (pl) { const ids = new Set(pl.map(x => x.id));
            nx2 = (i >= 0 ? (o.slice(i + 1).find(x => ids.has(x)) ?? o.slice(0, i).find(x => ids.has(x))) : undefined) ?? (pl.find(x => x.id > sid) || pl[0] || {}).id; }
          else { const pend = x => x !== sid && STATUS[x] === "pending"; nx2 = i >= 0 ? (o.slice(i + 1).find(pend) ?? o.slice(0, i).find(pend)) : undefined; }
          const bq = "#queue?s=pending&batch=" + encodeURIComponent(myB || "__none__");
          if (nx2 !== undefined) { if (pl && pl.length > 1) toast(`✓ Card #${sid} ${status}. ${plural(pl.length, "card")} still pending in this batch.`, 3000, true); location.hash = "review/" + nx2; }
          else if (pl) { try { if (S.cur && S.cur.id === sid) await openCard(sid, {keep: true}); } catch {}   // round 15 (newcomer r14): the card behind the dialog shows its new status
            const msg_ = `All done: no pending cards are left in ${S.cur.batch_label || "this batch"}.`; location.hash = bq; setTimeout(() => toast(msg_, 6000), 400); }   // after the route change (it clears toasts)   // round 22: a toast, not one more dialog
          else { toast("Couldn't check what is still pending: back to the queue.", 4000); location.hash = bq; }
        } else {
          const sp = saved.save_problems || {};
          toast(saved.notice || (status === "pending" ? `Card #${sid} moved back to pending.` : Object.keys(sp).length ? "Saved, but it can't be approved yet: " + Object.values(sp).join(" ") : "Changes saved."), saved.notice || Object.keys(sp).length ? 7000 : 4500, true);
          if (S.cur && S.cur.id === sid && location.hash === "#review/" + sid) await openCard(sid, {keep: true});   // round 12; round 14: keep typing done during the save: never pull the view back to a card the person already left
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
            buttons: [...(S.cur.dupes.updates_enabled ? [{label: "Same person: update their contact", cls: "primary", value: "update_existing", primary: true}] : []), {label: "Different person: add as new", value: "create_new", ...(S.cur.dupes.updates_enabled ? {} : {cls: "primary", primary: true})}, {label: "Cancel", value: null}]});
          if (!r.value) { dlgStopped(r); return; } body.crm_action = r.value; continue;
        }
        // round 13 (part-timer r5): never fail silently: say why in a dialog, not only a short toast
        await ask({title: status === "approved" ? "Not approved" : status === "rejected" ? "Not rejected" : "Not saved", html: `<p>${esc(e.message)}</p><p class="small">Nothing changed. Your edits are still here.</p>`, buttons: [{label: "OK", cls: "primary", value: 1, primary: true}]}); return;
      }
    }
  }); } finally { S.SAVING = false; recomputeDirty(); }   // round 21: never a stuck 'Saving…' after a refused save
}
$("#bApprove").onclick = e => decide("approved", e.currentTarget); $("#bReject").onclick = e => decide("rejected", e.currentTarget);
$("#bSave").onclick = e => decide(null, e.currentTarget); $("#bPending").onclick = e => decide("pending", e.currentTarget);
const step = d => { const o = S.cur ? navOrder(S.cur.id) : order(), i = o.indexOf(S.cur?.id);
  // opened from a link (not in the current queue list): J/K go to the nearest card of the list by number
  const n = i >= 0 ? o[i + d] : (d > 0 ? o.filter(x => x > S.cur.id).sort((a, b) => a - b)[0] : o.filter(x => x < S.cur.id).sort((a, b) => b - a)[0]);
  if (n !== undefined) location.hash = "review/" + n; else toast(d > 0 ? "No next card in the queue list." : "No previous card in the queue list."); };
$("#backFile").onchange = async e => {
  const file = e.target.files[0]; e.target.value = ""; if (!file || !S.cur) return;
  if (S.dirty) { toast("Save your edits first, then add the back.", 4000); return; }
  const send = confirm => { const fd = new FormData(); fd.append("image", file); if (confirm) fd.append("confirm_other_person", "1"); return call(`/api/cards/${S.cur.id}/back`, {method: "POST", body: fd}); };
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
      (r.not_added && Object.keys(r.not_added).length ? " Not added (not clearly printed, or doesn't match the card's email): " + Object.entries(r.not_added).map(([k, v]) => (LABEL[k] || k) + " " + [].concat(v).join(", ")).join("; ") + ". Type it in if it is right." : ""), r.not_added && Object.keys(r.not_added).length ? 9000 : 4000, true); openCard(S.cur.id); }
  catch (x) { hideToast(/^Reading the back/); toast("Not added: " + x.message, 5000); }
  finally { hideToast(/^Reading the back/); }
};
$("#bDelete").onclick = async () => {
  const r = await ask({title: `Delete card #${S.cur.id} permanently?`, html: "<p>For removal requests. Deletes the photo, details and stored export copies. This can't be undone. The audit log keeps who did what and when, with personal details removed. Files already in MC Trade must be removed there.</p><details class=\"more small\"><summary>More</summary>Export files already downloaded to a computer must be deleted there too.</details>",
    buttons: [{label: "Delete permanently", cls: "danger", value: 1}, {label: "Cancel", value: null, primary: true}]});
  if (!r.value) return;
  try { const x = await post(`/api/admin/cards/${S.cur.id}/delete`, {confirm: S.cur.id}); toast(`Card #${x.deleted} deleted.`); location.hash = SS.queueHash || "queue"; refreshCounts(); }
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
export {dirtyVals, openCard};
