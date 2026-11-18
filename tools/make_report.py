"""Builds the project report (Word .docx).

  .venv\\Scripts\\python.exe tools\\make_report.py  <output.docx>

Formatting follows the department's report format (tools/report_template, built by
tools/make_report_template.py from a format sample): Letter page with the RVCE
double page border and watermark, RVCE letterhead on the title page, RVCE logo on
the certificate and declaration, RVCE footer strip on the front pages, Times New
Roman throughout, body 12 pt justified at 1.5 line spacing, chapter headings
"CHAPTER n: TITLE" 14 pt bold, section headings 12 pt bold, figure captions 12 pt
bold centred below the figure.
"""
import copy
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Twips

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "docs" / "figures"
SHOT = ROOT / "docs" / "screenshots"
TPL = ROOT / "tools" / "report_template"
FONT = "Times New Roman"

doc = Document(TPL / "template.docx")
body_el = doc.element.body
marker = body_el.find(qn("w:p"))                      # carries the front-matter section definition
FRONT_SECT = copy.deepcopy(marker.find(qn("w:pPr")).find(qn("w:sectPr")))
body_el.remove(marker)


# ------------------------------------------------------------------ base styles
def set_font(style_or_run, size=None, bold=None, italic=None, name=FONT):
    f = style_or_run.font
    f.name = name
    if size:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    el = style_or_run.element if hasattr(style_or_run, "element") else style_or_run._element
    rpr = el.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(a), name)


normal = doc.styles["Normal"]
set_font(normal, 12)
normal.paragraph_format.space_before = Twips(56)
normal.paragraph_format.space_after = Pt(0)
normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

for name, size, spacing in (("Heading 1", 14, WD_LINE_SPACING.SINGLE),
                            ("Heading 2", 12, WD_LINE_SPACING.ONE_POINT_FIVE),
                            ("Heading 3", 12, WD_LINE_SPACING.ONE_POINT_FIVE)):
    st = doc.styles[name]
    set_font(st, size, bold=True, italic=False)
    pf = st.paragraph_format
    pf.space_before = Twips(56) if name != "Heading 1" else Pt(0)
    pf.space_after = Pt(6) if name == "Heading 1" else Pt(0)
    pf.line_spacing_rule = spacing
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf.keep_with_next = True
    rpr = st.element.get_or_add_rPr()
    for tag in ("w:color", "w:sz", "w:szCs"):
        for c in rpr.findall(qn(tag)):
            if tag == "w:color":
                rpr.remove(c)
    set_font(st, size)

cap = doc.styles["Caption"]
set_font(cap, 12, bold=True, italic=False)
cap.font.color.rgb = None
cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
cap.paragraph_format.space_before = Twips(56)
cap.paragraph_format.space_after = Pt(8)
cap.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

for nm in ("Figure Caption", "Table Caption"):
    st = doc.styles.add_style(nm, 1)
    st.base_style = cap
    set_font(st, 12, bold=True, italic=False)


# ------------------------------------------------------------------ list numbering (from the template)
numbering = doc.part.numbering_part.element
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _abstract_of(num_id):
    for n in numbering.findall(W + "num"):
        if n.get(W + "numId") == str(num_id):
            return n.find(W + "abstractNumId").get(W + "val")
    raise KeyError(num_id)


BULLET_NUM = 15                      # round bullet, hanging indent
DECIMAL_ABS = _abstract_of(18)       # "1." numbered list
_next_num = [max(int(n.get(W + "numId")) for n in numbering.findall(W + "num")) + 1]


def new_numbered_list():
    """A fresh w:num on the decimal list so every numbered list starts at 1."""
    nid = _next_num[0]
    _next_num[0] += 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(nid))
    a = OxmlElement("w:abstractNumId"); a.set(qn("w:val"), DECIMAL_ABS); num.append(a)
    o = OxmlElement("w:lvlOverride"); o.set(qn("w:ilvl"), "0")
    s = OxmlElement("w:startOverride"); s.set(qn("w:val"), "1"); o.append(s); num.append(o)
    numbering.append(num)
    return nid


def set_num(p, num_id):
    ppr = p._p.get_or_add_pPr()
    np_ = OxmlElement("w:numPr")
    il = OxmlElement("w:ilvl"); il.set(qn("w:val"), "0"); np_.append(il)
    ni = OxmlElement("w:numId"); ni.set(qn("w:val"), str(num_id)); np_.append(ni)
    ppr.insert(0, np_) if ppr.find(qn("w:pStyle")) is None else ppr.find(qn("w:pStyle")).addnext(np_)


# ------------------------------------------------------------------ helpers
def para(text="", size=12, bold=False, italic=False, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
         spacing=WD_LINE_SPACING.ONE_POINT_FIVE, before=None, after=None, style=None, color=None):
    p = doc.add_paragraph(style=style)
    p.alignment = align
    p.paragraph_format.line_spacing_rule = spacing
    if before is not None:
        p.paragraph_format.space_before = Pt(before)
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    if text:
        add_runs(p, text, size, bold, italic, color)
    return p


