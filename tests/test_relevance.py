from relevance import topic_present, precheck_document, qualify_analysis
from benchmark_models import grade


def test_pan_requires_tax_identifier_context():
    assert not topic_present("PAN", "PAN-India public health department campaign")
    assert not topic_present("PAN", "Company planning and expansion")
    assert topic_present("PAN", "Tender for PAN Card verification services")
    assert topic_present("PAN", "Procurement of Permanent Account Number API verification")


def test_strict_pan_document_filter():
    irrelevant = {"text": "Government tender for new office chairs. PAN India supply. " * 12,
                  "extraction_status": "ok"}
    relevant = {"text": "Request for Proposal for PAN card verification API services. " * 12,
                "extraction_status": "ok"}
    assert precheck_document("PAN", irrelevant)[0] is False
    assert precheck_document("PAN", relevant)[0] is True


def test_untitled_records_are_review_not_opportunities():
    document = {"text": "Tender for PAN card verification API services. " * 15}
    weak = {"tender_title": None, "issuing_authority": "Some department",
            "scope_summary": "PAN card verification tender requirements"}
    decision = qualify_analysis("PAN", weak, document)
    assert decision["status"] == "review"
    assert "title" in decision["reason"].lower()


def test_qualified_pan_tender():
    document = {"text": "Tender notice for PAN card verification API integration. " * 15}
    facts = {
        "tender_title": "RFP for PAN card verification API integration services",
        "scope_summary": "The supplier shall integrate PAN verification services in the department portal.",
        "tender_reference": "IT-PAN-2026-27",
    }
    assert qualify_analysis("PAN", facts, document)["status"] == "candidate"


def test_benchmark_prefers_facts_not_unsupported_output():
    assert grade({"tender_reference": "IT/PAN/2026/17",
                  "is_procurement": True,
                  "technical_requirements": ["Integrate PAN verification APIs"]},
                 "IT/PAN/2026/17", "pan") == 4
    assert grade({"tender_reference": "invented", "is_procurement": True},
                 None, "not_tender") == 0
