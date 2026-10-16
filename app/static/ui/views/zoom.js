// v0.4 #1: tap a field to zoom the photo to where it was read. Display only; no box = the whole photo. Esc resets.
import {$} from "../core/dom.js";
const KEY = {first_name: "name", last_name: "name", title: "title", company: "company", website: "website", address: "address", department: "department"};
let BOXES = {};
function setBoxes(b) { BOXES = b && typeof b === "object" ? b : {}; zoomReset(); }
function keyFor(el) {
  if (!el || !el.id) return null;
  if (el.id === "emails") { const i = el.value.slice(0, el.selectionStart ?? 0).split(",").length - 1; return BOXES["emails." + i] ? "emails." + i : "emails.0"; }
  if (el.id === "phones") { const i = el.value.slice(0, el.selectionStart ?? 0).split("\n").length - 1; return BOXES["phones." + i] ? "phones." + i : "phones.0"; }
  return KEY[el.id] || null;
}
function zoomTo(el) {
  const img = $("#rImg"), hint = $("#zHint"), k = keyFor(el), b = k && BOXES[k];
  if (!img) return;
  if (!b) { zoomReset(el ? "Not found on the photo" : null); return; }
  const [x, y, w, h] = b, ar = (img.naturalWidth || 1) / (img.naturalHeight || 1);
  // fit the box with some room around it; never more than 4x (beyond that the photo is just blur)
  const s = Math.max(1.4, Math.min(4, 0.8 / Math.max(w, h, 0.05))); void ar;
  const cl = (v, lo) => Math.min(0, Math.max(lo, v));
  const tx = cl(0.5 - s * (x + w / 2), 1 - s), ty = cl(0.5 - s * (y + h / 2), 1 - s);
  img.style.transformOrigin = "0 0"; img.style.transform = `translate(${(tx * 100).toFixed(2)}%, ${(ty * 100).toFixed(2)}%) scale(${s.toFixed(2)})`;
  img.dataset.zoom = k; if (hint) hint.textContent = "Esc: whole photo";
}
function zoomReset(msg) {
  const img = $("#rImg"), hint = $("#zHint"); if (!img) return;
  img.style.transform = ""; delete img.dataset.zoom; if (hint) hint.textContent = msg || "Tap a field to zoom";
}
function wireZoom() {
  const fs = $("#fields"); if (!fs || fs._zoom) return; fs._zoom = 1;
  fs.addEventListener("focusin", e => zoomTo(e.target));
  fs.addEventListener("click", e => { if (e.target.matches("input, textarea")) zoomTo(e.target); });
  fs.addEventListener("keyup", e => { if (["emails", "phones"].includes(e.target.id) && /Arrow|Home|End/.test(e.key)) zoomTo(e.target); });
}
export {setBoxes, wireZoom, zoomReset, zoomTo};