def add_runs(p, text, size=12, bold=False, italic=False, color=None):
    """Supports **bold** spans inside text."""
    parts = text.split("**")
    for i, part in enumerate(parts):
        if not part:
            continue
        r = p.add_run(part)
        set_font(r, size, bold=bold or (i % 2 == 1), italic=italic)
        if color:
            r.font.color.rgb = RGBColor.from_string(color)
    return p


def centre(text, size=14, bold=True, before=0, after=0, spacing=WD_LINE_SPACING.SINGLE, italic=False, color=None):
    return para(text, size, bold, italic, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=spacing,
                before=before, after=after, color=color)


def small_caps_heading(text, size=14, after=10):
    p = para("", align=WD_ALIGN_PARAGRAPH.LEFT, spacing=WD_LINE_SPACING.SINGLE, before=0, after=after)
    r = p.add_run(text)
    set_font(r, size)
    r.font.small_caps = True
    return p


def picture(path, width):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    p.add_run().add_picture(str(path), width=Inches(width))
    return p


def page_break():
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    p.add_run().add_break(WD_BREAK.PAGE)


def chapter_heading(text, new_page=True):
    if new_page:
        page_break()
    h = doc.add_paragraph(style="Heading 1")
    set_font(h.add_run(text), 14, bold=True)


def chapter(n, title):
    chapter_heading(f"CHAPTER {n}: {title.upper()}")


def section(num, title):
    h = doc.add_paragraph(style="Heading 2")
    set_font(h.add_run(f"{num} {title}"), 12, bold=True)


def sub(title):
    h = doc.add_paragraph(style="Heading 3")
    set_font(h.add_run(title), 12, bold=True)


def bullets(items, numbered=False):
    nid = new_numbered_list() if numbered else BULLET_NUM
    for it in items:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        p.paragraph_format.space_before = Twips(56)
        set_num(p, nid)
        add_runs(p, it)


def code(text):
    for line in text.strip("\n").split("\n"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.left_indent = Inches(0.3)
        r = p.add_run(line if line else " ")
        set_font(r, 10, name="Courier New")
    para("", spacing=WD_LINE_SPACING.SINGLE, before=0)


figures, tables = [], []


def figure(path, caption, width=6.2):
    if not Path(path).exists():
        para(f"[Figure missing: {Path(path).name}]", italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Inches(width))
    figures.append(caption)
    doc.add_paragraph(f"Figure {caption}", style="Figure Caption")


def table(caption, header, rows, widths=None):
    tables.append(caption)
    c_ = doc.add_paragraph(f"Table {caption}", style="Table Caption")
    c_.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        pp = c.paragraphs[0]
        pp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pp.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pp.paragraph_format.space_before = Pt(2)
        pp.paragraph_format.space_after = Pt(2)
        set_font(pp.add_run(h), 12, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            pp = cells[i].paragraphs[0]
            pp.alignment = WD_ALIGN_PARAGRAPH.LEFT
            pp.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            pp.paragraph_format.space_before = Pt(2)
            pp.paragraph_format.space_after = Pt(2)
            add_runs(pp, str(v), 12)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    para("", spacing=WD_LINE_SPACING.SINGLE, before=0)


def borderless(t):
    tblpr = t._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{side}"); e.set(qn("w:val"), "nil"); b.append(e)
    tblpr.append(b)


def field(p, instr):
    r = p.add_run()
    b = OxmlElement("w:fldChar"); b.set(qn("w:fldCharType"), "begin"); r._r.append(b)
    t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = instr; r._r.append(t)
    s = OxmlElement("w:fldChar"); s.set(qn("w:fldCharType"), "separate"); r._r.append(s)
    r2 = p.add_run("Right-click and choose Update Field to build this list.")
    set_font(r2, 12, italic=True)
    e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), "end"); p.add_run()._r.append(e)


def list_page(title, instr, first=False):
    if not first:
        page_break()
    small_caps_heading(title, 14, after=2)
    p = para("", align=WD_ALIGN_PARAGRAPH.RIGHT, spacing=WD_LINE_SPACING.SINGLE, before=0, after=8)
    r = p.add_run("Page No"); set_font(r, 12); r.font.small_caps = True
    field(doc.add_paragraph(), instr)


# ================================================================== title page
picture(TPL / "letterhead.png", 6.6)
centre("DEPARTMENT OF COMPUTER SCIENCE AND ENGINEERING", 14, spacing=WD_LINE_SPACING.DOUBLE, before=18)
centre("City ICU Bed Allocation System", 14, spacing=WD_LINE_SPACING.DOUBLE, color="FF0000")
centre("A transaction-safe bed booking system on MySQL 8 and Redis 7", 14,
       spacing=WD_LINE_SPACING.DOUBLE, after=6, color="FF0000")
centre("Database Management Systems Lab (CD252IA)", 14)
centre("Mini Project Report", 14, before=4)
centre("Submitted by", 12, bold=False, italic=True, before=40, after=6)
t = doc.add_table(rows=2, cols=2)
t.alignment = WD_TABLE_ALIGNMENT.CENTER
borderless(t)
for i, (n, u) in enumerate((("Rayyan Shaikh", "1RV24CY044"), ("Pooja Nagesh", "1RV24CY038"))):
    for j, v in enumerate((n, u)):
        c = t.rows[i].cells[j]
        c.text = ""
        pp = c.paragraphs[0]
        pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pp.paragraph_format.line_spacing_rule = WD_LINE_SPACING.DOUBLE
        set_font(pp.add_run(v), 12)
centre("Under the guidance of", 12, bold=False, italic=True, before=40, after=6)
centre("Prof. Shraddha H D", 12)
centre("Assistant Professor", 12, bold=False, before=4)
centre("Department of Computer Science and Engineering", 12, bold=False, before=4)
centre("RV College of Engineering, Bengaluru", 12, bold=False, before=4, after=40)
centre("Academic Year 2026-27", 12)

# ================================================================== certificate
page_break()
picture(TPL / "logo_certificate.png", 4.9)
centre("CERTIFICATE", 18, before=16, after=12)
para("Certified that the mini project titled **City ICU Bed Allocation System** has been carried out by "
     "**Rayyan Shaikh (1RV24CY044)** and **Pooja Nagesh (1RV24CY038)**, bonafide students of RV College of "
     "Engineering, Bengaluru, as part of the course Database Management Systems Lab (CD252IA) during the "
     "academic year 2026-27. The project report has been approved as it satisfies the academic requirements "
     "in respect of the mini project work prescribed for the course.")
for _ in range(3):
    para("", spacing=WD_LINE_SPACING.SINGLE)
sig = doc.add_table(rows=3, cols=2)
borderless(sig)
for j, lines in enumerate((("Prof. Shraddha H D", "Assistant Professor", "Department of CSE, RVCE"),
                           ("Head of Department", "Department of CSE", "RVCE, Bengaluru"))):
    for i, v in enumerate(lines):
        c = sig.rows[i].cells[j]
        c.text = ""
        pp = c.paragraphs[0]
        pp.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.RIGHT
        pp.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        set_font(pp.add_run(v), 12, bold=True if i == 0 else False)
for _ in range(2):
    para("", spacing=WD_LINE_SPACING.SINGLE)
centre("External Viva", 12, before=20, after=12)
ev = para("", bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, spacing=WD_LINE_SPACING.SINGLE, after=14)
ev.paragraph_format.left_indent = Inches(0.4)
ev.paragraph_format.tab_stops.add_tab_stop(Inches(3.9))
set_font(ev.add_run("Name of Examiners\tSignature with Date"), 12, bold=True)
for i in (1, 2):
    p = para("", align=WD_ALIGN_PARAGRAPH.LEFT, spacing=WD_LINE_SPACING.SINGLE, after=14)
    p.paragraph_format.left_indent = Inches(0.4)
    set_font(p.add_run(f"{i}"), 12, bold=True)

# ================================================================== declaration
page_break()
picture(TPL / "logo_declaration.png", 5.4)
centre("DECLARATION", 16, before=16, after=12)
para("We, **Rayyan Shaikh (1RV24CY044)** and **Pooja Nagesh (1RV24CY038)**, students of the Department of "
     "Computer Science and Engineering, RV College of Engineering, Bengaluru, declare that the mini project "
     "titled **City ICU Bed Allocation System** has been carried out by us under the guidance of "
     "Prof. Shraddha H D, Assistant Professor, Department of Computer Science and Engineering, as part of "
     "the Database Management Systems Lab (CD252IA) during the academic year 2026-27.")
para("We further declare that the work presented in this report is original, that all data used in the "
     "system is simulated, and that this work has not been submitted for any other course or degree.",
     before=12)
para("", spacing=WD_LINE_SPACING.SINGLE)
para("Place: Bengaluru", align=WD_ALIGN_PARAGRAPH.LEFT, before=12)
para("Date:", align=WD_ALIGN_PARAGRAPH.LEFT, before=12)
for name in ("Rayyan Shaikh (1RV24CY044)", "Pooja Nagesh (1RV24CY038)"):
    p = para(name, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT)
    p.paragraph_format.left_indent = Inches(0.4)

# ================================================================== acknowledgement
page_break()
small_caps_heading("Acknowledgement")
for t_ in (
    "We thank our guide, **Prof. Shraddha H D**, Assistant Professor, Department of Computer Science and "
    "Engineering, for her guidance throughout this mini project. Her questions about how the system behaves "
    "under concurrent access and failure shaped the direction of the work.",
    "We thank the Head of the Department and the faculty of the Department of Computer Science and "
    "Engineering for the laboratory facilities and the opportunity to apply database concepts to a "
    "practical problem.",
    "We thank the Principal and the management of RV College of Engineering for providing an environment "
    "that encourages hands-on learning. Finally, we thank our families and friends for their support.",
):
    para(t_, after=10)

# ================================================================== abstract
page_break()
small_caps_heading("Abstract")
for t_ in (
    "Critical-care beds are scarce, and during peak demand several helplines and ambulances may try to "
    "book the same bed at the same moment. If two requests are both told that the last ventilator bed is "
    "free, one patient is sent to a bed that does not exist. The City ICU Bed Allocation System addresses "
    "this problem by making the database, rather than the application, responsible for correctness.",
    "The system keeps the beds of seven Bengaluru hospitals in a MySQL 8 database using the InnoDB engine. "
    "A request is matched to the nearest suitable hospital using a Redis GEO index, and a single "
    "transaction then locks one free bed with SELECT ... FOR UPDATE SKIP LOCKED and records a hold that "
    "expires after thirty minutes. A UNIQUE index on a generated column guarantees that a bed can never "
    "carry two live holds, even when the application deliberately omits the lock. Triggers write an audit "
    "trail and enforce a per-account hold limit, a scheduled event expires stale holds inside the database, "
    "transfers use ordered locking to prevent deadlocks, and an asynchronous GTID read replica and two "
    "stateless application instances show how the design scales.",
    "The interface makes the database's behaviour visible as it happens: every SQL statement, row lock, "
    "deadlock, replication delay and crash recovery can be observed live. Automated tests ran the race for "
    "the last bed fifty times with exactly one winner every time, demonstrated the UNIQUE index rejecting a "
    "double booking with error 1062, showed InnoDB resolving a deadlock with error 1213, and confirmed that "
    "killing the MySQL server in the middle of a transfer leaves no partially moved patient. A rule-based "
    "natural language parser converts free-text requests into structured bookings.",
):
    para(t_, after=10)

# ================================================================== contents
page_break()
list_page("Table of Contents", 'TOC \\o "1-2" \\h \\z \\u', first=True)
list_page("List of Figures", 'TOC \\h \\z \\t "Figure Caption,1"')
list_page("List of Tables", 'TOC \\h \\z \\t "Table Caption,1"')

# front matter ends here: its section carries the RVCE footer strip
end_front = doc.add_paragraph()
end_front.paragraph_format.space_before = Pt(0)
end_front._p.get_or_add_pPr().append(FRONT_SECT)

# ================================================================== main body (page numbers from here)
body = doc.sections[-1]
pg = OxmlElement("w:pgNumType"); pg.set(qn("w:start"), "1")
body._sectPr.append(pg)
fp = body.footer.paragraphs[0]
for ch in list(fp._p):
    if ch.tag != qn("w:pPr"):
        fp._p.remove(ch)
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = fp.add_run()
for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
    if kind:
        e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), kind); r._r.append(e)
    else:
        e = OxmlElement("w:instrText"); e.text = text; r._r.append(e)
set_font(r, 12)

# ----------------------------------------------------------- chapter 1
chapter_heading("CHAPTER 1: INTRODUCTION", new_page=False)

section("1.1", "Background")
para("Intensive care units, ventilator beds and oxygen-supported beds are among the scarcest resources in "
     "a city's health system. When demand rises, patients are routed by emergency helplines and ambulance "
     "crews who must find a free bed quickly, often by calling hospitals one at a time. A shared, live view "
     "of bed availability removes those calls, but it introduces a classic database problem: many users "
     "reading and changing the same small set of rows at the same time.")
para("Database management systems were designed for exactly this situation. Transactions, isolation, row "
     "locking, integrity constraints, triggers and crash recovery together guarantee that concurrent users "
     "never see or create an inconsistent state. This project builds a bed allocation system whose "
     "correctness rests entirely on those guarantees, and then lets an evaluator try to break it.")

section("1.2", "Problem Statement")
para("Design and implement a city-wide ICU bed allocation system in which helplines and ambulances can "
     "find and hold the nearest suitable free bed, such that no bed is ever allocated to two patients, holds "
     "that are not converted into admissions are released automatically, the system remains consistent "
     "after a database crash, and every action can be audited. The system must integrate a relational "
     "database (MySQL) with a NoSQL store (Redis) and include an innovative component.")

section("1.3", "Objectives")
bullets([
    "Model hospitals, beds, users, patients, requests, reservations, transfers and an audit trail as a normalised relational schema with integrity constraints.",
    "Implement bed booking as a single ACID transaction that locks exactly one bed row and is safe under concurrent access.",
    "Use constraints, triggers and a scheduled event so that the database itself enforces the rules, independent of application code.",
    "Prevent deadlocks in transfers through ordered locking and demonstrate InnoDB deadlock detection when ordering is disabled.",
    "Demonstrate atomicity and durability by killing the database server in the middle of a transaction.",
    "Integrate Redis for geo search, live counters and event streaming while keeping MySQL as the single source of truth.",
    "Provide a natural language request parser and an interface that shows the database's internal behaviour live.",
])

section("1.4", "Scope")
para("The system covers seven simulated hospitals in Bengaluru with fifty-six beds of three types: ICU, "
     "ICU with ventilator, and oxygen-supported. It supports request intake by form or free text, "
     "nearest-bed search, thirty-minute holds, admission, cancellation, discharge, transfers between beds, "
     "automatic expiry, auditing of accounts that block beds, and a read-only query console. Real patient "
     "data, payments and authentication beyond a role selector are outside the scope of this project.")

