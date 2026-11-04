# KAIRO
## Product Requirements Document (PRD)
**Project:** Kairo — A Local-First Agent Execution Harness  
**Version:** 1.0  
**Team:** 2 Developers  
**Category:** AI Infrastructure / Agent Runtime / Developer Tools  
**Development Budget:** ₹0 additional spending  
**Target Platform:** macOS ARM64 for development, with portable Linux-compatible components  
**Development Approach:** Milestone-driven, test-first where practical, learning-oriented development with Codex

---

# 1. Executive Summary

Kairo is an open-source, local-first execution harness designed to run, coordinate, supervise, recover, and evaluate autonomous AI agents.

Rather than creating another AI chatbot or building a thin wrapper around an existing agent framework, Kairo aims to implement the underlying infrastructure that makes autonomous agents reliable.

The platform will provide:

- A custom agent execution runtime.
- A tool execution and permission system.
- Local LLM integration.
- Persistent execution state.
- Sandboxed command execution.
- Task scheduling and worker management.
- Checkpointing and crash recovery.
- Multi-agent task orchestration.
- Context and memory management.
- Execution tracing and observability.
- Human-in-the-loop approvals.
- Reproducible agent evaluations.
- An interactive web dashboard.

Kairo should eventually support multiple types of autonomous workflows, with software engineering agents serving as its first substantial use case.

The platform must be architected as an independent execution system, not as a dependency on a single LLM provider or coding-agent framework.

## Core Philosophy

**We are not building agents. We are building the infrastructure that allows agents to operate reliably.**

The development process is equally important as the final product.

Each milestone must introduce meaningful concepts from software engineering, systems programming, distributed systems, infrastructure, security, or AI engineering.

Codex is the development assistant, not a substitute for engineering understanding.

---

# 2. Problem Statement

Modern AI agents can generate text, reason about tasks, call tools, and interact with external environments.

However, the surrounding infrastructure introduces challenges:

1. Agents can fail midway through execution.
2. Tool calls can time out or produce inconsistent results.
3. Long-running workflows can exceed model context limits.
4. Multiple agents may conflict over shared resources.
5. Failed tasks may lose their execution history.
6. Retrying operations can cause duplicate side effects.
7. Agents may execute commands outside their intended permissions.
8. Developers may struggle to identify why a task failed.
9. Agent evaluation is often difficult to reproduce.
10. Human approval may be required before sensitive operations.

Several existing frameworks address subsets of these problems. Kairo is not intended to claim novelty for these individual capabilities.

Instead, Kairo will be a deliberately engineered, transparent implementation that brings them together in a coherent local-first runtime.

Its differentiating priorities are inspectability, reliability, controlled execution, and reproducible evaluation.

---

# 3. Project Objectives

## Primary Objectives

### O1 — Build a custom agent runtime

Implement the fundamental execution loop responsible for interacting with a model, processing responses, invoking tools, and continuing until completion or failure.

Learn how model-driven execution differs from ordinary deterministic software.

### O2 — Engineer reliable execution

Implement explicit state transitions, persistence, cancellation, timeouts, retries, and checkpoints.

Understand how to recover workflows without silently repeating unsafe operations.

### O3 — Introduce execution isolation

Allow agents to perform file and command operations inside restricted environments.

Study operating-system processes, containers, permissions, filesystem boundaries, and resource limits.

### O4 — Support coordinated autonomous workflows

Introduce task dependencies, multiple agent roles, message passing, and controlled concurrent execution.

Measure whether multi-agent systems actually improve task outcomes.

### O5 — Make execution observable

Expose the internal execution process through event logs, traces, metrics, and a developer dashboard.

### O6 — Establish reproducible evaluation

Measure completion rates, execution duration, model usage, tool failures, recovery behavior, and policy violations across a fixed task suite.

### O7 — Deliver a usable developer platform

Provide documented APIs, a web interface, local deployment instructions, and a demonstration application.

## Secondary Objectives

- Explore context management techniques.
- Experiment with local open-weight LLMs.
- Learn event-driven architecture.
- Practice advanced asynchronous Python.
- Learn infrastructure testing and failure injection.
- Build a meaningful open-source repository.
- Produce measurable, defensible engineering results for resumes and interviews.

---

# 4. Non-Goals

Kairo will NOT initially attempt to:

- Train a foundation model.
- Compete with complete commercial coding agents.
- Reproduce all features of Kubernetes.
- Build a cloud-hosted SaaS platform.
- Support arbitrary untrusted public users.
- Implement its own LLM inference engine.
- Build its own vector database.
- Create a visual no-code workflow builder.
- Support an unrestricted plugin marketplace.
- Implement sophisticated distributed consensus algorithms.
- Guarantee sandbox security against malicious adversaries.
- Implement every feature of established orchestration frameworks.

The focus must remain on understanding and implementing the core execution infrastructure.

---

# 5. Target Users

## Primary

Developers building local autonomous AI agents who need controlled execution, debugging, recovery, and evaluation.

