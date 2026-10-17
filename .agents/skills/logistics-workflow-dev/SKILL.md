---
name: logistics-workflow-dev
description: How to run, test, extend and demo the Logistics Autopilot project. Use when adding a tool, changing the workflow or state machine, running tests, or preparing the demo.
---

# Logistics Autopilot dev skill

## Run
```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000      # API
cd frontend && npm run dev                                     # UI on :5173 (proxies /api)
```

## Test (always run before claiming anything passes)
```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run build
```

## Add a tool
1. Implement a plain typed function in `backend/app/tools.py` (reads/writes SQLite itself).
2. Register it in `mcp_server.py` with `@mcp.tool()`.
3. Call it from the orchestrator through `mcp_client.call(...)`, never directly.
4. Record a `workflow_steps` row (name, tool, status, input, output, elapsed_ms).
5. Add a test.

## Add a state
Edit the transition table in `state_machine.py`, then add a test for legal and illegal edges.

## Demo script (about 3 min)
1. Reset. 2. "Happy path" scenario. 3. "Carrier outage" scenario: show WARNING then RECOVERED.
4. Re-send the idempotency scenario: same order, stock unchanged. 5. Ask the chat
"where is my last shipment?". 6. Show the verification card and `pytest` output.
