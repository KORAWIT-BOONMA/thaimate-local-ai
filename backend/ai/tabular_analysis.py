
import csv
import io
import json
import re

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from openpyxl import load_workbook

import workspace


# ==========================================
# Configuration
# ==========================================

MAX_FILE_BYTES = 10 * 1024 * 1024

SUPPORTED_EXTENSIONS = {
    ".csv",
    ".xlsx",
}

GROUP_FIELD_ALIASES = {
    "zone",
    "zone_name",
    "area",
    "area_name",
    "region",
    "site",
    "location",
    "greenhouse",
    "group",
    "กลุ่ม",
    "โซน",
    "พื้นที่",
    "บริเวณ",
    "โรงเรือน",
    "แปลง",
}

STATUS_FIELD_ALIASES = {
    "status",
    "สถานะ",
}

RECORD_ID_FIELD_ALIASES = {
    "record_id",
    "recordid",
    "id",
    "รหัส",
    "รหัสข้อมูล",
    "รหัสรายการ",
}

# Explicit mappings prevent unrelated numeric settings
# from being treated as sensor thresholds.

THRESHOLD_SETTING_MAP = {
    "soil_moisture_min_pct": (
        "soil_moisture_pct",
        "lt",
    ),
    "temperature_max_c": (
        "temperature_c",
        "gt",
    ),
    "air_humidity_min_pct": (
        "air_humidity_pct",
        "lt",
    ),
    "water_distance_max_cm": (
        "water_distance_cm",
        "gt",
    ),
}


class TabularAnalysisError(ValueError):
    """Raised when tabular data cannot be analyzed."""


# ==========================================
# File Validation
# ==========================================

def _load_file_path(source: str) -> Path:

    if not source:
        raise TabularAnalysisError(
            "ไม่ได้ระบุไฟล์"
        )

    try:
        path = workspace.safe_path(source)

    except Exception as exc:
        raise TabularAnalysisError(
            f"ไม่สามารถเข้าถึงไฟล์ที่ระบุได้: {exc}"
        ) from exc

    if not path.is_file():
        raise TabularAnalysisError(
            "ไม่พบไฟล์"
        )

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise TabularAnalysisError(
            "รองรับเฉพาะ CSV และ XLSX"
        )

    if path.stat().st_size > MAX_FILE_BYTES:
        raise TabularAnalysisError(
            "ไฟล์มีขนาดใหญ่เกินไป (สูงสุด 10 MB)"
        )

    return path


# ==========================================
# Shared Table Helpers
# ==========================================

def _unique_headers(
    raw_headers: list[Any],
) -> list[str]:

    headers = []
    used = Counter()

    for index, raw_header in enumerate(
        raw_headers,
        start=1,
    ):

        base = (
            str(raw_header).strip()
            if raw_header is not None
            else ""
        )

        base = base or f"column_{index}"

        used[base] += 1

        headers.append(
            base
            if used[base] == 1
            else f"{base}_{used[base]}"
        )

    return headers


def _cell_to_text(value: Any) -> str:

    if value is None:
        return ""

    if hasattr(value, "isoformat"):

        try:
            return value.isoformat()

        except (TypeError, ValueError):
            pass

    return str(value).strip()


def _is_non_empty_row(
    row: list[Any] | tuple[Any, ...],
) -> bool:

    return any(
        value is not None and str(value).strip()
        for value in row
    )


def _extend_headers(
    headers: list[str],
    required_length: int,
) -> None:

    while len(headers) < required_length:

        headers.append(
            f"column_{len(headers) + 1}"
        )


def _normalize_key(value: str) -> str:

    return re.sub(
        r"[\s\-]+",
        "_",
        str(value).strip().casefold(),
    )


def _find_field_name(
    records: list[dict[str, str]],
    aliases: set[str],
) -> str | None:

    if not records:
        return None

    for field in records[0].keys():

        if _normalize_key(field) in aliases:
            return field

    return None


# ==========================================
# CSV Reader
# ==========================================