## Secondary

AI engineering students and researchers experimenting with execution strategies, memory approaches, and orchestration patterns.

## Initial Usage Environment

One trusted developer or two collaborating developers operating Kairo locally.

Multi-user authentication, hosted deployments, and untrusted third-party workloads are outside the initial scope.

---

# 6. Product Architecture

Kairo will use a modular architecture with a clear separation between the control plane, execution plane, intelligence layer, and observability layer.

## 6.1 Control Plane

Responsibilities:

- Receive task requests.
- Validate execution configurations.
- Manage task state.
- Schedule pending work.
- Coordinate workers.
- Process cancellation and approval requests.
- Provide APIs to the dashboard.

## 6.2 Execution Plane

Responsibilities:

- Execute agent loops.
- Invoke registered tools.
- Manage workspaces and sandboxes.
- Enforce resource constraints.
- Capture tool outputs.
- Report execution events.

## 6.3 Intelligence Layer

Responsibilities:

- Communicate with LLMs.
- Maintain conversation context.
- Interpret tool-call requests.
- Apply context management strategies.
- Support agent-specific instructions.
- Handle structured model outputs.

## 6.4 Persistence Layer

Responsibilities:

- Store runs and tasks.
- Save execution steps.
- Persist durable events.
- Maintain checkpoints.
- Store approvals and tool execution records.
- Support recovery after process termination.

## 6.5 Observability Layer

Responsibilities:

- Collect structured execution events.
- Record spans and timing information.
- Expose logs and metrics.
- Provide timelines.
- Aggregate evaluation results.
- Enable run comparisons.

## 6.6 Presentation Layer

Responsibilities:

- Display tasks and agent runs.
- Stream live execution events.
- Show tool calls and model interactions.
- Support approval and cancellation.
- Visualize agent coordination.
- Display evaluation results.

---

# 7. Technical Stack

## Backend

- Python 3.11+
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- asyncio
- PostgreSQL

## Frontend

- Next.js
- TypeScript
- Tailwind CSS
- A minimal, consistent component system
- WebSockets or Server-Sent Events

## Local Inference

- Ollama
- Small locally runnable open-weight instruction/coding models
- A model-provider abstraction

## Execution Infrastructure

- Docker or a compatible local container runtime
- Docker Compose
- Restricted workspace mounts
- Explicit command and filesystem permissions

## Scheduling

Initial implementation:

- Database-backed task queue.
- Custom asyncio-based worker loop.
- PostgreSQL-backed task claiming.

Later implementation:

- Redis for coordination if justified.
- Multiple worker processes.
- Concurrency controls.
- Worker liveness tracking.

## Observability

- Structured Python logging.
- OpenTelemetry.
- Optional Jaeger for trace visualization.
- Application-level execution events stored in PostgreSQL.

## Testing

- Pytest
- pytest-asyncio
- HTTPX
- Playwright
- Ruff
- Mypy or Pyright

## Engineering Tools

- Git
- GitHub
- Codex
- Docker Compose
- VS Code or another preferred editor

All selected technologies must have a usable no-cost local development path.

Optional commercial integrations must never be required for the core project.

---

# 8. Core Functional Requirements

## FR-01: Agent Execution Runtime

Kairo must implement a custom execution loop.

A typical execution cycle:

1. Receive a task.
2. Load its execution configuration.
3. Assemble context.
4. Request a model response.
5. Interpret the response.
6. Identify tool calls or completion.
7. Validate requested actions.
8. Invoke permitted tools.
9. Record outcomes.
10. Update context.
11. Continue until termination.

### Required capabilities

- Configurable maximum steps.
- Per-step timeouts.
- Overall execution deadlines.
- Cancellation.
- Structured model responses.
- Tool-call validation.
- Terminal states.
- Persistent event recording.
- Deterministic mock models for testing.

### Acceptance Criteria

A single agent must complete a multi-step task using at least two registered tools.

Its entire execution must be inspectable and reproducible using recorded inputs and mock outputs.

---

## FR-02: Explicit State Machine

An agent run must have a clearly defined lifecycle.

Proposed states:

- CREATED
- QUEUED
- RUNNING
- WAITING_FOR_TOOL
- WAITING_FOR_APPROVAL
- PAUSED
- COMPLETED
- FAILED
- CANCELLED

State transitions must be explicitly validated.

Illegal transitions must be rejected.

Example:

COMPLETED → RUNNING must not be allowed on the same run.

A new attempt must instead have its own identity or explicitly versioned execution state.

### Acceptance Criteria

- Every transition is validated.
- Invalid transitions are tested.
- State persists across restarts.
- Terminal runs cannot be accidentally resumed.

---

## FR-03: Tool Registry and Execution

Kairo must support a structured tool interface.

Initial tools:

- Read file.
- Write file.
- List directory.
- Search files.
- Execute command.
- Inspect Git status.
- Read Git diff.

Each tool must define:

