
"""Extract searchable text from supported local documents."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from collections.abc import Iterable

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


MAX_SOURCE_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_TEXT_BYTES = 200_000

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".json", ".csv",
}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {
    ".pdf", ".docx", ".xlsx"
}


# Common field names with Thai descriptions.
# Original column names are always preserved.
COLUMN_LABELS = {
    "record_id": "รหัสรายการ",
    "timestamp": "วันและเวลาบันทึก",
    "zone": "โซนหรือพื้นที่",
    "soil_moisture_pct": "ความชื้นในดิน",
    "temperature_c": "อุณหภูมิ",
    "air_humidity_pct": "ความชื้นสัมพัทธ์ในอากาศ",
    "water_distance_cm": "ระยะห่างจากผิวน้ำ",
    "status": "สถานะ",
}


class DocumentReadError(ValueError):
    """Raised when a document cannot safely be converted to text."""


def _check_size(path: Path) -> None:
    if not path.is_file():
        raise DocumentReadError("ไม่พบไฟล์")

    if path.stat().st_size > MAX_SOURCE_FILE_BYTES:
        raise DocumentReadError("ไฟล์มีขนาดเกิน 10 MB")


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp874"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise DocumentReadError(
        "อ่านไฟล์ข้อความไม่ได้ รองรับ UTF-8 และ Windows Thai (CP874)"
    )


def _check_extracted_size(text: str) -> str:
    text = text.strip()

    if not text:
        raise DocumentReadError(
            "ไม่พบข้อความในไฟล์ หรือไฟล์อาจเป็นภาพสแกน"
        )

    if len(text.encode("utf-8")) > MAX_EXTRACTED_TEXT_BYTES:
        raise DocumentReadError(
            "ข้อความที่ดึงได้มีขนาดเกิน 200 KB "
            "กรุณาแบ่งเอกสารเป็นไฟล์ย่อยก่อนนำเข้า"
        )

    return text


# ==========================================
# Structured Table Extraction
# ==========================================

def _stringify_cell(value: object) -> str:
    """Convert a cell value into readable text."""

    if value is None:
        return ""

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return str(value).strip()


def _normalize_headers(values: list[str]) -> list[str]:
    """Preserve original headers and provide names for blank columns."""

    headers = []

    for index, value in enumerate(values, start=1):
        name = value.strip()

        if not name:
            name = f"column_{index}"

        headers.append(name)

    return headers


def _format_table(
    headers: list[str],
    rows: Iterable[list[str]],
    table_name: str,
) -> str:
    """
    Convert tabular data into explicit header-value pairs.

    This representation helps retrieval and prevents the LLM
    from confusing values between adjacent columns.
    """

    normalized_headers = _normalize_headers(headers)

    parts = [
        f"[ตารางข้อมูล: {table_name}]",
        "",
        "ชื่อคอลัมน์ทั้งหมด (Column headers):",
        " | ".join(normalized_headers),
        "",
        "ข้อมูลในแต่ละแถว:",
        "",
    ]

    row_count = 0

    for row_index, raw_values in enumerate(rows, start=1):
        values = list(raw_values)

        if not any(value.strip() for value in values):
            continue

        row_count += 1

        # Keep one value for every header.
        if len(values) < len(normalized_headers):
            values.extend(
                [""] * (len(normalized_headers) - len(values))
            )

        # Preserve extra cells rather than silently dropping them.
        current_headers = list(normalized_headers)

        if len(values) > len(current_headers):
            for extra_index in range(
                len(current_headers) + 1,
                len(values) + 1,
            ):
                current_headers.append(
                    f"extra_column_{extra_index}"
                )

        first_header = current_headers[0].lower()
        first_value = values[0].strip() if values else ""

        if first_value and first_header in {
            "record_id", "record", "id"
        }:
            row_title = f"[Record {first_value}]"
        else:
            row_title = f"[แถวข้อมูล {row_index}]"

        parts.append(row_title)

        for header, value in zip(current_headers, values):
            header_lower = header.lower()
            thai_label = COLUMN_LABELS.get(header_lower)

            if thai_label:
                display_name = f"{header} ({thai_label})"
            else:
                display_name = header

            clean_value = value.strip().replace("\r", " ").replace("\n", " / ")

            if clean_value:
                parts.append(f"{display_name}: {clean_value}")
            else:
                parts.append(f"{display_name}: (ว่าง)")

        # Keep original column order visible for verification.
        parts.append(
            "ข้อมูลเรียงตามคอลัมน์: "
            + " | ".join(value.strip() for value in values)
        )
        parts.append("")

    parts.insert(
        5,
        f"จำนวนแถวข้อมูลทั้งหมด: {row_count}",
    )

    return "\n".join(parts)


# ==========================================
# CSV Extraction
# ==========================================

def _extract_csv(path: Path) -> str:
    raw = path.read_bytes()
    text = _decode_text(raw)

    try:
        reader = csv.reader(io.StringIO(text, newline=""))

        rows = [
            [cell.strip() for cell in row]
            for row in reader
        ]

    except csv.Error as exc:
        raise DocumentReadError(
            f"อ่าน CSV ไม่สำเร็จ: {exc}"
        ) from exc

    # Remove completely empty rows.
    rows = [
        row for row in rows
        if any(cell.strip() for cell in row)
    ]

    if not rows:
        return ""

    headers = rows[0]
    data_rows = rows[1:]

    return _format_table(
        headers=headers,
        rows=data_rows,
        table_name=f"CSV: {path.name}",
    )


# ==========================================
# PDF Extraction
# ==========================================

def _extract_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path), strict=False)

        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    raise DocumentReadError(
                        "PDF นี้มีรหัสผ่าน ไม่สามารถอ่านได้"
                    )
            except Exception as exc:
                if isinstance(exc, DocumentReadError):
                    raise

                raise DocumentReadError(
                    "PDF นี้มีรหัสผ่าน ไม่สามารถอ่านได้"
                ) from exc

        pages = []

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):
            page_text = (page.extract_text() or "").strip()

            if page_text:
                pages.append(
                    f"[หน้า {page_number}]\n{page_text}"
                )

        return "\n\n".join(pages)

    except DocumentReadError:
        raise

    except Exception as exc:
        raise DocumentReadError(
            f"อ่าน PDF ไม่สำเร็จ: {exc}"
        ) from exc


# ==========================================
# DOCX Extraction
# ==========================================

def _extract_docx(path: Path) -> str:
    try:
        document = Document(str(path))
        parts = []

        for paragraph in document.paragraphs:
            value = paragraph.text.strip()

            if value:
                parts.append(value)

        for table_index, table in enumerate(
            document.tables,
            start=1,
        ):
            parts.append(f"[ตาราง {table_index}]")

            for row_index, row in enumerate(
                table.rows,
                start=1,
            ):
                values = [
                    cell.text.strip().replace("\n", " / ")
                    for cell in row.cells
                ]

                if any(values):
                    parts.append(
                        f"[แถว {row_index}] "
                        + " | ".join(values)
                    )

        return "\n".join(parts)

    except Exception as exc:
        raise DocumentReadError(
            f"อ่าน DOCX ไม่สำเร็จ: {exc}"
        ) from exc


# ==========================================
# XLSX Extraction
# ==========================================

def _extract_xlsx(path: Path) -> str:
    workbook = None

    try:
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=True,
        )

        parts = []

        for sheet in workbook.worksheets:
            rows = iter(
                sheet.iter_rows(values_only=True)
            )

            # Find the first non-empty row as the header.
            headers = None

            for row in rows:
                cells = [
                    _stringify_cell(value)
                    for value in row
                ]

                if any(value.strip() for value in cells):
                    headers = cells
                    break

            if headers is None:
                continue

            # Convert remaining rows into string values.
            def data_rows():
                for row in rows:
                    yield [
                        _stringify_cell(value)
                        for value in row
                    ]

            parts.append(
                _format_table(
                    headers=headers,
                    rows=data_rows(),
                    table_name=f"XLSX Sheet: {sheet.title}",
                )
            )

        return "\n\n".join(parts)

    except DocumentReadError:
        raise

    except Exception as exc:
        raise DocumentReadError(
            f"อ่าน XLSX ไม่สำเร็จ: {exc}"
        ) from exc

    finally:
        if workbook is not None:
            workbook.close()


# ==========================================
# Main Document Reader
# ==========================================

def extract_document_text(path: str | Path) -> str:
    """Extract searchable text from supported document formats."""

    file_path = Path(path)

    _check_size(file_path)

    suffix = file_path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentReadError(
            f"ยังไม่รองรับไฟล์นามสกุล "
            f"{suffix or '(ไม่มีนามสกุล)'}"
        )

    if suffix == ".pdf":
        extracted = _extract_pdf(file_path)

    elif suffix == ".docx":
        extracted = _extract_docx(file_path)

    elif suffix == ".xlsx":
        extracted = _extract_xlsx(file_path)

    elif suffix == ".csv":
        extracted = _extract_csv(file_path)

    else:
        extracted = _decode_text(
            file_path.read_bytes()
        )

    return _check_extracted_size(extracted)
