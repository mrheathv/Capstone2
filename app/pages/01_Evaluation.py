import sys
from pathlib import Path

# Add app/ to sys.path so all existing modules are importable
sys.path.append(str(Path(__file__).parent.parent))

import io
import streamlit as st
import pandas as pd
from datetime import datetime

from database import db_query
from evaluation import (
    load_cases, add_case, update_case, delete_case, import_from_csv, get_csv_template,
    run_case, run_all,
    parse_case, ConversationalCase, GoldenSqlCase, GoldenSqlPerfCase,
)

st.set_page_config(page_title="Evaluation Framework", layout="wide")
st.title("Evaluation Framework")

# ---------------------------------------------------------------------------
# Sidebar — shared agent selector (mirrors main app)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("User Context")
    try:
        agents_df = db_query("SELECT DISTINCT sales_agent FROM sales_teams ORDER BY sales_agent")
        agents = agents_df["sales_agent"].tolist()
    except Exception:
        agents = ["Unknown"]

    if "current_user" not in st.session_state:
        st.session_state.current_user = agents[0] if agents else "Unknown"

    selected_agent = st.selectbox(
        "Acting as:",
        options=agents,
        index=agents.index(st.session_state.current_user) if st.session_state.current_user in agents else 0,
    )
    st.session_state.current_user = selected_agent
    st.success(f"✓ Logged in as: {selected_agent}")

    st.divider()
    st.caption("Conversational tests will run as this agent.")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_cases, tab_run, tab_results, tab_import = st.tabs(
    ["Test Cases", "Run Evaluation", "Results", "Import CSV"]
)

