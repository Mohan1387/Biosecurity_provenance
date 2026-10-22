# Logger Agent -- User Activity Aggregation

## Purpose

The Logger is a background agent that continuously aggregates user activity from platform events into structured SQL tables. It serves as the data pipeline that feeds Detector and any future monitoring agents.

## Responsibilities

1. **Login tracking**: Record every login event (timestamp, IP, success/fail)
2. **Data access logging**: Record which datasets a user accesses, at which tier, and when
3. **Query history**: Store all chat queries sent through the LLM agent
4. **Activity summaries**: Periodic rollups of per-user activity metrics

## Data Flow

```
Platform Events (API requests, chat, data access)
        |
        v
   Audit Middleware (already in Phase 3)
        |
        v
   Logger (enriches + normalizes into dedicated tables)
        |
        v
   data_access_log, query_history tables
        |
        v
   Detector reads for anomaly detection
```

## New Tables

### `data_access_log`
| Column | Type | Description |
|--------|------|-------------|
| id | int PK | Auto-increment |
| user_id | int FK | References users.id |
| dataset_name | str | Name of dataset accessed |
| dataset_tier | enum | open/controlled/restricted |
| access_type | str | "query" / "download" / "view" |
| timestamp | datetime | When the access occurred |

### `query_history`
| Column | Type | Description |
|--------|------|-------------|
| id | int PK | Auto-increment |
| user_id | int FK | References users.id |
| query_text | text | The user's chat message |
| tools_invoked | text (JSON) | Which tools the agent called |
| response_summary | text | Brief summary of agent response |
| timestamp | datetime | When the query was made |

## Dependencies

- Phase 3 (Audit logging middleware) provides the raw event stream
- Builds on existing `AuditLog` and `LLMUsage` tables

## New Files

```
agents/logger/plan.md                    -- this file
backend/app/services/agents/logger.py    -- collector service
backend/app/models.py                             -- add DataAccessLog, QueryHistory models
```

## Open Questions

- [ ] Should the collector run as async middleware (inline) or as a periodic batch job?
- [ ] Retention policy for query_history? (privacy considerations)
- [ ] Should raw audit_log entries be pruned after collector processes them?