def _read_csv(
    path: Path,
) -> list[dict[str, str]]:

    raw = path.read_bytes()

    text = None

    for encoding in ("utf-8-sig", "cp874"):

        try:
            text = raw.decode(encoding)
            break

        except UnicodeDecodeError:
            continue

    if text is None:

        raise TabularAnalysisError(
            "ไม่สามารถอ่าน Encoding ของ CSV ได้"
        )

    try:

        try:

            dialect = csv.Sniffer().sniff(
                text[:8192],
                delimiters=",;\t|",
            )

        except csv.Error:

            dialect = csv.excel

        reader = csv.reader(
            io.StringIO(text, newline=""),
            dialect,
        )

        raw_headers = next(
            (
                row
                for row in reader
                if _is_non_empty_row(row)
            ),
            None,
        )

        if not raw_headers:

            raise TabularAnalysisError(
                "ไม่พบหัวตาราง CSV"
            )

        headers = _unique_headers(
            raw_headers
        )

        records = []

        for row in reader:

            if not _is_non_empty_row(row):
                continue

            _extend_headers(
                headers,
                len(row),
            )

            values = list(row)

            values.extend(
                [""] * (len(headers) - len(values))
            )

            records.append({
                header: _cell_to_text(value)
                for header, value in zip(headers, values)
            })

        for record in records:

            for header in headers:
                record.setdefault(header, "")

        return records

    except csv.Error as exc:

        raise TabularAnalysisError(
            f"อ่าน CSV ไม่สำเร็จ: {exc}"
        ) from exc


# ==========================================
# XLSX Reader
# ==========================================

def _read_xlsx(
    path: Path,
) -> dict[str, list[dict[str, str]]]:

    workbook = None

    try:

        workbook = load_workbook(
            path,
            read_only=True,
            data_only=True,
        )

        result = {}

        for sheet in workbook.worksheets:

            iterator = sheet.iter_rows(
                values_only=True
            )

            raw_headers = next(
                (
                    list(row)
                    for row in iterator
                    if _is_non_empty_row(row)
                ),
                None,
            )

            if raw_headers is None:
                continue

            headers = _unique_headers(
                raw_headers
            )

            records = []

            for row in iterator:

                if not _is_non_empty_row(row):
                    continue

                values = list(row)

                _extend_headers(
                    headers,
                    len(values),
                )

                values.extend(
                    [None] * (len(headers) - len(values))
                )

                records.append({
                    header: _cell_to_text(value)
                    for header, value in zip(headers, values)
                })

            for record in records:

                for header in headers:
                    record.setdefault(header, "")

            result[sheet.title] = records

        return result

    except Exception as exc:

        if isinstance(exc, TabularAnalysisError):
            raise

        raise TabularAnalysisError(
            f"อ่าน XLSX ไม่สำเร็จ: {exc}"
        ) from exc

    finally:

        if workbook is not None:
            workbook.close()


# ==========================================
# Numeric and Metadata Helpers
# ==========================================

def _parse_number(value: Any) -> float | None:

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = (
        text
        .replace(",", "")
        .replace("%", "")
        .strip()
    )

    if re.search(
        r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}",
        text,
    ):
        return None

    if re.search(r"\d{1,2}:\d{2}", text):
        return None

    try:
        return float(text)

    except (TypeError, ValueError):
        return None


def _is_metadata_field(
    field_name: str,
) -> bool:

    key = _normalize_key(field_name)

    compact = key.replace("_", "")

    metadata_names = {
        "id",
        "record_id",
        "recordid",
        "timestamp",
        "date",
        "time",
        "datetime",
        "status",
        "state",
        "สถานะ",
        "zone",
        "zone_name",
        "area",
        "region",
        "site",
        "location",
        "group",
        "โซน",
        "พื้นที่",
        "บริเวณ",
        "โรงเรือน",
        "แปลง",
        "กลุ่ม",
    }

    if key in metadata_names:
        return True

    if any(
        token in key
        for token in (
            "_id",
            "_code",
            "timestamp",
            "datetime",
            "date",
            "time",
            "status",
            "state",
            "zone",
            "area",
            "region",
            "location",
            "recordid",
        )
    ):
        return True

    return (
        compact.endswith("id")
        or compact.endswith("code")
    )


