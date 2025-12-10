#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from src.excel_analysis import ExcelAnalyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze an Excel workbook and emit a structured schema summary.")
    parser.add_argument("workbook", help="Path to the Excel workbook (.xlsx) to analyze.")
    parser.add_argument("--db-agent-version", default="0.1.0", help="Version identifier to embed in the analysis output.")
    parser.add_argument("--sample-values", type=int, default=20, help="Maximum number of sample values per column.")
    parser.add_argument("--enum-threshold", type=int, default=8, help="Distinct value threshold to consider a column an enum.")
    parser.add_argument("--output", help="Optional path to save the JSON output.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON with indentation.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyzer = ExcelAnalyzer(
        db_agent_version=args.db_agent_version,
        sample_values=args.sample_values,
        enum_threshold=args.enum_threshold,
    )

    try:
        analysis = analyzer.analyze_workbook(args.workbook)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None
    json_output = json.dumps(analysis, indent=indent)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json_output + ("\n" if not json_output.endswith("\n") else ""), encoding="utf-8")
    else:
        print(json_output)


if __name__ == "__main__":
    main()
