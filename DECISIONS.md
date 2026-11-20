# Decisions ledger (append-only)

One dated entry per decision; never edit an old entry, add a new one that supersedes it.

## 2026-11-20: The AI reads every card in full and its reading fills the review form

**Decision (owner):** "The model reads every card in full and its reading fills the review form. Fields where rules and model disagree get a Check flag. A person still approves each card."

**Why (measured on 36 real cards, 360 fields; the cards are not in the repo):**
- rules only: 274 of 360 fields right;
- the AI check as it was (asks only about doubted fields, shows suggestions): 293 if every suggestion is accepted;
- the same model reading the whole card, merged the way `pipeline.scan(photo, vlm_result=answer)` merges it: 331, with 15 wrong fields carrying no warning;
- the full read pushed through the old `_ai_run` merge instead: 321 (it merged into already post-fixed fields and skipped the steps `pipeline.scan` runs after a merge).

The office laptop needs about 3 minutes per card for a read, so a reviewer reaching a card before the AI does is the normal case. Implementation: `HANDOFF.md`, "AI double-check".

**Also decided (same day):** `AI_MAX_WAIT` default raised from 30 minutes to 4 hours (14400 s): a 38-card stack needs about 1 h 45 min of reading, so 30 minutes skipped most of it. A skipped card keeps its scanned values.

## 2026-11-20 (later): Simplify: no per-field Keep/Undo for AI-filled cards

**Decision (owner):** "Simplify, then merge. Remove the per-field Keep/Undo buttons for AI-filled cards. The AI fills the form, AI-set fields stay marked Check and show the earlier value as plain text; to change one you just edit it. No further review rounds." The project is an experiment: simplicity and low upkeep first.

**Why:** three review rounds (two model families each) did not approve the Keep/Undo design; almost every finding was an edge case of the per-field choice machinery (stale screens, unsaved typing, turned-down values, name parts). Removing the machinery removes the cases.

**What stays:** every-card queueing, the full read without hints, the apply guards (`ui._ai_blocker`, checked again under the lock), the second OCR through `pipeline.scan(vlm_result=...)`, the full before/after record in History, source `ai` with the Check flag until a person edits the field (or the card is decided), the suggestion flow of 04bf6ef for cards a person touched first, the draft mirror with its retry, reason codes for a reading that was not applied, `AI_MAX_WAIT` 4 hours.

**Known limits:** a card that came with a back photo is not auto-filled (its history holds `back_added`), it gets suggestions; a filled value is changed by editing it, and the earlier value stays in the card's History; editing one name part leaves the "name" flag while the other part is still the AI's.