def _get_numeric_summary(
    records: list[dict[str, str]],
) -> dict:

    numeric_values = defaultdict(list)

    if not records:
        return {}

    for field_name in records[0].keys():

        if _is_metadata_field(field_name):
            continue

        for record in records:

            number = _parse_number(
                record.get(field_name, "")
            )

            if number is not None:

                numeric_values[field_name].append(
                    number
                )

    return {
        field_name: {
            "count": len(values),
            "average": round(mean(values), 3),
            "minimum": min(values),
            "maximum": max(values),
        }
        for field_name, values in numeric_values.items()
        if values
    }


# ==========================================
# Group Analysis
# ==========================================

def _detect_group_fields(
    records: list[dict[str, str]],
    requested_group_by: str | list[str] | None = None,
) -> list[str]:

    if not records:
        return []

    available_fields = list(
        records[0].keys()
    )

    if requested_group_by:

        requested = (
            [requested_group_by]
            if isinstance(requested_group_by, str)
            else requested_group_by
        )

        matched = []

        for requested_name in requested:

            target = _normalize_key(
                requested_name
            )

            found = next(
                (
                    field
                    for field in available_fields
                    if _normalize_key(field) == target
                ),
                None,
            )

            if found:
                matched.append(found)

        if not matched:

            raise TabularAnalysisError(
                "ไม่พบคอลัมน์สำหรับจัดกลุ่ม: "
                + ", ".join(map(str, requested))
            )

        return matched

    return [
        field
        for field in available_fields
        if _normalize_key(field) in GROUP_FIELD_ALIASES
    ]


def _build_group_analysis(
    records: list[dict[str, str]],
    group_fields: list[str],
    status_field: str | None,
    record_id_field: str | None,
) -> dict:

    result = {}

    for field_name in group_fields:

        grouped = defaultdict(list)

        for record in records:

            value = str(
                record.get(field_name, "")
            ).strip() or "(ไม่ระบุ)"

            grouped[value].append(record)

        group_result = {}

        for label, group_records in sorted(
            grouped.items(),
            key=lambda item: item[0].casefold(),
        ):

            status_counts = Counter()
            alert_ids = []

            for record in group_records:

                status = (
                    str(
                        record.get(status_field, "")
                    ).strip().upper()
                    if status_field
                    else ""
                )

                if status:
                    status_counts[status] += 1

                if status == "ALERT" and record_id_field:

                    record_id = str(
                        record.get(record_id_field, "")
                    ).strip()

                    if record_id:
                        alert_ids.append(record_id)

            group_result[label] = {
                "total_rows": len(group_records),
                "status_counts": dict(status_counts),
                "alert_count": status_counts.get(
                    "ALERT",
                    0,
                ),
                "alert_record_ids": alert_ids,
                "numeric_summary": _get_numeric_summary(
                    group_records
                ),
            }

        result[field_name] = group_result

    return result


# ==========================================
# Configuration Sheet Analysis
# ==========================================

def _is_configuration_table(
    records: list[dict[str, str]],
) -> bool:

    if not records:
        return False

    fields = {
        _normalize_key(field)
        for field in records[0].keys()
    }

    return (
        "setting" in fields
        and "value" in fields
    )


