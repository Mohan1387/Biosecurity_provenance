# TCP Agents

This directory contains all agent definitions for the TCP (Tiered Compute Platform).

Each agent lives in its own subdirectory with a plan, configuration, and service code.

## Agent Registry

| Agent | Owner | Status | Description |
|-------|-------|--------|-------------|
| `detector/` | Sam | Planning | Research behavior anomaly detection via ORCID + query history |
| `profiler/` | Sam | Planning | ORCID publication fetcher and research profile builder |
| `logger/` | TBD | Planning | Collects user activity into the SQL audit database |

## Adding a New Agent

1. Create a subdirectory: `agents/<agent_name>/`
2. Add a `plan.md` describing the agent's purpose, inputs, outputs, and triggers
3. Implement the service in `backend/app/services/agents/<agent_name>.py`
4. Register any tools in `backend/app/services/tools.py`
5. Update this README with the agent entry
