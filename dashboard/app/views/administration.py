"""Administrative user and course management."""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token
from app.rbac import Permission, require_permission


def _load_pages(
    fetch_page,
) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    items: List[Dict[str, Any]] = []
    offset = 0
    total: Optional[int] = None
    while total is None or offset < total:
        ok, response = fetch_page(offset)
        if not ok:
            return False, [], str(response)
        if not isinstance(response, dict):
            return False, [], "The API returned an invalid paginated response."
        page_items = response.get("items")
        page_total = response.get("total")
        if (
            not isinstance(page_items, list)
            or any(not isinstance(item, dict) for item in page_items)
            or not isinstance(page_total, int)
            or isinstance(page_total, bool)
            or page_total < 0
            or (page_total > offset and not page_items)
        ):
            return False, [], "The API returned an invalid paginated response."
        items.extend(page_items)
        total = page_total
        offset += len(page_items)
    return True, items, None


def render() -> None:
    """Render admin-only user and course management tools."""
    user = get_current_user()
    if not require_permission(user, Permission.MANAGE_ADMINISTRATION):
        return
    token = get_token()
    if not token:
        st.warning("Please sign in again to administer the system.")
        return

    st.title("System Administration")
    st.caption("Manage user accounts and course catalog entries.")
    users_ok, users, users_error = _load_pages(
        lambda offset: api_client.list_users(
            token, is_active=None, limit=100, offset=offset
        )
    )
    active_courses_ok, active_courses, active_courses_error = _load_pages(
        lambda offset: api_client.list_courses(
            token, is_active=True, limit=100, offset=offset
        )
    )
    inactive_courses_ok, inactive_courses, inactive_courses_error = _load_pages(
        lambda offset: api_client.list_courses(
            token, is_active=False, limit=100, offset=offset
        )
    )
    courses_ok = active_courses_ok and inactive_courses_ok
    courses = active_courses + inactive_courses
    courses_error = active_courses_error or inactive_courses_error
    devices_ok, devices, devices_error = _load_pages(
        lambda offset: api_client.list_devices(
            token, limit=100, offset=offset
        )
    )
    valid_roles = {"student", "ta", "instructor", "admin"}
    if users_ok and any(
        not isinstance(item.get("id"), str)
        or not isinstance(item.get("email"), str)
        or not isinstance(item.get("full_name"), str)
        or item.get("role") not in valid_roles
        or not isinstance(item.get("is_active"), bool)
        for item in users
    ):
        users_ok = False
        users_error = "The user API returned an invalid account record."
    if courses_ok and any(
        not isinstance(item.get("id"), str)
        or not isinstance(item.get("code"), str)
        or not isinstance(item.get("name"), str)
        or not isinstance(item.get("semester"), str)
        or not isinstance(item.get("is_active"), bool)
        for item in courses
    ):
        courses_ok = False
        courses_error = "The course API returned an invalid course record."
    if devices_ok and any(
        not isinstance(item.get("id"), str)
        or not isinstance(item.get("user_id"), str)
        or not isinstance(item.get("device_fingerprint"), str)
        or not isinstance(item.get("is_active"), bool)
        or not isinstance(item.get("is_trusted"), bool)
        for item in devices
    ):
        devices_ok = False
        devices_error = "The device API returned an invalid device record."

    user_tab, course_tab, device_tab = st.tabs(["Users", "Courses", "Devices"])
    with user_tab:
        st.subheader("User accounts")
        if not users_ok:
            st.error(f"Could not load users: {users_error}")
        else:
            if users:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Name": item.get("full_name") or "",
                                "Email": item.get("email") or "",
                                "Role": item.get("role") or "unknown",
                                "Active": bool(item.get("is_active")),
                            }
                            for item in users
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
                user_options = {
                    f"{item.get('full_name') or item.get('email')} "
                    f"({item.get('role') or 'unknown'})": item
                    for item in users
                    if item.get("id")
                }
                if user_options:
                    selected_label = st.selectbox(
                        "Account to update",
                        list(user_options),
                        key="admin_user_to_update",
                    )
                    selected_user = user_options[selected_label]
                    with st.form("admin_user_update"):
                        role_options = ["student", "ta", "instructor", "admin"]
                        current_role = selected_user.get("role")
                        role_index = (
                            role_options.index(current_role)
                            if current_role in role_options
                            else 0
                        )
                        new_role = st.selectbox(
                            "Role",
                            role_options,
                            index=role_index,
                        )
                        is_active = st.checkbox(
                            "Account active",
                            value=bool(selected_user.get("is_active")),
                        )
                        save_user = st.form_submit_button("Save account")
                    if save_user:
                        ok_update, result = api_client.update_user(
                            token,
                            selected_user["id"],
                            {"role": new_role, "is_active": is_active},
                        )
                        if ok_update:
                            st.success("User account updated.")
                            st.rerun()
                        else:
                            st.error(f"Could not update user: {result}")
            else:
                st.info("No user accounts were returned.")

        st.subheader("Create user accounts")
        with st.form("admin_user_create"):
            new_email = st.text_input("Email")
            new_name = st.text_input("Full name")
            new_password = st.text_input("Temporary password", type="password")
            new_role = st.selectbox(
                "New account role",
                ["student", "ta", "instructor", "admin"],
                key="admin_user_create_role",
            )
            create_user = st.form_submit_button("Create account")
        if create_user:
            if not new_email.strip() or not new_name.strip():
                st.error("Email and full name are required.")
            elif len(new_password) < 8:
                st.error("Temporary password must contain at least 8 characters.")
            else:
                ok_create, result = api_client.create_users(
                    token,
                    [
                        {
                            "email": new_email.strip(),
                            "full_name": new_name.strip(),
                            "password": new_password,
                            "role": new_role,
                        }
                    ],
                )
                if ok_create and isinstance(result, dict):
                    if result.get("created") == 1:
                        st.success("User account created.")
                        st.rerun()
                    else:
                        errors = result.get("errors")
                        st.error(
                            f"Account was not created: "
                            f"{errors if isinstance(errors, list) else result}"
                        )
                else:
                    st.error(f"Could not create user account: {result}")

    with course_tab:
        st.subheader("Course catalog")
        if not courses_ok:
            st.error(f"Could not load courses: {courses_error}")
        else:
            if courses:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Code": item.get("code") or "",
                                "Name": item.get("name") or "",
                                "Semester": item.get("semester") or "",
                                "Instructor": item.get("instructor_name") or "Unassigned",
                                "Active": bool(item.get("is_active")),
                            }
                            for item in courses
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                course_options = {
                    f"{item.get('code')} - {item.get('name')}": item
                    for item in courses
                    if item.get("id")
                }
                if course_options:
                    selected_course_label = st.selectbox(
                        "Course to update",
                        list(course_options),
                        key="admin_course_to_update",
                    )
                    selected_course = course_options[selected_course_label]
                    with st.form("admin_course_update"):
                        updated_name = st.text_input(
                            "Course name",
                            value=selected_course.get("name") or "",
                        )
                        updated_semester = st.text_input(
                            "Semester",
                            value=selected_course.get("semester") or "",
                        )
                        active_course = st.checkbox(
                            "Course active",
                            value=bool(selected_course.get("is_active")),
                        )
                        save_course = st.form_submit_button("Save course")
                    if save_course:
                        if not updated_name.strip() or not updated_semester.strip():
                            st.error("Course name and semester are required.")
                        else:
                            ok_update, result = api_client.update_course(
                                token,
                                selected_course["id"],
                                {
                                    "name": updated_name.strip(),
                                    "semester": updated_semester.strip(),
                                    "is_active": active_course,
                                },
                            )
                            if ok_update:
                                st.success("Course updated.")
                                st.rerun()
                            else:
                                st.error(f"Could not update course: {result}")
                    confirm_delete = st.checkbox(
                        "Confirm deactivating this course",
                        key=f"delete_course_confirm_{selected_course['id']}",
                    )
                    if st.button(
                        "Deactivate course",
                        disabled=not confirm_delete
                        or not bool(selected_course.get("is_active")),
                        key=f"delete_course_{selected_course['id']}",
                    ):
                        ok_delete, result = api_client.delete_course(
                            token, selected_course["id"]
                        )
                        if ok_delete:
                            st.success("Course deactivated.")
                            st.rerun()
                        else:
                            st.error(f"Could not deactivate course: {result}")
            else:
                st.info("No course records were returned.")

        st.subheader("Create course")
        instructors = (
            [
                item
                for item in users
                if item.get("role") == "instructor" and item.get("is_active")
            ]
            if users_ok
            else []
        )
        instructor_options = {
            f"{item.get('full_name') or item.get('email')} ({item.get('email')})": item.get("id")
            for item in instructors
        }
        with st.form("admin_course_create"):
            code = st.text_input("Course code")
            name = st.text_input("Course name")
            semester = st.text_input("Semester")
            instructor_labels = ["Unassigned"] + list(instructor_options)
            selected_instructor = st.selectbox(
                "Instructor",
                instructor_labels,
                key="admin_course_create_instructor",
            )
            create_course = st.form_submit_button("Create course")
        if create_course:
            if not code.strip() or not name.strip() or not semester.strip():
                st.error("Course code, name, and semester are required.")
            else:
                instructor_id = (
                    instructor_options.get(selected_instructor)
                    if selected_instructor != "Unassigned"
                    else None
                )
                ok_create, result = api_client.create_course(
                    token,
                    {
                        "code": code.strip(),
                        "name": name.strip(),
                        "semester": semester.strip(),
                        "instructor_id": instructor_id,
                    },
                )
                if ok_create:
                    st.success("Course created.")
                    st.rerun()
                else:
                    st.error(f"Could not create course: {result}")
        if not users_ok:
            st.warning(
                "Instructor choices are unavailable because users could not be loaded."
            )

    with device_tab:
        st.subheader("Registered devices")
        if not devices_ok:
            st.error(f"Could not load devices: {devices_error}")
        elif not devices:
            st.info("No device records were returned.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Device ID": device.get("id"),
                            "User ID": device.get("user_id"),
                            "Name": device.get("device_name") or "",
                            "Platform": device.get("platform") or "",
                            "Trusted": device.get("is_trusted"),
                            "Active": device.get("is_active"),
                            "Last seen": device.get("last_seen_at") or "",
                        }
                        for device in devices
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            device_options = {
                f"{device.get('device_name') or device.get('device_fingerprint')} "
                f"({device.get('user_id')})": device
                for device in devices
            }
            selected_device_label = st.selectbox(
                "Device to update",
                list(device_options),
                key="admin_device_to_update",
            )
            selected_device = device_options[selected_device_label]
            with st.form("admin_device_update"):
                trusted = st.checkbox(
                    "Trusted",
                    value=selected_device["is_trusted"],
                )
                device_active = st.checkbox(
                    "Device active",
                    value=selected_device["is_active"],
                )
                confirm_deactivation = st.checkbox(
                    "Confirm deactivating this device",
                    disabled=not selected_device["is_active"],
                )
                save_device = st.form_submit_button("Save device")
            if save_device:
                if (
                    selected_device["is_active"]
                    and not device_active
                    and not confirm_deactivation
                ):
                    st.error("Confirm deactivation before saving.")
                else:
                    ok_update, result = api_client.update_device(
                        token,
                        selected_device["id"],
                        is_active=device_active,
                        is_trusted=trusted,
                    )
                    if ok_update:
                        st.success("Device updated.")
                        st.rerun()
                    else:
                        st.error(f"Could not update device: {result}")
