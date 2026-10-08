from cppp_adapter import extract_home_listings

HTML = """<table><tr><th>Tender Title</th><th>Reference No</th>
<th>Closing Date</th><th>Bid Opening Date</th></tr>
<tr><td><a href="/eprocure/app?notice=123">DigiLocker API integration</a></td>
<td>ABC/2026/01</td><td>28-Oct-2026 04:00 PM</td><td>29-Oct-2026 05:00 PM</td></tr>
<tr><td>Road resurfacing</td><td>RD/9</td>
<td>28-Oct-2026 04:00 PM</td><td>29-Oct-2026 05:00 PM</td></tr></table>"""


def test_public_listing_filters_at_row_level():
    rows = extract_home_listings(
        HTML, "https://eprocure.gov.in/eprocure/app", "DigiLocker", "cppp_eprocure"
    )
    assert len(rows) == 1
    assert rows[0]["tender_reference"] == "ABC/2026/01"
    assert rows[0]["submission_deadline"] is None
    assert rows[0]["tender_url"].startswith("https://eprocure.gov.in/")


def test_no_match_for_irrelevant_topic():
    assert not extract_home_listings(
        HTML, "https://eprocure.gov.in/eprocure/app", "Hospital", "cppp_eprocure"
    )
