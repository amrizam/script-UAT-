"""Menyusun dokumen UAT (.docx) mengikuti format dokumen contoh.

Dari dokumen contoh diambil: style, numbering, header/footer, ukuran halaman & margin (sectPr), format paragraf
heading/bullet, warna kolom label tabel test case, serta isi bagian umum (Informasi Umum, Tujuan, Ruang Lingkup,
Kriteria Penerimaan, tabel tanda tangan) sebagai nilai bawaan. Isi tubuh dokumen dibangun ulang dari hasil UAT.
Tanpa python-docx: XML ditulis langsung.
"""
import datetime
import os
import re
import struct
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
STATUS_COLOR = {"Pass": "1E7B34", "Fail": "C00000", "Blocked": "B26B00", "Not Run": "7F7F7F"}
HEADINGS = {
    "info": ["informasi umum", "general information"],
    "tujuan": ["tujuan uat", "tujuan", "objective"],
    "lingkup": ["ruang lingkup", "scope"],
    "kriteria": ["kriteria penerimaan", "acceptance criteria"],
    "tc": ["test case uat", "test case", "skenario uji"],
    "sign": ["persetujuan uat", "persetujuan", "approval", "sign off", "sign-off"],
}
INFO_LABELS = ["Nama Proyek", "Modul", "Disusun Oleh", "Ditinjau Oleh", "Tanggal", "Versi Dokumen"]


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Bukan file PNG: {path}")
    return struct.unpack(">II", head[16:24])


def t(s):
    return escape(str(s), {'"': "&quot;"})


def _text(el):
    return "".join(x.text or "" for x in el.iter(f"{{{W}}}t")).strip()


def _register_namespaces(xml):
    for prefix, uri in re.findall(r'xmlns:(\w+)="([^"]+)"', xml[:5000]):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass


def _frag(el):
    """Serialisasi elemen (pPr/rPr) tanpa deklarasi namespace tambahan."""
    s = ET.tostring(el, encoding="unicode")
    return re.sub(r'\s+xmlns:\w+="[^"]+"', "", s)


