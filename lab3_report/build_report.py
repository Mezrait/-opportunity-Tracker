#!/usr/bin/env python3
"""Build the Lab 3 Word report from the part markdown drafts and screenshots."""
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
IMG = HERE / "img"

# Front page details – edit these before building
STUDENT_NAME = "Mezrait Menber"
STUDENT_ID = "1093911"
SECTION = "103"
INSTRUCTOR = "Dr. Abid Mehmmood"
UNIVERSITY = "Abu Dhabi University"
VIDEO_LINK = "[Paste OneDrive video link here]"

FONT = "Calibri"

REFERENCES = [
    'Openwall, "yescrypt – scalable KDF and password hashing scheme." [Online]. Available: https://www.openwall.com/yescrypt/. [Accessed: Oct. 29, 2026].',
    'Ubuntu Manpages, "usermod – modify a user account," Ubuntu 24.04 (noble). [Online]. Available: https://manpages.ubuntu.com/manpages/noble/man8/usermod.8.html. [Accessed: Oct. 29, 2026].',
    'Ubuntu Manpages, "login.defs – shadow password suite configuration," Ubuntu 24.04 (noble). [Online]. Available: https://manpages.ubuntu.com/manpages/noble/man5/login.defs.5.html. [Accessed: Oct. 29, 2026].',
    'Ubuntu Manpages, "chmod – change file mode bits," Ubuntu 24.04 (noble). [Online]. Available: https://manpages.ubuntu.com/manpages/noble/man1/chmod.1.html. [Accessed: Oct. 29, 2026].',
    'Keycloak, "Server Administration Guide." [Online]. Available: https://www.keycloak.org/docs/latest/server_admin/. [Accessed: Oct. 29, 2026].',
    "D. M'Raihi, " 'S. Machani, M. Pei and J. Rydell, "TOTP: Time-Based One-Time Password Algorithm," RFC 6238, IETF, May 2011.',
    'N. Sakimura, J. Bradley and N. Agarwal, "Proof Key for Code Exchange by OAuth Public Clients," RFC 7636, IETF, Sep. 2015.',
    'T. Lodderstedt, J. Bradley, A. Labunets and D. Fett, "Best Current Practice for OAuth 2.0 Security," RFC 9700, IETF, Jan. 2025.',
]

# (markdown file, local citation number -> global reference number)
SECTIONS = [
    ("intro.md", {}),
    ("partA.md", {1: 1, 2: 2, 3: 3, 4: 4}),
    ("partB.md", {5: 5, 6: 6, 7: 7, 8: 8}),
    ("VIDEO", {}),
]

table_no = 0


def add_field(run, instr):
    """Insert a Word field (e.g. PAGE) into a run."""
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = instr
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(text)
    run._r.append(end)


def shade(cell, color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def add_inline(par, text, size=None):
    """Add text with **bold** support."""
    for i, part in enumerate(re.split(r"\*\*", text)):
        if not part:
            continue
        run = par.add_run(part)
        run.bold = i % 2 == 1
        if size:
            run.font.size = size


def setup_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11.5)):
        st = doc.styles[name]
        st.font.name = FONT
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        st.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
        st.paragraph_format.space_after = Pt(6)
    cap = doc.styles["Caption"]
    cap.font.name = FONT
    cap.font.size = Pt(9)
    cap.font.italic = True
    cap.font.bold = False
    cap.font.color.rgb = RGBColor(0x40, 0x40, 0x40)