def _analyze_configuration_records(
    records: list[dict[str, str]],
    table_name: str,
) -> dict:

    if not records:

        return {
            "table": table_name,
            "table_type": "configuration",
            "total_rows": 0,
            "settings_count": 0,
            "configuration_settings": [],
            "numeric_value_count": 0,
            "text_value_count": 0,
            "duplicate_settings": [],
            "empty_fields": {},
            "unexpected_empty_fields": {},
            "numeric_summary": {},
        }

    setting_field = _find_field_name(
        records,
        {"setting"},
    )

    value_field = _find_field_name(
        records,
        {"value"},
    )

    unit_field = _find_field_name(
        records,
        {"unit"},
    )

    description_field = _find_field_name(
        records,
        {"description", "คำอธิบาย"},
    )

    empty_fields = Counter()
    unexpected_empty_fields = Counter()
    setting_counts = Counter()
    settings = []

    numeric_value_count = 0
    text_value_count = 0

    for record in records:

        for field, value in record.items():

            if not str(value).strip():
                empty_fields[field] += 1

        setting = (
            str(record.get(setting_field, "")).strip()
            if setting_field
            else ""
        )

        value = (
            str(record.get(value_field, "")).strip()
            if value_field
            else ""
        )

        unit = (
            str(record.get(unit_field, "")).strip()
            if unit_field
            else ""
        )

        description = (
            str(record.get(description_field, "")).strip()
            if description_field
            else ""
        )

        normalized_setting = _normalize_key(
            setting
        )

        setting_counts[normalized_setting] += 1

        numeric_value = _parse_number(value)

        if numeric_value is not None:
            numeric_value_count += 1

        elif value:
            text_value_count += 1

        settings.append({
            "setting": setting,
            "value": value,
            "unit": unit,
            "description": description,
            "value_type": (
                "numeric"
                if numeric_value is not None
                else "text"
            ),
        })

        unit_is_expected_blank = (
            normalized_setting.endswith("_status")
            and not unit
        )

        for field, field_value in record.items():

            if str(field_value).strip():
                continue

            if (
                field == unit_field
                and unit_is_expected_blank
            ):
                continue

            unexpected_empty_fields[field] += 1

    duplicates = sorted(
        setting
        for setting, count in setting_counts.items()
        if setting and count > 1
    )

    return {
        "table": table_name,
        "table_type": "configuration_key_value",
        "total_rows": len(records),
        "settings_count": len([
            item
            for item in settings
            if item["setting"]
        ]),
        "configuration_settings": settings,
        "numeric_value_count": numeric_value_count,
        "text_value_count": text_value_count,
        "duplicate_settings": duplicates,
        "empty_fields": dict(empty_fields),
        "unexpected_empty_fields": dict(
            unexpected_empty_fields
        ),
        "numeric_summary": {},
    }


def _extract_configuration(
    records: list[dict[str, str]],
) -> dict[str, dict]:

    """Convert Configuration key-value rows into a setting lookup."""

    setting_field = _find_field_name(
        records,
        {"setting"},
    )

    value_field = _find_field_name(
        records,
        {"value"},
    )

    unit_field = _find_field_name(
        records,
        {"unit"},
    )

    description_field = _find_field_name(
        records,
        {"description", "คำอธิบาย"},
    )

    if not setting_field or not value_field:
        return {}

    settings = {}

    for record in records:

        name = _normalize_key(
            record.get(setting_field, "")
        )

        if not name:
            continue

        settings[name] = {
            "setting": str(
                record.get(setting_field, "")
            ).strip(),
            "value": str(
                record.get(value_field, "")
            ).strip(),
            "unit": (
                str(record.get(unit_field, "")).strip()
                if unit_field
                else ""
            ),
            "description": (
                str(record.get(description_field, "")).strip()
                if description_field
                else ""
            ),
        }

    return settings


# ==========================================
# Cross-Sheet Configuration Validation
# ==========================================

def _find_sensor_sheet(
    sheets: dict[str, list[dict[str, str]]],
) -> str | None:

    for name, records in sheets.items():

        normalized = _normalize_key(name)

        if normalized in {
            "sensordata",
            "sensor_data",
        }:
            return name

        fields = (
            {
                _normalize_key(field)
                for field in records[0].keys()
            }
            if records
            else set()
        )

        if {
            "status",
            "record_id",
        }.issubset(fields):
            return name

    return None


def _find_configuration_sheet(
    sheets: dict[str, list[dict[str, str]]],
) -> str | None:

    for name, records in sheets.items():

        normalized = _normalize_key(name)

        if (
            normalized == "configuration"
            or _is_configuration_table(records)
        ):
            return name

    return None


def _evaluate_configuration_against_sensors(
    sensor_records: list[dict[str, str]],
    configuration_records: list[dict[str, str]],
    sensor_sheet_name: str,
    configuration_sheet_name: str,
) -> dict:

    """Compare every sensor record with all configured thresholds."""

    config = _extract_configuration(
        configuration_records
    )

    if not config:

        return {
            "available": False,
            "reason": (
                "ไม่พบตาราง Configuration แบบ setting/value"
            ),
        }

    alert_setting = (
        config.get("alert_status", {}).get("value")
        or "ALERT"
    )

    normal_setting = (
        config.get("normal_status", {}).get("value")
        or "NORMAL"
    )

    alert_label = str(
        alert_setting
    ).strip().upper()

    normal_label = str(
        normal_setting
    ).strip().upper()

    sensor_fields = (
        set(sensor_records[0].keys())
        if sensor_records
        else set()
    )

    status_field = _find_field_name(
        sensor_records,
        STATUS_FIELD_ALIASES,
    )

    record_id_field = _find_field_name(
        sensor_records,
        RECORD_ID_FIELD_ALIASES,
    )

    zone_field = _find_field_name(
        sensor_records,
        GROUP_FIELD_ALIASES,
    )

    # Map the expected sensor field names to actual columns.

    sensor_field_lookup = {}

    for expected_field, _operator in THRESHOLD_SETTING_MAP.values():

        actual_field = next(
            (
                field
                for field in sensor_fields
                if _normalize_key(field) == expected_field
            ),
            None,
        )

        sensor_field_lookup[expected_field] = actual_field

    # Build available rules and record unavailable rules.

    configured_thresholds = []
    usable_rules = []
    unavailable_rules = []

    for setting_key, (
        sensor_field,
        operator,
    ) in THRESHOLD_SETTING_MAP.items():

        entry = config.get(setting_key)

        if not entry:

            unavailable_rules.append({
                "setting": setting_key,
                "reason": "ไม่พบ Setting ใน Configuration",
            })

            continue

        threshold = _parse_number(
            entry.get("value")
        )

        if threshold is None:

            unavailable_rules.append({
                "setting": setting_key,
                "reason": "ค่า Threshold ไม่ใช่ตัวเลขหรือไม่มีค่า",
            })

            continue

        actual_field = sensor_field_lookup.get(
            sensor_field
        )

        if actual_field is None:

            unavailable_rules.append({
                "setting": setting_key,
                "sensor_field": sensor_field,
                "reason": "ไม่พบคอลัมน์เซนเซอร์ใน SensorData",
            })

            continue

        rule = {
            "setting": entry.get(
                "setting",
                setting_key,
            ),
            "sensor_field": actual_field,
            "operator": (
                "<"
                if operator == "lt"
                else ">"
            ),
            "threshold": threshold,
            "unit": entry.get("unit", ""),
            "description": entry.get(
                "description",
                "",
            ),
            "_operator_code": operator,
        }

        usable_rules.append(rule)

        configured_thresholds.append({
            key: value
            for key, value in rule.items()
            if not key.startswith("_")
        })

    evaluated_records = []
    mismatches = []
    unverifiable = []

    computed_status_counts = Counter()
    recorded_status_counts = Counter()

    # --------------------------------------
    # Evaluate each sensor record
    # --------------------------------------

    for record in sensor_records:

        record_id = (
            str(
                record.get(record_id_field, "")
            ).strip()
            if record_id_field
            else ""
        )

        zone = (
            str(
                record.get(zone_field, "")
            ).strip()
            if zone_field
            else ""
        )

        recorded_status = (
            str(
                record.get(status_field, "")
            ).strip().upper()
            if status_field
            else ""
        )

        # ----------------------------------
        # 1. Collect original sensor values
        # ----------------------------------

        observed_values = {}
        missing_measurements = []

        for expected_field in dict.fromkeys(
            sensor_field
            for sensor_field, _operator
            in THRESHOLD_SETTING_MAP.values()
        ):

            actual_field = sensor_field_lookup.get(
                expected_field
            )

            if actual_field is None:

                observed_values[expected_field] = None
                missing_measurements.append(
                    expected_field
                )

                continue

            raw_value = record.get(
                actual_field,
                "",
            )

            numeric_value = _parse_number(
                raw_value
            )

            observed_values[expected_field] = (
                numeric_value
                if numeric_value is not None
                else None
            )

            if numeric_value is None:

                if expected_field not in missing_measurements:
                    missing_measurements.append(
                        expected_field
                    )

        # ----------------------------------
        # 2. Evaluate every configured rule
        # ----------------------------------

        condition_results = []
        triggered_conditions = []

        checked_conditions = 0

        for setting_key, (
            expected_sensor_field,
            operator_code,
        ) in THRESHOLD_SETTING_MAP.items():

            entry = config.get(setting_key)

            actual_field = sensor_field_lookup.get(
                expected_sensor_field
            )

            threshold = (
                _parse_number(entry.get("value"))
                if entry
                else None
            )

            operator = (
                "<"
                if operator_code == "lt"
                else ">"
            )

            unit = (
                entry.get("unit", "")
                if entry
                else ""
            )

            # Keep each condition in the output,
            # even when it cannot be evaluated.

            if not entry:

                condition_results.append({
                    "setting": setting_key,
                    "sensor_field": expected_sensor_field,
                    "observed_value": observed_values.get(
                        expected_sensor_field
                    ),
                    "operator": operator,
                    "threshold": None,
                    "unit": "",
                    "triggered": None,
                    "evaluation_status": "missing_configuration",
                })

                continue

            if threshold is None:

                condition_results.append({
                    "setting": entry.get(
                        "setting",
                        setting_key,
                    ),
                    "sensor_field": expected_sensor_field,
                    "observed_value": observed_values.get(
                        expected_sensor_field
                    ),
                    "operator": operator,
                    "threshold": None,
                    "unit": unit,
                    "triggered": None,
                    "evaluation_status": "invalid_threshold",
                })

                continue

            if actual_field is None:

                condition_results.append({
                    "setting": entry.get(
                        "setting",
                        setting_key,
                    ),
                    "sensor_field": expected_sensor_field,
                    "observed_value": None,
                    "operator": operator,
                    "threshold": threshold,
                    "unit": unit,
                    "triggered": None,
                    "evaluation_status": "missing_sensor_field",
                })

                continue

            actual_value = _parse_number(
                record.get(actual_field, "")
            )

            if actual_value is None:

                condition_results.append({
                    "setting": entry.get(
                        "setting",
                        setting_key,
                    ),
                    "sensor_field": actual_field,
                    "observed_value": None,
                    "operator": operator,
                    "threshold": threshold,
                    "unit": unit,
                    "triggered": None,
                    "evaluation_status": "missing_measurement",
                })

                continue

            checked_conditions += 1

            is_triggered = (
                actual_value < threshold
                if operator_code == "lt"
                else actual_value > threshold
            )

            condition_result = {
                "setting": entry.get(
                    "setting",
                    setting_key,
                ),
                "sensor_field": actual_field,
                "observed_value": actual_value,
                "operator": operator,
                "threshold": threshold,
                "unit": unit,
                "triggered": is_triggered,
                "evaluation_status": "evaluated",
            }

            condition_results.append(
                condition_result
            )

            if is_triggered:

                triggered_conditions.append({
                    "setting": condition_result["setting"],
                    "sensor_field": actual_field,
                    "observed_value": actual_value,
                    "operator": operator,
                    "threshold": threshold,
                    "unit": unit,
                })

        # ----------------------------------
        # 3. Determine evaluation completeness
        # ----------------------------------

        complete_evaluation = (
            len(condition_results) == len(THRESHOLD_SETTING_MAP)
            and len(usable_rules) == len(THRESHOLD_SETTING_MAP)
            and checked_conditions == len(THRESHOLD_SETTING_MAP)
            and all(
                item["evaluation_status"] == "evaluated"
                for item in condition_results
            )
        )

        expected_status = None
        status_consistent = None

        if complete_evaluation:

            # ALERT is triggered when at least one
            # configured condition is triggered.

            expected_status = (
                alert_label
                if triggered_conditions
                else normal_label
            )

            computed_status_counts[
                expected_status
            ] += 1

            if recorded_status:

                status_consistent = (
                    recorded_status == expected_status
                )

                if status_consistent is False:

                    mismatches.append({
                        "record_id": record_id,
                        "zone": zone,
                        "recorded_status": recorded_status,
                        "computed_status": expected_status,
                        "trigger_count": len(
                            triggered_conditions
                        ),
                    })

            else:

                unverifiable.append({
                    "record_id": record_id,
                    "zone": zone,
                    "reason": "ไม่มีค่า status ใน SensorData",
                    "missing_measurements": [],
                    "checked_conditions": checked_conditions,
                    "total_conditions": len(THRESHOLD_SETTING_MAP),
                })

        else:

            unverifiable.append({
                "record_id": record_id,
                "zone": zone,
                "reason": (
                    "ข้อมูลหรือเกณฑ์ไม่ครบสำหรับตรวจสอบทุกเงื่อนไข"
                ),
                "missing_measurements": missing_measurements,
                "checked_conditions": checked_conditions,
                "total_conditions": len(THRESHOLD_SETTING_MAP),
            })

        if recorded_status:

            recorded_status_counts[
                recorded_status
            ] += 1

        # ----------------------------------
        # 4. Store complete record result
        # ----------------------------------

        evaluated_records.append({
            "record_id": record_id,
            "zone": zone,

            # Original measurements from this exact record.
            "observed_values": observed_values,

            # Recorded status from the original file.
            "recorded_status": recorded_status or None,

            # Computed status from configured thresholds.
            "expected_status": expected_status,
            "computed_status": expected_status,

            # Only conditions that triggered an alert.
            "trigger_count": len(
                triggered_conditions
            ),

            "triggered_conditions": triggered_conditions,

            # All configured conditions, including False and None.
            "condition_results": condition_results,

            "checked_conditions": checked_conditions,
            "total_conditions": len(THRESHOLD_SETTING_MAP),

            "missing_measurements": missing_measurements,

            "evaluation_complete": complete_evaluation,

            "status_consistent": status_consistent,
        })

    # --------------------------------------
    # Summary
    # --------------------------------------

    consistent_count = sum(
        1
        for item in evaluated_records
        if item["status_consistent"] is True
    )

    return {
        "available": bool(usable_rules),
        "fully_configured": (
            len(usable_rules) == len(THRESHOLD_SETTING_MAP)
            and not unavailable_rules
        ),
        "sensor_sheet": sensor_sheet_name,
        "configuration_sheet": configuration_sheet_name,

        "comparison_rule": (
            "ค่าต่ำกว่า *_min ถือว่าเข้าเงื่อนไข; "
            "ค่าสูงกว่า *_max ถือว่าเข้าเงื่อนไข; "
            "ค่าเท่าขีดจำกัดยังไม่แจ้งเตือน"
        ),

        "status_rule": (
            "ALERT เมื่อมีอย่างน้อยหนึ่งเงื่อนไขเข้าเกณฑ์; "
            "NORMAL เมื่อทุกเงื่อนไขได้รับการตรวจครบและไม่มีเงื่อนไขเข้าเกณฑ์"
        ),

        "thresholds_used": configured_thresholds,
        "unavailable_rules": unavailable_rules,

        "total_sensor_records": len(sensor_records),

        "recorded_status_counts": dict(
            recorded_status_counts
        ),

        "computed_status_counts": dict(
            computed_status_counts
        ),

        "consistent_records": consistent_count,
        "mismatch_count": len(mismatches),
        "unverifiable_count": len(unverifiable),

        "status_mismatches": mismatches,
        "unverifiable_records": unverifiable,

        "evaluated_records": evaluated_records,

        "all_verifiable_statuses_match": (
            bool(evaluated_records)
            and not mismatches
            and not unverifiable
            and consistent_count == len(evaluated_records)
        ),
    }