- Unique identifier.
- Description.
- Input schema.
- Output schema.
- Timeout.
- Permission requirements.
- Error contract.
- Side-effect classification.

Tool execution must not depend on arbitrary model-generated Python code.

### Acceptance Criteria

An invalid tool request is rejected before execution.

All tool calls produce traceable records, including failures.

---

## FR-04: Sandbox and Permission System

Agent commands must execute inside restricted environments.

Initial requirements:

- Dedicated task workspace.
- Containerized command execution.
- No privileged containers.
- Explicit volume mounts.
- Resource limits.
- Command timeouts.
- Network disabled by default for sandboxed tasks.
- No host secrets mounted into the sandbox.
- Explicit approval for sensitive operations.

The system must distinguish between:

1. Read-only operations.
2. Workspace modification.
3. External side effects.
4. Privileged or prohibited operations.

A Docker container alone must not be described as a complete security guarantee.

### Acceptance Criteria

An agent cannot write outside its permitted workspace through ordinary exposed tools.

Attempts to access prohibited resources must be rejected and logged.

Security tests must cover path traversal, symlinks, permissions, environment variables, and command execution boundaries.

---

## FR-05: Persistent Execution State

Kairo must preserve sufficient state to reconstruct and inspect executions.

Store:

- Run ID.
- Task ID.
- Agent configuration.
- Current status.
- Model request metadata.
- Tool-call records.
- Execution events.
- Checkpoint references.
- Error information.
- Timestamps.
- Attempt identifiers.

The database must distinguish the execution state from dashboard presentation state.

### Acceptance Criteria

An interrupted execution retains its history after restarting the backend.

---

## FR-06: Checkpointing and Recovery

Kairo must support recovery from unexpected interruptions.

Checkpoints may include:

- Completed execution step.
- Current execution state.
- Relevant context references.
- Tool execution records.
- Pending operations.
- Workspace snapshot reference.
- Resume metadata.

Recovery must account for side effects.

Operations must not automatically repeat just because their acknowledgment was lost.

For operations whose completion cannot be proven, mark the outcome uncertain and require reconciliation or human intervention.

### Acceptance Criteria

Terminate a worker during a multi-step task.

After restart, Kairo must recover the last committed state, avoid repeating confirmed completed work, and handle uncertain side effects explicitly.

---

## FR-07: Scheduler and Worker System

The platform must support multiple pending tasks.

Required capabilities:

- Enqueue tasks.
- Claim work atomically.
- Limit concurrent execution.
- Track worker state.
- Recover abandoned task leases.
- Cancel queued or running tasks.
- Implement bounded retries.
- Prevent multiple workers from claiming the same active task.

Avoid introducing Redis merely because it is commonly used in distributed systems.

Begin with PostgreSQL and add Redis only when a measured need emerges.

### Acceptance Criteria

Two workers must not execute the same task simultaneously because of a scheduler race.

Tests must simulate worker termination and stale leases.

---

## FR-08: Context and Memory Management

The system must distinguish between:

### Working Context

Messages and tool results currently supplied to the model.

### Execution History

Durable records of earlier steps, regardless of whether they are still in model context.

### Persistent Task Memory

Information explicitly retained for later execution steps or related tasks.

Initial functionality:

- Configurable context budget.
- Message truncation or compaction.
- Tool-output size limits.
- Retrieval of older execution records.
- Recording which context was provided to a model.

Advanced functionality:

- Model-generated summaries.
- Relevance-based retrieval.
- Context compaction comparisons.
- Memory persistence across agent sessions.

### Acceptance Criteria

Long-running executions must respect a configured context budget.

Evaluations must compare context strategies under comparable conditions.

---

## FR-09: Multi-Agent Orchestration

Kairo must eventually support multiple agent roles.

Initial roles:

### Planner

Creates a structured task plan.

### Executor

Performs approved work using tools.

### Reviewer

Inspects outputs and evaluates completion conditions.

The system must support:

- Explicit task delegation.
- Dependency relationships.
- Structured messages.
- Independent agent contexts.
- Separate workspace ownership where required.
- Bounded retries and revision loops.
- Shared execution traces.
- Clear completion criteria.

Do not introduce multiple agents before the single-agent runtime is reliable.

### Acceptance Criteria

A multi-agent workflow must coordinate a task through planning, execution, and review, with all decisions and handoffs recorded.

A reviewer rejection must trigger a bounded correction workflow or a documented failure.

---

## FR-10: Human-in-the-Loop Approval

Kairo must allow users to approve or reject sensitive actions.

Examples:

- Modifying protected files.
- Executing potentially destructive commands.
- Creating a Git commit.
- Opening a pull request.
- Accessing network services.

Approval requests must include:

- Requested action.
- Relevant inputs.
- Risk classification.
- Requesting agent.
- Execution ID.
- Timestamp.
- Approval status.

Authorization must be enforced by the execution backend, not merely by a frontend prompt.

### Acceptance Criteria

A denied action must not execute.

An approval for one action must not silently authorize a different action.

---

## FR-11: Observability and Execution Tracing

Each run must provide an inspectable timeline.

Events should include:

- Run started.
- Model request.
- Model response.
- Tool requested.
- Tool started.
- Tool completed.
- Tool failed.
- State transition.
- Approval requested.
- Approval resolved.
- Checkpoint created.
- Retry scheduled.
- Run completed or failed.

Required metrics:

- Total execution duration.
- Per-step duration.
- Tool execution latency.
- Model request latency.
- Total tool calls.
- Failed tool calls.
- Retry count.
- Completion status.
- Token usage when reported by the provider.
- Estimated local resource consumption where measurable.

Do not fabricate token counts or pretend estimates are exact.

### Acceptance Criteria

A developer must be able to understand a failed run from its stored timeline without reading raw backend logs.

---

## FR-12: Evaluation Framework

Kairo must provide a reproducible evaluation suite.

Initial evaluation categories:

1. Basic tool-use tasks.
2. File modification tasks.
3. Multi-step reasoning and execution.
4. Command failures.
5. Timeouts.
6. Interrupted execution.
7. Permission violations.
8. Context-budget stress.
9. Multi-agent coordination.
10. Coding tasks with automated tests.

Every task must have a defined success condition.

The platform must distinguish:

- Deterministic infrastructure tests.
- Model-dependent behavioral evaluations.
- Human-reviewed outcomes.

Metrics:

- Task completion rate.
- Tool-call success rate.
- Runtime.
- Number of execution steps.
- Retry frequency.
- Recovery success rate.
- Context usage.
- Policy violation count.

Required comparisons:

- Single-agent versus multi-agent workflows.
- With versus without checkpoint recovery.
- Different context compaction strategies.
- Different local models where feasible.

Comparisons must use consistent tasks, budgets, environments, and evaluation conditions.

### Acceptance Criteria

A developer can execute a fixed evaluation suite twice, inspect the results, and compare the outcomes.

Infrastructure tests must not depend on model randomness.

---

# 9. Developer Dashboard

Kairo must include an interactive, professional frontend.

The UI is a product feature, not an optional demo page.

## 9.1 Overview

Display:

- Total runs.
- Active runs.
- Completed runs.
- Failed runs.
- Queued tasks.
- Recent activity.
- Worker status.

## 9.2 Task Explorer

Allow users to:

- Submit tasks.
- Configure execution limits.
- Select model adapters.
- View pending tasks.
- Cancel tasks.
- Inspect outcomes.

## 9.3 Agent Inspector

Display:

- Agent role.
- Current status.
- Execution history.
- Model interactions.
- Tool calls.
- Context information.
- Failures.
- Checkpoints.

## 9.4 Execution Timeline

Provide an interactive timeline showing:

- Model calls.
- Tool operations.
- State changes.
- Approval events.
- Retries.
- Recovery points.
- Execution duration.

## 9.5 Multi-Agent Arena

Display each agent involved in a workflow.

Include:

- Agent identities.
- Assigned subtasks.
- Dependency relationships.
- Communication history.
- Handoffs.
- Completion state.

Visualization should reflect actual backend events rather than simulated animations.

## 9.6 Evaluation Lab

Allow users to:

- Select evaluation suites.
- Run benchmarks.
- Compare historical runs.
- Inspect individual failures.
- Display charts and summary metrics.

## UI Standards

- Dark-first professional developer-tool design.
- Clear information hierarchy.
- Responsive layout.
- Fast navigation.
- Live execution updates.
- Accessible status indicators.
- No decorative fake metrics.
- Avoid excessive animations.
- Distinct error, cancellation, and recovery states.

---

# 10. Initial API Requirements

The following endpoints represent the intended public API shape.

Exact payloads should be defined during the relevant implementation milestone.

## Tasks and Runs

- POST /api/v1/tasks
- GET /api/v1/tasks
- GET /api/v1/tasks/{task_id}
- POST /api/v1/runs
- GET /api/v1/runs
- GET /api/v1/runs/{run_id}
- POST /api/v1/runs/{run_id}/cancel
- POST /api/v1/runs/{run_id}/resume

## Execution Inspection

- GET /api/v1/runs/{run_id}/events
- GET /api/v1/runs/{run_id}/tools
- GET /api/v1/runs/{run_id}/checkpoints
- GET /api/v1/runs/{run_id}/trace

## Approvals

- GET /api/v1/approvals
- POST /api/v1/approvals/{approval_id}/decision

## Workers

- GET /api/v1/workers
- GET /api/v1/workers/{worker_id}

## Evaluations

- POST /api/v1/evaluations
- GET /api/v1/evaluations
- GET /api/v1/evaluations/{evaluation_id}
- GET /api/v1/evaluations/{evaluation_id}/results

## Live Events

- GET /api/v1/runs/{run_id}/stream

Use server-sent events initially unless bidirectional communication becomes necessary.