section("1.5", "Organisation of the Report")
para("Chapter 2 specifies the hardware, software, functional and non-functional requirements. Chapter 3 "
     "presents the system architecture, the entity relationship model, the relational schema and its "
     "normalisation. Chapter 4 describes the implementation of the database objects, transactions, Redis "
     "integration, the natural language parser and the interface. Chapter 5 reports the tests and the "
     "observed results of each failure scenario. Chapter 6 concludes and lists future enhancements.")

# ----------------------------------------------------------- chapter 2
chapter(2, "Requirement Specification")
section("2.1", "Hardware Requirements")
table("2.1: Hardware requirements", ["Component", "Minimum", "Recommended"], [
    ["Processor", "64-bit quad-core with VT-x or AMD-V enabled", "Six cores or more"],
    ["Memory (RAM)", "8 GB", "16 GB"],
    ["Storage", "10 GB free disk space", "SSD with 20 GB free"],
    ["Display", "1366 x 768", "1920 x 1080 or a projector"],
    ["Network", "Localhost only while running", "Internet for the first setup"],
], [1.6, 2.6, 2.1])
section("2.2", "Software Requirements")
table("2.2: Software requirements", ["Layer", "Software", "Version"], [
    ["Operating system", "Windows 10 or 11, 64-bit, no administrator rights needed", "Current release"],
    ["Process manager", "app/services.py with portable MySQL and Redis builds", "Project script"],
    ["Relational database", "MySQL Community Server, InnoDB engine", "8.0"],
    ["NoSQL store", "Redis", "7.x"],
    ["Backend", "Python with FastAPI, Uvicorn and PyMySQL", "3.11"],
    ["NLP", "rapidfuzz and regular expressions", "3.10"],
    ["Frontend", "React with Vite, React Bits components", "React 18"],
    ["Testing", "pytest", "8.3"],
    ["Browser", "Chrome, Edge or Firefox", "Latest"],
], [1.7, 3.2, 1.4])
section("2.3", "Functional Requirements")
bullets([
    "Raise a bed request with patient details, bed type, pickup area and severity from 1 to 5.",
    "Parse a free-text request into the request fields, tolerating misspelt area names.",
    "Find the nearest hospitals with free beds of the requested type using Redis GEO search.",
    "Lock and hold one free bed for thirty minutes in a single transaction.",
    "Admit the patient or cancel the hold; release expired holds automatically through a MySQL event.",
    "Allow hospital staff to discharge patients, mark beds under maintenance and transfer patients.",
    "Show a live census of free beds per hospital and bed type.",
    "Record every change in an audit log through triggers and flag accounts that block beds.",
    "Provide a live database view of tables, SQL statements, locks, Redis data, server metrics and a read-only SQL console.",
    "Demonstrate the race for the last bed, deadlock handling, crash recovery, Redis outage and replication lag.",
], numbered=True)
section("2.4", "Non-functional Requirements")
bullets([
    "**Consistency:** a bed can never have two active holds, enforced by row locks and a UNIQUE constraint.",
    "**Reliability:** transactions are atomic and durable; a crash in the middle of a transfer leaves no partially moved bed.",
    "**Concurrency:** simultaneous requests are handled safely; deadlocks are detected and prevented by lock ordering.",
    "**Availability:** if Redis fails, search falls back to MySQL without wrong bookings.",
    "**Performance:** a booking transaction completes in under 50 ms; live views refresh within one second.",
    "**Security:** a read-only database user for queries, parameterised SQL and no real patient data.",
    "**Usability and portability:** a single-page interface that starts with one command.",
], numbered=True)

# ----------------------------------------------------------- chapter 3
chapter(3, "System Design")
section("3.1", "System Architecture")
para("The system runs as five ordinary processes on one machine: a MySQL 8 primary, a MySQL 8 read replica, "
     "Redis 7 and two identical application instances written in Python with FastAPI. The browser talks to "
     "an application instance over HTTP and receives live updates over a WebSocket. Every application "
     "instance is stateless; all shared state lives in MySQL, so either instance can serve any request.")
figure(FIG / "architecture.png", "3.1: System architecture")
para("MySQL is the source of truth. Redis holds only data that can be rebuilt from MySQL: the hospital "
     "locations used for nearest-first search, cached free-bed counters for the dashboard, and a pub/sub "
     "channel that carries change events to every open browser. The replica receives every committed "
     "transaction through the binary log and is used only for reading.")

section("3.2", "Entity Relationship Model")
para("The model has nine entities. A hospital has many beds; each bed is of one bed type. Users raise bed "
     "requests on behalf of patients; a request is fulfilled by one or more reservations over time, each "
     "of which holds one bed. A patient may occupy a bed and may be moved between beds by transfers. "
     "Every change to reservations, beds and transfers is performed by a user and recorded in the audit log.")
figure(FIG / "er_diagram.png", "3.2: Entity relationship diagram (Chen notation)")

