"""A minimal text-only PDF writer (standard library only; B3).

Used to generate synthetic invoices at seed time and the back-test report export. One base-14 font
(Courier, so columns stay aligned), no images, no scripts, no embedded files. ``watermark`` draws a
large grey diagonal line of text on every page (the draft mark of T-5.1.2).
"""

from __future__ import annotations

PAGE_W, PAGE_H = 612, 792  # US Letter in points
LINES_PER_PAGE = 60


def _esc(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(lines: list[str], *, title: str = "", watermark: str | None = None, font_size: int = 9) -> bytes:
    """Lay ``lines`` out top to bottom, ``LINES_PER_PAGE`` per page, and return the PDF bytes."""
    pages = [lines[i : i + LINES_PER_PAGE] for i in range(0, max(len(lines), 1), LINES_PER_PAGE)] or [[]]
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in below
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    info = add(f"<< /Title ({_esc(title)}) /Producer (MatchDesk) >>".encode("latin-1"))
    kids: list[int] = []
    for page_lines in pages:
        ops = []
        if watermark:
            ops.append(
                f"q 0.82 g BT /F1 44 Tf 0.7071 0.7071 -0.7071 0.7071 140 220 Tm ({_esc(watermark)}) Tj ET Q"
            )
        ops.append(f"BT /F1 {font_size} Tf 12 TL 40 {PAGE_H - 50} Td")
        for ln in page_lines:
            ops.append(f"({_esc(ln)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page = add(
            f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".encode()
        )
        kids.append(page)
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    objects[pages_obj - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    )
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