# ============================================================
# TAB 1 — Test Cases
# ============================================================
with tab_cases:
    cases = load_cases()

    col_header, col_add_btn = st.columns([5, 1])
    with col_header:
        st.subheader(f"Test Cases ({len(cases)} total)")
    with col_add_btn:
        if st.button("+ Add New", type="primary"):
            st.session_state["adding_case"] = True
            st.session_state.pop("editing_id", None)

    # ---- Add form -------------------------------------------------------
    if st.session_state.get("adding_case"):
        with st.form("add_case_form", clear_on_submit=True):
            st.markdown("**New Test Case**")
            new_name = st.text_input("Name", placeholder="e.g. Count tech accounts")
            new_type = st.selectbox("Type", ["golden_sql", "golden_sql_perf", "conversational"])
            new_question = st.text_area("Question", placeholder="Natural language question to ask")
            new_tags = st.text_input("Tags (comma-separated)", placeholder="accounts, filter")
            new_enabled = st.checkbox("Enabled", value=True)

            st.markdown("---")
            if new_type in ("golden_sql", "golden_sql_perf"):
                new_sql = st.text_area("Expected SQL", placeholder="SELECT ...")
                new_max_ms = st.number_input("Max exec (ms)", min_value=1, value=2000, disabled=(new_type == "golden_sql"))
                new_row_count = st.number_input("Expected row count (0 = skip)", min_value=0, value=0,
                                                disabled=(new_type == "golden_sql"))
            else:
                new_contains = st.text_input("Expected answer contains (semicolon-separated)",
                                             placeholder="sales; data; account")
                new_excludes = st.text_input("Expected answer excludes (semicolon-separated)", placeholder="")

            submitted = st.form_submit_button("Save")
            cancelled = st.form_submit_button("Cancel")

            if cancelled:
                st.session_state.pop("adding_case", None)
                st.rerun()

            if submitted:
                if not new_name or not new_question:
                    st.error("Name and Question are required.")
                else:
                    tags_list = [t.strip() for t in new_tags.split(",") if t.strip()]
                    base = dict(name=new_name, test_type=new_type, question=new_question,
                                tags=tags_list, enabled=new_enabled)
                    try:
                        if new_type == "golden_sql":
                            case = parse_case({**base, "expected_sql": new_sql.strip()})
                        elif new_type == "golden_sql_perf":
                            rc = int(new_row_count) if new_row_count > 0 else None
                            case = parse_case({**base, "expected_sql": new_sql.strip(),
                                              "max_exec_ms": int(new_max_ms), "expected_row_count": rc})
                        else:
                            contains = [s.strip() for s in new_contains.split(";") if s.strip()]
                            excludes = [s.strip() for s in new_excludes.split(";") if s.strip()]
                            case = parse_case({**base, "expected_answer_contains": contains,
                                              "expected_answer_excludes": excludes})
                        add_case(case)
                        st.session_state.pop("adding_case", None)
                        st.success("Case added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ---- Edit form -------------------------------------------------------
    editing_id = st.session_state.get("editing_id")
    if editing_id:
        edit_case = next((c for c in cases if c.id == editing_id), None)
        if edit_case:
            with st.form("edit_case_form"):
                st.markdown(f"**Editing: {edit_case.name}**")
                e_name = st.text_input("Name", value=edit_case.name)
                e_question = st.text_area("Question", value=edit_case.question)
                e_tags = st.text_input("Tags (comma-separated)", value=", ".join(edit_case.tags))
                e_enabled = st.checkbox("Enabled", value=edit_case.enabled)
                st.markdown(f"*Type: `{edit_case.test_type}` (not editable)*")

                st.markdown("---")
                if isinstance(edit_case, (GoldenSqlCase, GoldenSqlPerfCase)):
                    e_sql = st.text_area("Expected SQL", value=edit_case.expected_sql)
                    if isinstance(edit_case, GoldenSqlPerfCase):
                        e_max_ms = st.number_input("Max exec (ms)", min_value=1, value=edit_case.max_exec_ms)
                        e_row_count = st.number_input("Expected row count (0 = skip)", min_value=0,
                                                      value=edit_case.expected_row_count or 0)
                elif isinstance(edit_case, ConversationalCase):
                    e_contains = st.text_input("Expected answer contains (semicolon-separated)",
                                               value="; ".join(edit_case.expected_answer_contains))
                    e_excludes = st.text_input("Expected answer excludes (semicolon-separated)",
                                               value="; ".join(edit_case.expected_answer_excludes))

                save_btn = st.form_submit_button("Save Changes", type="primary")
                cancel_btn = st.form_submit_button("Cancel")

                if cancel_btn:
                    st.session_state.pop("editing_id", None)
                    st.rerun()

                if save_btn:
                    tags_list = [t.strip() for t in e_tags.split(",") if t.strip()]
                    base = dict(id=edit_case.id, name=e_name, test_type=edit_case.test_type,
                                question=e_question, tags=tags_list, enabled=e_enabled,
                                created_at=edit_case.created_at)
                    try:
                        if isinstance(edit_case, GoldenSqlPerfCase):
                            rc = int(e_row_count) if e_row_count > 0 else None
                            updated = parse_case({**base, "expected_sql": e_sql.strip(),
                                                  "max_exec_ms": int(e_max_ms), "expected_row_count": rc})
                        elif isinstance(edit_case, GoldenSqlCase):
                            updated = parse_case({**base, "expected_sql": e_sql.strip()})
                        else:
                            contains = [s.strip() for s in e_contains.split(";") if s.strip()]
                            excludes = [s.strip() for s in e_excludes.split(";") if s.strip()]
                            updated = parse_case({**base, "expected_answer_contains": contains,
                                                  "expected_answer_excludes": excludes})
                        update_case(updated)
                        st.session_state.pop("editing_id", None)
                        st.success("Case updated!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ---- Cases table -------------------------------------------------------
    if not cases:
        st.info("No test cases yet. Click '+ Add New' to create one.")
    else:
        TYPE_EMOJI = {"conversational": "💬", "golden_sql": "🗄️", "golden_sql_perf": "⚡"}

        for case in cases:
            emoji = TYPE_EMOJI.get(case.test_type, "")
            label = f"{emoji} **{case.name}** — `{case.test_type}`"
            if not case.enabled:
                label += " *(disabled)*"

            with st.expander(label, expanded=False):
                st.markdown(f"**Question:** {case.question}")
                if isinstance(case, (GoldenSqlCase, GoldenSqlPerfCase)):
                    st.code(case.expected_sql, language="sql")
                    if isinstance(case, GoldenSqlPerfCase):
                        st.caption(f"Max exec: {case.max_exec_ms}ms  |  Expected rows: {case.expected_row_count or 'any'}")
                elif isinstance(case, ConversationalCase):
                    st.markdown(f"**Must contain:** {', '.join(case.expected_answer_contains)}")
                    if case.expected_answer_excludes:
                        st.markdown(f"**Must exclude:** {', '.join(case.expected_answer_excludes)}")
                if case.tags:
                    st.caption(f"Tags: {', '.join(case.tags)}")

                col_run, col_edit, col_del = st.columns([1, 1, 1])
                with col_run:
                    if st.button("▶ Run", key=f"run_{case.id}"):
                        with st.spinner("Running..."):
                            result = run_case(case)
                        verdict = result["verdict"]
                        if verdict == "PASS":
                            st.success(f"PASS")
                        elif verdict == "FAIL_PERF":
                            st.warning(f"FAIL_PERF — {result.get('error_message', '')}")
                        elif verdict == "FAIL":
                            st.error(f"FAIL — {result.get('error_message', '')}")
                        else:
                            st.error(f"ERROR — {result.get('error_message', '')}")
                        if result.get("generated_sql"):
                            st.code(result["generated_sql"], language="sql")
                        if result.get("actual_answer"):
                            st.markdown(f"**Response:** {result['actual_answer']}")
                        if result.get("llm_reasoning"):
                            st.caption(f"Judge: {result['llm_reasoning']}")
                with col_edit:
                    if st.button("✏️ Edit", key=f"edit_{case.id}"):
                        st.session_state["editing_id"] = case.id
                        st.session_state.pop("adding_case", None)
                        st.rerun()
                with col_del:
                    if st.button("🗑️ Delete", key=f"del_{case.id}"):
                        st.session_state[f"confirm_del_{case.id}"] = True
                        st.rerun()

                if st.session_state.get(f"confirm_del_{case.id}"):
                    st.warning(f"Delete **{case.name}**?")
                    col_yes, col_no = st.columns(2)
                    with col_yes:
                        if st.button("Yes, delete", key=f"yes_del_{case.id}", type="primary"):
                            delete_case(case.id)
                            st.session_state.pop(f"confirm_del_{case.id}", None)
                            st.rerun()
                    with col_no:
                        if st.button("Cancel", key=f"no_del_{case.id}"):
                            st.session_state.pop(f"confirm_del_{case.id}", None)
                            st.rerun()


# ============================================================
# TAB 2 — Run Evaluation
# ============================================================
with tab_run:
    st.subheader("Run Evaluation Suite")

    cases = load_cases()
    enabled_cases = [c for c in cases if c.enabled]

    all_tags = sorted({tag for c in cases for tag in c.tags})
    all_types = ["conversational", "golden_sql", "golden_sql_perf"]

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_types = st.multiselect("Filter by type", all_types, default=all_types)
    with col_f2:
        filter_tags = st.multiselect("Filter by tag", all_tags) if all_tags else []
    with col_f3:
        enabled_only = st.checkbox("Enabled cases only", value=True)

    filtered = [
        c for c in cases
        if c.test_type in filter_types
        and (not enabled_only or c.enabled)
        and (not filter_tags or any(t in filter_tags for t in c.tags))
    ]

    st.markdown(f"**{len(filtered)} case(s) selected**")

    if not filtered:
        st.info("No cases match the current filters.")
    else:
        if st.button(f"Run {len(filtered)} case(s)", type="primary"):
            results = []
            progress_bar = st.progress(0)
            status_area = st.empty()

            def on_progress(i, total, result):
                progress_bar.progress(i / total)
                verdict = result["verdict"]
                icon = "✅" if verdict == "PASS" else ("⚠️" if verdict == "FAIL_PERF" else "❌")
                status_area.markdown(f"{icon} [{i}/{total}] **{result['name']}** → `{verdict}`")
                results.append(result)

            run_all(filtered, progress_callback=on_progress)
            progress_bar.progress(1.0)

            st.session_state["last_run_results"] = results
            st.session_state["last_run_at"] = datetime.now().isoformat()

            passed = sum(1 for r in results if r["verdict"] == "PASS")
            failed = sum(1 for r in results if r["verdict"] in ("FAIL", "FAIL_PERF"))
            errors = sum(1 for r in results if r["verdict"] == "ERROR")

            st.success(f"Done! {passed} passed · {failed} failed · {errors} errors")
            st.info("Switch to the **Results** tab for details.")


# ============================================================
# TAB 3 — Results
# ============================================================
with tab_results:
    results = st.session_state.get("last_run_results")
    ran_at = st.session_state.get("last_run_at")

    if not results:
        st.info("No results yet. Run the evaluation suite in the **Run Evaluation** tab.")
    else:
        st.subheader("Evaluation Results")
        if ran_at:
            st.caption(f"Last run: {ran_at}")

        # Summary metrics
        total = len(results)
        passed = sum(1 for r in results if r["verdict"] == "PASS")
        failed = sum(1 for r in results if r["verdict"] == "FAIL")
        fail_perf = sum(1 for r in results if r["verdict"] == "FAIL_PERF")
        errors = sum(1 for r in results if r["verdict"] == "ERROR")
        pass_rate = passed / total * 100 if total else 0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total", total)
        m2.metric("Passed", passed)
        m3.metric("Failed", failed)
        m4.metric("Fail Perf", fail_perf)
        m5.metric("Pass Rate", f"{pass_rate:.0f}%")

        st.divider()

        # Results table
        VERDICT_SYMBOL = {"PASS": "✅", "FAIL": "❌", "FAIL_PERF": "⚠️", "ERROR": "🔴"}
        summary_rows = []
        for r in results:
            row = {
                "": VERDICT_SYMBOL.get(r["verdict"], "?"),
                "Name": r["name"],
                "Type": r["test_type"],
                "Verdict": r["verdict"],
                "Exec (ms)": f"{r['exec_ms']:.0f}" if r.get("exec_ms") is not None else "—",
                "Rows (actual)": r.get("actual_row_count") if r.get("actual_row_count") is not None else "—",
                "Rows (expected)": r.get("expected_row_count") if r.get("expected_row_count") is not None else "—",
                "LLM Score": f"{r['llm_score']:.0%}" if r.get("llm_score") is not None else "—",
            }
            summary_rows.append(row)

        df_summary = pd.DataFrame(summary_rows)

        def _color_verdict(val):
            colors = {"PASS": "background-color: #d4edda", "FAIL": "background-color: #f8d7da",
                      "FAIL_PERF": "background-color: #fff3cd", "ERROR": "background-color: #f5c6cb"}
            return colors.get(val, "")

        styled = df_summary.style.applymap(_color_verdict, subset=["Verdict"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # CSV download
        csv_bytes = pd.DataFrame(results).to_csv(index=False).encode()
        st.download_button("Download full results as CSV", data=csv_bytes,
                           file_name=f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                           mime="text/csv")

        st.divider()
        st.subheader("Case Details")

        for r in results:
            symbol = VERDICT_SYMBOL.get(r["verdict"], "?")
            with st.expander(f"{symbol} {r['name']} — `{r['verdict']}`", expanded=(r["verdict"] != "PASS")):
                st.markdown(f"**Question:** {r['question']}")
                st.markdown(f"**Type:** `{r['test_type']}`  |  **Verdict:** `{r['verdict']}`")

                if r.get("error_message"):
                    st.error(r["error_message"])

                if r["test_type"] in ("golden_sql", "golden_sql_perf"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**Generated SQL**")
                        st.code(r.get("generated_sql") or "—", language="sql")
                    with col_b:
                        st.markdown("**Expected SQL**")
                        st.code(r.get("expected_sql") or "—", language="sql")
                    col_c, col_d, col_e = st.columns(3)
                    col_c.metric("Actual rows", r.get("actual_row_count", "—"))
                    col_d.metric("Expected rows", r.get("expected_row_count", "—"))
                    if r.get("exec_ms") is not None:
                        col_e.metric("Exec time", f"{r['exec_ms']:.0f}ms",
                                     delta=f"limit {r.get('max_exec_ms')}ms" if r.get("max_exec_ms") else None)

                if r["test_type"] == "conversational":
                    if r.get("actual_answer"):
                        st.markdown("**Agent Response**")
                        st.markdown(r["actual_answer"])
                    if r.get("llm_score") is not None:
                        st.metric("LLM Judge Score", f"{r['llm_score']:.0%}")
                    if r.get("llm_reasoning"):
                        st.caption(f"Judge reasoning: {r['llm_reasoning']}")


# ============================================================
# TAB 4 — Import CSV
# ============================================================
with tab_import:
    st.subheader("Import Test Cases from CSV")

    st.markdown("""
Upload a CSV file with the following columns. All list fields use **semicolon** as separator.

| Column | Required | Notes |
|---|---|---|
| `name` | Yes | Human-readable label |
| `test_type` | Yes | `conversational`, `golden_sql`, or `golden_sql_perf` |
| `question` | Yes | Natural language question |
| `expected_sql` | For SQL types | SQL to compare results against |
| `expected_answer_contains` | For conversational | Semicolon-separated phrases |
| `expected_answer_excludes` | For conversational | Semicolon-separated phrases |
| `max_exec_ms` | For perf type | Integer milliseconds |
| `expected_row_count` | Optional | Leave blank to skip row count check |
| `tags` | Optional | Semicolon-separated |
| `enabled` | Optional | `true`/`false` (default: true) |
""")

    # Template download
    template_df = get_csv_template()
    # Add sample rows
    sample_rows = pd.DataFrame([
        {
            "name": "Example SQL case",
            "test_type": "golden_sql",
            "question": "How many accounts are there?",
            "expected_sql": "SELECT COUNT(*) FROM accounts",
            "expected_answer_contains": "",
            "expected_answer_excludes": "",
            "max_exec_ms": "",
            "expected_row_count": "",
            "tags": "accounts",
            "enabled": "true",
        },
        {
            "name": "Example conversational case",
            "test_type": "conversational",
            "question": "What should I work on today?",
            "expected_sql": "",
            "expected_answer_contains": "Engaging;account",
            "expected_answer_excludes": "",
            "max_exec_ms": "",
            "expected_row_count": "",
            "tags": "open-work",
            "enabled": "true",
        },
    ])
    template_csv = sample_rows.to_csv(index=False).encode()
    st.download_button("Download CSV template", data=template_csv,
                       file_name="eval_cases_template.csv", mime="text/csv")

    st.divider()

    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded:
        try:
            df = pd.read_csv(uploaded)
            st.markdown(f"**Preview** ({len(df)} rows)")
            st.dataframe(df.head(10), use_container_width=True)

            if st.button("Import Cases", type="primary"):
                count, errors = import_from_csv(df)
                if count:
                    st.success(f"Imported {count} case(s) successfully.")
                if errors:
                    st.warning(f"{len(errors)} row(s) had errors:")
                    for err in errors:
                        st.caption(f"• {err}")
                if count:
                    st.rerun()
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