Endpoints must be implemented incrementally rather than generated as a large collection of nonfunctional placeholders.

---

# 11. Data Model

Initial domain entities:

## Task

Represents the requested work.

Fields:

- id
- description
- configuration
- created_at
- updated_at

## Run

Represents one execution of a task.

Fields:

- id
- task_id
- status
- current_attempt_id
- model_configuration
- created_at
- started_at
- completed_at

## RunAttempt

Represents an individual execution attempt.

Fields:

- id
- run_id
- worker_id
- status
- started_at
- ended_at
- failure_reason

## ExecutionEvent

Represents a durable event.

Fields:

- id
- run_id
- attempt_id
- sequence_number
- event_type
- payload
- occurred_at

## ToolExecution

Represents a tool invocation.

Fields:

- id
- run_id
- tool_name
- input
- output_reference
- status
- side_effect_class
- started_at
- completed_at

## Checkpoint

Represents a recovery point.

Fields:

- id
- run_id
- event_sequence
- state_reference
- workspace_reference
- created_at

## Approval

Represents a human authorization decision.

Fields:

- id
- run_id
- action_fingerprint
- status
- requested_at
- resolved_at

## Worker

Represents an execution worker.

Fields:

- id
- status
- heartbeat_at
- capabilities

## EvaluationRun

Represents one benchmark execution.

Fields:

- id
- suite_id
- configuration
- started_at
- completed_at
- results_reference

Database migrations must be version-controlled.

Persisted events must support ordered inspection, and sensitive payloads must be redacted where necessary.

---

# 12. Non-Functional Requirements

## Reliability

- Explicit lifecycle transitions.
- Predictable error handling.
- Persisted run state.
- Bounded retries.
- Recovery after worker crashes.
- No silent repetition of uncertain side effects.

## Performance

- Responsive local dashboard.
- Nonblocking event streaming.
- Configurable concurrency.
- Bounded model execution.
- No unbounded in-memory event retention.

Specific performance targets must be established using initial benchmarks rather than arbitrary assumptions.

## Security

- Restricted execution permissions.
- Explicit human approval.
- Input validation.
- No privileged containers.
- No automatic exposure of credentials.
- Limited filesystem access.
- Network restrictions for execution environments.
- Audit logs.
- No automatic execution of arbitrary downloaded code.

## Maintainability

- Modular codebase.
- Clear interfaces.
- Typed data models.
- Automated tests.
- Documented contracts.
- Version-controlled migrations.
- Consistent formatting.

## Portability

- macOS ARM64 development support.
- Linux-compatible backend and workers.
- No dependence on proprietary hosted services.
- Reproducible local setup.

---

# 13. Proposed Repository Structure

```text
kairo/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   └── tests/
│   └── web/
│       ├── src/
│       └── tests/
├── packages/
│   ├── core/
│   │   ├── runtime/
│   │   ├── state/
│   │   ├── models/
│   │   └── tools/
│   ├── orchestration/
│   │   ├── scheduler/
│   │   ├── workers/
│   │   └── coordination/
│   ├── execution/
│   │   ├── sandbox/
│   │   ├── permissions/
│   │   └── workspace/
│   ├── memory/
│   ├── observability/
│   └── evaluation/
├── infrastructure/
│   ├── docker/
│   └── compose/
├── examples/
│   └── coding-agent/
├── benchmarks/
├── scripts/
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── learning/
│   └── milestones/
├── AGENTS.md
├── README.md
└── .env.example
```

This is a target structure, not an instruction to create empty directories for every future component during M0.

Packages should be introduced when their functionality is implemented.

---

# 14. Team Organization

Two developers will work on separate components with explicit integration contracts.

## Developer A — Agent Runtime and Intelligence

Primary responsibilities:

- Runtime state machine.
- Model abstraction.
- Tool registry.
- Agent execution loop.
- Context management.
- Multi-agent coordination.
- Evaluation logic.

## Developer B — Infrastructure and Platform

Primary responsibilities:

- API architecture.
- Database and migrations.
- Scheduler and worker execution.
- Sandbox integration.
- Dashboard.
- Event streaming.
- Observability.

## Shared Responsibilities

- Architecture decisions.
- Security reviews.
- Cross-component integration.
- Test strategy.
- Debugging.
- Documentation.
- Performance analysis.
- Release preparation.

No component should be treated as exclusively understood by one developer.

Before each major integration, both developers should be able to explain the relevant interfaces and failure modes.

---

# 15. Development Milestones

## M0 — Architecture and Engineering Foundations

### Deliverables

- Finalized system boundaries.
- Development environment.
- Repository organization.
- Architecture diagram.
- State machine specification.
- Dependency selection.
- ADRs (Architecture Decision Records).
- Testing strategy.
- Local development commands.

### Learning Goals

- Modular architecture.
- Design by contract.
- Monorepo organization.
- Interface boundaries.
- Engineering tradeoffs.

### Exit Criteria