# ==========================================
# Main Table Analysis
# ==========================================

def _analyze_records(
    records: list[dict[str, str]],
    table_name: str,
    group_by: str | list[str] | None = None,
) -> dict:

    if _is_configuration_table(records):

        return _analyze_configuration_records(
            records,
            table_name,
        )

    if not records:

        return {
            "table": table_name,
            "total_rows": 0,
            "status_counts": {},
            "numeric_summary": {},
            "alerts": [],
            "duplicate_records": [],
            "duplicate_record_count": 0,
            "empty_fields": {},
            "group_analysis": {},
        }

    status_field = _find_field_name(
        records,
        STATUS_FIELD_ALIASES,
    )

    record_id_field = _find_field_name(
        records,
        RECORD_ID_FIELD_ALIASES,
    )

    status_counts = Counter()
    alerts = []
    record_id_counts = Counter()
    empty_fields = Counter()

    for record in records:

        for key, value in record.items():

            if value == "":
                empty_fields[key] += 1

        status = (
            str(
                record.get(status_field, "")
            ).strip().upper()
            if status_field
            else ""
        )

        if status:
            status_counts[status] += 1

        if status == "ALERT":
            alerts.append(record)

        record_id = (
            str(
                record.get(record_id_field, "")
            ).strip()
            if record_id_field
            else ""
        )

        if record_id:
            record_id_counts[record_id] += 1

    duplicate_records = sorted(
        record_id
        for record_id, count in record_id_counts.items()
        if count > 1
    )

    group_fields = _detect_group_fields(
        records,
        group_by,
    )

    return {
        "table": table_name,
        "total_rows": len(records),
        "status_counts": dict(status_counts),
        "numeric_summary": _get_numeric_summary(
            records
        ),
        "alerts": alerts,
        "duplicate_records": duplicate_records,
        "duplicate_record_count": sum(
            count - 1
            for count in record_id_counts.values()
            if count > 1
        ),
        "empty_fields": dict(empty_fields),
        "group_analysis": _build_group_analysis(
            records,
            group_fields,
            status_field,
            record_id_field,
        ),
    }


