"""
Audit Log Trail View - Security event explorer, compliance summary, and immutable audit trail export.
"""

from typing import Any, Dict, List
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import can_view_audit, get_current_user, get_token
from app.views._downloads import render_csv_download, render_json_download
from app.views._time import format_singapore_time


def render() -> None:
    """Render Audit Log Explorer view."""
    st.title("📜 Security Audit Trail")
    st.caption("Immutable append-only audit log tracking security events, check-in attempts, and administrative actions.")

    token = get_token()
    user = get_current_user()
    if not token or not user:
        st.warning("Please sign in to view audit logs.")
        return

    if not can_view_audit(user):
        st.error("Access restricted to Administrators.")
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
        render_csv_download(
            token=token,
            cache_key="audit",
            request_label="📥 Export Audit Trail CSV",
            download_label="Download Audit Trail CSV",
            file_name="security_audit_logs.csv",
            export=lambda: api_client.export_audit_csv(token),
            use_container_width=True,
        )
        render_json_download(
            token=token,
            cache_key="audit",
            request_label="📥 Export Audit Trail JSON",
            download_label="Download Audit Trail JSON",
            file_name="security_audit_logs.json",
            export=lambda: api_client.export_audit_json(token),
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
                "Timestamp": format_singapore_time(log.get("timestamp"), seconds=True),
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
        format_func=lambda i: f"{format_singapore_time(logs[i].get('timestamp'), seconds=True)} | {logs[i].get('action')} | {logs[i].get('user_email', 'system')}",
    )
    if logs:
        st.json(logs[selected_log_idx])