Both developers understand the proposed architecture, can run the initial checks, and agree on component contracts.

---

## M1 — Single-Agent Execution Kernel

### Deliverables

- Execution state machine.
- Agent configuration.
- Model adapter interface.
- Mock model.
- Basic execution loop.
- Step limits.
- Cancellation.
- Unit tests.

### Learning Goals

- Async Python.
- State machines.
- Dependency inversion.
- LLM tool-call semantics.
- Deterministic testing.

### Exit Criteria

A mock agent completes a multi-step task, with validated transitions and reproducible results.

---

## M2 — Tool System

### Deliverables

- Tool registry.
- Typed tool schemas.
- Tool invocation API.
- File tools.
- Command execution interface.
- Error handling.
- Tool execution tests.

### Learning Goals

- Interface design.
- Input validation.
- Process execution.
- Error boundaries.
- Side-effect modeling.

### Exit Criteria

An agent successfully uses multiple tools, and invalid requests fail safely.

---

## M3 — Persistence and Execution History

### Deliverables

- PostgreSQL integration.
- Run repository.
- Execution event storage.
- Database migrations.
- Durable execution history.
- Basic API for inspecting runs.

### Learning Goals

- SQL transactions.
- ORM tradeoffs.
- Event-oriented design.
- Database indexing.
- Persistence consistency.

### Exit Criteria

Execution records survive an application restart.

---

## M4 — Sandboxed Execution

### Deliverables

- Sandbox lifecycle manager.
- Workspace creation.
- Container command execution.
- Permission rules.
- Timeouts and resource limits.
- Security-focused tests.

### Learning Goals

- Containers.
- Filesystem isolation.
- Linux process concepts.
- Threat modeling.
- Resource management.

### Exit Criteria

An agent completes a filesystem and command-based task in a restricted workspace.

---

## M5 — Scheduling and Workers

### Deliverables

- Durable task queue.
- Worker service.
- Atomic task claiming.
- Concurrency controls.
- Worker heartbeat.
- Stale lease recovery.

### Learning Goals

- Concurrency.
- Transactions and locking.
- Work queues.
- Race conditions.
- Distributed execution concepts.

### Exit Criteria

Multiple workers process separate tasks without duplicate active execution.

---

## M6 — Checkpointing and Recovery

### Deliverables

- Checkpoint manager.
- Resume protocol.
- Run-attempt tracking.
- Retry policy.
- Idempotency handling.
- Fault-injection tests.

### Learning Goals

- Failure recovery.
- Idempotency.
- Transaction boundaries.
- At-least-once processing.
- Consistency guarantees.

### Exit Criteria

A worker can be terminated mid-run and recovery proceeds safely from persisted state.

---

## M7 — Context Management

### Deliverables

- Context budget manager.
- Tool-output trimming.
- Context compaction.
- Persistent context references.
- Context strategy tests.

### Learning Goals

- Token budgets.
- Context engineering.
- Information loss.
- Prompt construction.
- Evaluation design.

### Exit Criteria

Long-running tasks respect configured context limits, with observable context transformations.

---

## M8 — Multi-Agent Orchestration

### Deliverables

- Agent role definitions.
- Planner/executor/reviewer workflow.
- Task delegation.
- Agent handoffs.
- Dependency management.
- Coordination tests.

### Learning Goals

- Multi-agent design.
- Coordination protocols.
- Task decomposition.
- Dependency graphs.
- Deadlock and livelock avoidance.

### Exit Criteria

A multi-agent workflow completes a nontrivial task and records every handoff.

---

## M9 — Observability and Tracing

### Deliverables

- Structured event records.
- Execution traces.
- OpenTelemetry instrumentation.
- Trace correlation.
- Latency measurements.
- Failure inspection.

### Learning Goals

- Telemetry.
- Distributed tracing.
- Metrics design.
- Logging architecture.
- Root-cause analysis.

### Exit Criteria

A failed execution can be diagnosed using its timeline, logs, and correlated traces.

---

## M10 — Evaluation Framework

### Deliverables

- Fixed benchmark suite.
- Deterministic infrastructure tests.
- Model-dependent task evaluations.
- Result persistence.
- Comparison reports.
- Baseline experiments.

### Learning Goals

- Benchmarking.
- Experimental methodology.
- Statistical uncertainty.
- Reproducibility.
- Performance analysis.

### Exit Criteria

Two execution strategies can be compared using consistent evaluation conditions.

---

## M11 — Interactive Dashboard

### Deliverables

- Overview dashboard.
- Task explorer.
- Run inspector.
- Live execution timeline.
- Agent arena.
- Approval controls.
- Evaluation charts.

### Learning Goals

- Full-stack integration.
- Real-time data delivery.
- API contracts.
- UI state management.
- Information visualization.

### Exit Criteria

A developer can submit, monitor, inspect, and control agent executions through the UI.

---

## M12 — Autonomous Coding Demonstration

Build a reference application using Kairo's own infrastructure.

