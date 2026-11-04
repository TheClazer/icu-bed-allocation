"""Free-text request parser (the innovative component).

"need ventilator bed near Jaynagar, patient 60M critical"
    -> bed_type ICU_VENTILATOR, area Jayanagar, age 60, gender M, severity 5

Offline and explainable: keyword rules + regular expressions, plus fuzzy string
matching (rapidfuzz) so misspelt area names still resolve ("jaynagar" -> Jayanagar).
Every extracted field also returns the words it came from, so the UI can show
exactly why it decided what it decided.
"""
import re

from rapidfuzz import fuzz

from .areas import AREAS

BED_RULES = [
    ("ICU_VENTILATOR", 2, r"\bventilat\w*|\bvent\b|\bintubat\w*|\bmechanical(?:ly)? ventilat\w*"),
    ("OXYGEN", 3, r"\boxygen\b|\bo2\b|\boxy\b"),
    ("ICU", 1, r"\bicu\b|\bintensive care\b|\bcritical care\b|\bhdu\b"),
]

SEVERITY_RULES = [
    (5, r"\bcritical\w*|\bunconscious\b|\bunresponsive\b|\blife[- ]threatening\b|\bcode red\b|\bsinking\b"),
    (4, r"\bsevere\w*|\bserious\w*|\bemergenc\w*|\burgent\w*|\bdeteriorat\w*"),
    (3, r"\bmoderate\w*"),
    (2, r"\bstable\b"),
    (1, r"\bmild\w*|\bminor\b"),
]

MALE = r"\b(?:male|man|boy|gentleman|mr\.?|he|his|him)\b"
FEMALE = r"\b(?:female|woman|girl|lady|mrs\.?|ms\.?|she|her)\b"

STOP = {"need", "needs", "needed", "bed", "beds", "near", "patient", "required", "require", "with",
        "for", "the", "and", "from", "please", "ambulance", "urgent", "urgently", "critical",
        "male", "female", "year", "years", "old", "oxygen", "ventilator", "support", "icu"}


def _area_candidates():
    for a in AREAS:
        yield a, a["name"].lower()
        for alias in a["aliases"]:
            yield a, alias.lower()


def find_area(text):
    low = text.lower()
    # 1. exact name or alias anywhere in the text
    for a, key in _area_candidates():
        if re.search(r"\b" + re.escape(key) + r"\b", low):
            return a, key, 100
    # 2. fuzzy: compare every 1-3 word window against every name and alias
    words = re.findall(r"[a-z]+", low)
    best = (None, None, 0)
    for n in (1, 2, 3):
        for i in range(len(words) - n + 1):
            window = words[i:i + n]
            if n == 1 and (len(window[0]) < 4 or window[0] in STOP):
                continue
            phrase = " ".join(window)
            for a, key in _area_candidates():
                score = max(fuzz.ratio(phrase, key), fuzz.ratio(phrase.replace(" ", ""), key.replace(" ", "")))
                if score > best[2]:
                    best = (a, phrase, score)
    if best[2] >= 82:
        return best
    return None, None, 0


def parse(text):
    text = (text or "").strip()
    low = text.lower()
    out = {"text": text, "bed_type": None, "bed_type_id": None, "area": None, "lat": None, "lon": None,
           "age": None, "gender": None, "severity": None, "name": None, "evidence": [], "inferred": []}

    def evidence(field, words, how):
        out["evidence"].append({"field": field, "words": words, "how": how})

    # bed type (ventilator wins over ICU, since "ICU with ventilator" is a ventilator bed)
    masked = low
    for name, tid, pattern in BED_RULES:
        m = re.search(pattern, low)
        if m:
            out["bed_type"], out["bed_type_id"] = name, tid
            evidence("bed_type", m.group(0), "keyword")
            break
    for _, _, pattern in BED_RULES:
        masked = re.sub(pattern, " ", masked)   # so "critical care" is not read as severity

    # severity: explicit number first, then words
    m = re.search(r"\b(?:severity|sev|level|grade)\s*[:=]?\s*([1-5])\b", masked)
    if m:
        out["severity"] = int(m.group(1))
        evidence("severity", m.group(0), "explicit number")
    else:
        for level, pattern in SEVERITY_RULES:
            m = re.search(pattern, masked)
            if m:
                out["severity"] = level
                evidence("severity", m.group(0), "keyword")
                break

    # age and gender: "60M", "60 / F", "45 year old female", "aged 70", "72 yrs male"
    m = re.search(r"\b(\d{1,3})\s*(?:y|yr|yrs|year|years|yo|y/o)?(?:\s*old)?\s*[/,-]?\s*(m|f|male|female)\b", low)
    if m and 0 < int(m.group(1)) <= 120:
        out["age"] = int(m.group(1))
        out["gender"] = "M" if m.group(2).startswith("m") else "F"
        evidence("age", m.group(0), "pattern number + sex")
        evidence("gender", m.group(0), "pattern number + sex")
    else:
        m = re.search(r"\b(?:aged?|age)\s*[:=]?\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:years?|yrs?|yo|y/o)\b", low)
        if m:
            age = int(m.group(1) or m.group(2))
            if 0 < age <= 120:
                out["age"] = age
                evidence("age", m.group(0), "pattern")
    if out["gender"] is None:
        m_f, m_m = re.search(FEMALE, low), re.search(MALE, low)
        if m_f:
            out["gender"] = "F"
            evidence("gender", m_f.group(0), "keyword")
        elif m_m:
            out["gender"] = "M"
            evidence("gender", m_m.group(0), "keyword")

    # area
    area, words, score = find_area(text)
    if area:
        out["area"], out["lat"], out["lon"] = area["name"], area["lat"], area["lon"]
        evidence("area", words, "exact" if score == 100 else f"fuzzy match {round(score)}%")

    # patient name: "patient Ravi Kumar", "name: Meera Rao", "Mr Arjun"
    m = re.search(r"\b(?i:patient(?:'s)?(?: name)?|name|mr\.?|mrs\.?|ms\.?)\s*(?i:is|:|-)?\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text)
    if m:
        candidate = m.group(1)
        if candidate.lower() not in {a["name"].lower() for a in AREAS} and not find_area(candidate)[0]:
            out["name"] = candidate
            evidence("name", m.group(0), "pattern")

    # fill gaps sensibly and say so
    if out["bed_type"] is None and (out["severity"] or 0) >= 4:
        out["bed_type"], out["bed_type_id"] = "ICU", 1
        out["inferred"].append("bed_type")
    if out["severity"] is None:
        out["severity"] = 4 if out["bed_type"] == "ICU_VENTILATOR" else 3
        out["inferred"].append("severity")
    return out
