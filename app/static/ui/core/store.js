// Unsaved Review edits kept as drafts (sessionStorage / localStorage).
import {S} from "./state.js";
import {SS} from "./dom.js";
import {dirtyVals} from "../views/review.js";

function saveDraft() { if (S.SIGNING_OUT) return; if (S.dirty && S.cur) try { SS.draft = JSON.stringify({id: S.cur.id, uid: S.ME && S.ME.id, vals: dirtyVals()}); } catch {} keepDraft(); }
// round 7 (advice): a per-card draft in localStorage, restored when the card is opened again (after leaving, a crash, sign-out)
const draftKey = id => `gac-draft-${(S.ME && S.ME.id) || "x"}-${id}`;
function keepDraft() { if (S.SIGNING_OUT) return; if (S.cur && !S.dirty) { dropDraft(S.cur.id); return; } if (S.dirty && S.cur) try { localStorage.setItem(draftKey(S.cur.id), JSON.stringify({ts: Date.now(), version: S.cur.version, vals: dirtyVals()})); } catch {} }
function dropDraft(id) { try { localStorage.removeItem(draftKey(id)); } catch {} }
function clearDrafts() { try { Object.keys(localStorage).filter(k => k.startsWith("gac-draft-")).forEach(k => localStorage.removeItem(k)); delete SS.draft; } catch {} }
export {clearDrafts, draftKey, dropDraft, keepDraft, saveDraft};