### Workflow

1. Submit a coding task.
2. Inspect repository files.
3. Reproduce an issue.
4. Propose a modification.
5. Request approval where required.
6. Apply changes in a sandbox.
7. Run tests.
8. Review results.
9. Correct failures where possible.
10. Produce a final execution report.

### Learning Goals

- Git workflows.
- Software engineering agents.
- Testing automation.
- Tool orchestration.
- End-to-end systems integration.

### Exit Criteria

A real coding task completes through the system and produces a verifiable outcome.

---

## M13 — Release and Engineering Validation

### Deliverables

- Installation guide.
- Architecture documentation.
- API documentation.
- Recorded demo.
- Benchmark results.
- Security limitations.
- Known failure modes.
- Contributor instructions.
- Release version.
- Resume-ready engineering metrics.

### Exit Criteria

Another developer can clone the repository, launch the application locally, execute an example, and inspect the outcome without a paid API.

---

# 16. Learning Requirements

This is a learning-first engineering project.

Each milestone must contain:

1. Conceptual introduction.
2. Relevant engineering theory.
3. Design alternatives.
4. Selected architecture and justification.
5. Implementation plan.
6. Code implementation.
7. Automated testing.
8. Manual validation.
9. Failure scenarios.
10. Engineering retrospective.

## Mandatory Learning Questions

For every major component, answer:

- Why does this component exist?
- What would happen without it?
- Why was this implementation chosen?
- What alternatives were considered?
- What assumptions does it rely on?
- What could fail?
- How do we detect failure?
- How do we recover?
- How is correctness tested?
- What are the performance implications?

## Architecture Decision Records

Maintain a short ADR whenever a meaningful design choice is made.

For example:

- Why PostgreSQL-backed scheduling instead of Redis?
- Why an explicit state machine?
- Why use asyncio?
- Why Docker isolation?
- Why use immutable execution events?
- Why separate run attempts?
- Why choose SSE instead of WebSockets?

These decisions must remain understandable to both developers.

---

# 17. Codex Development Protocol

Codex must behave as a senior engineering mentor and implementation assistant.

It must NOT act as an autonomous code generator that silently implements the entire PRD.

## Rules

### Rule 1 — Milestone-by-Milestone Development

Only implement the currently requested milestone.

Do not implement future milestones unless a minimal shared interface is necessary.

### Rule 2 — Explain Before Implementing

Before coding, explain:

- The problem being solved.
- Relevant technical concepts.
- Proposed design.
- Alternatives.
- Tradeoffs.
- Files to create or modify.
- Tests to implement.

### Rule 3 — Exact File Paths

Every implementation instruction must reference exact repository-relative file paths.

Avoid ambiguous instructions such as "add this to the backend."

### Rule 4 — Test Every Component

Every meaningful feature must include relevant tests.

Infrastructure behavior should be tested with mocks or controlled environments when possible.

### Rule 5 — No Fake Functionality

Do not create:

- Fake agent responses presented as real inference.
- Dummy metrics presented as measured data.
- Nonfunctional dashboard actions.
- Mock execution timelines presented as real runs.
- Unimplemented endpoints that report success.

Mocks are permitted only when clearly labeled and used intentionally for development or testing.

### Rule 6 — Explain Failures

When tests fail:

1. Identify the actual failure.
2. Explain its likely cause.
3. Inspect the relevant implementation.
4. Propose a fix.
5. Validate the fix.
6. Report remaining uncertainty.

Do not hide failing tests.

### Rule 7 — Prioritize Understanding

When introducing a new concept, explain enough for a computer science student to understand its role and implementation.

Provide deeper explanations for concepts that are central to the milestone, rather than overwhelming the project with unrelated theory.

### Rule 8 — Maintain Documentation

Update relevant documentation as implementation progresses.

Do not defer all documentation until the final milestone.

### Rule 9 — Preserve Architectural Consistency

Do not introduce a new framework or infrastructure dependency without explaining why it is necessary.

Prefer straightforward, maintainable implementations.

### Rule 10 — Do Not Claim Success Without Validation

A milestone is complete only when its acceptance criteria are satisfied.

Report which checks actually ran and which could not be executed.

---

# 18. Development Workflow for Two Contributors

Each milestone should begin with an agreed shared design.

Afterward, the work can be split into independent tasks.

## Branch Strategy

- main
- feat/mX-component-name
- fix/issue-description

Avoid having both contributors modify the same implementation files simultaneously unless coordination is explicit.

## Integration Rules

- Shared contracts are agreed first.
- Both contributors follow the same type definitions.
- Each branch has tests.
- Integration tests validate connected components.
- The main branch remains functional.
- Cross-component changes receive review.

## Definition of Done

A task is complete when:

- The implementation works.
- Tests pass.
- Error cases are handled.
- Documentation is updated.
- No known critical regression remains.
- Both developers can explain the design.

---

# 19. Cost Constraints

Development must require ₹0 in additional purchases or subscriptions.

