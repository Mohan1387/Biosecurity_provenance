from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neighbors import LocalOutlierFactor


def score_within_user_anomalies(flat_table: pd.DataFrame) -> pd.DataFrame:
    table = flat_table.copy()
    table["prompt_length"] = table["prompt_length"].fillna(0).astype(float)
    table["response_length"] = table["response_length"].fillna(0).astype(float)
    table["event_timestamp"] = pd.to_datetime(table["event_timestamp"], errors="coerce")

    def zscore(series: pd.Series) -> pd.Series:
        mean = series.mean()
        std = series.std(ddof=0)
        if std == 0:
            return pd.Series(0.0, index=series.index)
        return (series - mean).abs() / std

    table["prompt_length_z"] = table.groupby("user_id")["prompt_length"].transform(zscore)
    table["response_length_z"] = table.groupby("user_id")["response_length"].transform(zscore)
    table["within_user_anomaly_score"] = table[["prompt_length_z", "response_length_z"]].max(axis=1)
    table["within_user_anomaly"] = table["within_user_anomaly_score"] > 3.0
    return table


def score_cross_user_anomalies(
    user_features: pd.DataFrame,
    n_neighbors: int = 20,
    contamination: float = 0.1,
) -> pd.DataFrame:
    if user_features.shape[0] < 2:
        output = user_features.copy()
        output["cross_user_anomaly_score"] = 0.0
        output["cross_user_anomaly"] = False
        return output

    n_neighbors = min(n_neighbors, user_features.shape[0] - 1)
    lof = LocalOutlierFactor(n_neighbors=n_neighbors, contamination=contamination)
    labels = lof.fit_predict(user_features)
    negative_factor = lof.negative_outlier_factor_
    scores = -negative_factor

    result = user_features.copy()
    result["cross_user_anomaly_score"] = scores
    result["cross_user_anomaly"] = labels == -1
    return result
