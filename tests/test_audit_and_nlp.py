"""Bed-blocking trigger, the audit view, and the free-text parser."""
import pytest

from app import demo, nlp


def test_hold_limit_trigger_and_audit_flag(fresh):
    res = demo.spam(8)
    assert res["held"] == 5 and res["refused"] == 3
    assert all(a["code"] == 1644 for a in res["attempts"] if a["outcome"] == "REJECTED")
    audit = demo.audit()
    flagged = [r["name"] for r in audit["rows"] if r["flagged"]]
    assert flagged == ["Suspicious Agent"]


SENTENCES = [
    ("need ventilator bed near Jayanagar, patient 60M critical", "ICU_VENTILATOR", "Jayanagar", 60, "M", 5),
    ("ICU bed required in jaynagar for 45 year old female, serious", "ICU", "Jayanagar", 45, "F", 4),
    ("oxygen support needed near koramangla, 72 yrs male, stable", "OXYGEN", "Koramangala", 72, "M", 2),
    ("Ambulance at Whitefeild with intubated patient aged 58, woman", "ICU_VENTILATOR", "Whitefield", 58, "F", None),
    ("Patient Ravi Kumar, 33M, needs ICU near MG Road, emergency", "ICU", "MG Road", 33, "M", 4),
    ("o2 bed near e city for 66 year old lady", "OXYGEN", "Electronic City", 66, "F", None),
    ("critical care bed hebbal 80 f severity 5", "ICU", "Hebbal", 80, "F", 5),
    ("need vent icu near indira nagar 12 year old boy critical", "ICU_VENTILATOR", "Indiranagar", 12, "M", 5),
    ("Malleshwaram, 50/F, ICU, moderate", "ICU", "Malleshwaram", 50, "F", 3),
    ("require oxygen bed at btm layout for male aged 41 mild breathing issue", "OXYGEN", "BTM Layout", 41, "M", 1),
    ("ventilator needed urgently near Electronic City 70M", "ICU_VENTILATOR", "Electronic City", 70, "M", 4),
    ("ICU bed in HSR for 29 yo female unconscious", "ICU", "HSR Layout", 29, "F", 5),
]


@pytest.mark.parametrize("text,bed,area,age,gender,severity", SENTENCES)
def test_nlp_sentence(text, bed, area, age, gender, severity):
    p = nlp.parse(text)
    assert p["bed_type"] == bed
    assert p["area"] == area
    assert p["age"] == age
    assert p["gender"] == gender
    if severity is not None:
        assert p["severity"] == severity


def test_nlp_extracts_name():
    assert nlp.parse("Patient Ravi Kumar, 33M, needs ICU near MG Road")["name"] == "Ravi Kumar"
