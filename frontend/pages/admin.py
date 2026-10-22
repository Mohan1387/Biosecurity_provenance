# Admin panel — user management + prompt history (restricted tier only)
import json
from datetime import datetime

import requests
import streamlit as st

import os
API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")

st.set_page_config(page_title="TCP Admin", page_icon="👥", layout="wide")

# ── Guard: must be logged in with restricted tier ─────
if not st.session_state.get("token"):
    st.error("Please log in first.")
    st.stop()

user = st.session_state.get("user", {})
if user.get("tier") != "restricted":
    st.error("Access denied. Restricted tier required.")
    st.stop()

headers = {"Authorization": f"Bearer {st.session_state.token}"}

st.title("👥 Admin Panel")

# Load users once (shared by both tabs)
resp = requests.get(f"{API_BASE}/admin/users", headers=headers, timeout=10)
if resp.status_code != 200:
    st.error("Failed to load users.")
    st.stop()
users = resp.json()

tab_mgmt, tab_history = st.tabs(["User Management", "Prompt History"])

# ══════════════════════════════════════════════════════
# TAB 1: User Management (original admin functionality)
# ══════════════════════════════════════════════════════
with tab_mgmt:
    # ── Create user ───────────────────────────────────
    st.subheader("Create New User")
    with st.form("create_user"):
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        with col1:
            new_username = st.text_input("Username")
        with col2:
            new_orcid = st.text_input("ORCID iD", placeholder="0000-0002-1825-0097")
        with col3:
            new_password = st.text_input("Password", type="password")
        with col4:
            new_tier = st.selectbox("Tier", ["open", "controlled", "restricted"])
        create_submit = st.form_submit_button("Create User")

    if create_submit:
        resp_create = requests.post(
            f"{API_BASE}/admin/users",
            headers=headers,
            json={"username": new_username, "orcid_id": new_orcid, "password": new_password, "tier": new_tier},
            timeout=10,
        )
        if resp_create.status_code == 201:
            st.success(f"User '{new_username}' created with tier '{new_tier}'.")
            st.rerun()
        else:
            st.error(resp_create.json().get("detail", "Failed to create user"))

    # ── User list ─────────────────────────────────────
    st.subheader("All Users")

    # ── Bulk delete ───────────────────────────────────
    selected_ids = []
    for u in users:
        if u["username"] != "admin":
            if st.checkbox(
                f"Select **{u['username']}** ({u['tier']})",
                key=f"del_{u['id']}",
            ):
                selected_ids.append(u["id"])

    if selected_ids:
        if st.button("🗑️ Delete Selected Users", type="primary"):
            del_resp = requests.post(
                f"{API_BASE}/admin/users/delete",
                headers=headers,
                json={"user_ids": selected_ids},
                timeout=10,
            )
            if del_resp.status_code == 200:
                data = del_resp.json()
                st.success(f"Deleted: {', '.join(data['deleted'])}")
                if data["skipped"]:
                    st.info(f"Protected (not deleted): {', '.join(data['skipped'])}")
                st.rerun()
            else:
                st.error("Delete failed")

    st.markdown("---")

    for u in users:
        orcid = u.get("orcid_id", "")
        interest = u.get("research_interest") or ""
        with st.expander(f"{u['username']}  —  {u['tier']}  {'✅' if u['is_active'] else '❌'}  |  ORCID: {orcid}"):
            if interest:
                st.caption(f"**Research interest:** {interest}")
            col_tier, col_active, col_save = st.columns([2, 2, 1])
            with col_tier:
                new_t = st.selectbox(
                    "Tier",
                    ["open", "controlled", "restricted"],
                    index=["open", "controlled", "restricted"].index(u["tier"]),
                    key=f"tier_{u['id']}",
                )
            with col_active:
                new_active = st.checkbox("Active", value=u["is_active"], key=f"active_{u['id']}")
            with col_save:
                if st.button("Save", key=f"save_{u['id']}"):
                    patch = requests.patch(
                        f"{API_BASE}/admin/users/{u['id']}",
                        headers=headers,
                        json={"tier": new_t, "is_active": new_active},
                        timeout=10,
                    )
                    if patch.status_code == 200:
                        st.success("Updated!")
                        st.rerun()
                    else:
                        st.error("Update failed")

            # Password reset
            reset_pw = st.text_input("New password", type="password", key=f"pw_{u['id']}")
            if st.button("Reset Password", key=f"reset_{u['id']}"):
                if not reset_pw or len(reset_pw) < 4:
                    st.warning("Password must be at least 4 characters.")
                else:
                    resp_reset = requests.post(
                        f"{API_BASE}/admin/users/{u['id']}/reset-password",
                        headers=headers,
                        json={"new_password": reset_pw},
                        timeout=10,
                    )
                    if resp_reset.status_code == 204:
                        st.success(f"Password reset for '{u['username']}'.")
                    else:
                        st.error(resp_reset.json().get("detail", "Reset failed"))

