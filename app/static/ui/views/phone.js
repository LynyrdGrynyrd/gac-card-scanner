// Scan page: "Scan with phone" pairing panel.
import {$} from "../core/dom.js";
import {call, post} from "../core/api.js";
import {toast} from "../ui/toast.js";

/* ---------- phone mode (Scan with phone) ---------- */
let phT = null;
async function phoneRefresh() {
  clearTimeout(phT);
  if (document.hidden) { phT = setTimeout(phoneRefresh, 5000); return; }   // audit 2026-10: no work while the tab is hidden
  try { const st = await call("/api/phone/status"); $("#bPhone").hidden = !st.allowed;
    if (!st.active) { $("#phonePanel").hidden = true; return; }
    $("#phoneCount").textContent = st.uploads || 0; const m = Math.max(0, Math.round((st.expires - Date.now() / 1000) / 60));
    $("#phoneExp").textContent = m ? `Code works for ${m} more min` : "Code expiring";
    phT = setTimeout(phoneRefresh, 5000);
  } catch {}
}
async function phoneStart() {
  try { const r = await post("/api/phone/start", {batch_label: $("#batchName").value.trim()});
    $("#phoneQr").src = r.qr; $("#phoneUrl").textContent = r.url.replace(/\?t=.*/, "?t=…"); $("#phonePanel").hidden = false;
    if (!r.lan_only) toast("No Wi-Fi connection found. Connect this computer to Wi-Fi.", 6000);
    const cand = r.candidates || [];   // part-timer r2: say which address the QR uses when the computer has several
    let cn = $("#phoneCand"); if (!cn) { $("#phoneUrl").insertAdjacentHTML("afterend", `<p id="phoneCand" class="small"></p>`); cn = $("#phoneCand"); }
    cn.textContent = cand.length > 1 ? `If the phone can't open the page, ask IT to set the phone address (now ${r.host}).` : "";
    phoneRefresh();
  } catch (e) { toast(e.message, 6000); }
}
$("#bPhone").onclick = phoneStart; $("#phoneNew").onclick = phoneStart;
$("#phoneStop").onclick = async () => { await post("/api/phone/stop", {}); $("#phonePanel").hidden = true; toast("Phone scanning stopped."); };
export {phoneRefresh};
