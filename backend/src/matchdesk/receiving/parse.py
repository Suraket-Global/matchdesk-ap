"""Read a receiving file into a header row and data rows (T-3.2.1 (a); TRD 8.7 limits).

CSV (UTF-8, comma or semicolon) and XLSX (first worksheet). XLSX is a zip container and is
opened only within the TRD 8.7 limits: at most 100 entries, at most 100 MB expanded and 100 times
its compressed size, no document-type declarations (so no entity expansion), at most 50,000 rows.
Standard library only; nothing in a file is ever executed.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET

MAX_ROWS = 50_000
MAX_ENTRIES = 100
MAX_EXPANDED = 100 * 1024 * 1024
MAX_RATIO = 100
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CSV_TYPE = "text/csv"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ReceivingFileError(ValueError):
    """The file cannot be read as a receiving file (reason in the message, safe to show)."""


def sniff_receiving(data: bytes) -> str | None:
    """Content type from the bytes; extension and declared type are ignored (TRD 8.7)."""
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "xl/workbook.xml" in z.namelist():
                    return XLSX_TYPE
        except zipfile.BadZipFile:
            return None
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        data[:65536].decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return CSV_TYPE


def read_table(data: bytes, mime: str) -> tuple[list[str], list[list[str]]]:
    if mime == CSV_TYPE:
        rows = _csv(data)
    elif mime == XLSX_TYPE:
        rows = _xlsx(data)
    else:
        raise ReceivingFileError("only CSV and XLSX receiving files are accepted")
    if not rows:
        raise ReceivingFileError("the file has no rows")
    if len(rows) - 1 > MAX_ROWS:
        raise ReceivingFileError(f"more than {MAX_ROWS} rows")
    header = [h.strip() for h in rows[0]]
    return header, [[c.strip() for c in r] for r in rows[1:]]


def _csv(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig")
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    out = []
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
        if i > MAX_ROWS + 1:
            raise ReceivingFileError(f"more than {MAX_ROWS} rows")
        if any(c.strip() for c in row):
            out.append(row)
    return out


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _safe_xml(raw: bytes) -> ET.Element:
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ReceivingFileError("XLSX with a document-type declaration is refused")
    return ET.fromstring(raw)  # noqa: S314 (DTD refused above)


def _xlsx(data: bytes) -> list[list[str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ReceivingFileError("not a readable XLSX file") from exc
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ReceivingFileError("XLSX has too many entries")
        if any(i.flag_bits & 0x1 for i in infos):
            raise ReceivingFileError("encrypted XLSX is refused")
        expanded = sum(i.file_size for i in infos)
        compressed = max(sum(i.compress_size for i in infos), 1)
        if expanded > MAX_EXPANDED or expanded > MAX_RATIO * compressed:
            raise ReceivingFileError("XLSX expands beyond the allowed size")
        names = set(z.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = _safe_xml(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        sheet = "xl/worksheets/sheet1.xml"
        if sheet not in names:
            raise ReceivingFileError("XLSX has no first worksheet")
        root = _safe_xml(z.read(sheet))
    rows: list[list[str]] = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        if len(rows) > MAX_ROWS + 1:
            raise ReceivingFileError(f"more than {MAX_ROWS} rows")
        cells: dict[int, str] = {}
        for c in row.findall("m:c", NS):
            idx = _col_index(c.get("r", "A1"))
            kind = c.get("t")
            v = c.find("m:v", NS)
            if kind == "s" and v is not None and v.text is not None:
                value = shared[int(v.text)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
            else:
                value = v.text if v is not None and v.text is not None else ""
            cells[idx] = value
        if cells and any(v.strip() for v in cells.values()):
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows
