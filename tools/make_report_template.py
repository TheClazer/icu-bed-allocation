"""Builds tools/report_template/template.docx from a department report used as a format sample.

  .venv\\Scripts\\python.exe tools\\make_report_template.py  "<sample report>.docx"

Only formatting is kept: page size and margins, the double page border, the RVCE
watermark header, the RVCE footer strip, base styles and list numbering. Every
paragraph, table and image of the sample's own content is removed. The RVCE
letterhead and logo images used on the title, certificate and declaration pages
are saved next to the template.
"""
import copy
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "report_template"
OUT.mkdir(parents=True, exist_ok=True)

src = Document(sys.argv[1])
body = src.element.body
sects = [p for p in body.iter(qn("w:sectPr"))]
front_sect = copy.deepcopy(sects[0])        # border, watermark header, RVCE footer strip
main_sect = copy.deepcopy(sects[1])         # border, plain footer (page number goes here)

# the RVCE letterhead and the two logo blocks, referenced from the sample's first pages
rels = src.part.rels
for rid, name in (("rId8", "letterhead.png"), ("rId9", "logo_certificate.png"), ("rId10", "logo_declaration.png")):
    (OUT / name).write_bytes(rels[rid].target_part.blob)

# drop every body element, then keep only the two section definitions
for child in list(body):
    body.remove(child)
marker = body.makeelement(qn("w:p"), {})
ppr = marker.makeelement(qn("w:pPr"), {})
ppr.append(front_sect)
marker.append(ppr)
body.append(marker)
body.append(main_sect)

# drop the sample's own content images and drawings from the document part
for rid, rel in list(rels.items()):
    if rel.reltype.endswith("/image"):
        del rels[rid]

# headings, list and table styles the report needs, taken from python-docx's default template
default = Document()
need = ["Heading 1", "Heading 2", "Heading 3", "Heading 1 Char", "Heading 2 Char", "Heading 3 Char",
        "Table Grid", "Title", "Title Char"]
have = {s.name for s in src.styles}
for name in need:
    if name not in have and name in {s.name for s in default.styles}:
        src.styles.element.append(copy.deepcopy(default.styles[name].element))

cp = src.core_properties
cp.title = cp.subject = cp.keywords = cp.comments = cp.category = ""
cp.author = cp.last_modified_by = ""

src.save(OUT / "template.docx")
print("saved", OUT / "template.docx")