# ==========================================
# Main Analysis Function
# ==========================================

def analyze_tabular_file(
    source: str,
    requested_sheet: str | None = None,
    group_by: str | list[str] | None = None,
) -> dict:

    """Analyze CSV/XLSX, including cross-sheet threshold validation."""

    path = _load_file_path(source)

    # --------------------------------------
    # CSV
    # --------------------------------------

    if path.suffix.lower() == ".csv":

        records = _read_csv(path)

        return {
            "source": source,
            "file_type": "CSV",
            "analysis": _analyze_records(
                records,
                path.name,
                group_by=group_by,
            ),
        }

    # --------------------------------------
    # XLSX
    # --------------------------------------

    all_sheets = _read_xlsx(path)

    selected_sheets = all_sheets

    if requested_sheet:

        matched_sheet = next(
            (
                sheet_name
                for sheet_name in all_sheets
                if sheet_name.casefold()
                == requested_sheet.casefold()
            ),
            None,
        )

        if matched_sheet is None:

            available = (
                ", ".join(all_sheets.keys())
                or "ไม่มี Sheet ที่มีข้อมูล"
            )

            raise TabularAnalysisError(
                f"ไม่พบ Sheet: {requested_sheet} "
                f"(Sheet ที่พบ: {available})"
            )

        selected_sheets = {
            matched_sheet: all_sheets[matched_sheet]
        }

    analysis = {
        sheet_name: _analyze_records(
            records,
            sheet_name,
            group_by=group_by,
        )
        for sheet_name, records in selected_sheets.items()
    }

    result = {
        "source": source,
        "file_type": "XLSX",
        "analysis": analysis,
    }

    # --------------------------------------
    # Cross-Sheet Detection
    # --------------------------------------

    sensor_sheet = _find_sensor_sheet(
        all_sheets
    )

    configuration_sheet = _find_configuration_sheet(
        all_sheets
    )

    if sensor_sheet and configuration_sheet:

        result["cross_sheet_analysis"] = (
            _evaluate_configuration_against_sensors(
                sensor_records=all_sheets[sensor_sheet],
                configuration_records=all_sheets[configuration_sheet],
                sensor_sheet_name=sensor_sheet,
                configuration_sheet_name=configuration_sheet,
            )
        )

    return result


