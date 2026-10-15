"""Round 24 checks: website lost dot, CamelCase brands, phone with a letter, READ-ME 1 row."""
from app import ui as U

def test_website_lost_dot_blocks():
    assert "website" in U.hard_errors({"first_name": "A", "website": "www.firestoneparkhardwexample.com"})
    assert "website" not in U.hard_errors({"first_name": "A", "website": "www.example.com", "emails": ["a@example.com"]})

def test_linkedin_not_blocked():
    for c in ("LinkedIn", "HubSpot", "QuickBooks", "PayPal"):
        assert "company" not in U.hard_errors({"first_name": "A", "company": c}), c

def test_phone_letter_message():
    e = U.hard_errors({"first_name": "A", "phones": [{"number": "33o-555-0100"}]})["phones"]
    assert "letter" in e and "area code" not in e
    assert "area code" in U.hard_errors({"first_name": "A", "phones": [{"number": "555-0100"}]})["phones"]