def front_page(doc):
    logo = IMG / "adu_logo.png"
    if logo.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(logo), width=Cm(6))
    else:
        for _ in range(3):
            doc.add_paragraph()
    lines = [] if logo.exists() else [(UNIVERSITY, 18, True), ("", 11, False)]
    lines += [
        ("ITE408: Information Security", 20, True),
        ("Fall 2026-27", 13, False),
        ("", 11, False),
        ("Lab 3 Report", 26, True),
        ("Authentication and Access Control", 14, False),
    ]
    for text, size, bold in lines:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = bold
    for _ in range(2 if logo.exists() else 4):
        doc.add_paragraph()
    info = [
        ("Student Name", STUDENT_NAME),
        ("Student ID", STUDENT_ID),
        ("Course", "ITE408 – Information Security"),
        ("Section", SECTION),
        ("Instructor", INSTRUCTOR),
        ("Submission Date", "8 November 2026"),
        ("Video Demonstration", VIDEO_LINK),
    ]
    t = doc.add_table(rows=len(info), cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for row, (k, v) in zip(t.rows, info):
        row.cells[0].width = Cm(5)
        row.cells[1].width = Cm(10)
        row.cells[0].text = ""
        row.cells[0].paragraphs[0].add_run(k).bold = True
        shade(row.cells[0], "DCE6F0")
        row.cells[1].text = v
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def contents_page(doc):
    doc.add_paragraph("Table of Contents", style="Heading 1")
    items = [
        "1. Introduction and Lab Environment",
        "2. Part A – Access Control in a Linux System",
        "3. Part B – Getting Started with Keycloak Identity Provider",
        "4. Video Demonstration",
        "5. References",
    ]
    for it in items:
        doc.add_paragraph(it)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def add_code(doc, lines):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(8)
    p_pr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F2F2F2")
    p_pr.append(shd)
    for i, line in enumerate(lines):
        r = p.add_run(line)
        r.font.name = "Consolas"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        r.font.size = Pt(9)
        if i < len(lines) - 1:
            r.add_break()


def add_table(doc, rows):
    global table_no
    table_no += 1
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-+:?", c) for c in r)]
    ncols = len(cells[0])
    wide = ncols > 10
    if wide:
        # The 26-letter key table: show it transposed into two rows of 13
        hdr, body = cells[0], cells[1]
        cells = [
            [hdr[0]] + hdr[1:14], [body[0]] + body[1:14],
            [hdr[0]] + hdr[14:], [body[0]] + body[14:],
        ]
        ncols = 14
    t = doc.add_table(rows=len(cells), cols=ncols)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    size = Pt(9) if wide else Pt(10)
    for ri, row in enumerate(cells):
        header = ri == 0 or (wide and ri % 2 == 0)
        for ci, val in enumerate(row):
            cell = t.rows[ri].cells[ci]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            # keep the table together with its caption
            p.paragraph_format.keep_with_next = True
            if wide:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_inline(p, val, size)
            if header:
                for r in p.runs:
                    r.bold = True
                shade(cell, "DCE6F0")
    cap = doc.add_paragraph(f"Table {table_no}: ", style="Caption")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return cap


def add_image(doc, name, caption):
    path = IMG / name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_after = Pt(2)
    from PIL import Image
    w, h = Image.open(path).size
    width = Cm(16)
    # keep tall screenshots from filling the whole page
    if h / w > 0.75:
        width = Cm(11)
    p.add_run().add_picture(str(path), width=width)
    c = doc.add_paragraph(caption, style="Caption")
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER


def render(doc, md, cite_map, heading_no):
    text = md.read_text()
    # drop the per-task reference list, the global one is at the end
    text = re.split(r"^## References\s*$", text, flags=re.M)[0]

    def remap(m):
        n = int(m.group(1))
        return f"[{cite_map[n]}]" if n in cite_map else m.group(0)

    if cite_map:
        text = re.sub(r"\[(\d+)\](?!\()", remap, text)

    lines = text.splitlines()
    i = 0
    pending_caption = None
    para = []

    def flush():
        if para:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            add_inline(p, " ".join(para))
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            flush()
            doc.add_paragraph(f"{heading_no}. {line[2:]}", style="Heading 1")
        elif line.startswith("### "):
            flush()
            doc.add_paragraph(line[4:], style="Heading 3")
        elif line.startswith("## "):
            flush()
            doc.add_paragraph(line[3:], style="Heading 2")
        elif line.startswith("[IMG "):
            flush()
            m = re.match(r"\[IMG ([^\]]+)\]\s*(.*)", line)
            add_image(doc, m.group(1).strip(), m.group(2).strip())
        elif line.startswith("    "):
            flush()
            block = []
            while i < len(lines) and lines[i].startswith("    "):
                block.append(lines[i][4:])
                i += 1
            add_code(doc, block)
            continue
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            pending_caption = add_table(doc, rows)
            continue
        elif line.startswith("- "):
            flush()
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, line[2:])
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()


TABLE_CAPTIONS = [
    "Meaning of chmod 705",
    "Summary of the special permission bits",
]


def main():
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(2.5))
    sec.top_margin = sec.bottom_margin = Cm(2.2)
    setup_styles(doc)

    front_page(doc)
    contents_page(doc)

    # header and page numbers start after the front page
    body = doc.sections[0]
    body.different_first_page_header_footer = True
    hp = body.header.paragraphs[0]
    hp.text = f"ITE408 Information Security – Lab 3 | {STUDENT_ID}"
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hp.runs[0].font.size = Pt(9)
    hp.runs[0].font.color.rgb = RGBColor(0x60, 0x60, 0x60)
    fp = body.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Page ")
    r.font.size = Pt(9)
    r = fp.add_run()
    r.font.size = Pt(9)
    add_field(r, "PAGE")

    n = 0
    for name, cmap in SECTIONS:
        n += 1
        if name.endswith(".md"):
            render(doc, HERE / name, cmap, n)
        elif name == "VIDEO":
            doc.add_paragraph(f"{n}. Video Demonstration", style="Heading 1")
            doc.add_paragraph("The 2–3 minute video demonstration with voiceover is available on OneDrive at the following link:")
            doc.add_paragraph().add_run(VIDEO_LINK).bold = True
        else:
            # placeholder for a part that is not written yet
            doc.add_paragraph(f"{n}. {name}", style="Heading 1")
            doc.add_paragraph("[This part is in progress and will be added here.]")
    # fill the table captions in order
    cap_pars = [p for p in doc.paragraphs if p.style.name == "Caption" and re.fullmatch(r"Table \d+: ", p.text)]
    for p, txt in zip(cap_pars, TABLE_CAPTIONS):
        p.add_run(txt)

    doc.add_paragraph(f"{n + 1}. References", style="Heading 1")
    for k, ref in enumerate(REFERENCES, start=1):
        p = doc.add_paragraph(f"[{k}] {ref}")
        p.paragraph_format.left_indent = Cm(0.8)
        p.paragraph_format.first_line_indent = Cm(-0.8)

    out = HERE / "ITE408_Lab3_Report_1093911.docx"
    doc.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
