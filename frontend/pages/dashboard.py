# Dashboard — Detector warnings + Clusterer persona/anomaly reports (restricted tier only)
import json
import os

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")

st.set_page_config(page_title="TCP Dashboard", page_icon="📊", layout="wide")

# ── Guard ─────────────────────────────────────────────
if not st.session_state.get("token"):
    st.error("Please log in first.")
    st.stop()

user = st.session_state.get("user", {})
if user.get("tier") != "restricted":
    st.error("Access denied. Restricted tier required.")
    st.stop()

headers = {"Authorization": f"Bearer {st.session_state.token}"}

st.title("📊 Analytics Dashboard")

tab_detector, tab_clusterer = st.tabs(["Detector — Anomaly Warnings", "Clusterer — Persona & Anomaly Analysis"])

# ══════════════════════════════════════════════════════
# TAB 1: Detector Warnings
# ══════════════════════════════════════════════════════
with tab_detector:
    st.subheader("Anomaly Detection (Detector Agent)")

    # ── Controls ──
    col_scan, col_filter = st.columns([1, 3])
    with col_scan:
        st.caption("Profiles are optional: without ORCID works, Detector uses signed queries and the declared interest only.")
        if st.button("🔍 Run Scan (All Users)", type="primary"):
            with st.spinner("Scanning all users..."):
                resp = requests.post(
                    f"{API_BASE}/admin/detector/scan",
                    headers=headers,
                    json={"user_id": None, "force": False},
                    timeout=60,
                )
            if resp.status_code == 200:
                new_warnings = resp.json()
                st.success(f"Scan complete. {len(new_warnings)} warning(s) generated.")
                st.rerun()
            else:
                try:
                    failure = resp.json()
                except ValueError:
                    failure = {}
                if resp.status_code == 409 and failure.get("reason") == "unsigned_input":
                    st.warning(
                        f"Scan stopped at {failure.get('subject', 'an unsigned record')}: "
                        "this record has no provenance receipt. It may predate provenance, "
                        "so its original source cannot be verified."
                    )
                else:
                    st.error(f"Scan failed: {resp.text}")

    with col_filter:
        filter_cols = st.columns(3)
        with filter_cols[0]:
            status_filter = st.selectbox("Status", ["all", "pending", "reviewed", "dismissed"])
        with filter_cols[1]:
            severity_filter = st.selectbox("Severity", ["all", "high", "medium", "low"])
        with filter_cols[2]:
            user_filter = st.text_input("User ID", placeholder="Leave blank for all")

    # ── Build query params ──
    params = {}
    if status_filter != "all":
        params["status_filter"] = status_filter
    if severity_filter != "all":
        params["severity"] = severity_filter
    if user_filter.strip():
        params["user_id"] = int(user_filter.strip())

    # ── Load warnings ──
    resp = requests.get(f"{API_BASE}/admin/detector/warnings", headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        st.error("Failed to load warnings.")
        st.stop()

    warnings = resp.json()

    if not warnings:
        st.info("No warnings match the current filters.")
    else:
        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        n_pending = sum(1 for w in warnings if w["status"] == "pending")
        n_high = sum(1 for w in warnings if w["severity"] == "high")
        n_medium = sum(1 for w in warnings if w["severity"] == "medium")
        m1.metric("Total Warnings", len(warnings))
        m2.metric("Pending", n_pending)
        m3.metric("High Severity", n_high)
        m4.metric("Medium Severity", n_medium)

        st.markdown("---")

        # ── Warning cards ──
        for w in warnings:
            verification = requests.get(
                f"{API_BASE}/admin/provenance/records/user_warnings/{w['id']}/verify",
                headers=headers, timeout=30,
            )
            verified = verification.status_code == 200
            try:
                failure = verification.json() if not verified else {}
            except ValueError:
                failure = {}
            unsigned = verification.status_code == 409 and failure.get("reason") == "unsigned_input"
            if not verified and not unsigned:
                st.error(f"Warning #{w['id']}: evidence could not be verified. Review is blocked.")
                continue
            sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(w["severity"], "⚪")
            status_icon = {"pending": "⏳", "reviewed": "✅", "dismissed": "❌"}.get(w["status"], "❓")

            with st.expander(
                f"{sev_icon} User #{w['user_id']} — {w['warning_type']} — "
                f"{w['severity'].upper()} — {status_icon} {w['status']}"
            ):
                if verified:
                    st.caption("Verified Detector result and signed evidence chain")
                else:
                    st.warning(
                        "Unsigned warning: this record may predate provenance. "
                        "Its original source cannot be verified, so it is read-only here."
                    )
                if verified and st.button("Inspect provenance", key=f"evidence_{w['id']}"):
                    receipt_id = verification.json()["receipt_id"]
                    evidence = requests.get(f"{API_BASE}/admin/provenance/receipts/{receipt_id}/verify", headers=headers, timeout=30)
                    if evidence.status_code == 200:
                        st.json(evidence.json())
                    else:
                        st.error("Evidence verification failed")
                # Detail JSON
                if w.get("detail"):
                    try:
                        detail = json.loads(w["detail"]) if isinstance(w["detail"], str) else w["detail"]
                        if isinstance(detail, dict):
                            if detail.get("profile_evidence_status") == "not_fetched":
                                st.info("Interest-only finding: no ORCID profile was available for this account.")
                            elif detail.get("profile_evidence_status") == "no_public_works":
                                st.info("Interest-only finding: the fetched ORCID record had no usable public works.")
                            if detail.get("profile_source_kind") == "synthetic":
                                st.info("This warning uses a signed synthetic demo profile, not a live ORCID profile.")
                            detail_cols = st.columns(2)
                            for i, (k, v) in enumerate(detail.items()):
                                with detail_cols[i % 2]:
                                    st.markdown(f"**{k}:** {v}")
                        else:
                            st.json(detail)
                    except (json.JSONDecodeError, TypeError):
                        st.text(str(w["detail"]))

                st.caption(f"Created: {w['created_at']}")

                # ── Actions ──
                if verified and w["status"] == "pending":
                    action_cols = st.columns(3)
                    with action_cols[0]:
                        if st.button("✅ Mark Reviewed", key=f"review_{w['id']}"):
                            resp_patch = requests.patch(
                                f"{API_BASE}/admin/detector/warnings/{w['id']}",
                                headers=headers,
                                json={"status": "reviewed"},
                                timeout=10,
                            )
                            if resp_patch.status_code == 200:
                                st.rerun()
                    with action_cols[1]:
                        if st.button("❌ Dismiss", key=f"dismiss_{w['id']}"):
                            resp_patch = requests.patch(
                                f"{API_BASE}/admin/detector/warnings/{w['id']}",
                                headers=headers,
                                json={"status": "dismissed"},
                                timeout=10,
                            )
                            if resp_patch.status_code == 200:
                                st.rerun()

                # ── View user profile ──
                if st.button("📋 View User Profile", key=f"profile_{w['id']}"):
                    profile_resp = requests.get(
                        f"{API_BASE}/admin/detector/user/{w['user_id']}/profile",
                        headers=headers,
                        timeout=10,
                    )
                    if profile_resp.status_code == 200:
                        p = profile_resp.json()
                        st.markdown(f"**Username:** {p['username']}")
                        st.markdown(f"**ORCID:** {p['orcid_id']}")
                        st.markdown(f"**Research Interest:** {p.get('research_interest', 'N/A')}")
                        st.markdown(f"**Topic Summary:** {p.get('topic_summary', 'N/A')}")
                        source_kind = p.get("profile_source_kind")
                        if source_kind == "synthetic":
                            st.info("Profile source: signed synthetic demo data; no ORCID lookup was performed.")
                        elif source_kind == "orcid_public_api":
                            st.caption("Profile source: ORCID public API, as observed by Profiler.")
                        score_cols = st.columns(3)
                        score_cols[0].metric("Interest Score", f"{p.get('interest_score', 'N/A')}")
                        score_cols[1].metric("Publication Score", f"{p.get('publication_score', 'N/A')}")
                        score_cols[2].metric("Query Count", p.get("query_count", 0))


# ══════════════════════════════════════════════════════
# TAB 2: Clusterer Persona & Anomaly Analysis
# ══════════════════════════════════════════════════════
with tab_clusterer:
    st.subheader("Persona Clustering & Anomaly Detection (Clusterer Agent)")

    col_run, col_save = st.columns(2)
    with col_run:
        run_btn = st.button("▶️ Run Analysis", type="primary")
    with col_save:
        save_btn = st.button("💾 Run & Save Artifacts")

    # Run analysis on button click
    if run_btn or save_btn:
        endpoint = "/admin/clusterer/analyze/save" if save_btn else "/admin/clusterer/analyze"
        with st.spinner("Running Clusterer pipeline (clustering + anomaly detection)..."):
            resp = requests.post(f"{API_BASE}{endpoint}", headers=headers, timeout=120)

        if resp.status_code != 200:
            st.error(f"Analysis failed: {resp.text}")
        else:
            result = resp.json()
            st.session_state["clusterer_result"] = result
            if save_btn:
                output_path = result.get("summary", {}).get("output_path", "output/clusterer/")
                st.success(f"Analysis complete. Artifacts saved to `{output_path}`")
            else:
                st.success("Analysis complete.")

    # Display results if available
    result = st.session_state.get("clusterer_result")
    if result:
        check = requests.get(f"{API_BASE}/admin/provenance/runs/{result.get('run_id', '')}/verify", headers=headers, timeout=30)
        if check.status_code != 200:
            st.error("Clusterer evidence or artifacts failed verification.")
            st.stop()
        result = check.json()["result"]
        st.caption("Verified Clusterer result, input evidence, and saved artifacts")
        summary = result.get("summary", {})
        if "synthetic" in summary.get("input_source_kinds", []):
            st.info("This analysis includes signed synthetic demo query history.")

        # ── Summary metrics ──
        s1, s2, s3 = st.columns(3)
        s1.metric("Users Analyzed", summary.get("n_users", 0))
        s2.metric("Query Events", summary.get("n_events", 0))
        s3.metric("Personas Found", summary.get("selected_personas", 0))

        st.markdown("---")

        # ── Persona Report ──
        persona_report = result.get("persona_report", {})
        st.markdown("### Persona Clusters")

        personas = persona_report.get("personas", [])
        if personas:
            for p in personas:
                with st.expander(f"Persona {p['persona_label']} — {p['member_count']} member(s)"):
                    st.markdown(f"**Members:** {p['member_count']}")
                    # Show top features
                    means = p.get("feature_means", {})
                    # Filter to most interesting features (non-SVD, non-zero)
                    interesting = {
                        k: round(v, 4) for k, v in sorted(means.items(), key=lambda x: abs(x[1]), reverse=True)
                        if abs(v) > 0.01
                    }
                    if interesting:
                        top_features = dict(list(interesting.items())[:15])
                        st.json(top_features)

            # User-persona assignments
            user_assignments = persona_report.get("users", [])
            if user_assignments:
                st.markdown("#### User Assignments")
                assignment_data = [
                    {"User ID": u["user_id"], "Persona": u["persona_label"]}
                    for u in user_assignments
                ]
                st.dataframe(assignment_data, use_container_width=True)

        st.markdown("---")

        # ── Anomaly Report ──
        anomaly_report = result.get("anomaly_report", {})
        st.markdown("### Anomaly Detection")

        # Cross-user anomalies
        user_anomalies = anomaly_report.get("user_anomalies", [])
        if user_anomalies:
            st.markdown("#### Cross-User Anomalies (LOF)")
            flagged = [u for u in user_anomalies if u.get("cross_user_anomaly")]
            if flagged:
                for u in flagged:
                    st.warning(
                        f"🚨 **User #{u['user_id']}** flagged — "
                        f"Anomaly Score: {u['cross_user_anomaly_score']:.3f}"
                    )
            else:
                st.info("No cross-user anomalies detected.")

            # Full table
            with st.expander("All user anomaly scores"):
                anomaly_data = [
                    {
                        "User ID": u["user_id"],
                        "Anomaly Score": round(u["cross_user_anomaly_score"], 4),
                        "Flagged": "Yes" if u["cross_user_anomaly"] else "No",
                    }
                    for u in sorted(user_anomalies, key=lambda x: x["cross_user_anomaly_score"])
                ]
                st.dataframe(anomaly_data, use_container_width=True)

        # Event-level anomalies
        event_anomalies = anomaly_report.get("event_anomalies", [])
        if event_anomalies:
            st.markdown("#### Top Event-Level Anomalies (Within-User)")
            event_data = [
                {
                    "User ID": e["user_id"],
                    "Anomaly Score": round(e["within_user_anomaly_score"], 4),
                    "Flagged": "Yes" if e["within_user_anomaly"] else "No",
                    "Prompt Length": int(e.get("prompt_length", 0)),
                    "Response Length": int(e.get("response_length", 0)),
                }
                for e in event_anomalies
            ]
            st.dataframe(event_data, use_container_width=True)
    else:
        st.info("Click **Run Analysis** to generate Clusterer reports.")
