"""
Audit Log Trail View - Security event explorer, compliance summary, and immutable audit trail export.
"""

from typing import Any, Dict, List
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token


def render() -> None:
    """Render Audit Log Explorer view."""
    st.title("📜 Security Audit Trail")
    st.caption("Immutable append-only audit log tracking security events, check-in attempts, and administrative actions.")

    token = get_token()
    user = get_current_user()
    if not token or not user:
        st.warning("Please sign in to view audit logs.")
        return

    # Check if user has admin/instructor role
    role = user.get("role", "")
    if role not in ["admin", "instructor"]:
        st.error("Access restricted to Administrators and Course Instructors.")
        return

    # -------------------------------------------------------------------------
    # Audit Summary KPIs
    # -------------------------------------------------------------------------
    with st.spinner("Loading audit summary..."):
        ok_sum, summary = api_client.get_audit_summary(token, days=7)

    if ok_sum and isinstance(summary, dict):
        s1, s2, s3, s4 = st.columns(4)
        total_logs = summary.get("total_logs", 0)
        success_map = summary.get("by_success", {})
        success_count = success_map.get("success", 0)
        fail_count = success_map.get("failure", 0)
        unique_users = summary.get("unique_users", 0)

        with s1:
            st.metric("Total Events (7d)", total_logs)
        with s2:
            st.metric("Successful Actions", success_count)
        with s3:
            st.metric("Failed / Denied Attempts", fail_count, delta_color="inverse")
        with s4:
            st.metric("Unique Users Active", unique_users)

    # Export Audit CSV
    col_exp1, col_exp2 = st.columns([3, 1])
    with col_exp2:
        ok_csv, audit_csv = api_client.export_audit_csv(token)
        if ok_csv and isinstance(audit_csv, bytes):
            st.download_button(
                label="📥 Export Audit Trail CSV",
                data=audit_csv,
                file_name="security_audit_logs.csv",
                mime="text/csv",
                use_container_width=True,
            )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Audit Filters & Table
    # -------------------------------------------------------------------------
    with st.expander("🔍 Filter Audit Trail", expanded=True):
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            action_options = [
                "All Actions",
                "login_success",
                "login_failed",
                "logout",
                "checkin_attempted",
                "checkin_reviewed",
                "checkin_appealed",
                "session_created",
                "session_updated",
                "session_deleted",
                "qr_generated",
                "enrollment_added",
                "enrollment_removed",
                "data_exported",
            ]
            selected_action = st.selectbox("Action Type", options=action_options)
            action_param = None if selected_action == "All Actions" else selected_action

        with f_col2:
            success_filter = st.selectbox("Outcome", options=["All", "Success Only", "Failure Only"])
            success_param = True if success_filter == "Success Only" else (False if success_filter == "Failure Only" else None)

        with f_col3:
            log_limit = st.selectbox("Log Limit", options=[50, 100, 250], index=1)

    # Fetch logs
    with st.spinner("Fetching audit trail..."):
        ok_logs, log_res = api_client.list_audit_logs(
            token=token,
            action=action_param,
            success=success_param,
            limit=log_limit,
        )

    if not ok_logs:
        st.error(f"Failed to fetch audit logs: {log_res}")
        return

    logs: List[Dict[str, Any]] = log_res.get("items", []) if isinstance(log_res, dict) else []

    if not logs:
        st.info("No audit logs matching criteria.")
        return

    st.write(f"Displaying **{len(logs)}** log record(s):")

    table_data = []
    for log in logs:
        success = log.get("success", True)
        table_data.append(
            {
                "Timestamp (UTC)": log.get("timestamp", "")[:19].replace("T", " "),
                "Action": log.get("action", "").upper(),
                "Outcome": "✅ SUCCESS" if success else "❌ FAILURE",
                "User": log.get("user_email") or log.get("user_id") or "System / Anonymous",
                "Resource": f"{log.get('resource_type', '')} ({log.get('resource_id', '')[:8] if log.get('resource_id') else '-'})",
                "IP Address": log.get("ip_address") or "N/A",
            }
        )

    df_logs = pd.DataFrame(table_data)
    st.dataframe(df_logs, use_container_width=True, hide_index=True)

    # Detail inspector on selected event
    st.markdown("#### Inspect Event Details")
    selected_log_idx = st.selectbox(
        "Select an event to view structured JSON payload:",
        options=range(len(logs)),
        format_func=lambda i: f"{logs[i].get('timestamp', '')[:19]} | {logs[i].get('action')} | {logs[i].get('user_email', 'system')}",
    )
    if logs:
        st.json(logs[selected_log_idx])