section("3.3", "Relational Schema")
table("3.1: Relations and their keys", ["Relation", "Primary key", "Foreign keys", "Purpose"], [
    ["hospital", "hospital_id", "none", "Hospitals with zone and coordinates"],
    ["bed_type", "bed_type_id", "none", "ICU, ICU_VENTILATOR, OXYGEN"],
    ["bed", "bed_id", "hospital_id, bed_type_id, patient_id", "Current status and occupant of each bed"],
    ["user_account", "user_id", "hospital_id", "Helpline, ambulance, staff and control room users"],
    ["patient", "patient_id", "none", "Simulated patient details"],
    ["bed_request", "request_id", "patient_id, raised_by, bed_type_id", "A need for a bed raised by a user"],
    ["reservation", "reservation_id", "request_id, bed_id", "A 30 minute hold and its outcome"],
    ["transfer", "transfer_id", "patient_id, from_bed_id, to_bed_id", "Movement of a patient between beds"],
    ["audit_log", "log_id", "user_id", "Every change, written by triggers"],
], [1.2, 1.2, 2.0, 1.9])
para("Integrity rules are declared in the schema rather than in code. CHECK constraints restrict every "
     "status column to its allowed values, keep severity between 1 and 5, keep ages between 0 and 120, and "
     "require that a bed has a patient exactly when it is occupied. A stored generated column "
     "active_bed_id equals bed_id only while a reservation is HELD; the UNIQUE index on that column allows "
     "any number of finished reservations per bed but at most one live hold.")

section("3.4", "Normalisation")
para("Every relation is in first normal form: all attributes are atomic, and repeating information such "
     "as the history of holds on a bed is stored as separate reservation rows rather than lists. Every "
     "relation has a single-attribute surrogate key, so no attribute depends on part of a key and the "
     "schema is in second normal form.")
para("Third normal form is reached by removing transitive dependencies. Hospital names and coordinates are "
     "stored only in hospital and are reached from a bed through hospital_id; bed type properties such as "
     "has_ventilator are stored only in bed_type; patient details are stored only in patient and referenced "
     "from bed_request and bed. A request and a reservation are kept separate because a request can be "
     "attempted several times: one hold may expire and a later one succeed. In every relation each "
     "determinant is a candidate key, so the schema also satisfies Boyce-Codd normal form.")

section("3.5", "Division of Work between SQL and NoSQL")
table("3.2: Responsibilities of MySQL and Redis", ["Concern", "MySQL (source of truth)", "Redis (derived)"], [
    ["Bed state", "Authoritative status, locked per row", "Free-bed counter per hospital and type"],
    ["Location", "Hospital latitude and longitude", "GEO set for nearest-first search"],
    ["History", "audit_log written by triggers", "events channel pushed to browsers"],
    ["Failure", "Crash recovery from redo and undo logs", "Rebuilt from MySQL on restart"],
], [1.3, 2.6, 2.4])

# ----------------------------------------------------------- chapter 4
chapter(4, "Implementation")
section("4.1", "Technology Stack")
para("The database layer is MySQL 8.0 with the InnoDB storage engine at its default REPEATABLE READ "
     "isolation level, with the event scheduler, binary log and GTID replication enabled. Redis 7 provides "
     "the NoSQL store. The backend is Python 3.11 with FastAPI and PyMySQL; no ORM is used, so every "
     "statement the application sends is plain SQL that the interface can display. The frontend is a React "
     "single-page application built with Vite. A small Python script, started by run.bat, downloads portable MySQL and Redis builds once, "
     "initialises both databases and starts all five processes with one double-click.")

section("4.2", "Booking Transaction")
para("A booking first asks Redis for hospitals within 50 km of the pickup point, nearest first, and skips "
     "hospitals whose cached free counter is zero. It then runs one transaction against MySQL:")
code("""
START TRANSACTION;
INSERT INTO patient (name, age, gender, contact_phone) VALUES (...);
INSERT INTO bed_request (patient_id, raised_by, bed_type_id, severity, ...) VALUES (...);
SELECT bed_id, hospital_id, ward FROM bed
 WHERE bed_type_id = 2 AND status = 'FREE' AND hospital_id = 1
 ORDER BY bed_id LIMIT 1
   FOR UPDATE SKIP LOCKED;
INSERT INTO reservation (request_id, bed_id, status, hold_expires_at)
VALUES (58, 104, 'HELD', sim_now() + INTERVAL 30 MINUTE);
UPDATE bed SET status = 'HELD' WHERE bed_id = 104;
COMMIT;
""")
para("FOR UPDATE places an exclusive row lock on the selected bed until the transaction ends. SKIP LOCKED "
     "makes a competing transaction pass over a locked row instead of waiting, so the losing request moves "
     "on to the next hospital at once. The locking query is issued once per hospital because a locking read "
     "locks every row it scans: a single query ordered across all hospitals would lock every candidate bed "
     "before sorting them. Only after COMMIT does the application refresh the Redis counter, by re-reading "
     "the count from MySQL, so the cache can never hold a value that was not committed.")
para("When locking is switched off for demonstration, both competing requests read the bed as free from "
     "their consistent snapshots and both attempt the INSERT. The UNIQUE index on active_bed_id makes the "
     "second insert wait for the first to commit and then fail with error 1062, so the double booking is "
     "stopped by the schema itself.")

section("4.3", "Triggers, Scheduled Event and Stored Function")
table("4.1: Database objects that enforce rules", ["Object", "Type", "Behaviour"], [
    ["trg_reservation_hold_limit", "BEFORE INSERT trigger", "Refuses a sixth live hold per account with SIGNAL SQLSTATE 45000"],
    ["trg_reservation_after_insert", "AFTER INSERT trigger", "Writes the new hold to audit_log"],
    ["trg_reservation_after_update", "AFTER UPDATE trigger", "Audits status changes and frees the bed when a hold expires or is cancelled"],
    ["trg_bed_after_update", "AFTER UPDATE trigger", "Audits bed status and occupant changes"],
    ["trg_transfer_after_update", "AFTER UPDATE trigger", "Audits transfer outcomes"],
    ["expire_holds", "Event, every 5 seconds", "Marks HELD reservations past sim_now() as EXPIRED"],
    ["sim_now()", "Stored function", "NOW() plus a simulated offset, so expiry can be demonstrated"],
    ["v_hold_conversion", "View", "Holds, admissions and failure percentage per account"],
], [2.1, 1.6, 2.6])
para("Expiry therefore happens entirely inside the database: the event updates the reservation, the "
     "trigger frees the bed and records the change with a NULL user to show that the scheduler acted. The "
     "application learns of the change only by reading the audit log, which it then publishes on Redis and "
     "uses to refresh the cached counters.")

section("4.4", "Transfers and Deadlock Prevention")
para("A transfer locks both beds involved, moves the patient (or swaps two patients when the target is "
     "occupied) and records the transfer, all in one transaction. When two wards move two patients into "
     "each other's beds at the same moment and each transaction locks its own source bed first, each holds "
     "one lock and waits for the other: a cycle in the wait-for graph. InnoDB detects the cycle, rolls back "
     "the transaction that is cheaper to undo with error 1213 and lets the other finish.")
para("The production setting prevents the cycle by always locking the lower bed_id first, so two crossing "
     "transfers queue on the same row and never wait in a circle. During implementation it was found that "
     "inserting the transfer row before locking the beds could still deadlock, because a foreign key check "
     "takes a shared lock on the referenced bed rows; the insert was therefore moved after both exclusive "
     "locks are held.")

section("4.5", "Crash Recovery and Replication")
para("To demonstrate atomicity and durability, a transfer is paused after freeing the old bed but before "
     "occupying the new one, and the mysqld process is killed outright, with no shutdown and no buffer flush. On restart InnoDB replays the "
     "redo log so that every committed change is present, then uses the undo log to roll back the "
     "unfinished transaction. Holds committed before the crash survive, and the half-done transfer "
     "disappears completely.")
para("The read replica uses GTID-based asynchronous replication. Its IO thread copies the primary's "
     "binary log into a relay log and its SQL thread applies it; super_read_only prevents any other write. "
     "Pausing the SQL thread shows the replica falling behind and catching up again, which is why "
     "bookings and locks always use the primary.")

section("4.6", "Natural Language Request Parser")
para("The innovative component converts a free-text request such as \"need ventilator bed near Jaynagar, "
     "60M critical\" into structured fields. Keyword rules identify the bed type and severity, regular "
     "expressions extract age and sex from forms such as 60M or 45 year old female, and fuzzy string "
     "matching with rapidfuzz resolves misspelt area names, so that Jaynagar matches Jayanagar with a "
     "similarity of 94 percent. Every extracted field is shown with the words it came from, and the "
     "original text is stored in bed_request.raw_text.")

section("4.7", "User Interface and Live Database View")
para("The interface is organised into three places so that only the current task is on screen. Book a bed "
     "is a guided flow: describe the patient, confirm the extracted details, and see the held bed with a "
     "summary of what the database did. Scenarios presents one failure experiment at a time. Database "
     "shows the live state of the system: bed census, raw tables with changed rows highlighted, every SQL "
     "statement in order, open transactions and row locks with a wait-for graph, Redis counters, server "
     "metrics and a read-only SQL console that connects as a user with SELECT privileges only.")

# ----------------------------------------------------------- chapter 5
chapter(5, "Testing and Results")
section("5.1", "Automated Tests")
para("The tests run against the live system and reset the demonstration "
     "data before each case. All twenty tests pass.")
table("5.1: Automated test results", ["Test", "What is checked", "Result"], [
    ["Race, 50 runs", "Two simultaneous requests for the only free ventilator bed; exactly one HELD reservation each time", "Pass, 50 of 50"],
    ["UNIQUE guard", "With locking disabled the second insert fails with error 1062 on one_active_booking_per_bed", "Pass"],
    ["Deadlock", "Request-order locking raises 1213 and rolls back one transfer; ordered locking completes both", "Pass"],
    ["Hold expiry", "After the clock moves 31 minutes the event expires the hold, the bed is freed and Redis matches MySQL", "Pass"],
    ["Late admission", "Admitting a hold after its expiry time is refused", "Pass"],
    ["Hold limit and audit", "Of 8 spam holds 5 are held and 3 refused with error 1644; the audit flags the account", "Pass"],
    ["Parser", "Twelve sample sentences and name extraction produce the expected fields", "Pass, 13 of 13"],
], [1.4, 3.6, 1.3])