class Template:
    """Membaca dokumen contoh (.docx)."""

    def __init__(self, path):
        self.path = path
        self.z = zipfile.ZipFile(path)
        self.doc_xml = self.z.read("word/document.xml").decode("utf8")
        _register_namespaces(self.doc_xml)
        root = ET.fromstring(self.doc_xml)
        self.body = root.find("w:body", NS)
        self.head = self.doc_xml[:self.doc_xml.index("<w:body>") + len("<w:body>")]
        self.sect = self.doc_xml[self.doc_xml.rindex("<w:sectPr"):]
        self.sect = self.sect[:self.sect.index("</w:body>")]
        self.old_title = self._core_title()
        self._layout()
        self._formats()
        self.defaults = self._content_defaults()

    def _core_title(self):
        try:
            core = self.z.read("docProps/core.xml").decode("utf8")
            m = re.search(r"<dc:title>([^<]*)</dc:title>", core)
            return m.group(1).strip() if m and m.group(1).strip() else None
        except KeyError:
            return None

    def _layout(self):
        def num(attr, xml, default):
            m = re.search(attr + r'="(\d+)"', xml)
            return int(m.group(1)) if m else default
        pg = re.search(r"<w:pgSz[^>]*/>", self.sect)
        mar = re.search(r"<w:pgMar[^>]*/>", self.sect)
        width = num("w:w", pg.group(0), 16838) if pg else 16838
        left = num("w:left", mar.group(0), 567) if mar else 567
        right = num("w:right", mar.group(0), 567) if mar else 567
        self.usable = max(6000, width - left - right)

    def _children(self):
        return list(self.body)

    def _heading_kind(self, p):
        txt = re.sub(r"^\d+[.)]?\s*", "", _text(p)).lower()
        for kind, names in HEADINGS.items():
            if any(txt == n or txt.startswith(n) for n in names):
                return kind
        return None

    def _formats(self):
        self.h_ppr = '<w:pPr><w:pStyle w:val="Heading1"/><w:keepNext/><w:spacing w:after="80" w:before="200"/></w:pPr>'
        self.h_rpr = '<w:rPr><w:b/><w:bCs/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
        self.h_numbered = False
        self.b_ppr = None
        self.step_ppr = None
        self.label_fill = "DBE6F1"
        self.font = '<w:rFonts w:ascii="Calibri" w:cs="Calibri" w:eastAsia="Calibri" w:hAnsi="Calibri"/>'
        self.sz = 17
        kids = self._children()
        for i, el in enumerate(kids):
            if el.tag != f"{{{W}}}p":
                continue
            kind = self._heading_kind(el)
            if not kind:
                continue
            ppr = el.find("w:pPr", NS)
            if ppr is not None and self.h_ppr.startswith('<w:pPr><w:pStyle w:val="Heading1"/><w:keepNext/><w:spacing'):
                self.h_ppr = _frag(ppr)
                self.h_numbered = ppr.find("w:numPr", NS) is not None
                r = el.find("w:r/w:rPr", NS)
                if r is not None:
                    self.h_rpr = _frag(r)
            if kind == "lingkup" and self.b_ppr is None:
                for nxt in kids[i + 1:i + 4]:
                    nppr = nxt.find("w:pPr", NS) if nxt.tag == f"{{{W}}}p" else None
                    if nppr is not None and nppr.find("w:numPr", NS) is not None:
                        self.b_ppr = _frag(nppr)
                        break
        for tbl in self.body.iter(f"{{{W}}}tbl"):
            rows = tbl.findall("w:tr", NS)
            if not rows:
                continue
            first = rows[0].findall("w:tc", NS)
            if first and _text(first[0]).lower() == "test case id":
                shd = first[0].find("w:tcPr/w:shd", NS)
                if shd is not None and shd.get(f"{{{W}}}fill") not in (None, "auto"):
                    self.label_fill = shd.get(f"{{{W}}}fill")
                rf = first[0].find(".//w:rPr/w:rFonts", NS)
                if rf is not None:
                    self.font = _frag(rf)
                sz = first[0].find(".//w:rPr/w:sz", NS)
                if sz is not None:
                    self.sz = int(sz.get(f"{{{W}}}val"))
                for tr in rows:
                    cells = tr.findall("w:tc", NS)
                    if len(cells) >= 2 and _text(cells[0]).lower() == "step":
                        p = cells[1].find("w:p/w:pPr", NS)
                        if p is not None and p.find("w:numPr", NS) is not None:
                            self.step_ppr = _frag(p)
                        break
                break
        if self.step_ppr is None:
            self.step_ppr = self.b_ppr

    def _content_defaults(self):
        d = {"intro": [], "tujuan": [], "lingkup": [], "kriteria": [], "info": {}, "signers": []}
        section = "intro"
        kids = self._children()
        for i, el in enumerate(kids):
            if el.tag == f"{{{W}}}p":
                kind = self._heading_kind(el)
                if kind:
                    section = kind
                    continue
                txt = _text(el)
                if txt and section in ("intro", "tujuan", "lingkup", "kriteria"):
                    d[section].append(txt)
                if txt and section == "sign" and i + 1 < len(kids) and kids[i + 1].tag == f"{{{W}}}tbl":
                    roles = self._sign_roles(kids[i + 1])
                    if roles:
                        d["signers"].append({"company": txt, "roles": roles})
            elif el.tag == f"{{{W}}}tbl" and section == "info":
                for tr in el.findall("w:tr", NS):
                    cells = [" ".join(t for t in (_text(p) for p in c.iter(f"{{{W}}}p")) if t) for c in tr.findall("w:tc", NS)]
                    if len(cells) >= 2 and cells[0]:
                        d["info"][cells[0]] = cells[1]
        return d

    @staticmethod
    def _sign_roles(tbl):
        rows = tbl.findall("w:tr", NS)
        if len(rows) < 2 or not _text(rows[0]).lower().startswith("signature"):
            return None
        return [_text(c) for c in rows[1].findall("w:tc", NS)]


