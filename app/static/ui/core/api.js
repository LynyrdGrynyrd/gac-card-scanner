// Talking to the server: call()/post(), the shared sign-in handling and downloads.
import {S} from "./state.js";
import {$, $$} from "./dom.js";
import {dropDraft, saveDraft} from "./store.js";
import {authPause, upPending} from "../views/upload.js";

// the app version this page was loaded with (main.js?v=…, set by the server); modules have no document.currentScript
const ASSET_V = ((document.querySelector('script[type="module"][src*="/static/ui/main.js"]') || {}).src || "").match(/[?&]v=([0-9a-f]+)/)?.[1] || "";
const csrf = () => (document.cookie.match(/(?:^|; )gac_csrf=([^;]*)/) || [])[1] || "";
// v0.4.3 #2: GETs made within a minute of a click/key say so; timed polling doesn't, so it never keeps a session alive
let LAST_INPUT = Date.now();
["pointerdown", "keydown", "wheel", "touchstart"].forEach(e => addEventListener(e, () => { LAST_INPUT = Date.now(); }, {passive: true, capture: true}));
async function call(u, o = {}) {
  if (o.method && o.method !== "GET") o.headers = {...(o.headers || {}), "X-CSRF-Token": csrf()};
  else if (Date.now() - LAST_INPUT < 60000) o.headers = {...(o.headers || {}), "X-User-Active": "1"};
  const r = await fetch(u, o); let j = null; try { j = await r.json(); } catch {}
  const av = r.headers.get("X-GAC-Asset");   // round 9: the app was updated while this tab was open
  if (av && ASSET_V && av !== ASSET_V && !$("#verWarn")) {
    if (!S.dirty && !S.SAVING && !$("#dlg").open && !$$('[aria-busy="true"]').length) { saveDraft(); location.reload(); }   // round 11 (newcomer r10): never mid-action
    else { document.body.insertAdjacentHTML("afterbegin", `<div id="verWarn" class="alert" role="alert">The scanner was updated. Save your work, then <button type="button" class="link" id="verReload">reload the page</button>.</div>`);
      $("#verReload").onclick = () => location.reload(); }   // audit 2026-10: a javascript: URL is blocked by the CSP
  }
  const uid = r.headers.get("X-GAC-User");
  if (S.ME && uid && uid !== String(S.ME.id) && !$("#swapWarn")) {   // another tab signed this browser in as someone else
    document.body.insertAdjacentHTML("afterbegin", `<div id="swapWarn" class="alert bad" role="alert">Someone else signed in on this browser in another tab, so your actions would be saved under <b>their name</b>. <a href="/ui">Reload</a> or sign in again.</div>`);
  }
  if (r.status === 401) { const e = new Error(handleAuth(401, j)); e.status = 401; e.data = j || {}; throw e; }
  if (!r.ok) { const e = new Error((j && (j.error || j.detail)) || ("Server error " + r.status)); e.status = r.status; e.data = j || {}; throw e; }
  if (o.meta) o.meta.headers = r.headers;   // audit 2026-10: paged lists read X-Total
  const sm = o.method === "POST" && u.match(/^\/api\/cards\/(\d+)$/); if (sm) dropDraft(+sm[1]);   // saved: the draft is no longer needed
  return j;
}
// audit 2026-10: ONE place for an expired session, used by call(), the downloads (fetchOk) and the uploads. While photos are
// still waiting to upload, a 401 pauses the uploads (the photos stay in this tab) instead of leaving the page for /login.
function handleAuth(status, j) {
  if (status !== 401) return (j && (j.error || j.detail)) || null;
  if (upPending()) { authPause(); return "Your sign-in expired. Sign in again: the waiting photos upload after that."; }
  saveDraft(); S.dirty = false; location.href = "/login?next=" + encodeURIComponent("/ui" + location.hash); return "Please sign in.";
}
async function fetchOk(u) {   // audit 2026-10: downloads need the raw Response (a Blob), but errors are handled like call()'s
  const r = await fetch(u, {credentials: "same-origin"}); if (r.ok) return r;
  let j = {}; try { j = await r.json(); } catch {}
  const e = new Error(handleAuth(r.status, j) || r.statusText || ("Server error " + r.status)); e.status = r.status; e.data = j; throw e;
}
const post = (u, b) => call(u, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(b)});
export {call, csrf, fetchOk, post};
