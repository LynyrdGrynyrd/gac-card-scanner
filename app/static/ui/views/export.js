// Export page: checks, sign-off, downloads (and what was really saved), export history.
import {S} from "../core/state.js";
import {$, $$, SS, esc, plural, when} from "../core/dom.js";
import {call, fetchOk, post} from "../core/api.js";
import {toast} from "../ui/toast.js";
import {ask} from "../ui/dialog.js";
import {refreshCounts} from "../header.js";
const HK = {xlsx: "Excel", csv: "CSV", vcf: "vCard"};   // v0.3.2: short export history rows

/* ---------- export ---------- */
async function exportInfo() {
  const st = $("#exStatus").value, eb = $("#exBatch").value; $("#exInfo").textContent = "Checking…";
  // v0.4.4 #6 (reviewer: another batch's "2 ready" / "0 cards ready" for 2-3 s): a newer check wins; until then, "Loading…"
  const seq = exportInfo.seq = (exportInfo.seq || 0) + 1;
  // v0.4.5 (reviewer e, item 10): one "Loading…" only, and Export can't be pressed until the count is known
  if ($("#exBig")) { $("#exBig").textContent = ""; $("#exBigT").textContent = "Loading…"; } $$(".tile").forEach(t => t.disabled = true);
  try {
    if (!exportInfo.busyList) {   // refreshed every time (manager L-new3: a new batch showed only after a reload)
      exportInfo.busyList = true; let bs; try { bs = await call("/api/batches"); exportInfo.list = bs; } finally { exportInfo.busyList = false; }
      let keepB = exportInfo.picked ? $("#exBatch").value : "";   // round 22: a fresh visit picks the default below (never a stale empty batch)   // the person may have picked a batch while the list was loading (r15int: "All batches" = "" is a real pick too)
      // round 7 (part-timer r1): your own batches first, and the default is your most recent batch, not "All batches"
      const cnt = b => st === "approved_new" ? `${b.ready ?? b.n} ready to export` : st === "approved" ? `${b.approved ?? b.n} approved` : `${plural(b.n, "card")}`;
      // v0.4.6 #7: two batches with the same name are told apart ("Monday (2)"), oldest first
      const dn = {}, seenN = {}; [...bs].sort((a, b) => (a.started || 0) - (b.started || 0)).forEach(b => { const l = b.batch_label || b.batch; seenN[l] = (seenN[l] || 0) + 1; dn[b.batch] = seenN[l] > 1 ? `${l} (${seenN[l]})` : l; });
      const opt = b => `<option value="${esc(b.batch)}">${esc(dn[b.batch] || b.batch_label || b.batch)} · ${cnt(b)}</option>`;
      // v0.4.2 #1: a reviewer can export only their own batches (the server refuses the rest); admins see everyone's
      const adm = S.ME && S.ME.role === "admin", others = adm ? bs.filter(b => !b.mine) : [];
      const rdy0 = b => (st === "approved_new" ? (b.ready ?? b.n) : st === "approved" ? (b.approved ?? b.n) : b.n) > 0, old0 = b => (b.started || 0) < Date.now() / 1000 - 14 * 86400;
      // v0.4.6 #7: batches with nothing to export are left out (a reviewer's always, an admin's old ones), except the one in use
      const mine = bs.filter(b => adm ? b.mine : b.own).filter(b => rdy0(b) || b.batch === exportInfo.last || ($("#exShowAll") && $("#exShowAll").checked) || (adm && !old0(b)));
      // round 8 (part-timer r2): your batches first; other people's only with "Show other people's batches too"
      const showAll = ($("#exShowAll") && $("#exShowAll").checked) || exportInfo.more, othShown = showAll ? others : others.filter(b => b.batch === keepB);
      const rdy = b => (st === "approved_new" ? (b.ready ?? b.n) : st === "approved" ? (b.approved ?? b.n) : b.n) > 0;
      if (SS.exportFrom) { const fb_ = bs.find(b => b.batch === SS.exportFrom); if (fb_ && fb_.mine && rdy(fb_) && !exportInfo.picked) keepB = SS.exportFrom; delete SS.exportFrom; }   // round 23: only your own   // round 22 (newcomer r21 HIGH): only when it has cards ready   // round 21 (newcomer r20 HIGH): the batch you came from / just finished
      // round 23 (mctrade-admin/reviewer r22 M2): the default is YOUR OWN newest batch from TODAY, or nothing ("Choose a batch");
      // never another tester's or an old batch. The list shows only that batch plus "More batches…" until More is chosen.
      if (!exportInfo.picked && !keepB) {
        const nw = (a, b) => (b.started || 0) - (a.started || 0), d0 = new Date(); d0.setHours(0, 0, 0, 0);
        const today = mine.filter(b => b.own && (b.started || 0) >= d0 / 1000).sort(nw);
        // v0.4.1 #7 (mctrade-admin M1): the CURRENT batch (the one on the Scan page), else your own batch from today, else "Choose a batch…"
        const curB = S.B && S.B.t0 && new Date(S.B.t0 * 1000).toDateString() === new Date().toDateString() && bs.find(b => b.batch === S.B.id && (b.own || S.ME.role === "admin"));   // v0.4.2 #5: today's only
        const def = curB || today[0]; keepB = def ? def.batch : "__choose__"; }
      const cur_ = bs.find(b => b.batch === keepB);
      $("#exBatch").innerHTML = (keepB === "__choose__" ? `<option value="__choose__">Choose a batch…</option>` : "") +
        (showAll ? (mine.length ? `<optgroup label="Your batches">${mine.map(opt).join("")}</optgroup>` : "") + (others.length ? `<optgroup label="Other people's batches">${others.map(opt).join("")}</optgroup>` : "") + (adm ? `<option value="">All batches (everyone's)</option>` : "")
                 // v0.4.5 (reviewer d): your own batches are listed straight away; "More batches…" is only for other people's (admins)
                 : [...mine].sort((a, b) => (b.started || 0) - (a.started || 0)).map(opt).join("") + (cur_ && !mine.includes(cur_) && adm ? opt(cur_) : "") + (keepB === "" && adm ? `<option value="">All batches (everyone's)</option>` : "") + (adm && others.length ? `<option value="__more__">More batches…</option>` : ""));
      if ($("#exShowAll")) { $("#exShowAll").nextElementSibling.textContent = adm ? " Show all batches" : " Show all my batches"; }
      $("#exBatch").value = [...$("#exBatch").options].some(o => o.value === keepB) ? keepB : ($("#exBatch").options[0] || {}).value || ""; filterExBatch(); }
    if ($("#exBatch").value !== "__more__") exportInfo.last = $("#exBatch").value;
    if ($("#exBatch").value === "__choose__") {   // nothing chosen: nothing to export, no check
      $("#exInfo").textContent = "Choose a batch."; if ($("#exBig")) { $("#exBig").textContent = "–"; $("#exBigT").textContent = "Choose a batch"; } $("#exDup").hidden = true; $$(".tile").forEach(t => t.disabled = true); loadExportHistory(); return {count: 0}; }
    if ($("#exBatch").value !== eb) { if (!exportInfo.depth) { exportInfo.depth = 1; try { return await exportInfo(); } finally { exportInfo.depth = 0; } } }   // selection changed meanwhile: check the batch actually shown
    const r = await call(`/api/export/check?status=${st}&batch=${encodeURIComponent(eb)}`);
    if (seq !== exportInfo.seq || $("#exBatch").value !== eb || $("#exStatus").value !== st) return r;   // stale answer: a newer check is on its way
    { const o_ = $("#exBatch").selectedOptions[0];   // v0.4.3 #4 (reviewer: "0 ready" in the list next to "2 cards ready"): the check is the one count
      if (o_ && eb && st === "approved_new" && typeof r.count === "number") o_.textContent = o_.textContent.replace(/· \d+ ready to export$/, `· ${r.count} ready to export`); }
    const bo_ = (exportInfo.list || []).find(b => b.batch === eb), notMine = eb === "" || (bo_ && !bo_.own);   // v0.4.1 #7: say whose batch it is, on the page
    // v0.4.2 #6 (reviewer: only a small chip): a full warning line, not a chip
    $("#exOwner")?.remove();
    if (notMine && r.count) $("#exInfo").insertAdjacentHTML("beforebegin", `<p class="alert bad" id="exOwner" role="status"><b>${eb === "" ? "All batches: this includes other people's cards." : `Not your batch: ${esc(bo_.owner || "someone else")} scanned it.`}</b> You will be asked before export.</p>`);
    $("#exInfo").innerHTML = "" + `${r.count ? "" : (!$("#exDone").hidden && $("#exDone").classList.contains("ok") && $("#exDone").dataset.batch === eb) ? "All cards in this batch are exported." : "Nothing to export yet. Approve some cards first."}` +
      (r.flagged && r.flagged.length ? `<span class="flag bad">To check: ${r.flagged.length} (${r.flagged.slice(0, 5).map(i => `<a href="#review/${i}" aria-label="Open card #${i}">#${i}</a>`).join(", ")}${r.flagged.length > 5 ? " …" : ""}).</span>` : "");   // v0.4.1 #4: same count as the preview and the sheet

    $("#exDup").hidden = !r.duplicates.length;
    // round 7: no button per pair (part-timer/newcomer: a flood of buttons that write onto other people's cards). The pairs are
    // a review list of links; open a card to decide. Only an admin gets "mark all", behind a confirm that lists the pairs.
    const pairsAll = r.duplicates.flatMap(p => p.with.filter(w => !(p.strong || []).includes(w)).map(w => [p.id, w]));
    $("#exDup").innerHTML = r.duplicates.length ? `<b>Export is blocked: some cards look like the same person.</b> ${eb ? "Open each card to merge, or mark them as different people there." : "<b>Tip:</b> choose your own batch; other people's look-alikes don't block it."}` +
      (!eb && r.ok_batches && r.ok_batches.length ? `<p>These batches can be exported now: ${r.ok_batches.map(b => `<a href="#" data-xbatch="${esc(b.batch)}">${esc(b.label)}</a> (${b.count})`).join(", ")}</p>` : "") +
      `<details${eb ? " open" : ""}><summary>Review list: ${plural(r.duplicates.length, "card")} with look-alikes</summary><ul>${r.duplicates.map(p => `<li><a href="#review/${p.id}">Card #${p.id}</a>${p.batch ? ` <span class="sub">(${esc(p.batch)})</span>` : ""} may duplicate ${p.with.map(w => `<a href="#review/${w}" aria-label="Open card #${w}">#${w}</a>` + ((p.strong || []).includes(w) ? ` <span class="sub">(duplicate scan: merge or reject one)</span>` : "")).join(", ")}</li>`).join("")}</ul></details>` : "";
    const pairs = S.ME.role === "admin" ? pairsAll : [];
    if (pairs.length > 1) {
      $("#exDup").insertAdjacentHTML("beforeend", `<p class="small">Admin only: <button class="btn small" id="xKeepAll">Mark all ${pairs.length} listed pairs as different people…</button> (check the list first)</p>`);
      $("#xKeepAll").onclick = async () => {
        const r = await ask({title: `Mark ${pairs.length} pairs as different people?`, html: `<p>This saves a “different person” link on each listed card for the card next to it (${esc(pairs.slice(0, 12).map(([a, w]) => `#${a}↔#${w}`).join(", "))}${pairs.length > 12 ? "…" : ""}). Duplicate scans aren't included. Undo is available.</p>`,
          buttons: [{label: "Mark them all", cls: "primary", value: 1, primary: true}, {label: "Cancel", value: null}]});
        if (!r.value) return; let ok = 0, bad = 0;
        for (const [a, w] of pairs) { try { const cv = (await call(`/api/cards/${a}`)).version; await post(`/api/cards/${a}`, {keep_apart: [w], card_id: a, version: cv}); ok++; } catch { bad++; } }
        toast(`${ok} pair(s) marked as different people` + (bad ? `, ${bad} not changed (open them)` : "") + ".", 4000, ok > 0); exportInfo(); };
    }
    $("#exDup").querySelectorAll("[data-xbatch]").forEach(a => a.onclick = e => { e.preventDefault(); $("#exBatch").value = a.dataset.xbatch; exportInfo(); });
    // v0.4.8 #1: the big number is the rows really going into the import file (never "1 card ready" over an empty file)
    const xl_ = (($("input[name=exKind]:checked") || {}).value || "xlsx") === "xlsx" && typeof r.rows === "number" && r.count > 0;
    const none_ = xl_ && r.rows === 0, admHeld = none_ && r.held > 0 && S.ME && S.ME.role === "admin";
    $$(".tile").forEach(t => t.disabled = !r.count || r.duplicates.length > 0 || (none_ && !admHeld)); loadExportHistory();
    if ($("#exBig")) { const n_ = xl_ ? r.rows : r.count; $("#exBig").textContent = n_;
      $("#exBigT").textContent = none_ ? "Nothing new to import." : xl_ ? (n_ === 1 ? "row ready" : "rows ready") : (n_ === 1 ? "card ready" : "cards ready"); }
    return r;
  } catch (e) { $("#exInfo").textContent = "Couldn't check: " + e.message; if ($("#exBigT") && $("#exBigT").textContent === "Loading…") $("#exBigT").textContent = "Couldn't check"; }
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
        const tbl = (h, rows) => `<div style="overflow:auto;max-height:40vh"><table class="aidiff pv"><thead><tr>${h.map(x => `<th scope="col">${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.map(r_ => `<tr>${r_.map(cell).join("")}</tr>`).join("") || `<tr><td colspan="${h.length}">none</td></tr>`}</tbody></table></div>`;
        const rn = v.row_notes || [], nChk = rn.filter(Boolean).length;   // v0.4.2 #3: an MC Trade look-alike is marked, not shown as a plain new profile
        const a = await ask({title: "Preview of the MC Trade files", html: `<p class="small">Nothing is downloaded or marked as exported.</p><p>${esc(v.source_text)}</p>` +
          // v0.4.3 #4: possible MC Trade matches get their own "Needs review" list, as in the dry run and the CSV Check column
          // v0.4.4 #3: the same 'To check' list (and number) as the page, the Save dialog and the READ-ME
          ((v.to_check_ids || []).length ? `<p><b>To check (${v.to_check_ids.length})</b></p><ul>${v.to_check_ids.map(i => `<li><a href="#review/${esc(i)}" aria-label="Open card #${esc(i)}">#${esc(i)}</a>${(v.mc_possible || {})[i] ? ": " + esc((v.mc_possible || {})[i]) : ""}</li>`).join("")}</ul>` : "") +
          `<p><b>New profiles (${plural(v.rows.length, "row")})</b></p>` + tbl(["Check", "Card", ...v.headers], v.rows.map((r_, i) => [rn[i] || "", v.row_ids ? "#" + v.row_ids[i] : "", ...r_])) +
          (v.updates.length ? `<p><b>UPDATES file (${v.updates.length})</b></p>` + tbl(v.headers, v.updates) : "") +
          `<p><b>Left out (${v.left.length})</b></p>` + tbl(["Card", "Why"], v.left.map(x => ["#" + x[0], x[1]])) +
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
$$("input[name=exKind]").forEach(x => x.onchange = () => exportInfo());   // v0.4.8 #1: rows for Excel, cards for CSV/vCard
$("#exBatch").onchange = () => { if ($("#exDone").dataset.batch !== $("#exBatch").value) $("#exDone").hidden = true;   // round 23 (newcomer r22): no stale success box for another batch
 if ($("#exBatch").value === "__more__") { if ($("#exShowAll")) $("#exShowAll").checked = true; exportInfo.more = true; $("#exBatch").value = exportInfo.last ?? ""; exportInfo.picked = true; exportInfo(); return; } exportInfo.picked = true; exportInfo(); };
function filterExBatch() { const t = ($("#exBatchQ")?.value || "").toLowerCase().trim();
  [...$("#exBatch").options].forEach(o => { o.hidden = !!t && o.value !== "" && !o.textContent.toLowerCase().includes(t); }); }
$("#exBatchQ") && ($("#exBatchQ").oninput = filterExBatch);
let exHistShow = 10;
$("#exHistMoreBtn").onclick = () => { exHistShow += 10; loadExportHistory(); };
$("#exHistAllBtn").onclick = () => { exHistShow = Infinity; loadExportHistory(); };
async function loadExportHistory() {
  const every = await call("/api/exports"), everyone = S.ME && S.ME.role === "admin" && $("#exHistEveryone") && $("#exHistEveryone").checked;   // part-timer r3: yours by default
  const all = everyone ? every : every.filter(x => x.own), h = all.slice(0, exHistShow);
  $("#exHistMore").hidden = all.length <= h.length; $("#exHistCount").textContent = `${h.length} of ${all.length} shown` + (everyone ? " (everyone's)" : "");
  $("#exHist").innerHTML = h.map(x => `<tr><td>${esc(when(x.ts))}</td><td>${esc(x.initials)}</td><td>${esc(HK[x.kind] || x.kind.toUpperCase())}${x.batch_label ? `<div class="sub">${esc(x.batch_label)}</div>` : ""}</td><td>${x.count}</td>
    <td>${x.available ? `<a href="/api/exports/${x.id}/download" title="${esc(x.filename)}">Download</a>` + (x.companions || []).map(c => ` · <a href="/api/exports/${x.id}/companion/${c}">${c === "readme.txt" ? "READ-ME" : c === "updates.xlsx" ? "Updates" : c === "summary.xlsx" ? "Summary" : "Extra details"}</a>`).join("") : `<span title="${esc(x.filename)}">File</span> <span class="sub">(${x.mine ? "copy deleted" : "only " + esc(x.initials) + " or an admin can download it"})</span>`}</td></tr>`).join("") || `<tr><td colspan="5">No exports yet.</td></tr>`;
}
$("#exHistEveryone") && ($("#exHistEveryone").onchange = () => loadExportHistory());
const KIND = {xlsx: "MC Trade import (Excel)", csv: "Spreadsheet (CSV)", vcf: "Contacts (vCard)"};
$$(".tile").forEach(t => t.onclick = async () => {   // round 14 (parttimer r6): busy at once, one click only, checks in parallel
  if (t.getAttribute("aria-busy") === "true") return;
  t.setAttribute("aria-busy", "true"); const lbl0 = t.style.cursor; t.style.cursor = "progress"; toast("Preparing the export…", 1500);
  try { await tileExport(t); } finally { t.removeAttribute("aria-busy"); t.style.cursor = lbl0; }
});
let incChg = false;
document.addEventListener("change", e => { if (e.target && e.target.id === "exIncChg") incChg = e.target.checked; });   // v0.4.7 #2
async function tileExport(t) {
  incChg = false;
  const kind = ($("input[name=exKind]:checked") || {}).value || t.dataset.ex || "xlsx", st = $("#exStatus").value;
  const pre = kind === "xlsx" ? call(`/api/export/xlsx?preview=1&view=1&status=${st}&batch=${encodeURIComponent($("#exBatch").value)}`).catch(e => ({__err: e})) : null;
  const info = await exportInfo(); if (!info || !info.count || info.duplicates.length) return;
  { const eb_ = $("#exBatch").value, bo = (S.BATCHES || []).find(b => b.batch === eb_) || (exportInfo.list || []).find(b => b.batch === eb_);   // round 24 (reviewer r23): warn before exporting someone else's batch
    if (eb_ === "" || (bo && !bo.own)) { const who_ = bo && bo.owner ? bo.owner : "other people";
      const a_ = await ask({title: eb_ === "" ? "Export everyone's cards?" : `Export ${who_}'s batch?`, html: `<p class="alert bad">${eb_ === "" ? "All batches includes cards other people scanned." : `<b>${esc(bo.batch_label || bo.batch)}</b> was scanned by <b>${esc(who_)}</b>, not you. They may still be working on it.`}</p>`,
        buttons: [{label: "Cancel", cls: "primary", value: null, primary: true, focus: true}, {label: eb_ === "" ? "Export all" : `Export ${who_}'s batch`, value: 1}]});
      if (!a_.value) return; } }
  let so = "", seenV = info.versions || null, nUpd = 0;
  const shw = (n, html) => n ? ` <details class="more small" style="display:inline"><summary>Show</summary>${html}</details>` : "";   // round 21: a count + Show, not an id wall   // round 16: what the sign-off was made from; the export is refused if it changed
  // round 7: 'ready to export' sign-off: what goes in which file, and what still needs a decision
  if (kind === "xlsx") { try { const v = await pre; if (v && v.__err) throw v.__err; if (v && v.versions) seenV = v.versions; nUpd = (v && v.updates || []).length;
    if (v && v.rows) { const nm = r_ => [r_[v.headers.indexOf("IndFirstName")], r_[v.headers.indexOf("IndLastName")]].filter(Boolean).join(" ");
      so = `<div class="alert"><ul><li><b>${info.count}</b> approved card${(info.count) === 1 ? "" : "s"} checked</li>` +
        `<li><b>${v.rows.length}</b> new contact${(v.rows.length) === 1 ? "" : "s"}${shw(v.rows.length, esc(v.rows.map(nm).join(", ")))}</li>` +
        (v.updates.length ? `<li><b>${v.updates.length}</b> update${(v.updates.length) === 1 ? "" : "s"} to existing contacts: ${esc(v.updates.map(nm).join(", "))}</li>` : "") +
        ((v.update_diff || []).length ? `<li><b>What the updates change in MC Trade</b> (an import overwrites non-blank cells and can't be undone):<div style="overflow:auto;max-height:30vh"><table class="aidiff" data-updiff="1"><thead><tr><th>Card</th><th>Profile</th><th>Field</th><th>Now in MC Trade</th><th>After import</th></tr></thead><tbody>${v.update_diff.map(u => u.fields.map(x => `<tr${x.changes ? ' class="chg"' : ""}><td><a href="#review/${u.card}" aria-label="Open card #${u.card}">#${u.card}</a></td><td>${esc(u.profile_id)}</td><td>${esc(x.field)}</td><td>${x.old === null ? "<i>not in the contacts export: check in MC Trade</i>" : esc(x.old)}</td><td>${x.changes || x.changes === null ? "<b>" + esc(x.new) + "</b>" : esc(x.new)}</td></tr>`).join("")).join("")}</tbody></table></div></li>` : "") +
        ((v.sample_email_matches || []).length ? `<li>${v.sample_email_matches.map(i => `<a href="#review/${i}" aria-label="Open card #${i}">#${i}</a>`).join(", ")}: May already be in MC Trade (test list).</li>` : "") +
        (() => { const dz = v.decisions || {}, rv = v.left.filter(x => dz[String(x[0])] === "review"), HW = /^(Edited after export|Already exported)/, hd = v.left.filter(x => HW.test(x[1] || "")), lo = v.left.filter(x => dz[String(x[0])] !== "review" && !HW.test(x[1] || ""));   // v0.4.8 #1: the real reason for a held card   // same classification as the export + dry run
          return (rv.length ? `<li><b>${rv.length}</b> card${(rv.length) === 1 ? "" : "s"} to review (in neither file)${shw(rv.length, rv.map(x => `<a href="#review/${x[0]}" title="${esc(x[1])}">#${x[0]}</a>`).join(", "))}</li>` : "") +
                 [...new Set(hd.map(x => x[1]))].map(w => { const xs = hd.filter(x => x[1] === w); return `<li><b>${xs.length}</b> ${esc(w.replace(/, so it is not in this file\.$/, "").toLowerCase())} (not in this file)${shw(xs.length, xs.map(x => `<a href="#review/${x[0]}">#${x[0]}</a>`).join(", "))}</li>`; }).join("") +
                 (lo.length ? `<li><b>${lo.length}</b> card${(lo.length) === 1 ? "" : "s"} left out (combined with another row, or to fix first)${shw(lo.length, lo.map(x => `<a href="#review/${x[0]}" title="${esc(x[1])}">#${x[0]}</a>`).join(", "))}</li>` : ""); })() +
        (info.pending_count ? `<li><b>${info.pending_count}</b> card${(info.pending_count) === 1 ? "" : "s"} still <b>pending</b>${shw(info.pending_count, info.pending.slice(0, 30).map(x => `<a href="#review/${x.id}" aria-label="Open card #${x.id}">#${x.id} ${esc(x.name)}</a>`).join(", "))}</li>` : "") +
        `</ul></div>`; } } catch {} }
  // v0.4 #5: a summary sheet first ("12 new, 1 to check"); the counts come from the server's own export re-check
  let sum = null; try { sum = await call(`/api/export/summary?status=${st}&batch=${encodeURIComponent($("#exBatch").value)}`); } catch {}
  const stat = (l, n, w) => `<div class="stat"><span>${l}</span><b${w && n ? ' class="w"' : ""}>${n}</b></div>`;
  const sheet = sum ? (kind === "xlsx" ? stat("New contacts", sum.new) + stat("Updates", sum.updated) : stat("Cards", sum.count)) + stat(kind === "xlsx" ? "Of these, to check" : "To check", sum.to_check, true) +   /* v0.4.7 #9: not a third group */
    (kind === "xlsx" && sum.ready ? `<p class="small" id="exReady">${esc(sum.ready.text)}</p>` : "") +
    // v0.4.8 #1-3: cards already in an earlier import file are not in this one (MC Trade would add them twice); one plain line each
    (kind === "xlsx" && ((sum.changed_ids || []).length || (sum.repeat_ids || []).length) ? `<p class="small" id="exChanged">` +
      [[sum.changed_ids || [], "Edited after export, so not in this file"], [sum.repeat_ids || [], "Already exported, so not in this file"]].filter(x => x[0].length)
        .map(([ids, t_]) => `${t_}: ${ids.slice(0, 5).map(i => `<a href="#review/${i}" aria-label="Open card #${i}">#${i}</a>`).join(", ")}${ids.length > 5 ? " …" : ""}.`).join(" ") +
      (S.ME && S.ME.role === "admin" ? ` <label><input type="checkbox" id="exIncChg"> Include anyway</label>` : "") + `</p>` : "") +
    // v0.4.7 #4: admins see what is still waiting for them
    (sum.needs_admin || sum.needs_admin_all ? `<p class="small" id="exNA"><a href="#queue?s=pending&amp;batch=all&amp;na=1">${sum.needs_admin} waiting for admin</a> (not in this export)` +
      (sum.needs_admin_all && sum.needs_admin_all > sum.needs_admin ? ` · <a href="#queue?s=pending&amp;batch=all&amp;na=1">${sum.needs_admin_all} in all batches</a>` : "") + `.</p>` : "") : "";
  const bl_ = (exportInfo.list || []).find(b => b.batch === $("#exBatch").value);
  const r = await ask({title: "Ready to save", html: `<p>Batch: <b>${esc(bl_ ? bl_.batch_label || bl_.batch : "All batches")}</b></p>` + sheet + `<details class="more small"><summary>More</summary>` + so + `<p>Format: <b>${KIND[kind]}</b></p><p>Cards: <b>${esc($("#exStatus").selectedOptions[0].textContent)}</b></p><p class="small">${kind === "xlsx" && sum && !sum.new && !sum.updated ? `<b>Nothing new to import: no file is made${S.ME && S.ME.role === "admin" && ((sum.changed_ids || []).length || (sum.repeat_ids || []).length) ? " unless you tick Include anyway" : ""}.</b>` : kind === "xlsx" ? `<b>You'll get ${(sum && sum.ready && sum.ready.files) || (nUpd ? 5 : 4)} files. Import only IMPORT-ME${nUpd ? " (updates separately)" : ""}.</b> NOT-FOR-IMPORT files are for reading.` : "You'll get one file."}</p></details>`,
    buttons: [{label: "Cancel", value: null}, {label: "Save", cls: "primary", value: 1, primary: true}]});
  if (!r.value) return;
  t.setAttribute("aria-busy", "true");
  try {
    const sv = seenV ? Object.entries(seenV).map(([k, x]) => `&seen_${k}=${encodeURIComponent(x)}`).join("") : "";
    const res = await fetchOk(`/api/export/${kind}?status=${st}&batch=${encodeURIComponent($("#exBatch").value)}` + sv + (incChg ? "&include_changed=1" : ""));
    if ((res.headers.get("Content-Type") || "").includes("application/json")) {   // v0.4.8 #1: nothing new: no file is made, nothing is marked
      const j = await res.json(); $("#exDone").hidden = false; $("#exDone").className = "alert";
      $("#exDone").innerHTML = `<b>${esc(j.message || "Nothing new to import.")}</b> No file was made.` + (j.ready && j.ready.text && j.ready.text !== j.message ? `<br><span class="small">${esc(j.ready.text.replace(/^Nothing new to import\.\s*/, ""))}</span>` : "");
      $("#exDone").dataset.batch = $("#exBatch").value; exportInfo.picked = true; exportInfo(); return; }   // v0.4.8 #12: one message (the box), no toast
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
    $("#exDone").innerHTML = (sm ? `<b>✓ ${plural(sm.cards, "card")} exported` + (sm.update_rows ? ` (${plural(sm.new_rows, "new contact")}, ${plural(sm.update_rows, "update")})` : "") + (sm.crm_real ? "" : " (test MC Trade list)") + `.</b>` +
        (sm.left_ids.length ? ` <span class="flag bad">Not imported: ${sm.left_ids.map(i => `<a href="#review/${i}" aria-label="Open card #${i}">#${i}</a>`).join(", ")}.</span>` : "") +
        (sm.possible.length ? ` <span class="flag low">May already be in MC Trade: ${sm.possible.map(i => `<a href="#review/${i}" aria-label="Open card #${i}">#${i}</a>`).join(", ")}.</span>` : "")
      : `<b>✓ Exported ${plural(n, "card")}</b>.`) + (kind === "xlsx" ? (sm && sm.ready ? `<br>${esc(sm.ready.text)}` : "") +
        // v0.4.7 #11: a short import checklist after a real export
        `<ol class="small" id="exCheck"><li>Read the READ-ME.</li><li>Import only the IMPORT-ME file${comp.includes("updates.xlsx") ? " (updates: the UPDATES file, separately)" : ""}.</li>${sm && sm.ready ? "" : "<li>Test 2 rows first.</li>"}</ol>`   /* the Ready line already says "Test 2 rows first." */ : "");
    const lost = lostFiles(outs);   // audit 2026-10: a cancelled Save dialog (desktop app) is said, never claimed as saved
    if (lost.length) $("#exDone").insertAdjacentHTML("beforeend", `<br><span class="flag bad">Not saved: ${esc(lost.map(o => o.name).join(", "))}.</span> Download ${lost.length === 1 ? "it" : "them"} again from Export history below.`);
    $("#exDone").dataset.batch = $("#exBatch").value;
    // v0.4.8 #12 (newcomer: two messages per export): the download line goes in the same box; a toast only when a file was not saved
    if (!lost.length) $("#exDone").insertAdjacentHTML("beforeend", `<p class="small" id="exSaved">${esc(savedText(outs))}</p>`); else toast(savedText(outs), 9000);
    exportInfo.picked = true; exportInfo(); refreshCounts();   // round 24 (newcomer r23): stay on the exported batch   // round 20 (newcomer r19)
  } catch (e) { $("#exDone").hidden = false; $("#exDone").className = "alert bad"; $("#exDone").textContent = "Export failed: " + e.message; }
  finally { t.removeAttribute("aria-busy"); }
}
export {exportInfo};
