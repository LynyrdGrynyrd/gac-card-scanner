"""Round 19: Cancel on the Scan screen drops cards still waiting in line; finished cards stay."""
import os, time

def _fake_job(ui, jid, who, state="queued"):
    with ui.JLOCK: ui.JOBS[jid] = {"id": jid, "state": state, "file": jid + ".jpg", "batch": "r19-c", "sha": jid, "created": time.time(), "who": who}
    open(os.path.join(ui.INBOX, jid + ".bin"), "wb").write(b"x")

def test_cancel_queued_keeps_done(env):
    ui, rc = env["ui"], env["rev"]
    me = rc.get("/api/me").json()
    me = (me.get("user") or me).get("initials")
    _fake_job(ui, "c19aaaaaaaa1", me); _fake_job(ui, "c19aaaaaaaa2", me, "done"); _fake_job(ui, "c19aaaaaaaa3", "ZZ")
    r = rc.post("/api/jobs/cancel", json={"ids": ["c19aaaaaaaa1", "c19aaaaaaaa2", "c19aaaaaaaa3", "nope"]})
    assert r.status_code == 200 and r.json()["cancelled"] == 1
    assert ui.JOBS["c19aaaaaaaa1"]["state"] == "cancelled" and not os.path.exists(os.path.join(ui.INBOX, "c19aaaaaaaa1.bin"))
    assert ui.JOBS["c19aaaaaaaa2"]["state"] == "done"            # already read: kept
    assert ui.JOBS["c19aaaaaaaa3"]["state"] == "queued"          # someone else's: untouched
    # the worker skips a cancelled job (no card is made)
    n = len(env["store"].list_cards()) if hasattr(env["store"], "list_cards") else None
    ui._run("c19aaaaaaaa1", None, "auto", ".jpg", "r19-c", None, "x.jpg", "x", me)
    assert ui.JOBS["c19aaaaaaaa1"]["state"] == "cancelled"
    if n is not None: assert len(env["store"].list_cards()) == n
    st = rc.get("/api/jobs?ids=c19aaaaaaaa1").json()["jobs"][0]; assert st["state"] == "cancelled"
    # admin may cancel anyone's
    assert env["adm"].post("/api/jobs/cancel", json={"ids": ["c19aaaaaaaa3"]}).json()["cancelled"] == 1
    for j in ("c19aaaaaaaa1", "c19aaaaaaaa2", "c19aaaaaaaa3"): ui.JOBS.pop(j, None)