section("5.2", "Observed Behaviour of the Scenarios")
table("5.2: Scenario results", ["Scenario", "Observation"], [
    ["Race for the last bed", "One request held bed 104; the other skipped the locked row and found no bed in under 30 ms"],
    ["No lock", "Both requests read the bed as free; the second failed with error 1062"],
    ["Hold expiry", "The expire_holds event expired the hold within 5 seconds with no application SQL"],
    ["Deadlock", "InnoDB rolled back one transfer with error 1213; the wait-for graph showed the cycle"],
    ["Database crash", "MySQL returned in about 16 seconds; its log reported rolling back the open transaction with 3 rows to undo"],
    ["Bed hoarding", "The trigger refused holds 6 to 8; the audit showed 57.1 percent unconverted holds for the suspicious account"],
    ["Replica lag", "With the apply thread paused the replica fell behind by several seconds, then converged after resuming"],
    ["Read-only console", "DELETE was refused with error 1142; EXPLAIN showed the booking query using idx_bed_search"],
], [1.7, 4.6])

section("5.3", "Screenshots")
for f, c in (("1_request_sqllog.png", "5.1: Booking with the live SQL log"),
             ("2_dashboard_census.png", "5.2: City census of beds"),
             ("3_demolab_xray.png", "5.3: Deadlock scenario with the lock view"),
             ("4_console_tables.png", "5.4: Live table view in its own window")):
    figure(SHOT / f, c, width=6.3)

# ----------------------------------------------------------- chapter 6
chapter(6, "Conclusion and Future Enhancements")
section("6.1", "Conclusion")
para("The City ICU Bed Allocation System shows that the correctness of a concurrent booking system can be "
     "placed in the database itself. Row locks with SKIP LOCKED let competing requests proceed without "
     "waiting, a UNIQUE index on a generated column stops double bookings even when the application is "
     "wrong, triggers and a scheduled event enforce business rules and expire holds without application "
     "code, ordered locking prevents deadlocks, and InnoDB's crash recovery guarantees that interrupted "
     "work disappears completely. Redis improves response time and live updates without ever being trusted "
     "for correctness, and the live database view makes each of these mechanisms observable.")
section("6.2", "Future Enhancements")
bullets([
    "Priority-aware allocation that reserves the last beds for the most severe cases.",
    "Real hospital integration through a standard interface such as HL7 FHIR.",
    "Semi-synchronous replication and automatic failover to the replica.",
    "Authentication and role-based authorisation backed by database privileges.",
    "Partitioning of the audit log by month for long-term retention.",
])

# ----------------------------------------------------------- references
page_break()
chapter_heading("REFERENCES", new_page=False)
refs = [
    "A. Silberschatz, H. F. Korth and S. Sudarshan, Database System Concepts, 7th ed. New York: McGraw-Hill, 2019.",
    "R. Elmasri and S. B. Navathe, Fundamentals of Database Systems, 7th ed. Boston: Pearson, 2016.",
    "Oracle Corporation, MySQL 8.0 Reference Manual, Chapter 17: The InnoDB Storage Engine (locking, deadlocks and crash recovery).",
    "Oracle Corporation, MySQL 8.0 Reference Manual, Chapter 19: Replication with Global Transaction Identifiers.",
    "Oracle Corporation, MySQL 8.0 Reference Manual, Sections on CREATE TRIGGER, CREATE EVENT and generated columns.",
    "Redis Ltd., Redis documentation: GEOSEARCH, data types and Pub/Sub.",
    "S. Ramirez, FastAPI documentation.",
    "Meta Open Source, React documentation.",
]
for i, r_ in enumerate(refs, 1):
    para(f"[{i}] {r_}", align=WD_ALIGN_PARAGRAPH.LEFT)

# ----------------------------------------------------------- appendix
page_break()
chapter_heading("APPENDIX: RUNNING THE SYSTEM", new_page=False)
bullets([
    "Install Python 3.10 or newer. No Docker and no administrator rights are needed.",
    "Double-click Start ICU Bed System.bat. The first run downloads MySQL and Redis once (about 260 MB) and sets up both databases.",
    "Open http://localhost:8000 for the application and http://localhost:8000/console for the live database view.",
    "Run the automated tests with .venv\Scripts\python -m pytest -q tests in the project folder.",
    "Stop the system with stop.bat; the data is kept for the next run.",
], numbered=True)

# ask Word to refresh the contents and lists when the file is opened
settings = doc.settings.element
upd = OxmlElement("w:updateFields")
upd.set(qn("w:val"), "true")
settings.append(upd)

out = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "report.docx")
doc.save(out)
print("saved", out)
