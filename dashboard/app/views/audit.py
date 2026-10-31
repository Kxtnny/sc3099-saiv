"""
Audit Log Trail View - Security event explorer, compliance summary, and immutable audit trail export.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token
from app.rbac import Permission, require_permission
from app.views._downloads import render_csv_download, render_json_download


def _clear_audit_filters() -> None:
    st.session_state["audit_action"] = "All Actions"
    st.session_state["audit_outcome"] = "All"
    st.session_state["audit_user_filter"] = ""
    st.session_state["audit_resource_type"] = "All"
    st.session_state["audit_resource_id"] = ""
    st.session_state["audit_start_date"] = None
    st.session_state["audit_end_date"] = None
    st.session_state["audit_page_size"] = 50
    st.session_state["audit_page"] = 0
    st.session_state["audit_filter_signature"] = None


def _utc_date_bound(value: date, *, end: bool = False) -> str:
    bound = datetime.combine(
        value + timedelta(days=1) if end else value,
        time.min,
        tzinfo=timezone.utc,
    )
    if end:
        bound -= timedelta(microseconds=1)
    return bound.isoformat().replace("+00:00", "Z")


def render() -> None:
    """Render Audit Log Explorer view."""
    st.title("📜 Security Audit Trail")
    st.caption("Immutable append-only audit log tracking security events, check-in attempts, and administrative actions.")

    token = get_token()
    user = get_current_user()
    if not token or not user:
        st.warning("Please sign in to view audit logs.")
        return

    if not require_permission(user, Permission.VIEW_AUDIT):
        return

    # -------------------------------------------------------------------------
    # Audit Summary KPIs
    # -------------------------------------------------------------------------
    with st.spinner("Loading audit summary..."):
        ok_sum, summary = api_client.get_audit_summary(token, days=7)

    if not ok_sum:
        st.error(f"Failed to load audit summary: {summary}")
    elif isinstance(summary, dict):
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
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
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
            selected_action = st.selectbox(
                "Action Type",
                options=action_options,
                key="audit_action",
            )
            action_param = None if selected_action == "All Actions" else selected_action

        with f_col2:
            success_filter = st.selectbox(
                "Outcome",
                options=["All", "Success Only", "Failure Only"],
                key="audit_outcome",
            )
            success_param = True if success_filter == "Success Only" else (False if success_filter == "Failure Only" else None)

        with f_col3:
            user_id_filter = st.text_input(
                "User ID",
                placeholder="Optional user UUID",
                key="audit_user_filter",
            ).strip()

        with f_col4:
            resource_type = st.selectbox(
                "Resource Type",
                options=[
                    "All",
                    "checkin",
                    "session",
                    "course",
                    "enrollment",
                    "audit_logs",
                ],
                key="audit_resource_type",
            )

        f_col5, f_col6, f_col7 = st.columns(3)
        with f_col5:
            resource_id_filter = st.text_input(
                "Resource ID",
                placeholder="Optional resource UUID",
                key="audit_resource_id",
            ).strip()
        with f_col6:
            start_filter = st.date_input(
                "From date",
                value=None,
                key="audit_start_date",
            )
        with f_col7:
            end_filter = st.date_input(
                "Through date",
                value=None,
                key="audit_end_date",
            )

        log_limit = st.selectbox(
            "Records per Page",
            options=[25, 50, 100],
            index=1,
            key="audit_page_size",
        )
        st.caption("Filters are applied immediately.")
        st.button(
            "Clear filters",
            key="clear_audit_filters",
            on_click=_clear_audit_filters,
        )

    if start_filter and end_filter and end_filter < start_filter:
        st.error("The end date must be on or after the start date.")
        return

    filter_signature = (
        action_param,
        success_param,
        user_id_filter,
        resource_type,
        resource_id_filter,
        start_filter,
        end_filter,
        log_limit,
    )
    if st.session_state.get("audit_filter_signature") != filter_signature:
        st.session_state["audit_filter_signature"] = filter_signature
        st.session_state["audit_page"] = 0
    page = st.session_state.get("audit_page", 0)

    # Fetch logs
    with st.spinner("Fetching audit trail..."):
        ok_logs, log_res = api_client.list_audit_logs(
            token=token,
            action=action_param,
            success=success_param,
            user_id=user_id_filter or None,
            resource_type=None if resource_type == "All" else resource_type,
            resource_id=resource_id_filter or None,
            start_date=_utc_date_bound(start_filter) if start_filter else None,
            end_date=_utc_date_bound(end_filter, end=True) if end_filter else None,
            limit=log_limit,
            offset=page * log_limit,
        )

    if not ok_logs:
        st.error(f"Failed to fetch audit logs: {log_res}")
        return

    logs: List[Dict[str, Any]] = log_res.get("items", []) if isinstance(log_res, dict) else []
    total_logs = log_res.get("total", len(logs)) if isinstance(log_res, dict) else len(logs)
    page_count = max(1, (total_logs + log_limit - 1) // log_limit)
    nav_prev, nav_page, nav_next = st.columns([1, 3, 1])
    with nav_prev:
        if st.button("← Previous", disabled=page <= 0, key="audit_prev"):
            st.session_state["audit_page"] = page - 1
            st.rerun()
    with nav_page:
        st.caption(f"Page {page + 1} of {page_count} · {total_logs} events")
    with nav_next:
        if st.button(
            "Next →",
            disabled=page + 1 >= page_count,
            key="audit_next",
        ):
            st.session_state["audit_page"] = page + 1
            st.rerun()

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
