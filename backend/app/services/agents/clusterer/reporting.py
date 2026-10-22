from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def build_persona_report(user_features: pd.DataFrame, persona_labels: pd.Series) -> dict:
    report = {
        "personas": [],
        "users": [],
    }
    combined = user_features.copy()
    combined["persona_label"] = persona_labels

    for persona_label, group in combined.groupby("persona_label"):
        report["personas"].append(
            {
                "persona_label": int(persona_label),
                "member_count": int(group.shape[0]),
                "feature_means": group.drop(columns=["persona_label"]).mean().to_dict(),
            }
        )

    for user_id, row in combined.iterrows():
        report["users"].append(
            {
                "user_id": int(user_id),
                "persona_label": int(row["persona_label"]),
                "features": row.drop(labels=["persona_label"]).to_dict(),
            }
        )
    return report


def build_anomaly_report(event_anomalies: pd.DataFrame, user_anomalies: pd.DataFrame) -> dict:
    report = {
        "event_anomalies": [],
        "user_anomalies": [],
    }

    for _, row in event_anomalies.sort_values("within_user_anomaly_score", ascending=False).head(25).iterrows():
        report["event_anomalies"].append(
            {
                "user_id": int(row["user_id"]),
                "prompt_id": int(row.get("prompt_id", -1)) if pd.notna(row.get("prompt_id")) else None,
                "within_user_anomaly_score": float(row["within_user_anomaly_score"]),
                "within_user_anomaly": bool(row["within_user_anomaly"]),
                "prompt_length": float(row["prompt_length"]),
                "response_length": float(row["response_length"]),
            }
        )

    for user_id, row in user_anomalies.iterrows():
        report["user_anomalies"].append(
            {
                "user_id": int(user_id),
                "cross_user_anomaly_score": float(row["cross_user_anomaly_score"]),
                "cross_user_anomaly": bool(row["cross_user_anomaly"]),
            }
        )

    return report


def save_json_report(report: dict, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)


def save_dataframe(df: pd.DataFrame, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=True)