# ==========================================
# Context Formatter
# ==========================================

def format_analysis_context(
    result: dict,
) -> str:

    """Format verified Python results for the language model."""

    instructions = [
        "PYTHON VERIFIED DATA ANALYSIS:",
        "The following statistics were calculated from the original file.",
        "Do not change, invent, or estimate numerical results.",
        "For Configuration tables, values may have different units; do not calculate a combined average.",
        "For cross_sheet_analysis, use evaluated_records and condition_results as the source of truth.",
        "Each observed_values object belongs only to its own Record ID.",
        "Never transfer sensor values between different records.",
        "condition_results includes both triggered and non-triggered conditions.",
        "triggered=true means the condition was triggered.",
        "triggered=false means the condition was evaluated and was not triggered.",
        "triggered=null means the condition could not be evaluated.",
        "Do not describe a missing measurement when observed_values contains an actual value.",
        "Do not claim a status is consistent when status_consistent is null or unverifiable.",
        "Use computed_status as the calculated status and recorded_status as the original stored status.",
        "The threshold comparison uses strict less-than for *_min and strict greater-than for *_max.",
        "A value exactly equal to a threshold does not trigger an alert under these rules.",
        "ALERT means at least one configured condition was triggered.",
        "These comparison rules are interpretations of the configuration names, not proof of the device firmware implementation.",
        "\n",
    ]

    return "\n".join(instructions) + json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
