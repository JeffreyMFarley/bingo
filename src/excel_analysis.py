from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet
import random


Value = Any


class ExcelAnalyzer:
    """Analyze Excel workbooks and emit structured metadata."""

    def __init__(self, db_agent_version: str = "0.1.0", sample_values: int = 3, enum_threshold: int = 8):
        self.db_agent_version = db_agent_version
        self.sample_values = sample_values
        self.enum_threshold = enum_threshold

    def analyze_workbook(self, workbook_path: str | Path) -> Dict[str, Any]:
        path = Path(workbook_path)
        if not path.exists():
            raise FileNotFoundError(f"Workbook not found: {path}")

        wb = load_workbook(filename=path, data_only=True, read_only=False)

        sheet_reports: List[Dict[str, Any]] = []
        table_profiles: List[Dict[str, Any]] = []

        for idx, sheet in enumerate(wb.worksheets):
            tables = self._extract_tables(sheet, sheet_index=idx)
            sheet_reports.append(
                {
                    "sheet_name": sheet.title,
                    "sheet_index": idx,
                    "detected_tables": [self._table_summary(t) for t in tables],
                    "non_tabular_regions": [],
                }
            )
            table_profiles.extend(tables)

        wb.close()

        foreign_key_lookup = self._detect_foreign_keys(table_profiles)
        warnings: List[Dict[str, Any]] = []
        table_reports: List[Dict[str, Any]] = []

        for table in table_profiles:
            columns_for_report: List[Dict[str, Any]] = []
            for column in table["columns"]:
                public_column = {k: v for k, v in column.items() if not k.startswith("_")}
                columns_for_report.append(public_column)

            primary_key = self._detect_primary_key(table)
            natural_keys = self._detect_natural_keys(table)
            indexes = self._suggest_indexes(table, foreign_key_lookup)
            foreign_keys = foreign_key_lookup.get(table["table_name"], [])

            warnings.extend(table["warnings"])

            table_reports.append(
                {
                    "table_name": table["table_name"],
                    "sheet_name": table["sheet_name"],
                    "range": table["range"],
                    "primary_key": primary_key,
                    "natural_keys": natural_keys,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
                    "columns": columns_for_report,
                }
            )

        analysis = {
            "workbook_name": path.name,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "db_agent_version": self.db_agent_version,
            "sheets": sheet_reports,
            "tables": table_reports,
            "warnings": warnings,
        }
        return analysis

    # ----- table extraction -------------------------------------------------

    def _extract_tables(self, sheet: Worksheet, sheet_index: int) -> List[Dict[str, Any]]:
        tables: List[Dict[str, Any]] = []
        table_counter = 1
        existing_ranges: List[str] = []

        if sheet.tables:
            for defined_table in sheet.tables.values():
                table = self._build_table_from_range(
                    sheet=sheet,
                    sheet_index=sheet_index,
                    ref=defined_table.ref,
                    table_name=defined_table.displayName or f"{sheet.title}_Table{table_counter}",
                    confidence=0.98,
                    notes=[f"Excel table '{defined_table.displayName}' detected"],
                )
                if table:
                    tables.append(table)
                    existing_ranges.append(table["range"])
                    table_counter += 1

        inferred_ranges = self._infer_table_ranges(sheet)
        for ref in inferred_ranges:
            if any(self._ranges_overlap(ref, existing) for existing in existing_ranges):
                continue
            table = self._build_table_from_range(
                sheet=sheet,
                sheet_index=sheet_index,
                ref=ref,
                table_name=f"{sheet.title}_Table{table_counter}",
                confidence=0.8,
                notes=[f"Contiguous data block detected at {ref}"],
            )
            if table:
                tables.append(table)
                table_counter += 1

        return tables

    def _build_table_from_range(
        self,
        sheet: Worksheet,
        sheet_index: int,
        ref: str,
        table_name: str,
        confidence: float,
        notes: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
        total_rows = max_row - min_row + 1
        if total_rows < 2:
            return None

        values = [
            list(row)
            for row in sheet.iter_rows(
                min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True
            )
        ]
        header = values[0]
        data_rows = values[1:]

        if not any(self._has_cell_value(v) for v in header):
            return None

        normalized_headers = self._normalize_header_row(header)
        row_count = len(data_rows)
        column_count = len(normalized_headers)
        data_start_row = min_row + 1

        table = {
            "table_name": table_name,
            "sheet_name": sheet.title,
            "sheet_index": sheet_index,
            "range": ref,
            "header_row": min_row,
            "data_start_row": data_start_row,
            "row_count": row_count,
            "column_count": column_count,
            "confidence": round(confidence, 2),
            "notes": (notes or []) + [f"Header row detected at row {min_row}"],
            "columns": [],
            "warnings": [],
        }

        for idx, header_value in enumerate(normalized_headers):
            column_letter = get_column_letter(min_col + idx)
            col_values = [row[idx] if idx < len(row) else None for row in data_rows]
            column_profile = self._profile_column(
                column_name=header_value,
                excel_column=column_letter,
                values=col_values,
                data_start_row=data_start_row,
                row_count=row_count,
                sheet_name=sheet.title,
                table_name=table_name,
            )
            table["columns"].append(column_profile)
            table["warnings"].extend(self._column_warnings(table_name, header_value, column_profile))

        return table

    def _infer_table_ranges(self, sheet: Worksheet) -> List[str]:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []

        blocks: List[Dict[str, int]] = []
        current_block: Optional[Dict[str, int]] = None

        for idx, row in enumerate(rows, start=1):
            columns_with_values = [i for i, value in enumerate(row, start=1) if self._has_cell_value(value)]
            if columns_with_values:
                min_col = min(columns_with_values)
                max_col = max(columns_with_values)
                if current_block is None:
                    current_block = {"start": idx, "end": idx, "min_col": min_col, "max_col": max_col}
                else:
                    current_block["end"] = idx
                    current_block["min_col"] = min(current_block["min_col"], min_col)
                    current_block["max_col"] = max(current_block["max_col"], max_col)
            else:
                if current_block:
                    blocks.append(current_block)
                    current_block = None

        if current_block:
            blocks.append(current_block)

        ranges: List[str] = []
        for block in blocks:
            if block["end"] - block["start"] < 1:
                continue
            start_col_letter = get_column_letter(block["min_col"])
            end_col_letter = get_column_letter(block["max_col"])
            ranges.append(f"{start_col_letter}{block['start']}:{end_col_letter}{block['end']}")

        return ranges

    # ----- column analysis --------------------------------------------------

    def _profile_column(
        self,
        column_name: str,
        excel_column: str,
        values: Sequence[Value],
        data_start_row: int,
        row_count: int,
        sheet_name: str,
        table_name: str,
    ) -> Dict[str, Any]:
        non_null_values = [v for v in values if self._has_cell_value(v)]
        normalized_values = [self._normalize_value(v) for v in non_null_values if self._normalize_value(v) is not None]
        unique_values = set(normalized_values)
        nullable = len(non_null_values) != len(values)
        unique_ratio = (len(unique_values) / len(non_null_values)) if non_null_values else 0.0

        data_type = self._infer_data_type(column_name, non_null_values, unique_values)
        inferred_constraints = self._infer_constraints(data_type, non_null_values, unique_values, column_name)

        sample_values = random.sample(non_null_values, min(self.sample_values, len(non_null_values)))
        sample_values = [self._stringify_value(v) for v in sample_values]
        source_cells = (
            f"{excel_column}{data_start_row}:{excel_column}{data_start_row + row_count - 1}"
            if row_count > 0
            else f"{excel_column}{data_start_row}"
        )

        profile = {
            "column_name": column_name,
            "excel_column": excel_column,
            "data_type": data_type,
            "nullable": nullable,
            "inferred_constraints": inferred_constraints,
            "sample_values": sample_values,
            "description": f"Column '{column_name}' from table '{table_name}' on sheet '{sheet_name}'.",
            "source_cells": source_cells,
            "_stats": {
                "non_null_count": len(non_null_values),
                "total_count": len(values),
                "unique_values": unique_values,
                "unique_ratio": unique_ratio,
                "enum_candidate": data_type == "enum" or len(unique_values) <= min(self.enum_threshold, max(1, len(non_null_values))),
                "is_numeric": data_type in {"integer", "decimal", "currency"},
                "is_text": data_type in {"string", "enum"},
                "is_date": data_type == "date",
                "nullable": nullable,
                "normalized_values": unique_values,
            },
        }
        return profile

    def _infer_data_type(self, column_name: str, values: Sequence[Value], unique_values: Iterable[str]) -> str:
        if not values:
            return "string"

        header = column_name.lower()
        if all(isinstance(v, bool) for v in values):
            return "boolean"

        if all(self._is_date_like(v) for v in values):
            return "date"

        if all(self._is_numeric_like(v) for v in values):
            if all(self._is_integer_like(v) for v in values):
                return "integer"
            if any(keyword in header for keyword in ("amount", "total", "subtotal", "price", "cost", "tax")):
                return "currency"
            return "decimal"

        if self._looks_like_enum(header, values, unique_values):
            return "enum"

        return "string"

    def _infer_constraints(
        self,
        data_type: str,
        values: Sequence[Value],
        unique_values: Iterable[str],
        column_name: str,
    ) -> Dict[str, Any]:
        constraints: Dict[str, Any] = {}
        unique = len(values) > 0 and len(set(unique_values)) == len(values)

        if data_type in {"integer", "decimal", "currency"}:
            numeric_values = [self._to_number(v) for v in values if self._to_number(v) is not None]
            if numeric_values:
                constraints["min"] = min(numeric_values)
                constraints["max"] = max(numeric_values)
        elif data_type == "date":
            date_values = [self._to_date(v) for v in values if self._to_date(v) is not None]
            if date_values:
                constraints["min"] = min(date_values).isoformat()
                constraints["max"] = max(date_values).isoformat()
        elif data_type == "string":
            lengths = [len(str(v)) for v in values]
            if lengths:
                constraints["max_length"] = max(lengths)
            if any(self._looks_like_email(str(v)) for v in values):
                constraints["pattern"] = "email"
        elif data_type == "enum":
            samples = sorted({self._stringify_value(v) for v in values})
            constraints["allowed_values"] = samples[:15]

        if unique:
            constraints["unique"] = True

        return constraints

    def _column_warnings(self, table_name: str, column_name: str, column_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        stats = column_profile["_stats"]
        warnings: List[Dict[str, Any]] = []
        if stats["enum_candidate"] and stats["non_null_count"] > 0:
            warnings.append(
                {
                    "code": "ENUM_GUESS",
                    "severity": "info",
                    "message": f"Column '{column_name}' appears to contain a small set of values.",
                    "table": table_name,
                    "column": column_name,
                    "examples": column_profile["sample_values"],
                }
            )
        return warnings

    # ----- key detection ----------------------------------------------------

    def _detect_primary_key(self, table: Dict[str, Any]) -> Dict[str, Any]:
        best_candidate: Optional[Tuple[Dict[str, Any], float]] = None
        for column in table["columns"]:
            stats = column["_stats"]
            if stats["non_null_count"] == 0:
                continue
            if stats["unique_ratio"] < 0.95 or stats["nullable"]:
                continue

            confidence = stats["unique_ratio"]
            if "id" in column["column_name"].lower():
                confidence += 0.05
            if stats["is_numeric"]:
                confidence += 0.02

            confidence = min(confidence, 0.99)
            if best_candidate is None or confidence > best_candidate[1]:
                best_candidate = (column, confidence)

        if best_candidate:
            column, confidence = best_candidate
            return {
                "columns": [column["column_name"]],
                "confidence": round(confidence, 2),
                "strategy": "unique_values",
            }

        return {"columns": [], "confidence": 0.0, "strategy": "not_detected"}

    def _detect_natural_keys(self, table: Dict[str, Any]) -> List[Dict[str, Any]]:
        natural_keys: List[Dict[str, Any]] = []
        for column in table["columns"]:
            stats = column["_stats"]
            if stats["non_null_count"] == 0:
                continue
            if stats["unique_ratio"] >= 0.85 and column["data_type"] in {"string", "enum"}:
                natural_keys.append(
                    {
                        "columns": [column["column_name"]],
                        "confidence": round(stats["unique_ratio"], 2),
                        "strategy": "unique_values",
                    }
                )
        return natural_keys

    def _detect_foreign_keys(self, tables: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        fk_map: Dict[str, List[Dict[str, Any]]] = {table["table_name"]: [] for table in tables}

        for table in tables:
            for column in table["columns"]:
                stats = column["_stats"]
                if stats["non_null_count"] == 0:
                    continue
                normalized_values = stats["normalized_values"]
                if not normalized_values:
                    continue

                for target_table in tables:
                    if target_table is table:
                        continue
                    for target_column in target_table["columns"]:
                        target_stats = target_column["_stats"]
                        if target_stats["non_null_count"] == 0:
                            continue
                        overlap = normalized_values.intersection(target_stats["normalized_values"])
                        if not overlap:
                            continue
                        overlap_ratio = len(overlap) / max(1, len(normalized_values))
                        name_score = self._foreign_key_name_score(column["column_name"], target_column["column_name"], target_table["table_name"])
                        if overlap_ratio < 0.5 and name_score < 0.6:
                            continue
                        confidence = min(0.99, 0.5 * overlap_ratio + 0.5 * name_score)
                        fk_map[table["table_name"]].append(
                            {
                                "columns": [column["column_name"]],
                                "references_table": target_table["table_name"],
                                "references_columns": [target_column["column_name"]],
                                "confidence": round(confidence, 2),
                                "strategy": "name_similarity_and_value_overlap",
                            }
                        )
        return fk_map

    def _foreign_key_name_score(self, column_name: str, target_column_name: str, target_table_name: str) -> float:
        cname = column_name.lower()
        target = target_column_name.lower()
        table = target_table_name.lower()

        if cname == target:
            return 0.9
        if cname.endswith("id"):
            prefix = cname[:-2]
            if prefix == table or prefix == target.rstrip("id"):
                return 0.85
        if cname.startswith(table):
            return 0.7
        if cname == f"{table}_id":
            return 0.9
        if cname == f"{target}_id":
            return 0.85
        return 0.4 if target in cname or table in cname else 0.2

    def _suggest_indexes(self, table: Dict[str, Any], fk_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        fk_columns = {tuple(fk["columns"]) for fk in fk_map.get(table["table_name"], [])}

        for fk in fk_map.get(table["table_name"], []):
            suggestions.append(
                {
                    "columns": fk["columns"],
                    "reason": "foreign key candidate",
                    "confidence": fk["confidence"],
                }
            )

        date_columns = [col["column_name"] for col in table["columns"] if col["data_type"] == "date"]
        for column_name in date_columns:
            suggestions.append(
                {
                    "columns": [column_name],
                    "reason": "date column useful for sorting/filtering",
                    "confidence": 0.7,
                }
            )

        name_columns = [col["column_name"] for col in table["columns"] if "name" in col["column_name"].lower()]
        if len(name_columns) >= 2:
            pair = name_columns[:2]
            if tuple(pair) not in fk_columns:
                suggestions.append(
                    {
                        "columns": pair,
                        "reason": "text columns likely involved in searches",
                        "confidence": 0.65,
                    }
                )

        return suggestions

    # ----- helpers ----------------------------------------------------------

    def _table_summary(self, table: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "table_name": table["table_name"],
            "range": table["range"],
            "header_row": table["header_row"],
            "data_start_row": table["data_start_row"],
            "row_count": table["row_count"],
            "column_count": table["column_count"],
            "confidence": table["confidence"],
            "notes": table["notes"],
        }

    def _ranges_overlap(self, ref_a: str, ref_b: str) -> bool:
        min_col_a, min_row_a, max_col_a, max_row_a = range_boundaries(ref_a)
        min_col_b, min_row_b, max_col_b, max_row_b = range_boundaries(ref_b)
        rows_overlap = not (max_row_a < min_row_b or min_row_a > max_row_b)
        cols_overlap = not (max_col_a < min_col_b or min_col_a > max_col_b)
        return rows_overlap and cols_overlap

    def _normalize_header_row(self, header: Sequence[Value]) -> List[str]:
        normalized: List[str] = []
        seen: Dict[str, int] = {}
        for idx, value in enumerate(header, start=1):
            text = str(value).strip() if self._has_cell_value(value) else ""
            if not text:
                text = f"Column{idx}"
            key = text.lower()
            if key in seen:
                seen[key] += 1
                text = f"{text}_{seen[key]}"
            else:
                seen[key] = 1
            normalized.append(text)
        return normalized

    def _has_cell_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    def _normalize_value(self, value: Value) -> Optional[str]:
        if not self._has_cell_value(value):
            return None
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, float):
            if math.isfinite(value) and value.is_integer():
                return str(int(value))
            return f"{value}"
        return str(value).strip()

    def _stringify_value(self, value: Value) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return "" if value is None else str(value)

    def _is_numeric_like(self, value: Value) -> bool:
        if isinstance(value, (int, float)) and math.isfinite(value):
            return True
        if isinstance(value, str):
            stripped = value.replace(",", "").strip()
            if not stripped:
                return False
            try:
                float(stripped)
                return True
            except ValueError:
                return False
        return False

    def _is_integer_like(self, value: Value) -> bool:
        if isinstance(value, int):
            return True
        if isinstance(value, float) and value.is_integer():
            return True
        if isinstance(value, str):
            stripped = value.strip().replace(",", "")
            return stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit())
        return False

    def _looks_like_enum(self, header: str, values: Sequence[Value], unique_values: Iterable[str]) -> bool:
        if any(keyword in header for keyword in ("status", "type", "category", "state")):
            return True
        unique_count = len(set(unique_values))
        return unique_count <= min(self.enum_threshold, max(1, len(values)))

    def _looks_like_email(self, value: str) -> bool:
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value))

    def _is_date_like(self, value: Value) -> bool:
        if isinstance(value, (datetime, date)):
            return True
        if isinstance(value, str):
            try:
                datetime.fromisoformat(value)
                return True
            except ValueError:
                return bool(re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", value.strip()))
        return False

    def _to_number(self, value: Value) -> Optional[float]:
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
        if isinstance(value, str):
            stripped = value.replace(",", "").strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    def _to_date(self, value: Value) -> Optional[date]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
                return parsed.date()
            except ValueError:
                match = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})$", value.strip())
                if match:
                    year, month, day = map(int, match.groups())
                    return date(year, month, day)
        return None
