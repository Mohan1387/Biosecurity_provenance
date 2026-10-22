from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


def choose_num_personas(
    feature_matrix: pd.DataFrame,
    min_k: int = 2,
    max_k: int = 6,
) -> int:
    if feature_matrix.shape[0] < min_k:
        return max(feature_matrix.shape[0], 1)

    best_k = min_k
    best_score = -1.0
    for k in range(min_k, min(max_k, feature_matrix.shape[0] - 1) + 1):
        model = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = model.fit_predict(feature_matrix)
        if len(set(labels)) <= 1:
            continue
        score = silhouette_score(feature_matrix, labels)
        if score > best_score:
            best_score = score
            best_k = k
    return best_k


def fit_persona_model(feature_matrix: pd.DataFrame, n_personas: int) -> KMeans:
    if n_personas <= 1 or feature_matrix.shape[0] < 2:
        return KMeans(n_clusters=1, random_state=42, n_init=10).fit(feature_matrix)
    return KMeans(n_clusters=n_personas, random_state=42, n_init=10).fit(feature_matrix)


def assign_personas(feature_matrix: pd.DataFrame, model: KMeans) -> pd.Series:
    labels = model.predict(feature_matrix)
    return pd.Series(labels, index=feature_matrix.index, name="persona_label")


def describe_personas(feature_matrix: pd.DataFrame, persona_labels: pd.Series) -> pd.DataFrame:
    labeled = feature_matrix.copy()
    labeled["persona_label"] = persona_labels
    description = labeled.groupby("persona_label").mean()
    description["member_count"] = labeled.groupby("persona_label").size()
    return description
