"""Persist test cases to data/eval_cases.json."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from datetime import datetime

from .schema import AnyCase, parse_case

# Resolve path: app/evaluation/store.py → repo root → data/eval_cases.json
_REPO_ROOT = Path(__file__).parent.parent.parent
DATA_FILE = _REPO_ROOT / "data" / "eval_cases.json"

# ---------------------------------------------------------------------------
# Seed cases written on first run
# ---------------------------------------------------------------------------
_SEED_CASES: list[dict] = [
    {
        "id": "seed-001",
        "name": "Count accounts by sector",
        "test_type": "golden_sql",
        "question": "How many accounts are in each sector?",
        "enabled": True,
        "tags": ["accounts", "aggregation"],
        "created_at": "2026-03-17T00:00:00",
        "expected_sql": "SELECT sector, COUNT(*) as count FROM accounts GROUP BY sector ORDER BY count DESC",
    },
    {
        "id": "seed-002",
        "name": "Technology sector accounts",
        "test_type": "golden_sql",
        "question": "Show me all accounts in the technology sector",
        "enabled": True,
        "tags": ["accounts", "filter"],
        "created_at": "2026-03-17T00:00:00",
        "expected_sql": "SELECT account_id, account, revenue FROM accounts WHERE sector = 'technolgy'",
    },
    {
        "id": "seed-003",
        "name": "Open engaging deals",
        "test_type": "golden_sql",
        "question": "Show me all deals currently in the Engaging stage",
        "enabled": True,
        "tags": ["pipeline", "filter"],
        "created_at": "2026-03-17T00:00:00",
        "expected_sql": "SELECT * FROM v_pipeline_snapshot WHERE deal_stage = 'Engaging'",
    },
    {
        "id": "seed-004",
        "name": "GTX Basic price",
        "test_type": "golden_sql",
        "question": "What is the price of GTX Basic?",
        "enabled": True,
        "tags": ["products"],
        "created_at": "2026-03-17T00:00:00",
        "expected_sql": "SELECT product, sales_price FROM products WHERE product = 'GTX Basic'",
    },
    {
        "id": "seed-005",
        "name": "Pipeline snapshot performance",
        "test_type": "golden_sql_perf",
        "question": "Show me the full pipeline snapshot",
        "enabled": True,
        "tags": ["pipeline", "performance"],
        "created_at": "2026-03-17T00:00:00",
        "expected_sql": "SELECT * FROM v_pipeline_snapshot",
        "max_exec_ms": 2000,
        "expected_row_count": None,
    },
    {
        "id": "seed-006",
        "name": "Accounts summary performance",
        "test_type": "golden_sql_perf",
        "question": "Show me the accounts summary",
        "enabled": True,
        "tags": ["accounts", "performance"],
        "created_at": "2026-03-17T00:00:00",
        "expected_sql": "SELECT * FROM v_accounts_summary",
        "max_exec_ms": 3000,
        "expected_row_count": None,
    },
    {
        "id": "seed-007",
        "name": "Agent redirects off-topic",
        "test_type": "conversational",
        "question": "What is the weather like today?",
        "enabled": True,
        "tags": ["safety", "off-topic"],
        "created_at": "2026-03-17T00:00:00",
        "expected_answer_contains": ["sales", "data"],
        "expected_answer_excludes": ["sunny", "temperature", "forecast"],
    },
    {
        "id": "seed-008",
        "name": "Open work today",
        "test_type": "conversational",
        "question": "What should I work on today?",
        "enabled": True,
        "tags": ["open-work"],
        "created_at": "2026-03-17T00:00:00",
        "expected_answer_contains": ["Engaging", "account"],
        "expected_answer_excludes": [],
    },
    {
        "id": "seed-009",
        "name": "Deal stage explanation",
        "test_type": "conversational",
        "question": "What do the deal stages mean?",
        "enabled": True,
        "tags": ["pipeline", "explanation"],
        "created_at": "2026-03-17T00:00:00",
        "expected_answer_contains": ["Prospecting", "Engaging", "Won", "Lost"],
        "expected_answer_excludes": [],
    },
]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def load_cases() -> list[AnyCase]:
    """Load all test cases from disk. Seeds the file if it doesn't exist."""
    if not DATA_FILE.exists():
        cases = [parse_case(d) for d in _SEED_CASES]
        save_cases(cases)
        return cases
    with open(DATA_FILE, "r") as f:
        raw = json.load(f)
    return [parse_case(d) for d in raw]


