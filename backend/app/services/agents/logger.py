"""Logger Agent -- User Activity Aggregation.

Records query history and data access events into dedicated tables
that feed the Detector anomaly detection agent.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataAccessLog, QueryHistory, Tier
from app.services.provenance import sign_row

logger = logging.getLogger("logger")


async def record_query(
    db: AsyncSession,
    user_id: int,
    query_text: str,
    tools_invoked: list[dict] | None = None,
    response_summary: str | None = None,
) -> QueryHistory:
    """Record a chat query into the query_history table."""
    entry = QueryHistory(
        user_id=user_id,
        query_text=query_text,
        tools_invoked=json.dumps(tools_invoked) if tools_invoked else None,
        response_summary=response_summary[:500] if response_summary else None,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(entry)
    await sign_row(db, entry, "logger", processing={"operation": "record_query", "version": 1,
                                                     "source_kind": "live_chat"})
    logger.debug("Recorded query for user %d: %s", user_id, query_text[:80])
    return entry


async def record_data_access(
    db: AsyncSession,
    user_id: int,
    dataset_name: str,
    dataset_tier: Tier,
    access_type: str = "query",
) -> DataAccessLog:
    """Record a dataset access event."""
    entry = DataAccessLog(
        user_id=user_id,
        dataset_name=dataset_name,
        dataset_tier=dataset_tier,
        access_type=access_type,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(entry)
    await sign_row(db, entry, "logger", processing={"operation": "record_data_access", "version": 1,
                                                     "source_kind": "live_chat"})
    logger.debug("Recorded %s access to %s for user %d", access_type, dataset_name, user_id)
    return entry