## Allowed

- Open-source software.
- Free local infrastructure.
- Ollama local inference.
- Existing developer tooling.
- Free GitHub repositories.
- Free local containers.
- Deterministic mock models.
- Existing laptop hardware.

## Not Required

- Paid LLM API access.
- Paid cloud VMs.
- Hosted vector databases.
- Paid observability platforms.
- Paid task queues.
- Commercial agent frameworks.
- Dedicated GPUs.

Optional features must never turn paid infrastructure into a mandatory project dependency.

Resource usage must remain configurable to accommodate consumer laptops.

---

# 20. Project Risks

## Risk 1 — Scope Expansion

Building a complete production-grade orchestration platform is too large for two developers within a short schedule.

Mitigation:

- Milestone gates.
- Strict non-goals.
- Modular design.
- Prioritize reliable core execution.

## Risk 2 — Local Model Performance

Smaller local models may struggle with complex tool-based coding tasks.

Mitigation:

- Model-independent architecture.
- Mock-based infrastructure testing.
- Small evaluation tasks.
- Controlled concurrency.
- Model-capability reporting.

## Risk 3 — Infrastructure Complexity

Containers, workers, scheduling, and checkpoint recovery introduce significant complexity.

Mitigation:

- Begin with one process.
- Add concurrency incrementally.
- Use fault-injection tests.
- Document state transitions.
- Avoid premature microservices.

## Risk 4 — Security

Agents executing commands can create security and privacy risks.

Mitigation:

- Restrict capabilities.
- Use isolated workspaces.
- Require approval for sensitive actions.
- Avoid privileged execution.
- Document sandbox limitations.
- Never expose public execution endpoints by default.

## Risk 5 — Overreliance on Codex

Rapid code generation may reduce architectural understanding.

Mitigation:

- Explain-first workflow.
- Architecture reviews.
- Written learning notes.
- Manual reasoning exercises.
- Both contributors review critical code.

## Risk 6 — Unconvincing Benchmarks

Agent performance is variable and may be distorted by inconsistent test conditions.

Mitigation:

- Fixed benchmark tasks.
- Consistent resource limits.
- Repeated experiments.
- Documented model configurations.
- Separate infrastructure correctness from agent performance.

---

# 21. Success Criteria

Kairo's final success must be evaluated through demonstrable engineering capabilities.

## Functional Success

- Single-agent execution works.
- Tool execution is validated and traceable.
- State persists.
- Workers can process queued tasks.
- Interrupted executions recover safely.
- Permission rules are enforced.
- Multi-agent coordination works.
- Execution histories are observable.
- Evaluations are reproducible.
- The dashboard uses genuine backend data.

## Engineering Success

- Core modules have automated tests.
- Major design decisions are documented.
- Important failure modes are tested.
- The platform runs without paid services.
- A new developer can reproduce the setup.
- The implementation remains maintainable.

## Learning Success

Both developers can confidently explain:

- Agent execution loops.
- Async execution.
- Process isolation.
- Queue semantics.
- Concurrency control.
- Transaction boundaries.
- Checkpointing.
- Idempotency.
- Multi-agent orchestration.
- LLM context management.
- Distributed tracing.
- Evaluation methodology.

---

# 22. Final Demonstration

The final demonstration should showcase a complete autonomous software engineering workflow.

A user submits a task involving a small repository with an intentionally reproducible bug.

Kairo:

1. Accepts the task.
2. Queues it.
3. Assigns a worker.
4. Initializes a restricted workspace.
5. Runs the agent.
6. Inspects relevant files.
7. Reproduces the bug.
8. Proposes a fix.
9. Requests approval if required.
10. Modifies the workspace.
11. Runs tests.
12. Records all operations.
13. Handles a deliberately introduced failure.
14. Recovers from a checkpoint.
15. Completes execution.
16. Produces a structured report.

The dashboard must show the real execution timeline, including the interruption and recovery.

The demonstration should prove that Kairo provides useful infrastructure beyond the reasoning capability of the underlying model.

---

# 23. Expected Final Deliverables

1. Open-source GitHub repository.
2. Documented agent runtime.
3. Tested tool system.
4. Sandboxed execution environment.
5. Persistent state and checkpoints.
6. Scheduler and worker service.
7. Multi-agent orchestration.
8. Context management.
9. Interactive dashboard.
10. Observability and tracing.
11. Reproducible evaluation suite.
12. Autonomous coding example.
13. Architecture documentation.
14. Benchmark report.
15. End-to-end demonstration.

---

# 24. Final Product Vision

Kairo should evolve into a lightweight, understandable agent execution platform.

A developer should be able to define a task, select an agent configuration, provide permitted tools, and execute an autonomous workflow while retaining control over permissions, execution history, failure recovery, and evaluation.

Its most important quality is not the number of agents it can run.

It is the reliability, transparency, and control it provides around autonomous execution.

**Kairo: Infrastructure for agents that actually do work.**