def save_cases(cases: list[AnyCase]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump([c.model_dump() for c in cases], f, indent=2)


def add_case(case: AnyCase) -> None:
    cases = load_cases()
    cases.append(case)
    save_cases(cases)


def update_case(updated: AnyCase) -> None:
    cases = load_cases()
    cases = [updated if c.id == updated.id else c for c in cases]
    save_cases(cases)


def delete_case(case_id: str) -> None:
    cases = load_cases()
    cases = [c for c in cases if c.id != case_id]
    save_cases(cases)


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "name", "test_type", "question",
    "expected_sql",
    "expected_answer_contains",  # semicolon-separated
    "expected_answer_excludes",  # semicolon-separated
    "max_exec_ms",
    "expected_row_count",
    "tags",  # semicolon-separated
    "enabled",
]


def get_csv_template() -> pd.DataFrame:
    return pd.DataFrame(columns=_CSV_COLUMNS)


def import_from_csv(df: pd.DataFrame) -> tuple[int, list[str]]:
    """Import test cases from a DataFrame. Returns (imported_count, error_list)."""
    imported = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + 2  # 1-based + header row
        try:
            test_type = str(row.get("test_type", "")).strip()
            if test_type not in ("conversational", "golden_sql", "golden_sql_perf"):
                errors.append(f"Row {row_num}: invalid test_type {test_type!r}")
                continue

            name = str(row.get("name", "")).strip()
            question = str(row.get("question", "")).strip()
            if not name or not question:
                errors.append(f"Row {row_num}: missing required field 'name' or 'question'")
                continue

            def split_semi(val: str) -> list[str]:
                return [s.strip() for s in str(val).split(";") if s.strip()] if pd.notna(val) and str(val).strip() else []

            tags = split_semi(row.get("tags", ""))
            enabled_raw = row.get("enabled", True)
            enabled = str(enabled_raw).strip().lower() not in ("false", "0", "no") if pd.notna(enabled_raw) else True

            base = dict(name=name, test_type=test_type, question=question, tags=tags, enabled=enabled)

            if test_type == "conversational":
                contains = split_semi(row.get("expected_answer_contains", ""))
                if not contains:
                    errors.append(f"Row {row_num}: conversational case requires 'expected_answer_contains'")
                    continue
                case = parse_case({**base, "expected_answer_contains": contains,
                                   "expected_answer_excludes": split_semi(row.get("expected_answer_excludes", ""))})
            elif test_type == "golden_sql":
                sql = str(row.get("expected_sql", "")).strip()
                if not sql:
                    errors.append(f"Row {row_num}: golden_sql requires 'expected_sql'")
                    continue
                case = parse_case({**base, "expected_sql": sql})
            else:  # golden_sql_perf
                sql = str(row.get("expected_sql", "")).strip()
                raw_ms = row.get("max_exec_ms")
                if not sql or pd.isna(raw_ms):
                    errors.append(f"Row {row_num}: golden_sql_perf requires 'expected_sql' and 'max_exec_ms'")
                    continue
                row_count_raw = row.get("expected_row_count")
                row_count = int(row_count_raw) if pd.notna(row_count_raw) and str(row_count_raw).strip() else None
                case = parse_case({**base, "expected_sql": sql, "max_exec_ms": int(raw_ms),
                                   "expected_row_count": row_count})

            add_case(case)
            imported += 1
        except Exception as e:
            errors.append(f"Row {row_num}: {e}")

    return imported, errors
