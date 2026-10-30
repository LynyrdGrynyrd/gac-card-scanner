# UX audit: v0.4 screens

Checklist: ux-review `CHECKLIST.md` (9 categories, 0–3 each, max 27). Screens were taken on a throwaway instance with
made-up cards only (`tests/cards`), light and dark, 1280 px and 320 px wide. axe-core (WCAG 2.0/2.1/2.2 A+AA) ran on
every state. Screenshots: `docs/screenshots/v0.4/`.

States covered: scan (empty, More open, reading, done), queue (empty, full), review (open, field zoomed, More open,
blocked by an error, dark), duplicate, export (empty batch, ready), export sheet (light, dark), 320 px reflow.

## Score: 25 / 27, no red flags

| Category | Score | Notes |
|---|---|---|
| Hierarchy & layout | 2 | One primary per screen: Scan / Approve / Export (the Scan button turns plain once "Review batch" shows). Rare actions under More. Approve stays in view on long cards. **Minor fails:** the review form is still two columns (H6); the scan page is 3 px too wide at 320 px (H7). |
| Copy & microcopy | 3 | Buttons are 1–2 words (Scan, Approve, Skip, Same, Different, Export, Save). One short helper line at most ("Drop photos or a PDF.", "Tap a field to zoom"). "Please check" is now "Check". |
| Forms & settings | 2 | Labels stay visible, format rules are shown up front ("commas between", "one per line"). **Minor fail:** many optional fields are not marked "(optional)" (F4); unchanged from v0.3. |
| Status, errors & empty states | 3 | Shaky fields get a soft yellow highlight and a "Check" tag on the field (not colour alone); blocks still come from the server. Empty export says "Nothing to export yet. Approve some cards first." Toasts are `role=status`. |
| Dialogs & destructive actions | 3 | Export sheet "Ready to save": Cancel + Save, counts first. Delete still names the card and the consequence. Esc closes every dialog. |
| Consistency & terminology | 3 | "Skip" is the one name for "next card" (Skip button, Skip → pager, J). Same / Different everywhere for duplicates. |
| Accessibility | 3 | axe: 0 violations on every state, light and dark (dark colours checked ≥ 4.5:1, also in a unit test). Targets ≥ 44 px. Keyboard: ↵ approve, Tab next field, ←/→ card, ⌘Z/Ctrl+Z undo, Esc whole photo. Reduced motion turns all animation off. |
| Speed & feedback | 3 | Busy states on Export and Approve; scan progress with Cancel; the photo zooms in 0.35 s; toasts after every action. |
| Onboarding & help | 3 | First action is obvious (one Scan button); key hints are visible under the card; Help link in the header. |

**Red flags:** none. One primary per screen; no paragraphs under controls; no paths or stack traces; every error has a
next step; deletes confirm; empty and loading states are distinct; feedback within 1 s; one name per thing; no
placeholder-only labels; keyboard, focus and contrast pass.

**Keyboard safety (checked in e2e `tests/e2e/test_v04.py`):** Enter never approves while any dialog is open, while the card
has unsaved edits, while an error is shown, or before the card has loaded; it says "Unsaved edits: use Approve or Save."
The server still validates every approve.

**Caveat on the rubric:** a "3" in the checklist assumes checks verified with at least 3 real users. These scores come from
the checks, axe and scripted persona walk-throughs on the throwaway instance, not from 3 real users.
