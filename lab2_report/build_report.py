#!/usr/bin/env python3
"""Build the Lab 2 Word report from the task markdown drafts and screenshots."""
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
SECTION = "[Section]"
INSTRUCTOR = "[Instructor Name]"
UNIVERSITY = "Abu Dhabi University"
VIDEO_LINK = "[Paste OneDrive video link here]"

FONT = "Calibri"

REFERENCES = [
    'Wikipedia, "Cryptography," Wikipedia, The Free Encyclopedia. [Online]. Available: https://en.wikipedia.org/wiki/Cryptography. [Accessed: Oct. 18, 2026].',
    'Wikipedia, "Frequency analysis." [Online]. Available: https://en.wikipedia.org/wiki/Frequency_analysis. [Accessed: Oct. 18, 2026].',
    'Wikipedia, "Bigram." [Online]. Available: https://en.wikipedia.org/wiki/Bigram. [Accessed: Oct. 18, 2026].',
    'Wikipedia, "Trigram." [Online]. Available: https://en.wikipedia.org/wiki/Trigram. [Accessed: Oct. 18, 2026].',
    'OpenSSL Project, "openssl-enc – symmetric cipher routines," OpenSSL 3.0 manual. [Online]. Available: https://docs.openssl.org/3.0/man1/openssl-enc/. [Accessed: Oct. 18, 2026].',
    'OpenSSL Project, "OSSL_PROVIDER-legacy – OpenSSL legacy provider," OpenSSL 3.0 manual. [Online]. Available: https://docs.openssl.org/3.0/man7/OSSL_PROVIDER-legacy/. [Accessed: Oct. 18, 2026].',
    'K. Bhargavan and G. Leurent, "On the Practical (In-)Security of 64-bit Block Ciphers: Collision Attacks on HTTP over TLS and OpenVPN," in Proc. ACM CCS, 2016.',
    'Wikipedia, "Block cipher mode of operation." [Online]. Available: https://en.wikipedia.org/wiki/Block_cipher_mode_of_operation. [Accessed: Oct. 18, 2026].',
    'W. Stallings, Cryptography and Network Security: Principles and Practice, 8th ed. Pearson, 2020.',
]

# (markdown file, local citation number -> global reference number)
SECTIONS = [
    ("intro.md", {}),
    ("task1.md", {1: 1}),
    ("task2.md", {1: 2, 2: 3, 3: 4}),
    ("task3.md", {1: 5, 2: 6, 3: 7}),
    ("task4.md", {1: 8}),
    ("task5.md", {1: 8, 2: 9}),
    ("conclusion.md", {}),
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
    for name, size in (("Heading 1", 16), ("Heading 2", 13)):
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
    lines = [
        (UNIVERSITY, 18, True),
        ("", 11, False),
        ("ITE408: Information Security", 20, True),
        ("Fall 2026-27", 13, False),
        ("", 11, False),
        ("Lab 2 Report", 26, True),
        ("Secret-Key Encryption, Frequency Analysis,", 14, False),
        ("Encryption Modes and Error Propagation", 14, False),
    ]
    for text, size, bold in lines:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = bold
    for _ in range(4):
        doc.add_paragraph()
    info = [
        ("Student Name", STUDENT_NAME),
        ("Student ID", STUDENT_ID),
        ("Course", "ITE408 – Information Security"),
        ("Section", SECTION),
        ("Instructor", INSTRUCTOR),
        ("Submission Date", "18 October 2026"),
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
        "1. Introduction and Lab Setup",
        "2. Task 1 – Encryption using Substitution Cipher",
        "3. Task 2 – Frequency Analysis",
        "4. Task 3 – Encryption using Different Ciphers and Modes",
        "5. Task 4 – Encryption Mode (ECB vs. CBC)",
        "6. Task 5 – Error Propagation – Corrupted Cipher Text",
        "7. Video Demonstration",
        "8. Conclusion",
        "9. References",
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
    "Most frequent n-grams in ciphertext.txt",
    "Recovered substitution key (ciphertext → plaintext)",
    "File sizes of the plaintext and the three ciphertexts",
    "Predicted effect of a one-bit error in each mode",
    "Byte 55 before and after the bit flip",
    "Measured effect of the one-bit error",
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
    hp.text = f"ITE408 Information Security – Lab 2 | {STUDENT_ID}"
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

    caps = []
    for n, (name, cmap) in enumerate(SECTIONS, start=1):
        if name == "conclusion.md":
            doc.add_paragraph(f"{n}. Video Demonstration", style="Heading 1")
            p = doc.add_paragraph("The video demonstration of Task 2 and Task 4 with voice narration is available on OneDrive at the following link:")
            p = doc.add_paragraph()
            p.add_run(VIDEO_LINK).bold = True
            n += 1
        render(doc, HERE / name, cmap, n)
    # fill the table captions in order
    cap_pars = [p for p in doc.paragraphs if p.style.name == "Caption" and re.fullmatch(r"Table \d+: ", p.text)]
    for p, txt in zip(cap_pars, TABLE_CAPTIONS):
        p.add_run(txt)

    doc.add_paragraph(f"{len(SECTIONS) + 2}. References", style="Heading 1")
    for k, ref in enumerate(REFERENCES, start=1):
        p = doc.add_paragraph(f"[{k}] {ref}")
        p.paragraph_format.left_indent = Cm(0.8)
        p.paragraph_format.first_line_indent = Cm(-0.8)

    out = HERE / "ITE408_Lab2_Report_1093911.docx"
    doc.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