# ══════════════════════════════════════════════════════
# TAB 2: Prompt History
# ══════════════════════════════════════════════════════
with tab_history:
    st.subheader("User Prompt History")

    # Build user lookup (id -> info)
    user_map = {u["id"]: u for u in users}
    user_options = {f"{u['username']} (ID {u['id']})": u["id"] for u in users if u["username"] != "admin"}

    selected_user_label = st.selectbox("Select User", list(user_options.keys()))
    selected_user_id = user_options[selected_user_label]
    selected_user_info = user_map[selected_user_id]

    # ── User profile card ──
    st.markdown("---")
    prof_cols = st.columns([2, 2, 1])
    with prof_cols[0]:
        st.markdown(f"**Username:** {selected_user_info['username']}")
        st.markdown(f"**ORCID:** {selected_user_info.get('orcid_id', 'N/A')}")
        tier_colors = {"open": "🟢", "controlled": "🟡", "restricted": "🔴"}
        tier_val = selected_user_info["tier"]
        st.markdown(f"**Tier:** {tier_colors.get(tier_val, '')} {tier_val}")
    with prof_cols[1]:
        interest = selected_user_info.get("research_interest") or "Not specified"
        st.markdown(f"**Research Interest:** {interest}")
        st.markdown(f"**Active:** {'Yes' if selected_user_info['is_active'] else 'No'}")

    st.caption("This demo account and its query history are synthetic. Its fixed ORCID ID is not proof of account ownership.")
    if st.button("Fetch public ORCID works for this user", key=f"fetch_orcid_{selected_user_id}"):
        with st.spinner("Requesting public works from ORCID and signing the Profiler result..."):
            fetch_resp = requests.post(
                f"{API_BASE}/admin/profiler/fetch/{selected_user_id}",
                headers=headers,
                timeout=40,
            )
        if fetch_resp.status_code == 200:
            fetched = fetch_resp.json()
            st.success(f"Verified-source profile stored with {fetched['publication_count']} public work(s).")
            st.rerun()
        elif fetch_resp.status_code == 404:
            st.info(
                "ORCID returned 404 for this assigned ID. No publication profile was created. "
                "Detector can still analyze the signed demo queries against the account's declared interest."
            )
        else:
            st.error(f"ORCID profile fetch failed: {fetch_resp.text}")

    # ── Detector profile (divergence scores) ──
    with prof_cols[2]:
        profile_resp = requests.get(
            f"{API_BASE}/admin/detector/user/{selected_user_id}/profile",
            headers=headers,
            timeout=10,
        )
        if profile_resp.status_code == 200:
            profile = profile_resp.json()
            i_score = profile.get("interest_score")
            st.metric("Interest Score", f"{i_score:.3f}" if i_score is not None else "N/A")
            st.metric("Query Count", profile.get("query_count", 0))

    # ── Query history ──
    st.markdown("---")
    limit = st.slider("Max queries to show", 10, 200, 50, key="history_limit")

    queries_resp = requests.get(
        f"{API_BASE}/admin/detector/user/{selected_user_id}/queries",
        headers=headers,
        params={"limit": limit},
        timeout=10,
    )

    if queries_resp.status_code != 200:
        st.error("Failed to load query history.")
    else:
        queries = queries_resp.json()
        if not queries:
            st.info("No queries found for this user.")
        else:
            st.markdown(f"**Showing {len(queries)} queries** (newest first)")

            # Summary stats
            stat_cols = st.columns(3)
            stat_cols[0].metric("Total Queries", len(queries))

            # Tools used breakdown
            tools_used = {}
            for q in queries:
                if q.get("tools_invoked"):
                    try:
                        tool_list = json.loads(q["tools_invoked"]) if isinstance(q["tools_invoked"], str) else q["tools_invoked"]
                        for t in tool_list:
                            tools_used[t] = tools_used.get(t, 0) + 1
                    except (json.JSONDecodeError, TypeError):
                        pass
            if tools_used:
                top_tool = max(tools_used, key=tools_used.get)
                stat_cols[1].metric("Most Used Tool", top_tool)
                stat_cols[2].metric("Distinct Tools", len(tools_used))

            st.markdown("---")

            # Query table
            table_data = []
            for q in queries:
                ts_raw = q.get("timestamp", "")
                # Format timestamp for readability
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    ts_str = ts.strftime("%Y-%m-%d %H:%M")
                except (ValueError, AttributeError):
                    ts_str = ts_raw

                table_data.append({
                    "Time": ts_str,
                    "Query": q["query_text"][:120],
                    "Tools": q.get("tools_invoked", ""),
                })

            st.dataframe(table_data, use_container_width=True, height=400)

            # ── Expandable detail view ──
            st.markdown("#### Query Details")
            for i, q in enumerate(queries):
                ts_raw = q.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    ts_str = ts_raw

                with st.expander(f"{ts_str} — {q['query_text'][:80]}..."):
                    st.markdown(f"**Full Query:**\n> {q['query_text']}")
                    if q.get("tools_invoked"):
                        st.markdown(f"**Tools:** `{q['tools_invoked']}`")
                    if q.get("response_summary"):
                        st.markdown(f"**Response:** {q['response_summary']}")
