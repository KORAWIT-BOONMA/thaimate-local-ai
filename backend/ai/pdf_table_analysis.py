
"""Python-based analysis of grade/score tables in local PDF files."""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber


SUBJECT_ALIASES = {
    "สังคมศึกษา": ("สังคมศึกษา", "สังคม"),
    "ประวัติศาสตร์": ("ประวัติศาสตร์", "ประวัติ"),
    "หน้าที่พลเมือง": ("หน้าที่พลเมือง", "พลเมือง"),
}


# Thai marks from the embedded font used by some PDFs
# are exposed as private-use Unicode characters.
_THAI_PDF_GLYPHS = str.maketrans({
    "\uf70a": "่",
    "\uf70b": "้",
    "\uf706": "้",
    "\uf70e": "์",
    "\uf702": "ี",
})


def _clean(value: object) -> str:

    if value is None:
        return ""

    text = str(value)

    if any(
        "\u0e00" <= char <= "\u0e7f"
        for char in text
    ):
        text = text.translate(_THAI_PDF_GLYPHS)

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _compact(text: str) -> str:

    return re.sub(
        r"[\s:：,，.()（）\[\]{}_-]+",
        "",
        text,
    ).casefold()


def is_pdf_table_analysis_request(
    query: str,
) -> bool:
    """Detect questions requiring full-table analysis."""

    q = _compact(str(query or ""))

    data_terms = (
        "เกรด",
        "คะแนน",
        "นักเรียน",
        "ผู้เรียน",
        "เลขประจำตัว",
        "ชื่อสกุล",
        "รายวิชา",
    )

    action_terms = (
        "กี่คน",
        "กี่ราย",
        "จำนวน",
        "นับ",
        "ใคร",
        "รายชื่อ",
        "สูงสุด",
        "มากที่สุด",
        "ต่ำสุด",
        "น้อยที่สุด",
        "เรียง",
        "แจกแจง",
        "เปรียบเทียบ",
        "ทั้งหมด",
        "ทุกคน",
        "ทุกเกรด",
    )

    return (
        any(term in q for term in data_terms)
        and any(term in q for term in action_terms)
    )


def _number(value: str) -> float | None:

    value = _clean(value).replace(",", "")

    if not re.fullmatch(
        r"[-+]?\d+(?:\.\d+)?",
        value,
    ):
        return None

    return float(value)


def _parse_page_tables(
    page,
    page_number: int,
) -> list[dict]:
    """Extract student records from tables on one PDF page."""

    text = page.extract_text() or ""

    code_match = re.search(
        r"รหัส\s*วิชา\s*([ก-๙A-Za-z0-9]+)",
        text,
    )

    subject_match = re.search(
        r"รายวิชา\s*([^\r\n]+)",
        text,
    )

    course_code = (
        code_match.group(1).strip()
        if code_match
        else "ไม่ระบุ"
    )

    subject = (
        _clean(subject_match.group(1))
        if subject_match
        else "ไม่ทราบชื่อวิชา"
    )

    parsed = []

    for table_no, table in enumerate(
        page.extract_tables() or [],
        start=1,
    ):

        if not table:
            continue

        # Find the header containing both name and grade.
        header_index = None
        headers = []

        for index, raw in enumerate(table[:5]):

            candidate = [
                _clean(value)
                for value in (raw or [])
            ]

            joined = " ".join(candidate).casefold()

            if "เกรด" in joined and "ชื่อ" in joined:

                header_index = index
                headers = candidate
                break

        if header_index is None:
            continue

        grade_index = next(
            index
            for index, header in enumerate(headers)
            if "เกรด" in header.casefold()
        )

        name_index = next(
            index
            for index, header in enumerate(headers)
            if "ชื่อ" in header or "name" in header.casefold()
        )

        student_id_index = next(
            (
                index
                for index, header in enumerate(headers)
                if (
                    "เลข" in header
                    and (
                        "ประจํา" in header
                        or "ประจำ" in header
                        or "ตัว" in header
                    )
                    and "ประชาชน" not in header
                )
            ),
            None,
        )

        score_index = next(
            (
                index
                for index, header in enumerate(headers)
                if (
                    "รวม" in header
                    or "คะแนนรวม" in header
                    or "total" in header.casefold()
                )
            ),
            None,
        )

        highest_index = max(
            index
            for index in (
                grade_index,
                name_index,
                student_id_index,
                score_index,
            )
            if index is not None
        )

        records = []

        for raw_row in table[header_index + 1:]:

            row = [
                _clean(value)
                for value in (raw_row or [])
            ]

            row.extend(
                [""] * max(
                    0,
                    highest_index + 1 - len(row),
                )
            )

            grade = _number(row[grade_index])
            name = row[name_index]

            if grade is None or not name:
                continue

            records.append({
                "name": name,
                "student_id": (
                    row[student_id_index]
                    if student_id_index is not None
                    else ""
                ),
                "grade": grade,
                "score": (
                    _number(row[score_index])
                    if score_index is not None
                    else None
                ),
            })

        if records:

            parsed.append({
                "page": page_number,
                "table": table_no,
                "subject": subject,
                "course_code": course_code,
                "records": records,
            })

    return parsed


