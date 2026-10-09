"""Read a CSV/TXT/Excel table into plain text cells (no pandas).

Owner: INPUTS branch.
SPDX-License-Identifier: GPL-3.0-or-later

Fixes the v1 renamer's table bugs (01 section 3, P3.4/P3.5): CSV saved by a Spanish Excel
(';' + Windows-1252), 'CSV UTF-8' with a BOM, '.CSV' in capitals, Pos columns that became
"1.0", and the .xls that needed a missing library.
"""
from __future__ import annotations

import codecs
import csv
import datetime as dt
import io
from dataclasses import dataclass
from pathlib import Path

CSV_EXTS = (".csv", ".txt", ".tsv")
XLSX_EXTS = (".xlsx", ".xlsm")
XLS_EXTS = (".xls",)
TABLE_EXTS = CSV_EXTS + XLSX_EXTS
DELIMITERS = (";", ",", "\t")
_EXCEL_EPOCHS = (dt.date(1899, 12, 30), dt.date(1899, 12, 31), dt.date(1900, 1, 1))


class TableError(Exception):
    """A user-facing problem reading a table. str(error) is Spanish and says what to do."""


@dataclass(frozen=True)
class RawTable:
    headers: list[str]
    rows: list[list[str]]          # every row padded to len(headers); empty cells are ""
    encoding: str | None           # "utf-8-sig" | "utf-8" | "cp1252" | "utf-16"; None for Excel
    delimiter: str | None          # ";" | "," | "\t"; None for Excel
    sheet: str | None              # Excel sheet name; None for CSV


def read_table(path: Path) -> RawTable:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in XLS_EXTS:
        raise TableError("Los .xls del Excel antiguo no se pueden leer. Guarda el archivo como .xlsx o .csv "
                         "desde Excel (Archivo > Guardar como).")
    if ext not in TABLE_EXTS:
        raise TableError(f"No sé leer archivos {ext or 'sin extensión'}. Usa un .csv, .txt o .xlsx.")
    try:
        if ext in XLSX_EXTS:
            return _read_xlsx(p)
        return _read_csv(p.read_bytes())
    except OSError as e:
        raise TableError(f"No se pudo abrir {p.name}: {e.strerror or e}.") from e


# ---------------------------------------------------------------- CSV / TXT


def decode_bytes(data: bytes) -> tuple[str, str]:
    """-> (text, encoding). UTF-16 by BOM, then UTF-8 (with or without BOM), then Windows-1252."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        text = data.decode("utf-8-sig")
        return text, ("utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


def _split(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter), [])


def _consistent(lines: list[str], delimiter: str, width: int) -> bool:
    rows = [_split(ln, delimiter) for ln in lines[1:]]
    if not rows:
        return True
    same = sum(1 for r in rows if len(r) == width)
    return same >= 0.8 * len(rows)


def detect_delimiter(text: str) -> str:
    """csv.Sniffer over ';', ',' and tab, checked against the header; else the header count wins."""
    lines = [ln for ln in text.splitlines() if ln.strip()][:50]
    if not lines:
        return ","
    try:
        sniffed = csv.Sniffer().sniff("\n".join(lines), delimiters="".join(DELIMITERS)).delimiter
    except csv.Error:
        sniffed = None
    if sniffed in DELIMITERS:
        width = len(_split(lines[0], sniffed))
        if width >= 2 and _consistent(lines, sniffed, width):
            return sniffed
    counts = {d: len(_split(lines[0], d)) for d in DELIMITERS}
    best = max(DELIMITERS, key=lambda d: (counts[d] >= 2 and _consistent(lines, d, counts[d]), counts[d]))
    return best if counts[best] >= 2 else ","


def _clean_cells(cells: list) -> list[str]:
    out = [("" if c is None else str(c)).replace("\r", " ").replace("\n", " ").strip() for c in cells]
    while out and not out[-1]:
        out.pop()
    return out


def _to_table(raw_rows: list[list[str]], *, encoding, delimiter, sheet) -> RawTable:
    rows = [r for r in (_clean_cells(r) for r in raw_rows) if any(r)]
    if not rows:
        raise TableError("La tabla está vacía.")
    headers, data = rows[0], rows[1:]
    width = len(headers)
    data = [r + [""] * (width - len(r)) if len(r) < width else r for r in data]
    return RawTable(headers=headers, rows=data, encoding=encoding, delimiter=delimiter, sheet=sheet)


def _read_csv(data: bytes) -> RawTable:
    text, encoding = decode_bytes(data)
    delimiter = detect_delimiter(text)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as e:
        raise TableError("El archivo no parece una tabla de texto. Guárdalo como .csv desde Excel.") from e
    return _to_table(rows, encoding=encoding, delimiter=delimiter, sheet=None)


# ---------------------------------------------------------------- Excel


def _hms(total: float) -> str:
    s = int(round(total))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def cell_text(v) -> str:
    """Excel value -> text: integers never become '1.0'; times become HH:MM:SS."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, dt.datetime):
        if v.date() in _EXCEL_EPOCHS:
            return _hms(v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6)
        return v.isoformat(sep=" ")
    if isinstance(v, dt.time):
        return _hms(v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6)
    if isinstance(v, dt.timedelta):
        return _hms(v.total_seconds())
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


def _read_xlsx(p: Path) -> RawTable:
    import openpyxl  # lazy: only needed for Excel files

    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    except Exception as e:  # BadZipFile, InvalidFileException, KeyError on broken files
        raise TableError(f"No se pudo abrir {p.name} como Excel. Guárdalo de nuevo como .xlsx o .csv.") from e
    try:
        for ws in wb.worksheets:
            rows = [[cell_text(v) for v in r] for r in ws.iter_rows(values_only=True)]
            if any(any(c.strip() for c in r) for r in rows):
                return _to_table(rows, encoding=None, delimiter=None, sheet=ws.title)
    finally:
        wb.close()
    raise TableError(f"{p.name} no tiene ninguna hoja con datos.")
