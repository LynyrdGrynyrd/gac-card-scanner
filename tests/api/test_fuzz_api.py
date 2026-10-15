"""Schemathesis fuzzing of the HTTP API, in-process against app.main:app, signed in as an admin with the CSRF header + cookie
on every request (what the page sends). The check is "no 500": every bad input must get a 4xx with a message. Response
schemas are not checked: the handlers take free-form JSON (dict = Body()), so the generated OpenAPI says little.
Run: python -m pytest -q tests/api   (data goes to a temp folder, see conftest.py; every 500 found gets a plain TestClient
test in tests/unit/test_fuzz_regressions.py)."""
import copy, json
import pytest, schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.python.asgi import ASGIClient
from schemathesis.checks import not_a_server_error
from app import main

# Left out, with why. Everything else (incl. user admin, settings, deletes, uploads, exports) is fuzzed.
EXCLUDE = {
    ("POST", "/api/auth/logout"): "ends the fuzzing session itself",
    ("POST", "/api/me/password"): "would change the fuzzing admin's own password",
    ("POST", "/api/admin/ai-helper/download"): "downloads ~3 GB from the internet in a thread (not hermetic)",
    ("POST", "/api/phone/start"): "opens the phone-mode LAN listener (a real socket on the network)",
}
# There is no backup/restore HTTP endpoint (backups run in-process at startup, restore is a command-line step), so nothing to exclude.
# GET /api/update stays in: it only reads the cached result; the network check runs from the lifespan, which never runs here.
ANY = {}   # any JSON value: wrong types in known keys are the inputs most likely to crash a handler
CARD_FIELDS = ["first_name", "last_name", "credentials", "title", "company", "department", "emails", "phones", "website", "address",
               "other_address", "social"]
FIELDS = {"type": "object", "properties": {k: ANY for k in CARD_FIELDS}}
# The keys each handler reads (the generated schema only says "object"), so generated bodies reach the validation code.
BODY_KEYS = {
    "/api/auth/setup": ["username", "display", "password", "initials"], "/api/auth/login": ["username", "password"],
    "/api/admin/users": ["username", "display", "password", "role", "initials"], "/api/admin/users/{uid}": ["active", "password", "role"],
    "/api/admin/settings": ["_seen", "image_retention_days", "export_retention_days", "retention_enabled", "ai_check_enabled", "phone_format",
                            "mctrade_affcode", "phone_mode_allowed", "update_check_enabled", "mctrade_updates_enabled", "corrections_enabled"],
    "/api/cards/{cid}": ["version", "card_id", "fields", "status", "note", "override_reason", "confirm_redecide", "dup_resolution", "merge_into",
                         "crm_action", "crm", "confirm_cross_batch", "keep_apart", "open", "_allow_blank"],
    "/api/cards/{cid}/ai-decide": ["version", "choices", "record_only"], "/api/validate": ["card_id", "fields", "note"],
    "/api/cards/{cid}/confirm-correct": ["version", "field", "value", "reason"], "/api/cards/{cid}/merge-preview": ["into", "fields", "keep_apart"],
    "/api/cards-bulk": ["ids", "status", "versions", "batch", "confirm_cross_batch", "confirm_redecide", "dry_run", "open", "unresolved_queue"],
    "/api/batches/archive": ["batch", "confirm"], "/api/undo": ["id"],
    "/api/admin/cards/{cid}/delete": ["confirm", "card", "cards", "export_id", "file", "override"], "/api/jobs/cancel": ["ids", "batch", "all_waiting", "session"],
}
N_CARDS = 8

