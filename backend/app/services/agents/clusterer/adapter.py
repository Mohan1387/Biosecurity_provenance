"""Adapter: map TCP's SQLAlchemy tables to the flat DataFrame clusterer expects.

TCP schema:
  users        (id, username, orcid_id, tier, created_at, ...)
  query_history (id, user_id, query_text, response_summary, timestamp, ...)
  data_access_log (id, user_id, dataset_tier, timestamp, ...)

clusterer expected flat table columns:
  user_id, username, email, user_first_login, user_last_login,
  tier, session_id, prompt_id, prompt_text, response_text,
  prompt_length, response_length, event_timestamp
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def build_flat_table_from_tcp(sqlite_path: str) -> pd.DataFrame:
    """Read TCP's SQLite and produce the flat event table clusterer expects."""
    path = Path(sqlite_path)
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    conn = sqlite3.connect(str(path))
    try:
        users = pd.read_sql_query(
            "SELECT id AS user_id, username, tier, created_at FROM users",
            conn,
        )
        queries = pd.read_sql_query(
            "SELECT id AS prompt_id, user_id, query_text AS prompt_text, "
            "response_summary AS response_text, timestamp AS event_timestamp "
            "FROM query_history ORDER BY user_id, timestamp",
            conn,
        )
    finally:
        conn.close()

    return build_flat_table(users, queries)


def build_flat_table(users: pd.DataFrame, queries: pd.DataFrame) -> pd.DataFrame:
    """Transform the exact verified in-memory records (no second database read)."""

    if queries.empty:
        return pd.DataFrame()

    # Normalize timestamps
    users["created_at"] = pd.to_datetime(users["created_at"], errors="coerce")
    queries["event_timestamp"] = pd.to_datetime(queries["event_timestamp"], errors="coerce")

    # Derive user login windows from query timestamps
    query_windows = queries.groupby("user_id")["event_timestamp"].agg(["min", "max"])
    query_windows.columns = ["user_first_login", "user_last_login"]
    users = users.merge(query_windows, left_on="user_id", right_index=True, how="left")

    # Fill users with no queries using created_at
    users["user_first_login"] = users["user_first_login"].fillna(users["created_at"])
    users["user_last_login"] = users["user_last_login"].fillna(users["created_at"])

    # TCP has no session concept; use user_id as session_id
    queries["session_id"] = queries["user_id"]

    # Merge user info onto queries
    flat = queries.merge(
        users[["user_id", "username", "tier", "user_first_login", "user_last_login"]],
        on="user_id",
        how="left",
    )

    # Add computed length columns
    flat["prompt_text"] = flat["prompt_text"].fillna("")
    flat["response_text"] = flat["response_text"].fillna("")
    flat["prompt_length"] = flat["prompt_text"].str.len()
    flat["response_length"] = flat["response_text"].str.len()
    flat["email"] = ""  # TCP doesn't store email

    # Reorder to match clusterer expected schema
    column_order = [
        "user_id", "username", "email", "user_first_login", "user_last_login",
        "tier", "session_id", "prompt_id", "prompt_text", "response_text",
        "prompt_length", "response_length", "event_timestamp",
    ]
    flat = flat[[col for col in column_order if col in flat.columns]]
    return flat
