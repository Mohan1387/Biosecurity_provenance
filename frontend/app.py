# Streamlit frontend — TCP Platform
import streamlit as st
import os

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")

st.set_page_config(page_title="TCP Platform", page_icon="🔐", layout="wide")


# ── Session state defaults ────────────────────────────
for key, default in {
    "token": None,
    "user": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def api_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


def logout():
    st.session_state.token = None
    st.session_state.user = None


# ── Sidebar ───────────────────────────────────────────
with st.sidebar:
    if st.session_state.user:
        user = st.session_state.user
        st.markdown(f"**{user['username']}**")
        tier_colors = {"open": "🟢", "controlled": "🟡", "restricted": "🔴"}
        st.markdown(f"Tier: {tier_colors.get(user['tier'], '')} `{user['tier']}`")
        if st.button("Logout"):
            logout()
            st.rerun()
    else:
        st.markdown("*Not logged in*")


# ── Pages ─────────────────────────────────────────────
def show_login():
    """Login / register form."""
    import requests

    st.title("🔐 TCP Platform")
    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
        if submitted:
            resp = requests.post(
                f"{API_BASE}/auth/login",
                json={"username": username, "password": password},
                timeout=10,
            )
            if resp.status_code == 200:
                st.session_state.token = resp.json()["access_token"]
                me = requests.get(
                    f"{API_BASE}/auth/me",
                    headers=api_headers(),
                    timeout=10,
                )
                if me.status_code == 200:
                    st.session_state.user = me.json()
                st.rerun()
            else:
                st.error(resp.json().get("detail", "Login failed"))

    with tab_register:
        with st.form("register_form"):
            new_user = st.text_input("Choose a username")
            new_orcid = st.text_input("ORCID iD", placeholder="0000-0002-1825-0097")
            new_pass = st.text_input("Choose a password", type="password")
            reg_submit = st.form_submit_button("Register")
        if reg_submit:
            resp = requests.post(
                f"{API_BASE}/auth/register",
                json={"username": new_user, "orcid_id": new_orcid, "password": new_pass},
                timeout=10,
            )
            if resp.status_code == 201:
                st.success("Registered! Switch to Login tab.")
            else:
                st.error(resp.json().get("detail", "Registration failed"))


def show_home():
    """Authenticated home page."""
    user = st.session_state.user
    st.title("TCP Platform")
    st.write(f"Welcome, **{user['username']}**! Your access tier is **{user['tier']}**.")

    st.markdown("---")
    st.subheader("Available features")

    cols = st.columns(3)
    with cols[0]:
        st.markdown("### 💬 Chat")
        st.write("Interact with the AI agent.")
        st.page_link("pages/chat.py", label="Open Chat")
    with cols[1]:
        if user["tier"] == "restricted":
            st.markdown("### 📊 Dashboard")
            st.write("Detector warnings & Clusterer analysis.")
            st.page_link("pages/dashboard.py", label="Open Dashboard")
        else:
            st.markdown("### 📊 Dashboard")
            st.write("Requires restricted tier access.")
    with cols[2]:
        if user["tier"] == "restricted":
            st.markdown("### 👥 Admin")
            st.write("User management & prompt history.")
            st.page_link("pages/admin.py", label="Open Admin Panel")
        else:
            st.markdown("### 🔒 Admin")
            st.write("Requires restricted tier access.")


# ── Main area ─────────────────────────────────────────
if st.session_state.token is None:
    show_login()
else:
    show_home()
