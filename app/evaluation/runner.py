"""Execute test cases and score results."""
from __future__ import annotations
import json
import time
from datetime import datetime
from typing import Any

import pandas as pd

from .schema import AnyCase, ConversationalCase, GoldenSqlCase, GoldenSqlPerfCase


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Sort columns and rows for consistent comparison."""
    df = df.copy()
    df = df[sorted(df.columns)]
    df = df.astype(str)
    df = df.sort_values(by=list(df.columns)).reset_index(drop=True)
    return df


def _run_golden_sql(case: GoldenSqlCase | GoldenSqlPerfCase) -> dict[str, Any]:
    from agent.text_to_sql import generate_sql_with_retry
    from database import db_query

    result: dict[str, Any] = {
        "case_id": case.id,
        "name": case.name,
        "test_type": case.test_type,
        "question": case.question,
        "verdict": "ERROR",
        "generated_sql": None,
        "expected_sql": case.expected_sql,
        "actual_row_count": None,
        "expected_row_count": None,
        "exec_ms": None,
        "max_exec_ms": getattr(case, "max_exec_ms", None),
        "actual_answer": None,
        "llm_score": None,
        "llm_reasoning": None,
        "error_message": None,
        "ran_at": datetime.now().isoformat(),
    }

    # Execute expected SQL first — if this fails the test case is broken
    try:
        expected_df = db_query(case.expected_sql)
    except Exception as e:
        result["error_message"] = f"Expected SQL failed: {e}"
        return result

    result["expected_row_count"] = len(expected_df)

    # Generate SQL from natural language
    generated_sql, gen_error = generate_sql_with_retry(case.question)
    result["generated_sql"] = generated_sql

    if gen_error:
        result["verdict"] = "FAIL"
        result["error_message"] = f"SQL generation failed: {gen_error}"
        return result

    # Execute generated SQL and time it
    try:
        t0 = time.perf_counter()
        actual_df = db_query(generated_sql)
        exec_ms = (time.perf_counter() - t0) * 1000
    except Exception as e:
        result["verdict"] = "FAIL"
        result["error_message"] = f"Generated SQL execution failed: {e}"
        return result

    result["actual_row_count"] = len(actual_df)
    result["exec_ms"] = round(exec_ms, 1)

    # Compare result sets
    try:
        match = _normalize_df(expected_df).equals(_normalize_df(actual_df))
    except Exception as e:
        result["verdict"] = "ERROR"
        result["error_message"] = f"DataFrame comparison failed: {e}"
        return result

    if not match:
        result["verdict"] = "FAIL"
        result["error_message"] = (
            f"Result mismatch: expected {len(expected_df)} rows, got {len(actual_df)} rows"
        )
        return result

    # Performance check (golden_sql_perf only)
    if isinstance(case, GoldenSqlPerfCase):
        if exec_ms > case.max_exec_ms:
            result["verdict"] = "FAIL_PERF"
            result["error_message"] = f"Execution too slow: {exec_ms:.0f}ms > {case.max_exec_ms}ms limit"
            return result
        if case.expected_row_count is not None and len(actual_df) != case.expected_row_count:
            result["verdict"] = "FAIL"
            result["error_message"] = (
                f"Row count mismatch: expected {case.expected_row_count}, got {len(actual_df)}"
            )
            return result

    result["verdict"] = "PASS"
    return result


def _run_conversational(case: ConversationalCase) -> dict[str, Any]:
    import streamlit as st
    from agent.core import agent_answer
    from openai import OpenAI

    result: dict[str, Any] = {
        "case_id": case.id,
        "name": case.name,
        "test_type": case.test_type,
        "question": case.question,
        "verdict": "ERROR",
        "generated_sql": None,
        "expected_sql": None,
        "actual_row_count": None,
        "expected_row_count": None,
        "exec_ms": None,
        "max_exec_ms": None,
        "actual_answer": None,
        "llm_score": None,
        "llm_reasoning": None,
        "error_message": None,
        "ran_at": datetime.now().isoformat(),
    }

    try:
        actual_answer = agent_answer(case.question)
    except Exception as e:
        result["error_message"] = f"agent_answer failed: {e}"
        return result

    result["actual_answer"] = actual_answer
    actual_lower = actual_answer.lower()

    # Fast pre-check: all required phrases present and no excluded phrases
    contains_ok = all(p.lower() in actual_lower for p in case.expected_answer_contains)
    excludes_ok = all(p.lower() not in actual_lower for p in case.expected_answer_excludes)

    if contains_ok and excludes_ok:
        result["verdict"] = "PASS"
        result["llm_score"] = 1.0
        result["llm_reasoning"] = "All required phrases found; no excluded phrases present."
        return result

    # LLM judge for ambiguous / failing cases
    try:
        client = OpenAI()
        prompt = (
            f"You are an evaluation judge. Decide if the actual answer satisfies the requirements.\n\n"
            f"Question: {case.question}\n"
            f"Must contain (all): {case.expected_answer_contains}\n"
            f"Must NOT contain (any): {case.expected_answer_excludes}\n"
            f"Actual answer: {actual_answer}\n\n"
            f'Respond with JSON only: {{"verdict": "PASS" or "FAIL", "score": 0.0-1.0, "reasoning": "one sentence"}}'
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        result["verdict"] = parsed.get("verdict", "ERROR")
        result["llm_score"] = float(parsed.get("score", 0.0))
        result["llm_reasoning"] = parsed.get("reasoning", "")
    except Exception as e:
        result["verdict"] = "ERROR"
        result["error_message"] = f"LLM judge failed: {e}"

    return result


def run_case(case: AnyCase) -> dict[str, Any]:
    """Run a single test case and return a result dict."""
    try:
        if isinstance(case, ConversationalCase):
            return _run_conversational(case)
        else:
            return _run_golden_sql(case)
    except Exception as e:
        return {
            "case_id": case.id,
            "name": case.name,
            "test_type": case.test_type,
            "question": case.question,
            "verdict": "ERROR",
            "generated_sql": None,
            "expected_sql": None,
            "actual_row_count": None,
            "expected_row_count": None,
            "exec_ms": None,
            "max_exec_ms": None,
            "actual_answer": None,
            "llm_score": None,
            "llm_reasoning": None,
            "error_message": str(e),
            "ran_at": datetime.now().isoformat(),
        }


def run_all(cases: list[AnyCase], progress_callback=None) -> list[dict[str, Any]]:
    """Run all cases. Optionally call progress_callback(i, total, result) after each."""
    results = []
    total = len(cases)
    for i, case in enumerate(cases):
        result = run_case(case)
        results.append(result)
        if progress_callback:
            progress_callback(i + 1, total, result)
    return results
