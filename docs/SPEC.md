# Logistics Autopilot - Spec

## Gap analysis (codebase vs PRD, as of 12:28)

| Requirement | Status | Action |
|---|---|---|
| Dashboard, request UI, seeds, persistence | Done | Polish, chat panel, agent trace |
| Explicit states + validated transitions | Partial: states exist, not enforced | Add `state_machine.py`, enforce |
| Atomic reservation | Done (BEGIN IMMEDIATE) | Add concurrency test |
| Idempotency | Partial: check-then-insert race | Catch UNIQUE violation, test threads |
| Timeline with elapsed time | Done | Add agent/LLM steps |
| Carrier failure + alternative | Done | Add LLM diagnosis + feedback loop |
| Persisted verification | Done | Also commit reservations; no overclaiming |
| Reset + scenarios | Done | Keep |
| Tests | 5 pass | Add transitions, concurrency, MCP, chat, API |
| Agent SDK (ADK) | Missing | `agent.py` |
| Multi-model | Missing | flash for parse/chat, pro for diagnosis |
| Conversational agent | Missing | `/api/chat` + UI panel |
| MCP | Missing | `mcp_server.py` + client |
| Google Maps | Missing | `maps.py` with simulated fallback |
| Feedback loop | Missing | Evaluate each tool result, adjust plan |
| README, GitHub | Missing | README, git init + commit |

## State machine
SUBMITTED -> VALIDATED -> INVENTORY_CHECKED -> INVENTORY_RESERVED -> ITEMS_PICKED
-> PACKAGED -> CARRIER_BOOKED -> VERIFIED -> COMPLETED
Side edges: CARRIER_BOOKING_FAILED/RETRYING (from PACKAGED), any non-terminal -> FAILED.
COMPLETED and FAILED are terminal. Illegal transitions raise `InvalidTransition`.

## Agent design
- Orchestrator runs the plan; each step is a tool call over MCP (stdio client -> `mcp_server.py`).
- Feedback loop: after each tool, `evaluate()` compares the result to persisted evidence.
  On mismatch or tool error, it chooses: retry, alternative, or fail (with reservation release).
- LLM roles (ADK agents, `agent.py`):
  - ParserAgent (gemini-flash): NL -> structured order JSON. Validated against the catalog.
  - DiagnosisAgent (gemini-pro): reads a failure + eligible alternatives, proposes an action.
    The orchestrator only accepts proposals that name an eligible carrier id from the DB.
  - ChatAgent (gemini-flash): conversational control; calls MCP tools for read/inspect/ship.
- Fallbacks: regex parser and rule-based diagnosis, used when no key or on any LLM error.
  Timeline records which path ran (`llm` or `deterministic`).

## Google APIs
- Gemini via ADK. Maps Distance Matrix for distance/ETA from warehouse to destination;
  if no key or the call fails, a seeded city table is used and the step is marked `simulated`.

## Acceptance checks
1. Happy path completes; DB shows order, items, RESERVED rows, tracking id.
2. Carrier outage -> WARNING -> RECOVERED with a different eligible carrier.
3. Same idempotency key twice -> same order, stock reserved once.
4. 20 concurrent orders for limited stock -> no oversell.
5. Illegal transition rejected.
6. Reset restores seeds. 7. MCP server lists and executes tools. 8. `/api/chat` works offline.
