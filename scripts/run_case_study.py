"""Run every query in sql/analysis/ and write the questions, SQL and results to docs/sql_case_study.md.

Run the pipeline first:  python run_pipeline.py && python scripts/run_case_study.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import PipelineConfig  # noqa: E402

QUERY_DIR = ROOT / "sql" / "analysis"


def parse_query(path: Path) -> tuple[str, str]:
    """Return (question, sql) from a query file whose first comment line starts with '-- Question:'."""
    text = path.read_text(encoding="utf-8")
    question = next(line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("-- Question:"))
    return question, text.strip()


def run_queries(db_path: Path) -> list[tuple[str, str, str, pd.DataFrame]]:
    results = []
    with sqlite3.connect(db_path) as conn:
        for path in sorted(QUERY_DIR.glob("q*.sql")):
            question, sql = parse_query(path)
            results.append((path.name, question, sql, pd.read_sql_query(sql, conn)))
    return results


def to_markdown(df: pd.DataFrame) -> str:
    """Small markdown table writer (avoids the optional `tabulate` dependency)."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in df.itertuples(index=False):
        cells = [f"{v:,.0f}" if isinstance(v, float) and abs(v) >= 1000 else ("" if pd.isna(v) else str(v)) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    results = run_queries(PipelineConfig().db_path)
    out = ["# SQL case study: business questions and answers", "",
           "Each question is answered by one query in [`sql/analysis/`](../sql/analysis). "
           "Results come from the default run (`python run_pipeline.py`, seed 42). "
           "Regenerate this file with `python scripts/run_case_study.py`.", ""]
    for i, (name, question, _, _) in enumerate(results, 1):
        out.append(f"{i}. [{question}](#q{i})")
    out.append("")
    for i, (name, question, sql, df) in enumerate(results, 1):
        out += [f"## <a id=\"q{i}\"></a>{i}. {question}", "", f"[`{name}`](../sql/analysis/{name})", "",
                "<details><summary>Show SQL</summary>", "", "```sql", sql, "```", "", "</details>", "",
                to_markdown(df), ""]
    path = ROOT / "docs" / "sql_case_study.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)} ({len(results)} queries)")


if __name__ == "__main__":
    main()
