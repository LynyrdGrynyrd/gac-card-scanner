// DOM and formatting helpers.
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const SS = sessionStorage;
const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;
const LABEL = {name: "Name", title: "Job title", company: "Company", emails: "Email", phones: "Phone", website: "Website", address: "Address", first_name: "First name", last_name: "Last name", social: "Social profiles", note: "Note", department: "Department", other_address: "Other address", credentials: "Credentials (e.g. CPA, PhD)"};
const when = t => t ? new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "";
function fmtEta(s) { s = Math.max(1, Math.round(s)); return s < 90 ? `${s} s` : `${Math.round(s / 60)} min`; }
export {$, $$, LABEL, SS, esc, fmtEta, plural, when};
