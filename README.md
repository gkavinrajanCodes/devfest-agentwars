# Logistics Autopilot

GDG hackathon project: an autonomous logistics handler agent. A user asks for a shipment in plain
English; the agent validates the order, checks stock across two warehouses, plans the route, reserves
stock atomically, picks, packages, books a carrier, verifies the result against persisted records and
produces an execution report. If the carrier fails, it diagnoses the failure and re-plans with an
eligible alternative.

## GDG criteria and where each one lives

| Criterion | Implementation |
|---|---|
| Agent SDK | Google ADK (`google-adk`), [`backend/app/agent.py`](backend/app/agent.py) |
| Multi-model agents | `gemini-2.5-flash` for parsing and chat, `gemini-2.5-pro` for failure diagnosis (env-configurable) |
| Conversational agent | `POST /api/chat` and the Operator Chat panel: ship, check stock, track, toggle outages |
| API integration | FastAPI backend, simulated carrier APIs, Google Maps Distance Matrix ([`maps.py`](backend/app/maps.py)) |
| MCP | [`mcp_server.py`](backend/app/mcp_server.py) serves 14 tools over stdio; the orchestrator calls every step through [`mcp_client.py`](backend/app/mcp_client.py) |
| Feedback loop | After each mutating step the orchestrator re-reads SQLite and compares it with the tool result (`evidence` in the timeline). A mismatch fails the step |
| Self-healing | Carrier failure -> state `RETRYING` -> eligible-carrier lookup -> diagnosis (LLM, validated against the DB, or rule-based) -> retry, up to 3 attempts. If recovery is exhausted, reserved stock is released |

## Architecture

```
React UI (Vite, :5173) --/api--> FastAPI (:8000) --> Orchestrator --MCP stdio--> mcp_server --> tools --> SQLite (WAL)
                                     |                   |
                                     |                   +--> state_machine (validated transitions)
                                     +--> /api/chat --> ADK ChatAgent --tools via MCP client
                               ParserAgent (flash) and DiagnosisAgent (pro) are consulted by the orchestrator
```

Rules the design enforces:

- The LLM can parse, diagnose and chat. It never writes DB rows and never decides that something succeeded.
- LLM output is validated: parsed product ids must exist in the catalog, and a proposed recovery carrier must be in the
  database's eligible list. Otherwise the deterministic path is used and the timeline says so (`parse: deterministic`, `diagnosis.source`).
- States: `SUBMITTED -> VALIDATED -> INVENTORY_CHECKED -> INVENTORY_RESERVED -> ITEMS_PICKED -> PACKAGED -> (RETRYING)* -> CARRIER_BOOKED -> VERIFIED -> COMPLETED`, plus `FAILED`. Illegal transitions raise.
- Reservation runs in a `BEGIN IMMEDIATE` transaction and is idempotent per order. Shipments are idempotent per
  `idempotency_key` (UNIQUE constraint, race-safe).
- Nothing is fabricated: tracking ids exist only after a carrier tool call that was persisted and re-read.
  Maps data is labelled `simulated` when the API key is missing or the call fails.

## Setup

Requirements: Python 3.12+, Node 20+.

```bash
# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in keys (optional, see below)

# frontend
cd ../frontend
npm install
```

### Environment (`backend/.env`)

| Variable | Needed | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | optional | Enables ADK agents (parser, diagnosis, chat). Without it the deterministic path runs |
| `GOOGLE_MAPS_API_KEY` | optional | Live distance/ETA via Distance Matrix API. Without it a seeded table is used and labelled `simulated` |
| `GEMINI_FAST_MODEL` / `GEMINI_PRO_MODEL` | optional | Override model names |
| `LLM_DISABLED=1` | optional | Force the deterministic path even if a key is set |
| `LOGISTICS_DB_PATH` | optional | SQLite file location (default `backend/logistics.db`) |

API setup: create a key at <https://aistudio.google.com/apikey> for Gemini. For Maps, enable the **Distance Matrix API** in
Google Cloud and create a key.

## Run

```bash
./run.sh            # starts API on :8000 and UI on :5173
```

or manually: `cd backend && .venv/bin/uvicorn app.main:app --port 8000` and `cd frontend && npm run dev`.
Open <http://localhost:5173>. The header shows what is actually active (MCP tool count, Gemini or deterministic, Maps live or sim).

MCP server standalone (for any MCP client): `cd backend && .venv/bin/python -m app.mcp_server`.

## Demo script (about 3 minutes)

1. **Demo reset**, then **Run now** on *Standard Express Dispatch*. Walk through the timeline: every step shows its MCP transport, elapsed ms and SQLite evidence, then the verification card and execution report.
2. **Run now** on *Carrier Outage & Autonomous Fallback*: `WARNING` with the diagnosis, then `RECOVERED` on a different eligible carrier.
3. Run *Duplicate Request* twice: same order, stock reserved once.
4. In chat: "how much stock is left?", "where is my last shipment?", "ship 1 thermal imaging core to Denver".
5. Show `pytest` output.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run build
```

Covers: happy path with evidence on every step, carrier recovery, exhausted recovery with stock release, state-machine
legality, concurrent reservations (no oversell), idempotency under parallel requests, reset, MCP over real stdio, LLM guardrails
(mocked model replies), offline chat, and the HTTP API. Tests never call Gemini or Maps; they use a temp DB.

## API

`POST /api/shipments`, `GET /api/shipments[/{id}]`, `GET /api/inventory`, `GET /api/carriers`, `POST /api/carriers/{id}/toggle-failure`,
`GET /api/demo/scenarios`, `POST /api/demo/reset`, `POST /api/chat`, `GET /api/agent/info`. Docs at <http://localhost:8000/docs>.

## Troubleshooting

- **Header says `DETERMINISTIC`**: no `GEMINI_API_KEY` in `backend/.env` (restart the API after adding it).
- **`MCP DOWN`**: the MCP subprocess failed to start; check `mcp_error` at `/api/agent/info`. The orchestrator then calls tools in-process and marks transport `direct`.
- **Port in use**: stop the old uvicorn/vite, or change ports (and the Vite proxy in `frontend/vite.config.ts`).
- **Stale data**: press *Demo Reset*.
- **LLM errors**: any model error falls back to the deterministic path; the chat reply shows `llm_error`.

## Repository layout

```
PRD.md                  brief
docs/SPEC.md            gap analysis and design
.agents/                steering rules and project skill
backend/app/            database, state_machine, tools, read_tools, maps, mcp_server, mcp_client, agent, orchestrator, main
backend/tests/          pytest suites
frontend/src/           React dashboard
```