class DocBuilder:
    def __init__(self, template_path):
        self.tpl = Template(template_path)
        u = self.tpl.usable
        self.u = u
        self.label_w = int(u * 0.1465)
        self.px = u / 15.0  # twips → piksel (96 dpi)
        k = self.px / 1047.0
        self.maxw = {1: 760 * k, 2: 500 * k, 3: 328 * k}
        self.maxh = {1: 430 * k, 2: 400 * k, 3: 400 * k}
        self.rels, self.media, self.missing = [], [], []
        self.next_docpr = 1
        rels = self.tpl.z.read("word/_rels/document.xml.rels").decode("utf8")
        ids = [int(x) for x in re.findall(r'Id="rId(\d+)"', rels)]
        self.next_rid = (max(ids) + 1) if ids else 100

    # ── potongan XML ────────────────────────────────────────────────────
    def run(self, text, b=False, i=False, sz=None, color=None):
        sz = sz or self.tpl.sz
        rp = (self.tpl.font + ("<w:b/><w:bCs/>" if b else "") + ("<w:i/><w:iCs/>" if i else "")
              + (f'<w:color w:val="{color}"/>' if color else "") + f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
        return f'<w:r><w:rPr>{rp}</w:rPr><w:t xml:space="preserve">{t(text)}</w:t></w:r>'

    @staticmethod
    def para(runs, ppr=""):
        return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>" if ppr and not ppr.startswith("<w:pPr") else f"<w:p>{ppr}{runs}</w:p>"

    def h1(self, n, text):
        label = text if self.tpl.h_numbered else f"{n}. {text}"
        return f"<w:p>{self.tpl.h_ppr}<w:r>{self.tpl.h_rpr}<w:t xml:space=\"preserve\">{t(label)}</w:t></w:r></w:p>"

    def bullet(self, text, step=False):
        ppr = self.tpl.step_ppr if step else self.tpl.b_ppr
        if ppr:
            return f"<w:p>{ppr}{self.run(text)}</w:p>"
        return self.para(self.run("•  " + text), '<w:spacing w:after="20" w:before="0"/><w:ind w:left="360" w:hanging="200"/>')

    def spacer(self):
        return '<w:p><w:pPr><w:spacing w:after="120" w:before="0"/></w:pPr></w:p>'

    def image(self, path, n):
        if not os.path.exists(path):
            self.missing.append(path)
            return self.para(self.run(f"[screenshot tidak tersedia: {os.path.basename(path)}]", i=True, sz=16),
                             '<w:spacing w:after="20" w:before="60"/><w:jc w:val="center"/>')
        w, h = png_size(path)
        sc = min(1.0, self.maxw[n] / w, self.maxh[n] / h)
        cx, cy = int(round(w * sc)) * 9525, int(round(h * sc)) * 9525
        rid = f"rId{self.next_rid}"
        self.next_rid += 1
        name = f"media/uat_{len(self.media) + 1:03d}.png"
        self.rels.append((rid, name))
        self.media.append(("word/" + name, path))
        dp = self.next_docpr
        self.next_docpr += 1
        A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        base = t(os.path.basename(path))
        drawing = (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                   f'<wp:effectExtent t="0" r="0" b="0" l="0"/><wp:docPr id="{5000 + dp}" name="{base}" descr="{base}"/>'
                   f'<wp:cNvGraphicFramePr><a:graphicFrameLocks {A} noChangeAspect="1"/></wp:cNvGraphicFramePr>'
                   f'<a:graphic {A}><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                   f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="{base}"/>'
                   f'<pic:cNvPicPr><a:picLocks noChangeAspect="1" noChangeArrowheads="1"/></pic:cNvPicPr></pic:nvPicPr>'
                   f'<pic:blipFill><a:blip r:embed="{rid}"/><a:srcRect/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                   f'<pic:spPr bwMode="auto"><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                   f'</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')
        return self.para(drawing, '<w:spacing w:after="20" w:before="60"/><w:jc w:val="center"/>')

    def fig(self, path, cap, n):
        return self.image(path, n) + self.para(self.run(cap, i=True, sz=16), '<w:spacing w:after="60" w:before="0"/><w:jc w:val="center"/>')

    # ── tabel ───────────────────────────────────────────────────────────
    B_NONE = ('<w:top w:val="none" w:color="FFFFFF" w:sz="0"/><w:left w:val="none" w:color="FFFFFF" w:sz="0"/>'
              '<w:bottom w:val="none" w:color="FFFFFF" w:sz="0"/><w:right w:val="none" w:color="FFFFFF" w:sz="0"/>')
    B_GREY = ('<w:top w:val="single" w:color="808080" w:sz="4"/><w:left w:val="single" w:color="808080" w:sz="4"/>'
              '<w:bottom w:val="single" w:color="808080" w:sz="4"/><w:right w:val="single" w:color="808080" w:sz="4"/>')
    B_AUTO = ('<w:top w:val="single" w:color="auto" w:sz="4"/><w:left w:val="single" w:color="auto" w:sz="4"/>'
              '<w:bottom w:val="single" w:color="auto" w:sz="4"/><w:right w:val="single" w:color="auto" w:sz="4"/>'
              '<w:insideH w:val="single" w:color="auto" w:sz="4"/><w:insideV w:val="single" w:color="auto" w:sz="4"/>')
    MAR = '<w:tcMar><w:top w:type="dxa" w:w="40"/><w:left w:type="dxa" w:w="90"/><w:bottom w:type="dxa" w:w="40"/><w:right w:type="dxa" w:w="90"/></w:tcMar>'
    SP = '<w:spacing w:after="30" w:before="0"/>'
    SP0 = '<w:spacing w:after="0" w:before="0"/>'

    @staticmethod
    def grid(widths):
        return "<w:tblGrid>" + "".join('<w:gridCol w:w="%d"/>' % w for w in widths) + "</w:tblGrid>"

    def tc_row(self, label, value_xml):
        lw, vw = self.label_w, self.u - self.label_w
        label_xml = self.para(self.run(label, b=True), self.SP0)
        lab = (f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{lw}"/><w:tcBorders>{self.B_GREY}</w:tcBorders>'
               f'<w:shd w:fill="{self.tpl.label_fill}" w:color="auto" w:val="clear"/>{self.MAR}<w:vAlign w:val="center"/></w:tcPr>'
               f'{label_xml}</w:tc>')
        val = f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{vw}"/><w:tcBorders>{self.B_GREY}</w:tcBorders>{self.MAR}<w:vAlign w:val="center"/></w:tcPr>{value_xml}</w:tc>'
        return f"<w:tr><w:trPr><w:cantSplit/></w:trPr>{lab}{val}</w:tr>"

    def vals(self, v):
        items = [x for x in (v if isinstance(v, list) else [v]) if x]
        return "".join(self.para(self.run(x), self.SP) for x in items) or self.para("", self.SP)

    def numbered(self, items):
        return "".join(self.para(self.run(f"{k}. ") + self.run(x), self.SP + '<w:ind w:left="300" w:hanging="300"/>')
                       for k, x in enumerate(items, 1)) or self.para("", self.SP)

    def img_rows(self, images):
        out = []
        inner_w = self.u - 200
        for k in range(0, len(images), 3):
            grp = images[k:k + 3]
            n = len(grp)
            if n == 1:
                inner = self.fig(grp[0][0], grp[0][1], 1)
            else:
                cw = inner_w // n
                cells = "".join(f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{cw}"/><w:tcBorders>{self.B_NONE}</w:tcBorders><w:vAlign w:val="bottom"/></w:tcPr>{self.fig(p, c, n)}</w:tc>'
                                for p, c in grp)
                inner = (f'<w:tbl><w:tblPr><w:tblW w:type="dxa" w:w="{inner_w}"/><w:jc w:val="center"/><w:tblBorders>{self.B_NONE}'
                         f'<w:insideH w:val="none" w:color="FFFFFF" w:sz="0"/><w:insideV w:val="none" w:color="FFFFFF" w:sz="0"/></w:tblBorders></w:tblPr>'
                         f'{self.grid([cw] * n)}<w:tr>{cells}</w:tr></w:tbl><w:p/>')
            out.append(f'<w:tr><w:trPr><w:cantSplit/></w:trPr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{self.u}"/><w:gridSpan w:val="2"/>'
                       f'<w:tcBorders>{self.B_GREY}</w:tcBorders>{self.MAR}<w:vAlign w:val="center"/></w:tcPr>{inner}</w:tc></w:tr>')
        return "".join(out)

    def tc_table(self, tc):
        status = tc["status"]
        rows = [
            self.tc_row("Test Case ID", self.vals(tc["id"])),
            self.tc_row("Scenario", self.vals(tc["scenario"])),
            self.tc_row("Pre-condition", self.vals(tc.get("pre", ""))),
            self.tc_row("Step", "".join(self.bullet(s, step=True) for s in tc["steps"]) or self.para("", self.SP)),
            self.tc_row("Expected Result", self.vals(tc.get("expected", ""))),
            self.tc_row("Actual Result", self.numbered(tc.get("actual", []))),
            self.tc_row("Status", self.para(self.run(status, b=True, color=STATUS_COLOR.get(status)), self.SP)),
            self.tc_row("Notes", self.vals(tc.get("notes", []))),
        ]
        imgs = self.img_rows(tc.get("images", [])) if tc.get("images") else ""
        lw = self.label_w
        return (f'<w:tbl><w:tblPr><w:tblW w:type="dxa" w:w="{self.u}"/><w:tblBorders>{self.B_AUTO}</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
                f'<w:tblGrid><w:gridCol w:w="{lw}"/><w:gridCol w:w="{self.u - lw}"/></w:tblGrid>{"".join(rows)}{imgs}</w:tbl>') + self.spacer()

    def info_table(self, rows):
        lw = 2200
        vw = self.u - lw - 360
        out = []
        for label, val in rows:
            label_xml = self.para(self.run(label, b=True), self.SP0)
            val_xml = self.para(self.run(val), self.SP)
            out.append(f'<w:tr><w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{lw}"/><w:tcBorders>{self.B_NONE}</w:tcBorders></w:tcPr>'
                       f'{label_xml}</w:tc>'
                       f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{vw}"/><w:tcBorders>{self.B_NONE}</w:tcBorders></w:tcPr>'
                       f'{val_xml}</w:tc></w:tr>')
        return (f'<w:tbl><w:tblPr><w:tblW w:type="dxa" w:w="{lw + vw}"/><w:tblInd w:type="dxa" w:w="360"/><w:tblBorders>{self.B_NONE}'
                f'<w:insideH w:val="none" w:color="FFFFFF" w:sz="0"/><w:insideV w:val="none" w:color="FFFFFF" w:sz="0"/></w:tblBorders></w:tblPr>'
                f'{self.grid([lw, vw])}{"".join(out)}</w:tbl>')

    def sign_block(self, company, roles):
        w = min(3090, (self.u - 360) // max(1, len(roles)))
        hdr = '<w:shd w:fill="FFE699" w:color="auto" w:val="clear"/>'

        def c(text, b, shade="", valign="", keep=True, jc=True):
            ppr = ("<w:keepNext/>" if keep else "") + '<w:spacing w:after="0" w:before="0"/>' + ('<w:jc w:val="center"/>' if jc else "")
            return (f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{w}"/><w:tcBorders>{self.B_GREY}</w:tcBorders>{shade}{self.MAR}{valign}</w:tcPr>'
                    f'{self.para(self.run(text, b=b), ppr)}</w:tc>')
        r1 = '<w:tr><w:trPr><w:cantSplit/></w:trPr>' + "".join(c("Signature", True, hdr) for _ in roles) + "</w:tr>"
        r2 = ('<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="1500" w:hRule="atLeast"/></w:trPr>'
              + "".join(c(r, False, "", '<w:vAlign w:val="bottom"/>') for r in roles) + "</w:tr>")
        r3 = '<w:tr><w:trPr><w:cantSplit/></w:trPr>' + "".join(c("Date:", True, "", "", keep=False, jc=False) for _ in roles) + "</w:tr>"
        title = self.para(self.run(company, b=True), '<w:keepNext/><w:spacing w:after="80" w:before="160"/><w:ind w:left="360"/>')
        return (title + f'<w:tbl><w:tblPr><w:tblW w:type="dxa" w:w="{w * len(roles)}"/><w:tblInd w:type="dxa" w:w="360"/><w:tblBorders>{self.B_AUTO}</w:tblBorders></w:tblPr>'
                f'{self.grid([w] * len(roles))}{r1}{r2}{r3}</w:tbl>')

    # ── dokumen ─────────────────────────────────────────────────────────
    def build(self, content, results, out_path):
        """content: title, intro(list), info(list of (label, value)), tujuan(list), lingkup(list), kriteria(list), signers."""
        tpl = self.tpl
        B = [self.para(self.run(x), '<w:spacing w:after="120" w:before="0"/>') for x in content["intro"]]
        B.append(self.h1(1, "Informasi Umum"))
        B.append(self.info_table(content["info"]))
        B.append(self.h1(2, "Tujuan UAT"))
        B += [self.para(self.run(x), '<w:spacing w:after="80"/><w:ind w:left="360"/>') for x in content["tujuan"]]
        B.append(self.h1(3, "Ruang Lingkup Pengujian"))
        B += [self.bullet(x) for x in content["lingkup"]]
        B.append(self.h1(4, "Kriteria Penerimaan"))
        B += [self.bullet(x) for x in content["kriteria"]]
        B.append(self.h1(5, "Test Case UAT"))
        for tc in results:
            B.append(self.tc_table(tc))
        B.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        B.append(self.h1(6, "Persetujuan UAT"))
        for k, s in enumerate(content["signers"]):
            if k:
                B.append(self.spacer())
            B.append(self.sign_block(s["company"], s["roles"]))

        head = tpl.head
        for prefix, uri in (("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
                            ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing")):
            if f"xmlns:{prefix}=" not in head:
                head = head.replace("<w:document ", f'<w:document xmlns:{prefix}="{uri}" ', 1)
        document = head + "".join(B) + tpl.sect + "</w:body></w:document>"

        z = tpl.z
        rels = z.read("word/_rels/document.xml.rels").decode("utf8")
        rels = re.sub(r'<Relationship [^>]*Type="[^"]+/image"[^>]*/>', "", rels)
        rels = rels.replace("</Relationships>", "".join(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{tg}"/>'
            for rid, tg in self.rels) + "</Relationships>")
        ctypes = z.read("[Content_Types].xml").decode("utf8")
        if 'Extension="png"' not in ctypes:
            ctypes = ctypes.replace("<Types ", "<Types ", 1).replace("</Types>", '<Default Extension="png" ContentType="image/png"/></Types>')
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        title = content["title"]

        tmp = out_path + ".tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
            for item in z.infolist():
                n = item.filename
                if n.startswith("word/media/"):
                    continue
                data = z.read(n)
                if n == "word/document.xml":
                    data = document.encode("utf8")
                elif n == "word/_rels/document.xml.rels":
                    data = rels.encode("utf8")
                elif n == "[Content_Types].xml":
                    data = ctypes.encode("utf8")
                elif re.match(r"word/(footer|header)\d*\.xml$", n) and tpl.old_title:
                    data = data.decode("utf8").replace(tpl.old_title, title).encode("utf8")
                elif n == "docProps/core.xml":
                    core = data.decode("utf8")
                    core = re.sub(r"<dc:title>[^<]*</dc:title>", f"<dc:title>{t(title)}</dc:title>", core)
                    core = re.sub(r"(<dcterms:created[^>]*>)[^<]*", r"\g<1>" + now, core)
                    core = re.sub(r"(<dcterms:modified[^>]*>)[^<]*", r"\g<1>" + now, core)
                    data = core.encode("utf8")
                zo.writestr(item, data)
            for zn, src in self.media:
                zo.write(src, zn)
        os.replace(tmp, out_path)
        return out_path
