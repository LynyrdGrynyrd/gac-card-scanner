"""v0.4.10: the earlier-export date works on every OS (Windows has no strftime "%-d"). Made-up data only."""
import os, re, time
from test_app import mk  # noqa: F401  (imports the app the way the other tests do)


def test_v0410_no_glibc_only_strftime_codes():
    bad = re.compile(r"strftime\([^)]*%[-#][a-zA-Z]")
    hits = []
    for d, _, fs in os.walk("app"):
        for f in fs:
            if f.endswith(".py"):
                p = os.path.join(d, f)
                for i, line in enumerate(open(p, encoding="utf-8"), 1):
                    if bad.search(line): hits.append(f"{p}:{i}")
    assert not hits, hits


def test_v0410_when_where_date():
    import app.main  # noqa: F401  (load the app first, as the server does)
    from app import exporting
    ts = time.mktime((2026, 10, 3, 12, 0, 0, 0, 0, -1))
    assert exporting.when_where({"ts": ts, "file": "x.xlsx", "user": "bob"}, {"username": "amy"}) == "in an earlier export (Oct 3)"
    assert exporting.when_where({"ts": ts, "file": "x.xlsx", "user": "amy"}, {"username": "amy"}) == "in x.xlsx (Oct 3)"
    assert exporting.when_where(None) == "in an earlier export"
