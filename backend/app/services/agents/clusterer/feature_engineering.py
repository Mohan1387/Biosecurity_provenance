from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler


def extract_user_behavior_features(flat_table: pd.DataFrame) -> pd.DataFrame:
    event_table = flat_table.copy()
    event_table = event_table.assign(
        prompt_length=event_table["prompt_length"].fillna(0).astype(float),
        response_length=event_table["response_length"].fillna(0).astype(float),
    )
    event_table["event_timestamp"] = pd.to_datetime(event_table["event_timestamp"], errors="coerce")
    event_table["event_hour"] = event_table["event_timestamp"].dt.hour.fillna(-1).astype(int)

    grouped = event_table.groupby("user_id")
    summary = grouped.agg(
        total_prompts=("prompt_id", "count"),
        unique_sessions=("session_id", "nunique"),
        unique_tiers=("tier", "nunique"),
        avg_prompt_length=("prompt_length", "mean"),
        median_prompt_length=("prompt_length", "median"),
        prompt_length_std=("prompt_length", "std"),
        avg_response_length=("response_length", "mean"),
        median_response_length=("response_length", "median"),
        response_length_std=("response_length", "std"),
        active_days=("event_timestamp", lambda x: (x.max() - x.min()).days if x.notna().any() else 0),
        avg_event_hour=("event_hour", "mean"),
        prompt_hour_std=("event_hour", "std"),
    )

    summary["prompt_length_std"] = summary["prompt_length_std"].fillna(0.0)
    summary["response_length_std"] = summary["response_length_std"].fillna(0.0)
    summary["prompt_hour_std"] = summary["prompt_hour_std"].fillna(0.0)
    summary["active_days"] = summary["active_days"].fillna(0).astype(float)
    summary["event_rate_per_day"] = summary.apply(
        lambda row: row["total_prompts"] / max(row["active_days"], 1), axis=1
    )

    numeric_cols = [
        "total_prompts",
        "unique_sessions",
        "unique_tiers",
        "avg_prompt_length",
        "median_prompt_length",
        "prompt_length_std",
        "avg_response_length",
        "median_response_length",
        "response_length_std",
        "active_days",
        "event_rate_per_day",
        "avg_event_hour",
        "prompt_hour_std",
    ]

    summary[numeric_cols] = summary[numeric_cols].fillna(0.0)
    return summary


def vectorize_prompt_history(
    flat_table: pd.DataFrame,
    max_features: int = 100,
    svd_components: int = 20,
) -> pd.DataFrame:
    prompt_table = flat_table.copy()
    prompt_table["prompt_text"] = prompt_table["prompt_text"].fillna("")

    if prompt_table.empty:
        return pd.DataFrame(index=pd.Index([], name="user_id"))

    vectorizer = TfidfVectorizer(max_features=max_features, stop_words="english")
    prompt_matrix = vectorizer.fit_transform(prompt_table["prompt_text"])
    if prompt_matrix.shape[0] == 0:
        return pd.DataFrame(index=prompt_table["user_id"].unique(), dtype=float)

    group_ids = prompt_table["user_id"].astype(str).tolist()
    users = prompt_table["user_id"].astype(str).values
    df_prompt = pd.DataFrame(prompt_matrix.toarray(), index=prompt_table.index)

    if prompt_matrix.shape[1] > 1 and prompt_matrix.shape[0] > 1:
        n_components = min(svd_components, prompt_matrix.shape[0] - 1, prompt_matrix.shape[1] - 1)
        if n_components > 0:
            svd = TruncatedSVD(n_components=n_components, random_state=42)
            reduced = svd.fit_transform(df_prompt)
            df_prompt = pd.DataFrame(reduced, index=prompt_table.index)

    df_prompt["user_id"] = users
    user_prompt_summary = df_prompt.groupby("user_id").mean()
    user_prompt_summary.index = user_prompt_summary.index.astype(int)
    user_prompt_summary = user_prompt_summary.add_prefix("text_feature_")
    user_prompt_summary.index.name = "user_id"
    return user_prompt_summary


def build_user_feature_matrix(
    flat_table: pd.DataFrame,
    max_text_features: int = 100,
    svd_components: int = 20,
) -> pd.DataFrame:
    behavior = extract_user_behavior_features(flat_table)
    text_features = vectorize_prompt_history(flat_table, max_features=max_text_features, svd_components=svd_components)

    features = behavior.join(text_features, how="left").fillna(0.0)

    scaler = StandardScaler()
    scaled_values = scaler.fit_transform(features)
    scaled = pd.DataFrame(scaled_values, index=features.index, columns=features.columns)
    scaled.index.name = "user_id"
    return scaled
