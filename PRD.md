We have exactly 90 minutes to build a complete GDG hackathon MVP called Logistics Autopilot.

Act as a senior engineer focused on end-to-end execution, not code generation for its own sake. Build the smallest reliable application that demonstrates an autonomous logistics workflow.

PRODUCT:
A user requests a shipment in natural language. The system validates the order, checks inventory, reserves stock, picks items, packages them, creates a shipment, generates a tracking ID, verifies the persisted result, and presents a final execution report.

REQUIRED:
1. A polished, responsive logistics operations dashboard.
2. A working shipment request interface.
3. Seeded products, two warehouses, inventory, packaging options and simulated carriers.
4. A complete backend workflow with persistent state.
5. Explicit workflow states and validated state transitions.
6. Atomic or otherwise concurrency-safe inventory reservation.
7. Idempotent operations to prevent duplicate reservations and shipments.
8. A visible execution timeline with tool results and elapsed time.
9. A failure-recovery demonstration, preferably a carrier failure followed by an eligible alternative.
10. A final verification step based on persisted backend records.
11. A deterministic demo reset and predefined scenario buttons.
12. Automated checks for the core workflow and recovery.

TECHNICAL APPROACH:
Inspect the existing workspace first. Reuse a working scaffold if one exists. If starting from scratch, use React + TypeScript + Vite for the frontend and Python + FastAPI + SQLite for the backend. Keep the architecture small and run everything locally.

AGENT DESIGN:
Use one orchestrator, a registered set of typed tools and an explicit state machine. The LLM may parse requests and help interpret failures, but it must not write database records directly or decide that an operation succeeded without evidence. Provide a deterministic scenario path if the LLM is unavailable.

EXECUTION STRATEGY:
Work in milestones. First make the backend happy path execute and persist correctly. Then add recovery. Then connect the UI. Do not spend time on MCP, Google Maps, multimodal input, custom model training, multiple independent agents, or real carrier integrations.

HARD CONSTRAINTS:
- Do not leave buttons disconnected.
- Do not use fake UI-only state to represent completed backend operations.
- Do not fabricate carrier bookings, deliveries or verification results.
- Do not overwrite unrelated existing project files.
- Do not build abstractions that are unnecessary for this MVP.
- Do not claim tests passed unless they were actually run.
- Preserve a working application at every milestone.

TIME MANAGEMENT:
Prioritize a running application with a complete happy path over additional features. If behind schedule, remove optional features rather than compromising the core workflow. Reserve the final 8 minutes for a clean demonstration and submission.

Start by inspecting the workspace and reporting the existing project structure. Then implement the first milestone immediately. Do not stop after producing a plan; write the code, run it, test it and fix integration failures.




# GDG Hackathon — Logistics Handler Agent

## 1. Objective

Build a fully functional, end-to-end logistics handler agent that automates a supply-chain workflow. The chosen scenario may involve warehouse or godown management, inventory handling, packaging, shipping, or a combination of these operations.

The application must demonstrate a complete working workflow, not merely a UI prototype or a partially implemented agent.

## 2. Required Toolsets

- **Agent SDK:** Use an agent SDK to implement agent orchestration, tool calling, and the required agent behaviors.
- **Google Products and APIs:** Integrate relevant Google products or APIs where they add practical value, such as Google Maps Platform for location and routing.

## 3. Mandatory Agent Criteria

1. **Multi-model agents:** Demonstrate the use of multiple models or specialized model-driven agent components where appropriate.
2. **Conversational agents:** Support natural-language interaction through which users can request, inspect, and manage logistics operations.
3. **API integration:** Use APIs to execute real or simulated logistics operations and retrieve relevant data.
4. **MCP integration:** Integrate the Model Context Protocol (MCP) to expose or consume tools and capabilities.
5. **Feedback loop:** Implement a closed-loop process in which the agent observes execution results, evaluates outcomes, and adjusts its next actions.
6. **Self-healing agents:** Detect failures, diagnose their causes, and automatically recover through safe retries, alternative plans, or corrective actions when possible.

## 4. Quality and Completeness Requirements

- Deliver a complete A-to-Z implementation with clear setup, execution, and usage instructions.
- Ensure the entire demonstrated workflow works end to end.
- Implement the required agent capabilities rather than merely describing them.
- Validate the workflow, handle failures, and verify the final outcome.
- Avoid incomplete integrations, nonfunctional controls, and undocumented dependencies.

## 5. Submission Requirements

- Host the project in a GitHub repository.
- Submit the repository link.
- Include a detailed README covering the application, architecture, agent design, dependencies, environment configuration, API setup, MCP integration, execution steps, testing, and troubleshooting.
- Ensure another developer can follow the instructions to configure, run, and evaluate the application.

## 6. Submission Priority

Submissions follow a first-come, first-served process. The application must therefore be implemented, tested, documented, pushed to GitHub, and submitted as early as practical without sacrificing the minimum required functionality.