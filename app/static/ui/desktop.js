"use strict";
// Desktop-app glue (pywebview window). Does nothing in a normal browser.
// - folder picking via a native dialog (an <input webkitdirectory> is unreliable inside WebView2/WKWebView)
// - downloads/exports saved through a native Save dialog (webviews don't have a download manager)
(function () {
  const isDesk = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.save_file);
  const b64 = buf => { const u = new Uint8Array(buf); let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const fname = (res, url) => { const cd = res.headers.get("content-disposition") || "";
    const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
    return m ? decodeURIComponent(m[1]) : decodeURIComponent((url.split("?")[0].split("/").pop()) || "download"); };
  const blobs = new Map(); const _cou = URL.createObjectURL.bind(URL);   // CSP blocks fetch(blob:), so keep the Blob itself
  URL.createObjectURL = o => { const u = _cou(o); if (o instanceof Blob) { blobs.set(u, o); setTimeout(() => blobs.delete(u), 120000); } return u; };
  async function saveUrl(url, name) {
    if (blobs.has(url)) { const where = await window.pywebview.api.save_file(name || "download", b64(await blobs.get(url).arrayBuffer()));
      if (where && typeof toast === "function") toast("Saved: " + where, 4000); return; }
    const res = await fetch(url, {credentials: "same-origin"});
    if (!res.ok) { let m = res.statusText; try { m = (await res.json()).error || m; } catch {} throw new Error(m); }
    const n = name || fname(res, url), data = b64(await res.arrayBuffer());
    const where = await window.pywebview.api.save_file(n, data);
    if (where && typeof toast === "function") toast("Saved: " + where, 4000);
  }
  window.gacDownload = url => isDesk() ? saveUrl(url).catch(e => typeof toast === "function" ? toast(e.message, 5000) : alert(e.message)) : (location.href = url);
  // every <a download> / <a href="/api/...download"> click (including programmatic a.click()) goes through the Save dialog
  document.addEventListener("click", ev => {
    if (!isDesk()) return;
    const a = ev.target.closest && ev.target.closest("a[href]"); if (!a) return;
    const href = a.getAttribute("href") || "";
    if (a.hasAttribute("download") || /^\/api\/(export|exports)\b/.test(href)) {
      ev.preventDefault(); saveUrl(a.href, a.getAttribute("download") || "").catch(e => typeof toast === "function" && toast(e.message, 5000));
    }
  }, true);
  window.addEventListener("pywebviewready", () => {
    document.documentElement.classList.add("desktop-app");
    const bf = document.querySelector("#bFolder"); if (!bf) return;
    bf.onclick = async () => {
      const files = await window.pywebview.api.pick_folder();   // [{name, type, b64}] images in the chosen folder (recursive)
      if (!files || !files.length) return;
      const list = files.map(f => new File([unb64(f.b64)], f.name, {type: f.type}));
      if (typeof enqueue === "function") enqueue(list);
    };
  });
})();
