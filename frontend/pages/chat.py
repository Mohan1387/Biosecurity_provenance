# Chat page — Streamlit chat interface for the TCP AI agent
import json
import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")

st.set_page_config(page_title="TCP Chat", page_icon="💬", layout="wide")

# ── Guard: must be logged in ──────────────────────────
if not st.session_state.get("token"):
    st.error("Please log in first.")
    st.stop()

user = st.session_state.get("user", {})
headers = {"Authorization": f"Bearer {st.session_state.token}"}

# ── Sidebar info ──────────────────────────────────────
with st.sidebar:
    st.markdown(f"**{user['username']}**")
    tier_colors = {"open": "🟢", "controlled": "🟡", "restricted": "🔴"}
    st.markdown(f"Tier: {tier_colors.get(user['tier'], '')} `{user['tier']}`")

    st.markdown("---")
    st.markdown("**Available tools:**")
    tool_tiers = {
        "open": ["search_public_docs", "get_current_time"],
        "controlled": ["search_public_docs", "get_current_time", "query_dataset", "analyze_data"],
        "restricted": ["search_public_docs", "get_current_time", "query_dataset", "analyze_data", "list_platform_users", "get_usage_stats"],
    }
    for tool_name in tool_tiers.get(user["tier"], []):
        st.markdown(f"- `{tool_name}`")

    st.markdown("---")
    if st.button("🗑️ Clear Conversation"):
        requests.post(f"{API_BASE}/chat/reset", headers=headers, timeout=10)
        st.session_state.pop("chat_messages", None)
        st.rerun()

st.title("💬 TCP Chat")

# ── Load history from backend on first render ─────────
if "chat_messages" not in st.session_state:
    resp = requests.get(f"{API_BASE}/chat/history", headers=headers, timeout=10)
    if resp.status_code == 200:
        history = resp.json()
        st.session_state.chat_messages = []
        for msg in history:
            entry = {"role": msg["role"], "content": msg["content"]}
            if msg.get("tool_calls_json"):
                entry["tool_calls"] = json.loads(msg["tool_calls_json"])
            st.session_state.chat_messages.append(entry)
    else:
        st.session_state.chat_messages = []

# ── Display chat history ──────────────────────────────
for msg in st.session_state.chat_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("tool_calls"):
            with st.expander(f"🔧 Tool calls ({len(msg['tool_calls'])})"):
                for tc in msg["tool_calls"]:
                    st.markdown(f"**{tc['name']}**")
                    st.code(json.dumps(tc["input"], indent=2), language="json")
                    st.markdown("Result:")
                    st.code(tc["result"][:2000])

# ── Chat input ────────────────────────────────────────
if prompt := st.chat_input("Ask the TCP agent..."):
    # Show user message immediately
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call backend
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            resp = requests.post(
                f"{API_BASE}/chat",
                headers=headers,
                json={"message": prompt},
                timeout=120,
            )

        if resp.status_code == 200:
            data = resp.json()
            st.markdown(data["reply"])

            entry = {"role": "assistant", "content": data["reply"]}

            if data.get("tool_calls"):
                entry["tool_calls"] = data["tool_calls"]
                with st.expander(f"🔧 Tool calls ({len(data['tool_calls'])})"):
                    for tc in data["tool_calls"]:
                        st.markdown(f"**{tc['name']}**")
                        st.code(json.dumps(tc["input"], indent=2), language="json")
                        st.markdown("Result:")
                        st.code(tc["result"][:2000])

            if data.get("usage"):
                st.caption(
                    f"Tokens: {data['usage'].get('input_tokens', 0)} in / "
                    f"{data['usage'].get('output_tokens', 0)} out"
                )

            st.session_state.chat_messages.append(entry)
        elif resp.status_code == 503:
            st.error("API key not configured. Set ANTHROPIC_API_KEY in your environment.")
        else:
            try:
                detail = resp.json().get("detail", "Chat request failed")
            except ValueError:
                detail = f"Chat request failed (HTTP {resp.status_code}): {resp.text[:300]}"
            st.error(detail)
