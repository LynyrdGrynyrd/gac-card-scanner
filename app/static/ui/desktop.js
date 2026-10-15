"use strict";
// Desktop-app glue (pywebview window). Does nothing in a normal browser.
// - folder picking via a native dialog (an <input webkitdirectory> is unreliable inside WebView2/WKWebView)
// - downloads/exports saved through a native Save dialog (webviews don't have a download manager)
(function () {
  const isDesk = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.save_file);
  const say = (m, ms) => { if (typeof toast === "function") toast(m, ms); };
  const b64 = buf => { const u = new Uint8Array(buf); let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const fname = (res, url) => { const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
    return m ? decodeURIComponent(m[1]) : decodeURIComponent((url.split("?")[0].split("/").pop()) || "download"); };
  const blobs = new Map(); const _cou = URL.createObjectURL.bind(URL);   // CSP blocks fetch(blob:), so keep the Blob itself
  URL.createObjectURL = o => { const u = _cou(o); if (o instanceof Blob) { blobs.set(u, o); setTimeout(() => blobs.delete(u), 120000); } return u; };
  const _rou = URL.revokeObjectURL.bind(URL); URL.revokeObjectURL = u => { blobs.delete(u); _rou(u); };
  let chain = Promise.resolve();   // v0.2.1: Save dialogs one after another (an export saves 3 files)
  const queue = fn => { const p = chain.then(fn); chain = p.catch(() => {}); return p; };
  // audit 2026-10: save_file answers {path} | {cancelled} | {error} (older launchers: the path, or "" when cancelled).
  // Every save resolves to {name, saved: path} | {name, cancelled: true} | {name, error}, so the page can say what was saved.
  const result = (r, name) => typeof r === "string" ? (r ? {name, saved: r} : {name, cancelled: true})
    : r && r.path ? {name: r.name || name, saved: r.path} : r && r.cancelled ? {name: r.name || name, cancelled: true}
    : {name: (r && r.name) || name, error: (r && r.error) || "The file could not be saved."};
  const saveData = async (name, buf) => { try { return result(await window.pywebview.api.save_file(name, b64(buf)), name); } catch (e) { return {name, error: e.message || String(e)}; } };
  const told = o => o.saved ? say("Saved: " + o.saved, 4000) : o.cancelled ? say(`Not saved: ${o.name} (cancelled).`, 5000) : say(`Not saved: ${o.name}. ${o.error}`, 7000);
  // ui.js awaits this for exports, so it can report what was really saved (and what wasn't)
  window.gacSaveBlob = (blob, name) => isDesk() ? queue(async () => saveData(name || "download", await blob.arrayBuffer())) : null;
  const saveUrl = (url, name) => queue(async () => {
    if (blobs.has(url)) return saveData(name || "download", await blobs.get(url).arrayBuffer());
    const res = await fetch(url, {credentials: "same-origin"});
    if (!res.ok) { let m = res.statusText; try { m = (await res.json()).error || m; } catch {} return {name: name || fname(res, url), error: m}; }
    const n = name || fname(res, url); return saveData(n, await res.arrayBuffer());
  });
  // every <a download> / <a href="/api/...download"> click (including programmatic a.click()) goes through the Save dialog
  document.addEventListener("click", ev => {
    if (!isDesk()) return;
    const a = ev.target.closest && ev.target.closest("a[href]"); if (!a) return;
    const href = a.getAttribute("href") || "";
    if (/^\/static\/.*\.pdf(\?|#|$)/i.test(href) && window.pywebview.api.open_url) {   // Help PDFs: system browser, not a webview download
      ev.preventDefault(); window.pywebview.api.open_url(href.split("#")[0]); return;
    }
    if (a.hasAttribute("download") || /^\/api\/(export|exports)\b|^\/api\/admin\/audit\?(.*&)?fmt=csv\b/.test(href)) {   // audit 2026-10: the audit-log CSV too
      ev.preventDefault(); saveUrl(a.href, a.getAttribute("download") || "").then(told, e => say(e.message, 5000));
    }
  }, true);
  window.addEventListener("pywebviewready", () => {
    document.documentElement.classList.add("desktop-app");
    const bf = document.querySelector("#bFolder"); if (!bf) return;
    bf.onclick = async () => {
      const r = await window.pywebview.api.pick_folder();   // {files: [{name, type, b64}], skipped_big, capped, ...} (older launchers: the list)
      const files = Array.isArray(r) ? r : (r && r.files) || [];
      // audit 2026-10: the pick is read into memory, so the launcher caps it; say what was left out
      const left = [r && r.skipped_big ? `${r.skipped_big} file${r.skipped_big === 1 ? "" : "s"} over ${r.max_file_mb || 25} MB skipped.` : "",
                    r && r.capped ? `Only the first ${files.length} file${files.length === 1 ? "" : "s"} (up to ${r.max_mb || 300} MB) ${files.length === 1 ? "was" : "were"} added: pick a smaller folder, or fewer photos, for the rest.` : ""].filter(Boolean).join(" ");
      if (!files.length) { if (left) say(left, 9000); return; }
      const list = files.map(f => new File([unb64(f.b64)], f.name, {type: f.type}));
      if (typeof enqueue === "function") { await enqueue(list); if (left) say(left, 9000); }
    };
  });
})();
