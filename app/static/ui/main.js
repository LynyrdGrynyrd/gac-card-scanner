// Entry point (loaded as <script type="module">): evaluates every module, then starts the page.
import {S} from "./core/state.js";
import {$} from "./core/dom.js";
import {call} from "./core/api.js";
import {toast} from "./ui/toast.js";
import {aiQueueTick, loadMe, refreshCounts, refreshUndo, updateCheck} from "./header.js";
import {route} from "./router.js";
import {enqueue, refreshBatchCards} from "./views/upload.js";
import {phoneRefresh} from "./views/phone.js";
import "./core/store.js";
import "./ui/dialog.js";
import "./views/queue.js";
import "./views/review.js";
import "./views/export.js";
import "./views/admin.js";

try { localStorage.removeItem("reviewer"); } catch {}
// audit 2026-10 P2: page start-up; every module has been evaluated by now
call("/api/batches").then(b => S.BATCHES = b).catch(() => {});
(async () => { await loadMe(); route(); refreshCounts(); refreshUndo(); })();
fetch("/health").then(r => r.json()).then(h => { const el = $("#appVer"); if (el) el.textContent = `v${h.version || "?"}` + (h.commit && h.commit !== "unknown" && h.commit !== "?" ? ` (${h.commit})` : ""); }).catch(() => {});   // round 11
setInterval(() => { if (!document.hidden) refreshCounts(); }, 15000);
// round 10 (newcomer r9): the upload list updates by itself (a card approved, rejected or merged elsewhere shows its new state)
setInterval(() => { if (!document.hidden && S.B && (location.hash || "#upload").startsWith("#upload")) refreshBatchCards(); }, 15000);
window.addEventListener("focus", () => { refreshUndo(); if (S.B && (location.hash || "#upload").startsWith("#upload")) refreshBatchCards(); });   // audit 2026-10: Undo state from other tabs
$(".skip").onclick = e => { e.preventDefault(); $("#main").focus(); };   // the hash is the router: don't navigate to "#main"

phoneRefresh();
aiQueueTick();
setTimeout(updateCheck, 6000);
// audit 2026-10 P2: the only names the classic desktop.js glue uses (it used to read ui.js globals)
window.gac = Object.freeze({toast, enqueue});
