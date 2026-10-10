from it_fit import it_fit
from relevance import qualify_analysis


def test_pure_ration_card_printing_is_not_it_lead():
    text = "Tender for supply and personalization of plastic ration cards. Printer shall deliver printed cards."
    facts = {"tender_title": "Tender for printing ration cards",
             "scope_summary": "The agency shall print and supply plastic ration cards."}
    decision = qualify_analysis("Ration Card", facts, {"text": text})
    assert decision["status"] == "rejected"
    assert "IT" in decision["reason"]


def test_ration_card_portal_api_is_it_opportunity():
    text = "RFP for ration card management API integration, citizen portal and digital system."
    facts = {"tender_title": "RFP for ration card management portal",
             "scope_summary": "Implement an online citizen portal with database and API integration."}
    assert qualify_analysis("Ration Card", facts, {"text": text})["status"] == "candidate"


def test_pan_card_physical_delivery_is_not_an_it_implementation():
    assert it_fit("PAN card supply contract",
                  "Printing PAN cards and physical delivery of cards.")["status"] == "non_it"


def test_digilocker_software_integration_is_it():
    fit = it_fit("DigiLocker integration RFP",
                 "Develop API integration with a citizen portal and database")
    assert fit["status"] == "it_candidate"


def test_department_name_does_not_create_it_fit():
    result = it_fit("Office furniture tender", "Supply chairs and office furniture")
    assert result["status"] != "it_candidate"


def test_ambiguous_it_mention_stays_in_review():
    assert it_fit("Tender for ration card service", "Use computers for tracking deliveries")["status"] == "review"
