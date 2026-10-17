# Logistics Autopilot - Steering Rules

Always-on rules for any agent or engineer working in this repo.
Source of truth for scope: `PRD.md` (hackathon brief) and `docs/SPEC.md`.

## Objective
GDG hackathon MVP: an autonomous logistics handler agent that takes a natural-language
shipment request and drives it end to end (validate, inventory, reserve, pick, package,
route, book carrier, verify persisted result, report). It must really work, not just look good.

## Mandatory GDG criteria (all must be implemented, not described)
1. Agent SDK: Google ADK (`google-adk`).
2. Multi-model: a fast model for parsing/chat, a stronger model for failure diagnosis.
3. Conversational agent: `/api/chat` to request, inspect and manage logistics.
4. API integration: FastAPI + Google Maps (Distance Matrix) with simulated-carrier APIs.
5. MCP: all logistics tools are served by an MCP server and consumed through an MCP client.
6. Feedback loop: observe -> evaluate with evidence -> adjust next action.
7. Self-healing: carrier failure is diagnosed and re-planned with an eligible alternative.

## Architecture invariants
- One orchestrator (`backend/app/orchestrator.py`), a registered tool set (`tools.py`,
  exposed by `mcp_server.py`), and an explicit state machine (`state_machine.py`).
- The LLM may parse requests, interpret failures and chat. It MUST NOT write DB rows,
  and MUST NOT decide that a step succeeded. Success = evidence read from SQLite.
- Every LLM-assisted step has a deterministic fallback so the demo works with no API key.
- Only the orchestrator changes order status, and only through `state_machine.transition`.
- Inventory reservation is atomic (`BEGIN IMMEDIATE`) and idempotent per order.
- Shipments are idempotent per `idempotency_key` (UNIQUE constraint, race-safe).

## Hard constraints (from PRD)
- No disconnected buttons. No UI-only state standing in for backend results.
- Never fabricate carrier bookings, tracking, or verification results.
- Do not claim tests passed unless they were run. Quote real output.
- Do not overwrite unrelated files. No unnecessary abstractions.
- Keep the app runnable after every milestone.

## Conventions
- Backend: Python 3.12, FastAPI, SQLite (WAL), pytest. Run from `backend/` with `.venv`.
- Frontend: React + TypeScript + Vite, vanilla CSS, `lucide-react` icons.
- Secrets only in `backend/.env` (gitignored). Document every variable in `.env.example`.
- Tests use a temp DB via `LOGISTICS_DB_PATH`. Never touch `logistics.db` from tests.
