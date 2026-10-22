"""Clusterer pipeline adapted for TCP.

Replaces the original pipeline.py's SQLite ingestion with the TCP adapter,
then runs the same analytics: feature engineering → persona clustering →
anomaly detection → reporting.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .anomaly_detection import score_cross_user_anomalies, score_within_user_anomalies
from .feature_engineering import build_user_feature_matrix
from .persona_model import assign_personas, choose_num_personas, fit_persona_model
from .reporting import build_anomaly_report, build_persona_report


def run_pipeline(
    sqlite_path: str,
    output_dir: str | None = None,
    min_personas: int = 2,
    max_personas: int = 6,
    max_text_features: int = 100,
    svd_components: int = 20,
    flat_table: pd.DataFrame | None = None,
) -> dict:
    """Run the full clusterer analysis pipeline against TCP's database.

    Returns a dict with summary, persona_report, and anomaly_report.
    Optionally saves CSV/JSON artifacts to output_dir.
    """
    if flat_table is None:
        raise ValueError("Clusterer requires verified input from its API service")
    if flat_table.empty:
        raise ValueError("No query history records found in the database.")

    user_feature_matrix = build_user_feature_matrix(
        flat_table,
        max_text_features=max_text_features,
        svd_components=svd_components,
    )

    selected_personas = choose_num_personas(
        user_feature_matrix, min_k=min_personas, max_k=max_personas,
    )
    persona_model = fit_persona_model(user_feature_matrix, selected_personas)
    persona_labels = assign_personas(user_feature_matrix, persona_model)

    event_anomalies = score_within_user_anomalies(flat_table)
    user_anomalies = score_cross_user_anomalies(user_feature_matrix)

    persona_report = build_persona_report(user_feature_matrix, persona_labels)
    anomaly_report = build_anomaly_report(event_anomalies, user_anomalies)

    summary = {
        "n_users": int(user_feature_matrix.shape[0]),
        "n_events": int(flat_table.shape[0]),
        "selected_personas": int(selected_personas),
    }

    # Optionally persist artifacts
    if output_dir:
        from .reporting import save_dataframe, save_json_report

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        save_json_report(persona_report, out / "persona_report.json")
        save_json_report(anomaly_report, out / "anomaly_report.json")
        save_json_report(summary, out / "summary_report.json")
        save_dataframe(user_feature_matrix, out / "user_feature_matrix.csv")
        save_dataframe(event_anomalies, out / "event_anomalies.csv")
        save_dataframe(user_anomalies, out / "user_anomalies.csv")
        summary["output_path"] = str(out.resolve())

    return {
        "summary": summary,
        "persona_report": persona_report,
        "anomaly_report": anomaly_report,
    }