def _select_subjects(
    tables: list[dict],
    query: str,
) -> tuple[list[dict], str | None]:
    """Select a named subject without mixing different subjects."""

    q = _compact(query)

    matched = [
        (name, aliases)
        for name, aliases in SUBJECT_ALIASES.items()
        if any(
            _compact(alias) in q
            for alias in aliases
        )
    ]

    if matched:

        selected = [
            table
            for table in tables
            if any(
                _compact(alias) in _compact(table["subject"])
                for _, aliases in matched
                for alias in aliases
            )
        ]

        return (
            selected,
            ", ".join(name for name, _ in matched),
        )

    # Fallback for other subject names.
    # A short prefix tolerates unusual embedded Thai font glyphs.

    for table in tables:

        key = _compact(table["subject"])[:6]

        if len(key) >= 4 and key in q:

            return (
                [
                    item for item in tables
                    if key in _compact(item["subject"])
                ],
                table["subject"],
            )

    # No subject specified:
    # Keep each subject separate.

    return tables, None


def analyze_pdf_table_file(
    pdf_path: str | Path,
    query: str,
) -> str:
    """Read all grade tables and calculate verified Python results."""

    path = Path(pdf_path)

    if (
        not path.is_file()
        or path.suffix.lower() != ".pdf"
    ):
        raise ValueError(
            "ไม่พบไฟล์ PDF สำหรับวิเคราะห์ตาราง"
        )

    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(
            "PDF มีขนาดเกิน 10 MB"
        )

    tables = []

    with pdfplumber.open(path) as pdf:

        for page_number, page in enumerate(
            pdf.pages,
            start=1,
        ):

            tables.extend(
                _parse_page_tables(
                    page,
                    page_number,
                )
            )

    if not tables:
        raise ValueError(
            "ไม่พบตารางที่มีคอลัมน์ชื่อและเกรดใน PDF"
        )

    selected, subject_scope = _select_subjects(
        tables,
        query,
    )

    if not selected:

        known = ", ".join(
            dict.fromkeys(
                table["subject"]
                for table in tables
            )
        )

        return (
            "ไม่พบรายวิชาที่ตรงกับคำถาม "
            f"รายวิชาในเอกสาร: {known}"
        )

    q = _compact(query)

    grade_four = (
        "เกรด4" in q
        or "เกรด๔" in q
        or "เกรดสี่" in q
    )

    wants_names = any(
        term in q
        for term in ("ใคร", "รายชื่อ", "ชื่อ")
    )

    all_names = (
        "รายชื่อ" in q
        and "นักเรียน" in q
        and any(
            term in q
            for term in ("ทั้งหมด", "ทุกคน")
        )
    )

    high_score = (
        "คะแนน" in q
        and any(
            term in q
            for term in ("สูงสุด", "มากที่สุด")
        )
    )

    low_score = (
        "คะแนน" in q
        and any(
            term in q
            for term in ("ต่ำสุด", "น้อยที่สุด")
        )
    )

    high_grade = (
        "เกรด" in q
        and any(
            term in q
            for term in ("สูงสุด", "มากที่สุด")
        )
        and not grade_four
    )

    output = [
        "VERIFIED PDF TABLE ANALYSIS (Python source of truth)",
        f"Source file: {path.name} [L1]",
        (
            f"ขอบเขตรายวิชา: {subject_scope}"
            if subject_scope
            else "ไม่ได้ระบุรายวิชา: แสดงแยกรายวิชา ไม่รวมจำนวนนักเรียนข้ามวิชา"
        ),
        "Python อ่านทุกแถวจากตาราง PDF และคำนวณผลด้านล่างแล้ว",
        "",
    ]

    for table in selected:

        records = table["records"]

        grade4 = [
            record
            for record in records
            if record["grade"] == 4
        ]

        output.extend([
            f"รายวิชา: {table['subject']}",
            f"รหัสวิชา: {table['course_code']}",
            f"จำนวนผู้เรียนที่อ่านได้: {len(records)} คน",
            f"จำนวนผู้เรียนที่ได้เกรด 4: {len(grade4)} คน",
        ])

        if grade_four and wants_names:

            output.append(
                "รายชื่อผู้เรียนที่ได้เกรด 4:"
            )

            for record in grade4:

                sid = (
                    f" (เลขประจำตัว {record['student_id']})"
                    if record["student_id"]
                    else ""
                )

                output.append(
                    f"- {record['name']}{sid}"
                )

        if all_names:

            output.append(
                "รายชื่อนักเรียนทั้งหมด:"
            )

            for record in records:

                sid = (
                    f" (เลขประจำตัว {record['student_id']})"
                    if record["student_id"]
                    else ""
                )

                output.append(
                    f"- {record['name']}{sid}"
                )

        scored = [
            record
            for record in records
            if record["score"] is not None
        ]

        if scored and high_score:

            value = max(
                record["score"]
                for record in scored
            )

            output.append(
                f"คะแนนรวมสูงสุด: {value:g} คะแนน"
            )

            for record in scored:

                if record["score"] == value:

                    sid = (
                        f" (เลขประจำตัว {record['student_id']})"
                        if record["student_id"]
                        else ""
                    )

                    output.append(
                        f"- {record['name']}{sid}"
                    )

        if scored and low_score:

            value = min(
                record["score"]
                for record in scored
            )

            output.append(
                f"คะแนนรวมต่ำสุด: {value:g} คะแนน"
            )

            for record in scored:

                if record["score"] == value:

                    sid = (
                        f" (เลขประจำตัว {record['student_id']})"
                        if record["student_id"]
                        else ""
                    )

                    output.append(
                        f"- {record['name']}{sid}"
                    )

        if high_grade:

            value = max(
                record["grade"]
                for record in records
            )

            output.append(
                f"เกรดสูงสุด: {value:g}"
            )

            for record in records:

                if record["grade"] == value:

                    sid = (
                        f" (เลขประจำตัว {record['student_id']})"
                        if record["student_id"]
                        else ""
                    )

                    output.append(
                        f"- {record['name']}{sid}"
                    )

        if not (
            grade_four
            or wants_names
            or high_score
            or low_score
            or high_grade
            or all_names
        ):

            counts: dict[str, int] = {}

            for record in records:

                grade = f"{record['grade']:g}"

                counts[grade] = (
                    counts.get(grade, 0) + 1
                )

            output.append(
                "จำนวนผู้เรียนแยกตามเกรด:"
            )

            for grade, count in sorted(
                counts.items(),
                key=lambda item: float(item[0]),
                reverse=True,
            ):

                output.append(
                    f"- เกรด {grade}: {count} คน"
                )

        output.append("")

    output.extend([
        "STRICT INSTRUCTIONS FOR THE LANGUAGE MODEL:",
        "- Python is the source of truth for all counts and row-to-name/student-ID mappings above.",
        "- Preserve the exact counts, names, IDs, grades, and scores; do not recalculate or alter them.",
        "- Do not claim the document is incomplete when these results are supplied.",
        "- Never mix results from different subjects.",
        "- Answer in Thai and cite the source as [L1].",
    ])

    return "\n".join(output)
