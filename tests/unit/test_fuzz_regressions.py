"""Fuzz 2026-10: every 500 the Schemathesis run (tests/api) found, as a plain request. Wrong JSON types in a known key must
get a 4xx with a message, never a crash."""
import pytest


def _card(env):
    f = {"first_name": "Fay", "last_name": "Fuzz", "emails": ["fay@fuzz.io"], "phones": [{"type": "work", "number": "330-555-0199"}], "social": []}
    cid = env["store"].add("test", "raw", f, ""); env["ui"].set_meta(cid, batch="bfz", batch_label="Fuzz")
    from test_app import _rev_ini; env["ui"].log(cid, _rev_ini(env["ui"]), "scanned"); return cid   # v0.4.6: rev's own card


@pytest.mark.parametrize("body", [{"username": [None, None], "password": "x"}, {"username": "adm", "password": {"a": 1}}])
def test_login_non_text_is_422(env, body):
    r = env["rev"].post("/api/auth/login", json=body)
    assert r.status_code == 422 and "text" in r.json()["error"]


@pytest.mark.parametrize("body", [{"username": None, "display": None, "password": "temp-pass-1234"},
                                  {"username": "fz1", "display": "Fz One", "password": "temp-pass-1234", "initials": {}},
                                  {"username": "fz2", "display": ["x"], "password": "temp-pass-1234"},
                                  {"username": "fz3", "display": "Fz Three", "password": True}])
def test_add_user_non_text_is_422(env, body):
    r = env["adm"].post("/api/admin/users", json=body)
    assert r.status_code == 422 and r.json()["error"]


def test_edit_user_password_non_text_is_422(env):
    uid = next(u["id"] for u in env["adm"].get("/api/admin/users").json() if u["username"] == "rev2")
    r = env["adm"].post(f"/api/admin/users/{uid}", json={"active": None, "password": True, "role": None})
    assert r.status_code == 422 and "text" in r.json()["error"]
    assert env["rev2"].get("/api/me").status_code == 200   # nothing was written: rev2 is still signed in


@pytest.mark.parametrize("fields", [[None], {"phones": True}, {"phones": [None]}, {"phones": [{"number": 3305550100}]},
                                    {"social": True}, {"emails": "ann@acme.com"}, {"emails": [None]}, {"first_name": {"x": 1}}])
def test_validate_bad_field_shapes_are_422(env, fields):
    r = env["rev"].post("/api/validate", json={"card_id": None, "fields": fields, "note": None})
    assert r.status_code == 422 and r.json()["need"] == "fix", r.text


@pytest.mark.parametrize("fields", [[None], {"emails": "fay@fuzz.io"}, {"phones": True}])
def test_save_bad_field_shapes_are_422_and_change_nothing(env, fields):
    cid = _card(env); before = env["store"].get(cid)["fields"]
    r = env["rev"].post(f"/api/cards/{cid}", json={"fields": fields})   # the Client fills in the current version
    assert r.status_code == 422 and r.json()["need"] == "fix", r.text
    assert env["store"].get(cid)["fields"] == before


def test_save_with_good_shapes_still_works(env):
    cid = _card(env)
    r = env["rev"].post(f"/api/cards/{cid}", json={"fields": {"title": "CTO", "emails": ["fay@fuzz.io"], "phones": [{"type": "mobile", "number": "330-555-0198"}]}})
    assert r.status_code == 200, r.text
    assert env["store"].get(cid)["fields"]["title"] == "CTO"


def test_merge_preview_bad_fields_is_422(env):
    a, b = _card(env), _card(env)
    r = env["rev"].post(f"/api/cards/{a}/merge-preview", json={"into": b, "fields": [1]})
    assert r.status_code == 422, r.text


BIG = 2 ** 63   # one past SQLite's INTEGER range: 'Python int too large to convert to SQLite INTEGER' was a 500
@pytest.mark.parametrize("url", [f"/api/exports/{BIG}/download", f"/api/exports/{BIG}/companion/readme.txt", f"/api/admin/audit?limit={BIG}",
                                 f"/api/admin/audit?q=x&limit={-BIG}", f"/img/nope.jpg?w={BIG}"])
def test_huge_numbers_in_urls_are_not_500(env, url):
    r = env["adm"].get(url)
    assert r.status_code in (404, 422) or (url.startswith("/img/") and r.status_code == 200), (r.status_code, r.text)


def test_huge_user_id_is_404(env):
    r = env["adm"].post(f"/api/admin/users/{BIG}", json={"role": "admin"})
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("batch", [{}, [], 5, None, ""])
def test_archive_batch_must_be_a_name(env, batch):
    r = env["adm"].post("/api/batches/archive", json={"batch": batch, "confirm": None})
    assert r.status_code == 422 and "batch" in r.json()["error"]


@pytest.mark.parametrize("fields", [{"company": "a" * 65000}, {"emails": ["a" * 65000]}, {"phones": [{"type": "work", "number": "1" * 65000}]},
                                    {"x_department": "a" * 65000}, {"note": "a" * 65000}])
def test_validate_overlong_value_is_422(env, fields):
    """Fuzz 2026-11 (schemathesis 4.33): a 65,000-letter company kept /api/validate busy for more than 10 s; text values had no length limit."""
    r = env["rev"].post("/api/validate", json={"card_id": None, "fields": fields, "note": None})
    assert r.status_code == 422 and "too long" in r.json()["error"]
    ok = env["rev"].post("/api/validate", json={"card_id": None, "fields": {"company": "a" * 1000, "overall_confidence": 0.9, "confidence": {"name": 0.9}}, "note": None})
    assert ok.status_code == 200


@pytest.mark.parametrize("fields", [{"x_department": {"v": "a" * 2000}}, {"x_credentials": [["a" * 2000]]}, {"x_other_address": 5}])
def test_alias_fields_must_be_text_too(env, fields):
    """Review 2026-11 (Codex + Gemini): a dict under x_department passed the shape check and became its str() form, any length."""
    r = env["rev"].post("/api/validate", json={"card_id": None, "fields": fields, "note": None})
    assert r.status_code == 422 and "must be text" in r.json()["error"] and r.json()["need"] == "fix", r.text


def test_apply_fields_never_turns_a_container_into_text(env):
    f = {"note": "keep", "department": ""}
    assert env["ui"]._apply_fields(f, {"note": {"v": "a" * 2000}, "x_department": ["a" * 2000]}) == {} and f == {"note": "keep", "department": ""}


def test_save_and_merge_preview_refuse_an_overlong_value(env):
    a, b = _card(env), _card(env); before = env["store"].get(a)["fields"]
    r = env["rev"].post(f"/api/cards/{a}", json={"fields": {"company": "a" * 1001}})
    assert r.status_code == 422 and "too long" in r.json()["error"] and r.json()["need"] == "fix" and env["store"].get(a)["fields"] == before
    r = env["rev"].post(f"/api/cards/{a}/merge-preview", json={"into": b, "fields": {"x_department": "a" * 1001}})
    assert r.status_code == 422 and "too long" in r.json()["error"] and r.json()["need"] == "fix"


def test_length_limit_ignores_what_can_never_become_card_text(env):
    """Review 2026-11 (Codex): a long string inside a list under a key the server ignores, or under an unused phone key, must not refuse the edit."""
    fields = {"company": "Acme", "unused": ["x" * 1001], "boxes": {"company": ["x" * 1001]}, "phones": [{"type": "work", "number": "330-555-0100", "label": "x" * 1001}]}
    r = env["rev"].post("/api/validate", json={"card_id": None, "fields": fields, "note": None})
    assert r.status_code == 200, r.text
