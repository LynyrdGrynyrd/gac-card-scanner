"use strict";
// Phone mode page. Works over plain http on the LAN: photos come from <input capture="environment"> (opens the camera app).
// Live preview (getUserMedia) is only offered where the browser allows it (secure context: https / localhost).
const $ = s => document.querySelector(s);
const csrf = () => (document.cookie.match(/(?:^|; )gac_phone_csrf=([^;]+)/) || [])[1] || "";
const shots = {front: null, back: null}; let sent = [], target = "front", stream = null, expires = 0;
function msg(t, err) { $("#msg").textContent = t; $("#msg").className = err ? "err" : ""; }
async function shrink(file, max = 2400) {         // smaller upload, faster on Wi-Fi; the computer reads up to this size anyway
  if (/\.pdf$/i.test(file.name || "") || file.type === "application/pdf") return file;   // round 18: PDFs go as they are
  try {
    const bm = await createImageBitmap(file, {imageOrientation: "from-image"}); const s = Math.min(1, max / Math.max(bm.width, bm.height));
    if (s === 1 && file.size < 4e6) return file;
    const c = document.createElement("canvas"); c.width = Math.round(bm.width * s); c.height = Math.round(bm.height * s);
    c.getContext("2d").drawImage(bm, 0, 0, c.width, c.height);
    return await new Promise(r => c.toBlob(b => r(b || file), "image/jpeg", 0.9));
  } catch { return file; }
}
function setShot(side, blob) {
  shots[side] = blob; const img = side === "front" ? $("#pFront") : $("#pBack");
  if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
  if (blob) { img.dataset.url = URL.createObjectURL(blob); img.src = img.dataset.url; } else img.removeAttribute("src");
  $("#send").disabled = !shots.front;
  $(side === "front" ? "#bFront" : "#bBack").textContent = blob ? "Retake" : (side === "front" ? "📷 Front" : "📷 Back");
}
function pick(side) {
  target = side;
  if (stream) { $("#live").hidden = false; $("#live").scrollIntoView({behavior: "smooth"}); return; }
  $(side === "front" ? "#fFront" : "#fBack").click();
}
$("#bFront").onclick = () => pick("front"); $("#bBack").onclick = () => pick("back");
// audit 2026-10: the phone's camera app takes a sharper photo than a 1920x1080 preview frame (better for reading), so it is
// offered even while the live preview is on
$("#camApp").onclick = () => $(target === "back" ? "#fBack" : "#fFront").click();
$("#fFront").onchange = async e => { if (e.target.files[0]) setShot("front", await shrink(e.target.files[0])); e.target.value = ""; };
$("#bFile").onclick = () => $("#fFile").click();   // round 18: saved photo / HEIC / PDF (no camera)
$("#fFile").onchange = async e => { const f = e.target.files[0]; e.target.value = ""; if (!f) return;
  setShot("front", await shrink(f)); if (/\.pdf$/i.test(f.name) || f.type === "application/pdf") msg(`PDF “${f.name}” chosen. Each card in it becomes a card. Tap Send.`); };
$("#fBack").onchange = async e => { if (e.target.files[0]) setShot("back", await shrink(e.target.files[0])); e.target.value = ""; };

/* ---- live preview with a light "card in frame" detector (secure context only) ---- */
async function startLive() {
  if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("#camNote").textContent = "Live preview needs a secure (https) connection, which the office network doesn't have, so the phone's own camera app opens instead. That works the same.";
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}}, audio: false});
    if (document.hidden) { stopLive(true); return; }   // hidden while the permission prompt was open
    const v = $("#video"); v.srcObject = stream; await v.play(); $("#live").hidden = false; detect();
    $("#camNote").textContent = "Live preview on. The frame turns green when a card fills it. For the sharpest photo, tap “Use camera app”.";
  } catch { stream = null; $("#camNote").textContent = "Camera permission was not given, so the camera app is used instead."; }
}
// audit 2026-10: the camera (and the 4 Hz detect loop) kept running while the page was hidden. Stop the tracks when the page
// is hidden and start the preview again when it comes back.
let liveWanted = false, detGen = 0;
function stopLive(keep) {
  liveWanted = !!keep && (liveWanted || !!stream); detGen++;
  if (stream) stream.getTracks().forEach(t => t.stop());
  stream = null; const v = $("#video"); if (v) v.srcObject = null;
}
document.addEventListener("visibilitychange", () => { if (document.hidden) { if (stream) stopLive(true); } else if (liveWanted && !stream) { liveWanted = false; startLive(); } });
addEventListener("pagehide", () => stopLive(false));
function detect() {   // compares edge strength along the guide's border vs. the middle: cheap, no library needed
  const v = $("#video"), c = document.createElement("canvas"), W = 160, H = 90; c.width = W; c.height = H; const g = c.getContext("2d", {willReadFrequently: true});
  const gen = ++detGen;
  const tick = () => {
    if (!stream || gen !== detGen || document.hidden) return;
    if (v.videoWidth) {
      g.drawImage(v, 0, 0, W, H); const d = g.getImageData(0, 0, W, H).data, L = (x, y) => { const i = (y * W + x) * 4; return d[i] * .3 + d[i + 1] * .59 + d[i + 2] * .11; };
      const x0 = Math.round(W * .06), x1 = Math.round(W * .94), y0 = Math.round(H * .14), y1 = Math.round(H * .86); let e = 0, n = 0;
      for (let x = x0; x < x1; x += 2) { e += Math.abs(L(x, y0 - 2) - L(x, y0 + 2)) + Math.abs(L(x, y1 - 2) - L(x, y1 + 2)); n += 2; }
      for (let y = y0; y < y1; y += 2) { e += Math.abs(L(x0 - 2, y) - L(x0 + 2, y)) + Math.abs(L(x1 - 2, y) - L(x1 + 2, y)); n += 2; }
      $(".guide").classList.toggle("ok", e / n > 18);
    }
    setTimeout(tick, 250);
  };
  tick();
}
$("#snap").onclick = () => {
  const v = $("#video"); if (!stream || !v.videoWidth) return;   // audit 2026-10: the preview is restarting (page was hidden)
  const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext("2d").drawImage(v, 0, 0);
  c.toBlob(b => { setShot(target, b); if (target === "front" && !shots.back) { target = "back"; msg("Front captured. Turn the card over for the back, or tap Send."); } }, "image/jpeg", 0.9);
};