def _raw_schema():
    raw = copy.deepcopy(main.app.openapi())
    for path, ops in raw["paths"].items():
        for op in ops.values():
            for p in op.get("parameters", []):
                # ids mostly point at seeded rows (else every case is a 404); 0 and N+1 still probe the edges.
                # uid >= 2: never deactivate / demote / re-password the fuzzing admin (uid 1) - that ends the session.
                if p["in"] == "path" and p["name"] == "cid": p["schema"] = {"type": "integer", "minimum": 0, "maximum": N_CARDS + 1}
                if p["in"] == "path" and p["name"] == "uid": p["schema"] = {"type": "integer", "minimum": 2, "maximum": 4}
                if p["in"] == "path" and p["name"] == "eid": p["schema"] = {"type": "integer", "minimum": 0, "maximum": 3}
            js = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if js is not None and path in BODY_KEYS:
                js["properties"] = {k: (FIELDS if k == "fields" else ANY) for k in BODY_KEYS[path]}
                js.pop("default", None)
    return raw

schema = schemathesis.openapi.from_dict(_raw_schema())
for (m, p) in EXCLUDE: schema = schema.exclude(method=m, path=p)
schema.app = main.app

@pytest.fixture(scope="module")
def session():
    """An admin signed in through the real endpoints. The ASGI client is NOT entered as a context manager, so the app's
    lifespan (workers, AI-helper autostart, update check) never runs: the fuzzing is hermetic."""
    from app import store, ui
    s = ASGIClient(main.app); s.headers["Origin"] = "http://testserver"   # same-origin, like the page
    r = s.post("/api/auth/setup", json={"username": "fuzz", "display": "Fuzz Admin", "password": "fuzz-pass-1234"}); assert r.status_code == 200, r.text
    for u in ("rev", "rev2"):
        assert s.post("/api/admin/users", json={"username": u, "display": u.title() + " Rev", "password": "temp-pass-1234"},
                      headers={"X-CSRF-Token": s.cookies.get("gac_csrf")}).status_code == 200
    for i in range(N_CARDS):   # cards for the {cid} operations: a pending batch, one approved card, one with no email
        f = {"first_name": "Ann", "last_name": f"Lee{i}", "title": "CFO", "company": "Acme Inc", "emails": [] if i == 3 else [f"ann{i}@acme.com"],
             "phones": [{"type": "work", "number": f"330-555-01{i:02d}"}], "website": "acme.com", "address": "1 Main St, Akron, OH 44308", "social": []}
        cid = store.add("fuzz", "raw", f, ""); ui.set_meta(cid, batch="b1", batch_label="B1")
        if i == 1: store.update(cid, status="approved", reviewer="FA", note="")
    s.headers["X-CSRF-Token"] = s.cookies.get("gac_csrf")   # double-submit: the cookie goes along with every request
    return s

def _fill_versions(case, s):
    """Like the page: saves carry the card's current version and the settings page its shown values. Only filled in when the
    generated body has no such key, so wrong/missing versions are fuzzed too, but most cases get past optimistic locking."""
    b = case.body
    if not isinstance(b, dict): return
    cid = (case.path_parameters or {}).get("cid")
    if case.method == "POST" and cid is not None and "version" not in b and case.path.endswith(("{cid}", "/ai-decide", "/confirm-correct")):
        g = s.get(f"/api/cards/{cid}")
        if g.status_code == 200: b["version"] = g.json().get("version")
    if case.path == "/api/admin/settings" and "_seen" not in b:
        b["_seen"] = {k: v for k, v in s.get("/api/admin/settings").json().items() if not k.startswith("_")}
    if case.path == "/api/cards-bulk" and "versions" not in b and isinstance(b.get("ids"), list):
        vs = {}
        for i in b["ids"]:
            g = s.get(f"/api/cards/{i}") if isinstance(i, int) and 0 < i < 10**6 else None
            if g is not None and g.status_code == 200: vs[str(i)] = g.json().get("version")
        b["versions"] = vs

@schema.parametrize()
@settings(max_examples=30, deadline=None, derandomize=True, database=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large])
def test_api_never_500(case, session):
    _fill_versions(case, session)
    r = case.call(session=session)
    case.validate_response(r, checks=[not_a_server_error])
    # a wrong password at /api/auth/login is a 401 on purpose; anywhere else it means a case signed the fuzzing admin out
    if r.status_code == 401 and case.path != "/api/auth/login":
        pytest.fail(f"the fuzzing session was signed out by {case.method} {case.formatted_path}: {json.dumps(case.body, default=str)[:500]}")
