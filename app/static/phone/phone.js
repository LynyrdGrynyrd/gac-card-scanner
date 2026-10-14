"use strict";
// Phone mode page. Works over plain http on the LAN: photos come from <input capture="environment"> (opens the camera app).
// Live preview (getUserMedia) is only offered where the browser allows it (secure context: https / localhost).
const $ = s => document.querySelector(s);
const csrf = () => (document.cookie.match(/(?:^|; )gac_phone_csrf=([^;]+)/) || [])[1] || "";
const shots = {front: null, back: null}; let sent = [], target = "front", stream = null, expires = 0;
function msg(t, err) { $("#msg").textContent = t; $("#msg").className = err ? "err" : ""; }
async function shrink(file, max = 2400) {         // smaller upload, faster on Wi-Fi; the computer reads up to this size anyway
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
$("#fFront").onchange = async e => { if (e.target.files[0]) setShot("front", await shrink(e.target.files[0])); e.target.value = ""; };
$("#fBack").onchange = async e => { if (e.target.files[0]) setShot("back", await shrink(e.target.files[0])); e.target.value = ""; };

/* ---- live preview with a light "card in frame" detector (secure context only) ---- */
async function startLive() {
  if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("#camNote").textContent = "Live preview needs a secure (https) connection, which the office network doesn't have, so the phone's own camera app opens instead. That works the same.";
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}}, audio: false});
    const v = $("#video"); v.srcObject = stream; await v.play(); $("#live").hidden = false; detect();
    $("#camNote").textContent = "Live preview on. The frame turns green when a card fills it.";
  } catch { stream = null; $("#camNote").textContent = "Camera permission was not given, so the camera app is used instead."; }
}
function detect() {   // compares edge strength along the guide's border vs. the middle: cheap, no library needed
  const v = $("#video"), c = document.createElement("canvas"), W = 160, H = 90; c.width = W; c.height = H; const g = c.getContext("2d", {willReadFrequently: true});
  const tick = () => {
    if (!stream) return;
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
  const v = $("#video"), c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext("2d").drawImage(v, 0, 0);
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
    sent.unshift({id: j.job, state: "queued", n: j.uploads, back: !!shots.back}); setShot("front", null); setShot("back", null); target = "front";
    msg(`Card ${j.uploads} sent${j.ahead ? ` (${j.ahead} ahead in the queue)` : ""}. Ready for the next card.`); render(); poll();
  } catch (e) { msg(e.message, true); $("#send").disabled = false; }
};
const WORDS = {queued: "waiting", reading: "reading…", done: "✓ in review queue", error: "⚠ not added"};
function render() { $("#count").textContent = sent.length; $("#list").innerHTML = sent.map(s => `<li><span>Card ${s.n}${s.back ? " (front + back)" : ""}</span><span>${WORDS[s.state] || s.state}</span></li>`).join(""); }
let pT = null;
async function poll() {
  clearTimeout(pT);
  try { const r = await fetch("/m/api/jobs", {credentials: "same-origin"}); if (r.status === 401) return; const j = await r.json();
    for (const x of j.jobs) { const s = sent.find(y => y.id === x.id); if (s) s.state = x.state; } render();
    if (sent.some(s => s.state === "queued" || s.state === "reading")) pT = setTimeout(poll, 3000);
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
