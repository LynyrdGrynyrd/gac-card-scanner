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
    $("#exInfo").innerHTML = `${r.count ? `<b>${plural(r.count, "card")}</b> will be exported.` : (!$("#exDone").hidden && $("#exDone").classList.contains("ok") && $("#exDone").dataset.batch === eb) ? "All cards in this batch are exported." : "Nothing to export yet. Approve some cards first."}` +
      (r.flagged && r.flagged.length ? ` <span class="flag bad">${r.flagged.length === 1 ? "1 card has" : r.flagged.length + " cards have"} a warning (${r.flagged.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}). See the READ-ME.</span>` : "");   // round 23: no '1 were approved'

    $("#exDup").hidden = !r.duplicates.length;
    // round 7: no button per pair (part-timer/newcomer: a flood of buttons that write onto other people's cards). The pairs are
    // a review list of links; open a card to decide. Only an admin gets "mark all", behind a confirm that lists the pairs.
    const pairsAll = r.duplicates.flatMap(p => p.with.filter(w => !(p.strong || []).includes(w)).map(w => [p.id, w]));
    $("#exDup").innerHTML = r.duplicates.length ? `<b>Export is blocked: some cards look like the same person.</b> ${eb ? "Open each card to merge, or mark them as different people there." : "<b>Tip:</b> choose your own batch; other people's look-alikes don't block it."}` +
      (!eb && r.ok_batches && r.ok_batches.length ? `<p>These batches can be exported now: ${r.ok_batches.map(b => `<a href="#" data-xbatch="${esc(b.batch)}">${esc(b.label)}</a> (${b.count})`).join(", ")}</p>` : "") +
      `<details${eb ? " open" : ""}><summary>Review list: ${plural(r.duplicates.length, "card")} with look-alikes</summary><ul>${r.duplicates.map(p => `<li><a href="#review/${p.id}">Card #${p.id}</a>${p.batch ? ` <span class="sub">(${esc(p.batch)})</span>` : ""} may duplicate ${p.with.map(w => `<a href="#review/${w}">#${w}</a>` + ((p.strong || []).includes(w) ? ` <span class="sub">(duplicate scan: merge or reject one)</span>` : "")).join(", ")}</li>`).join("")}</ul></details>` : "";
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
    $$(".tile").forEach(t => t.disabled = !r.count || r.duplicates.length > 0); loadExportHistory();
    if ($("#exBig")) { $("#exBig").textContent = r.count; $("#exBigT").textContent = r.count === 1 ? "card ready" : "cards ready"; }
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
  $("#exHistMore").hidden = all.length <= h.length; $("#exHistCount").textContent = `${h.length} of ${all.length} shown` + (everyone ? " (everyone's)" : "");
  $("#exHist").innerHTML = h.map(x => `<tr><td>${esc(when(x.ts))}</td><td>${esc(x.initials)}</td><td>${esc(HK[x.kind] || x.kind.toUpperCase())}${x.batch_label ? `<div class="sub">${esc(x.batch_label)}</div>` : ""}</td><td>${x.count}</td>
    <td>${x.available ? `<a href="/api/exports/${x.id}/download" title="${esc(x.filename)}">Download</a>` + (x.companions || []).map(c => ` · <a href="/api/exports/${x.id}/companion/${c}">${c === "readme.txt" ? "READ-ME" : c === "updates.xlsx" ? "Updates" : "Extra details"}</a>`).join("") : `<span title="${esc(x.filename)}">File</span> <span class="sub">(${x.mine ? "copy deleted" : "only " + esc(x.initials) + " or an admin can download it"})</span>`}</td></tr>`).join("") || `<tr><td colspan="5">No exports yet.</td></tr>`;
}
$("#exHistEveryone") && ($("#exHistEveryone").onchange = () => loadExportHistory());
const KIND = {xlsx: "MC Trade import (Excel)", csv: "Spreadsheet (CSV)", vcf: "Contacts (vCard)"};
$$(".tile").forEach(t => t.onclick = async () => {   // round 14 (parttimer r6): busy at once, one click only, checks in parallel
  if (t.getAttribute("aria-busy") === "true") return;
  t.setAttribute("aria-busy", "true"); const lbl0 = t.style.cursor; t.style.cursor = "progress"; toast("Preparing the export…", 1500);
  try { await tileExport(t); } finally { t.removeAttribute("aria-busy"); t.style.cursor = lbl0; }
});
async function tileExport(t) {
  const kind = ($("input[name=exKind]:checked") || {}).value || t.dataset.ex || "xlsx", st = $("#exStatus").value;
  const pre = kind === "xlsx" ? call(`/api/export/xlsx?preview=1&view=1&status=${st}&batch=${encodeURIComponent($("#exBatch").value)}`).catch(e => ({__err: e})) : null;
  const info = await exportInfo(); if (!info || !info.count || info.duplicates.length) return;
  { const eb_ = $("#exBatch").value, bo = (S.BATCHES || []).find(b => b.batch === eb_) || (exportInfo.list || []).find(b => b.batch === eb_);   // round 24 (reviewer r23): warn before exporting someone else's batch
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
        `<li><b>${v.rows.length}</b> new contact${(v.rows.length) === 1 ? "" : "s"}${shw(v.rows.length, esc(v.rows.map(nm).join(", ")))}</li>` +
        (v.updates.length ? `<li><b>${v.updates.length}</b> update${(v.updates.length) === 1 ? "" : "s"} to existing contacts: ${esc(v.updates.map(nm).join(", "))}</li>` : "") +
        ((v.update_diff || []).length ? `<li><b>What the updates change in MC Trade</b> (an import overwrites non-blank cells and can't be undone):<div style="overflow:auto;max-height:30vh"><table class="aidiff" data-updiff="1"><thead><tr><th>Card</th><th>Profile</th><th>Field</th><th>Now in MC Trade</th><th>After import</th></tr></thead><tbody>${v.update_diff.map(u => u.fields.map(x => `<tr${x.changes ? ' class="chg"' : ""}><td><a href="#review/${u.card}">#${u.card}</a></td><td>${esc(u.profile_id)}</td><td>${esc(x.field)}</td><td>${x.old === null ? "<i>not in the contacts export: check in MC Trade</i>" : esc(x.old)}</td><td>${x.changes || x.changes === null ? "<b>" + esc(x.new) + "</b>" : esc(x.new)}</td></tr>`).join("")).join("")}</tbody></table></div></li>` : "") +
        ((v.sample_email_matches || []).length ? `<li>${v.sample_email_matches.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")} may already be in MC Trade (test list).</li>` : "") +
        (() => { const dz = v.decisions || {}, rv = v.left.filter(x => dz[x[0]] === "review"), lo = v.left.filter(x => dz[x[0]] !== "review");   // same classification as the export + dry run
          return (rv.length ? `<li><b>${rv.length}</b> card${(rv.length) === 1 ? "" : "s"} to review (in neither file)${shw(rv.length, rv.map(x => `<a href="#review/${x[0]}" title="${esc(x[1])}">#${x[0]}</a>`).join(", "))}</li>` : "") +
                 (lo.length ? `<li><b>${lo.length}</b> card${(lo.length) === 1 ? "" : "s"} left out (merged into another row, or to fix first)${shw(lo.length, lo.map(x => `<a href="#review/${x[0]}" title="${esc(x[1])}">#${x[0]}</a>`).join(", "))}</li>` : ""); })() +
        (info.pending_count ? `<li><b>${info.pending_count}</b> card${(info.pending_count) === 1 ? "" : "s"} still <b>pending</b>${shw(info.pending_count, info.pending.slice(0, 30).map(x => `<a href="#review/${x.id}">#${x.id} ${esc(x.name)}</a>`).join(", "))}</li>` : "") +
        `</ul></div>`; } } catch {} }
  // v0.4 #5: a summary sheet first ("12 new, 1 to check"); the counts come from the server's own export re-check
  let sum = null; try { sum = await call(`/api/export/summary?status=${st}&batch=${encodeURIComponent($("#exBatch").value)}`); } catch {}
  const stat = (l, n, w) => `<div class="stat"><span>${l}</span><b${w && n ? ' class="w"' : ""}>${n}</b></div>`;
  const sheet = sum ? (kind === "xlsx" ? stat("New contacts", sum.new) + stat("Updated", sum.updated) : stat("Cards", sum.count)) + stat("To check", sum.to_check, true) : "";
  const r = await ask({title: "Ready to save", html: sheet + `<details class="more small"><summary>More</summary>` + so + `<p>Format: <b>${KIND[kind]}</b></p><p>Cards: <b>${esc($("#exStatus").selectedOptions[0].textContent)}</b></p><p>Batch: <b>${esc($("#exBatch").selectedOptions[0]?.textContent || "All batches")}</b></p><p class="small">${kind === "xlsx" ? `<b>You'll get ${nUpd ? 4 : 3} files. Import only the .xlsx${nUpd ? " (and the UPDATES .xlsx as a separate import)" : ""}.</b> <details class="more"><summary>More</summary>The READ-ME.txt and extra-columns.csv are for reading, not for import.</details>` : "You'll get one file."}</p></details>`,
    buttons: [{label: "Cancel", value: null}, {label: "Save", cls: "primary", value: 1, primary: true}]});
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
    $("#exDone").innerHTML = (sm ? `<b>✓ ${plural(sm.cards, "card")} exported` + (sm.update_rows ? ` (${plural(sm.new_rows, "new contact")}, ${plural(sm.update_rows, "update")})` : "") + (sm.crm_real ? "" : " (test MC Trade list)") + `.</b>` +
        (sm.left_ids.length ? ` <span class="flag bad">Not imported: ${sm.left_ids.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}.</span>` : "") +
        (sm.possible.length ? ` <span class="flag low">Maybe in MC Trade: ${sm.possible.map(i => `<a href="#review/${i}">#${i}</a>`).join(", ")}.</span>` : "")
      : `<b>✓ Exported ${plural(n, "card")}</b>.`) + (kind === "xlsx" ? `<br>Import only the .xlsx${comp.includes("updates.xlsx") ? " (updates separately)" : ""}` + ((sm ? sm.new_rows + (sm.update_rows || 0) : +n) > 2 ? "; test 2 rows first." : ".") : "");
    const lost = lostFiles(outs);   // audit 2026-10: a cancelled Save dialog (desktop app) is said, never claimed as saved
    if (lost.length) $("#exDone").insertAdjacentHTML("beforeend", `<br><span class="flag bad">Not saved: ${esc(lost.map(o => o.name).join(", "))}.</span> Download ${lost.length === 1 ? "it" : "them"} again from Export history below.`);
    $("#exDone").dataset.batch = $("#exBatch").value;
    toast(savedText(outs) + (kind === "xlsx" && !lost.length ? " Read the READ-ME first." : ""), lost.length ? 9000 : 5000); exportInfo.picked = true; exportInfo(); refreshCounts();   // round 24 (newcomer r23): stay on the exported batch   // round 20 (newcomer r19)
  } catch (e) { $("#exDone").hidden = false; $("#exDone").className = "alert bad"; $("#exDone").textContent = "Export failed: " + e.message; }
  finally { t.removeAttribute("aria-busy"); }
}
export {exportInfo};
