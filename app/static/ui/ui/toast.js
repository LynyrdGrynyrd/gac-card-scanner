// The status toast (one live region) with its optional Undo button.
import {$} from "../core/dom.js";
import {doUndo, refreshUndo} from "../header.js";

// audit 2026-10 (WCAG 2.2.1): the toast waits while the pointer or keyboard focus is in it, and a faded toast leaves no
// focusable Undo button behind
const toastOff = t => { t.classList.remove("show"); clearTimeout(t._h); t.querySelectorAll(".toastbtn").forEach(b => b.remove()); };
const toastLater = (t, ms) => { clearTimeout(t._h); t._h = setTimeout(() => { if (!t.contains(document.activeElement)) toastOff(t); }, ms); };
const hideToast = re_ => { const t = $("#toast"); if (!re_ || re_.test(t.textContent)) toastOff(t); };
const toast = (m, ms = 4500, undo = false) => { const t = $("#toast"); t.textContent = m;   /* round 15 (reviewer r14): 2.6 s was too quick */   // undo: true = the card Undo, or a function = its own undo
  if (undo) { const b = document.createElement("button"); b.type = "button"; b.className = "toastbtn"; b.textContent = "Undo"; b.onclick = () => typeof undo === "function" ? undo() : doUndo(); t.append(b); ms = Math.max(ms, 6000); }
  t.classList.add("show"); toastLater(t, ms); if (undo) refreshUndo();   // audit 2026-10: no GET /api/undo for every toast, only after undoable actions
  t.onmouseenter = () => clearTimeout(t._h); t.onmouseleave = () => toastLater(t, 2500); };   // round 17 (reviewer r16 N5)
{ const t = $("#toast"); t.addEventListener("focusin", () => clearTimeout(t._h)); t.addEventListener("focusout", () => toastLater(t, 2500)); }   // audit 2026-10: keyboard focus pauses it too
export {hideToast, toast};