/* ---- upload ---- */
$("#batch").value = localStorage.getItem("gacBatch") || "";
$("#batch").onchange = () => localStorage.setItem("gacBatch", $("#batch").value.trim());
$("#send").onclick = async () => {
  if (!shots.front) return; $("#send").disabled = true; msg("Sending…");
  const fd = new FormData(); fd.append("image", shots.front, "front.jpg"); if (shots.back) fd.append("back", shots.back, "back.jpg"); fd.append("batch_label", $("#batch").value.trim());
  try {
    const r = await fetch("/m/api/upload", {method: "POST", body: fd, headers: {"X-CSRF-Token": csrf()}, credentials: "same-origin"});
    const j = await r.json().catch(() => ({}));
    if (r.status === 401) { location.href = "/m"; return; }
    if (!r.ok) throw new Error(j.error || `Upload failed (${r.status}).`);
    const ids = j.jobs && j.jobs.length ? j.jobs : [j.job];   // round 18: a PDF or a sheet of cards is several cards
    ids.forEach((id, k) => sent.unshift({id, state: "queued", n: ids.length > 1 ? `${j.uploads}.${k + 1}` : j.uploads, back: ids.length === 1 && !!shots.back}));
    setShot("front", null); setShot("back", null); target = "front";
    msg(ids.length > 1 ? `Upload ${j.uploads} sent: ${ids.length} cards found. Ready for the next one.` : `Card ${j.uploads} sent${j.ahead ? ` (${j.ahead} ahead in the queue)` : ""}. Ready for the next card.`); render(); poll();
  } catch (e) { msg(e.message, true); $("#send").disabled = false; }
};
const WORDS = {queued: "waiting", reading: "reading…", done: "✓ in review queue", error: "⚠ not added", splitting: "reading PDF…", split: "✓ PDF read", cancelled: "stopped"};
function render() { $("#count").textContent = sent.length; $("#list").innerHTML = sent.map(s => `<li><span>Card ${s.n}${s.back ? " (front + back)" : ""}</span><span>${WORDS[s.state] || s.state}</span></li>`).join(""); }
let pT = null;
async function poll() {
  clearTimeout(pT);
  try { const r = await fetch("/m/api/jobs", {credentials: "same-origin"}); if (r.status === 401) return; const j = await r.json();
    for (const x of j.jobs) { const s = sent.find(y => y.id === x.id); if (s) s.state = x.state; }
    // round 20: a PDF's cards appear one line each as its pages are read (the PDF line goes once it is read)
    for (const x of j.jobs) if (x.parent && !sent.some(y => y.id === x.id)) { const p = sent.find(y => y.id === x.parent); if (p) { p.kids = (p.kids || 0) + 1; sent.splice(sent.indexOf(p), 0, {id: x.id, state: x.state, n: `${p.n}.${p.kids}`}); } }
    for (let i = sent.length - 1; i >= 0; i--) if (sent[i].state === "split") sent.splice(i, 1);
    render();
    if (sent.some(s => s.state === "queued" || s.state === "reading" || s.state === "splitting")) pT = setTimeout(poll, document.hidden ? 10000 : 3000);   // audit 2026-10: slower while hidden
  } catch { pT = setTimeout(poll, 5000); }
}
async function state() {
  const r = await fetch("/m/api/state", {credentials: "same-origin"}); if (r.status === 401) { location.href = "/m"; return; }
  const j = await r.json(); expires = j.expires; $("#who").textContent = `Connected to ${j.by}'s scanner. Cards go into their review queue.`;
  if (!$("#batch").value && j.batch_label) $("#batch").value = j.batch_label;
}
setInterval(() => { const m = Math.max(0, Math.round((expires - Date.now() / 1000) / 60)); $("#exp").textContent = expires ? (m ? `${m} min left` : "expiring") : ""; }, 5000);
if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/m/sw.js", {scope: "/m"}).catch(() => {});
state().then(() => $("#exp").textContent = ""); startLive();
