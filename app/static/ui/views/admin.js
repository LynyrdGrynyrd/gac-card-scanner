// Admin page: reviewers, settings, MC Trade files, audit log, the desktop AI helper.
import {S} from "../core/state.js";
import {$, $$, esc, plural, when} from "../core/dom.js";
import {call, post} from "../core/api.js";
import {toast} from "../ui/toast.js";
import {ask, busy} from "../ui/dialog.js";
import {aiHeader, aiWord} from "../header.js";

/* ---------- admin ---------- */
let adminTab = "users";
$$("#adminTabs button").forEach(b => b.onclick = () => { adminTab = b.dataset.t; loadAdmin(); });
const ADMV = {};   // round 15: versions of the shared admin state as shown on this page
async function loadAdmin() {
  if (!S.ME) return;   // route() runs again once the signed-in user is known
  if (S.ME.role !== "admin") { ["users", "settings", "audit"].forEach(t => $("#t-" + t).hidden = true); $("#adminTabs").hidden = true; toast("Only admins can open the Admin page."); return; }
  $$("#adminTabs button").forEach(x => x.setAttribute("aria-pressed", x.dataset.t === adminTab));
  ["users", "settings", "audit"].forEach(t => $("#t-" + t).hidden = t !== adminTab);
  if (adminTab === "users") {
    const us = await call("/api/admin/users");
    $("#uBody").innerHTML = us.map(u => `<tr data-u="${u.id}"><td>${esc(u.display)}</td><td>${esc(u.username)}${/^qa[-_]/i.test(u.username) ? '<div class="sub" style="color:#b45309">Shared test login: deactivate before go-live</div>' : ""}</td><td>${esc(u.initials)}</td><td>${u.role === "admin" ? "Admin" : "Reviewer"}</td><td>${u.active ? "Active" : "Deactivated"}${u.must_change ? '<div class="sub">temporary password</div>' : ""}</td>
      <td>${u.id === S.ME.id ? '<span class="sub">(you)</span>' : `<button class="link" data-act="pw">Reset password</button> · <button class="link" data-act="active">${u.active ? "Deactivate" : "Reactivate"}</button> · <button class="link" data-act="role">${u.role === "admin" ? "Make reviewer" : "Make admin"}</button>`}</td></tr>`).join("");
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
    call("/api/admin/backup-status").then(b => { const w = $("#sBackupWarn");
      // audit 2026-10 P1: a failed or missing backup is shown here too, not only in the server console
      const old_ = b.enabled && (!b.last_at || Date.now() / 1000 - b.last_at > 50 * 3600), when_ = t => new Date(t * 1000).toLocaleString();
      const msgs = [];
      if (b.last_error) msgs.push(`<b>The last backup failed</b> (${esc(when_(b.last_error_at))}): ${esc(b.last_error)}. The scanner tries again every 10 minutes.`);
      else if (old_) msgs.push(b.last_at ? `<b>No backup since ${esc(when_(b.last_at))}.</b> Backups run at night while the scanner is open.` : `<b>No backup yet.</b> The first one is made within a few minutes, then every night.`);
      if (b.same_disk) msgs.push(`<b>Backups are on this computer only.</b> Ask IT to set a backup drive. <details class="more"><summary>More</summary>If this disk fails, the cards and backups are lost together. Backup folder: ${esc(b.dir)}. IT: see the admin guide, section 2.5.</details>`);
      w.hidden = !msgs.length; w.innerHTML = msgs.join("<br>"); }).catch(() => {});
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

// ---- Desktop "AI helper" download/start/stop (Admin > Settings). Shown only in the packaged desktop app.
let aiHelperTimer = null;
async function aiHelperRefresh() {
  if (document.hidden && aiHelperRefresh.ran) { clearTimeout(aiHelperTimer); aiHelperTimer = setTimeout(aiHelperRefresh, 8000); return; }   // audit 2026-10
  aiHelperRefresh.ran = true;
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
  if ($(id)) $(id).onclick = async () => {   // audit 2026-10: the app's own dialog, not the browser's confirm()
    if (path === "remove" && !(await ask({title: "Delete the AI helper?", html: "<p>The downloaded AI helper files are deleted from this computer. You can download them again later.</p>",
        buttons: [{label: "Delete", cls: "danger", value: 1}, {label: "Cancel", value: null, primary: true, focus: true}]})).value) return;
    try { await post("/api/admin/ai-helper/" + path, {}); } catch (e) { toast(e.message, 5000); } aiHelperRefresh(); };
export {loadAdmin};
