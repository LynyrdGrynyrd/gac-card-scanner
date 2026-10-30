// The app's own dialog (ask) and the busy-button helper.
import {S} from "../core/state.js";
import {$, $$, esc} from "../core/dom.js";

async function busy(btn, label, fn) {
  if (btn.getAttribute("aria-busy") === "true") return;
  const old = btn.innerHTML; btn._old = old; btn.setAttribute("aria-busy", "true"); btn.disabled = true; btn.innerHTML = label;
  const t0 = Date.now();   // round 16 (part-timer r15): the busy label stays at least 0.5 s, so "Saving…" is seen even on a fast save
  try { return await fn(); } finally { const w = 500 - (Date.now() - t0); if (w > 0) await new Promise(r => setTimeout(r, w)); btn.removeAttribute("aria-busy"); btn.disabled = ["bApprove", "bReject", "bSave", "bPending"].includes(btn.id) && !S.CARD_READY; btn.innerHTML = old; }
}

/* ---------- dialog helper ---------- */
function ask({title, html = "", input = null, buttons, wide = false, check = null, timeout = 0}) {
  $$('[aria-busy="true"]').forEach(b => { if (b._old !== undefined) { b.innerHTML = b._old; b.removeAttribute("aria-busy"); } });   // no spinner behind a question
  const d = $("#dlg"); d.classList.toggle("wide", !!wide); $("#dlgTitle").textContent = title; $("#dlgBody").innerHTML = html; $("#dlgErr").textContent = "";
  $("#dlgInputWrap").hidden = !input;
  if (input) { $("#dlgInputLabel").textContent = input.label; $("#dlgInput").value = input.value || ""; $("#dlgInput").placeholder = input.placeholder || ""; $("#dlgInput").maxLength = input.max || 200; $("#dlgInput").type = input.type || "text"; }
  $("#dlgBtns").innerHTML = buttons.map((b, i) => `<button type="button" class="btn ${b.cls || ""}${b.focus ? " dfocus" : ""}" data-i="${i}">${esc(b.label)}</button>`).join("");
  if (S.DLG_DONE) S.DLG_DONE({value: null, cancelled: true});   // round 14: a question replaced by another one is answered "cancelled", never left hanging
  return new Promise(res => {
    let tm = null; const done = v => { clearTimeout(tm); S.DLG_DONE = null; d.close(); res(v); };
    if (timeout) tm = setTimeout(() => done({value: null, timedOut: true}), timeout);   // v0.4.2 #2: the idle sign-out question
    S.DLG_DONE = done;
    $$("#dlgBtns button").forEach(el => el.onclick = () => {
      const b = buttons[+el.dataset.i], val = $("#dlgInput").value.trim();
      if (b.needInput && input && !val) { $("#dlgErr").textContent = input.required || "Please fill this in."; $("#dlgInput").focus(); return; }
      if (b.needInput && check) { const ce = check(val); if (ce) { $("#dlgErr").textContent = ce; $("#dlgInput").focus(); return; } }   // round 24: the dialog stays open on a bad input
      done({value: b.value, input: val});
    });
    d.oncancel = e => { e.preventDefault(); done({value: null}); };
    $("#dlgForm").onsubmit = e => { e.preventDefault(); const p = buttons.find(b => b.primary); if (p) $(`#dlgBtns [data-i="${buttons.indexOf(p)}"]`).click(); };
    d.showModal(); (input ? $("#dlgInput") : ($("#dlgBtns button.dfocus") || $("#dlgBtns button"))).focus();   // reviewer r8: a destructive dialog focuses Cancel
  });
}

$("#dlgInput").type = "text";
export {ask, busy};
