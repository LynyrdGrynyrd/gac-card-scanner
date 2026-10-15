// audit 2026-10 P2: page state that several modules read AND change lives here, in one object (an imported binding can't be
// reassigned by the importer). Everything else is module-local or exported read-only.
const S = {
  ME: null,            // the signed-in user (/api/me)
  B: null,             // the upload batch on the Scan page: {id, label, rows: [...]}, kept in sessionStorage
  BATCHES: [],         // /api/batches as last loaded
  cur: null,           // the card open on the Review page
  dirty: false,        // the Review form has unsaved edits
  SAVING: false,       // a card save is in flight
  CARD_READY: false,   // the Review card finished loading (Save/Approve stay off until then)
  DLG_DONE: null,      // resolves the open ask() dialog (answered "cancelled" when the page moves on)
  SIGNING_OUT: false,  // no draft may be written once sign-out started
};
export {S};
