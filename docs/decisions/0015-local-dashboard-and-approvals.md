# 0015 — Local dashboard, replayable events and action-specific approval

M11 uses Next.js App Router/React/TypeScript and Tailwind as required by the PRD.
There is no hosted dependency, external font, chart framework or agent framework.
A Next rewrite proxies `/api` to loopback FastAPI. The browser never imports Python
policy or accesses PostgreSQL. API remains the authority; UI state is a projection.

SSE fits one-way event delivery better than WebSockets here. Ordered durable event
sequence numbers form cursors; Last-Event-ID supports reconnect replay, terminal
streams close after their backlog, and heartbeat comments keep idle streams active.
Polling PostgreSQL avoids introducing Redis; it costs bounded queries per live viewer.
Dashboard collections are bounded; overview totals are SQL aggregates, not page counts.

Optional embedded service mode runs the existing worker/reaper and control ticks.
`scripts/serve.py` enables it. Bare uvicorn remains inspection/control without implicit
workers. Workflow ticks and atomic evaluation claims make UI submission functional;
records survive process restarts. An interrupted evaluator is not silently replayed.
Service shutdown cancels/joins owned work. This is trusted one-host development,
not a distributed deployment or multi-user authentication system.

Approval gates are opt-in on JobSpec for compatibility with existing explicitly
approved infrastructure scripts; UI enables them by default. Writes and commands
wait in WAITING_FOR_APPROVAL. A hash binds canonical tool/arguments, invocation UUID,
run and attempt. Backend decisions lock job → run → approval and require a current
lease/attempt. Consumption is once-only. Rejection dispatches no tool. Approval does
not expand file permissions, exact argv grants, mounts, or network access. Stale
requests remain audit history and are not actionable. Waiting counts against the
run deadline, not the model/tool step budget. Crash before dispatch may require a
fresh approval; no approval is silently transferred to another attempt.

Alternative UI-only confirmations would be bypassable; a global approval boolean
would authorize unrelated actions. In-memory approvals disappear on restart. These
are why migration 0006 stores explicit requests and decisions. No new Python dependency.

Sources: https://nextjs.org/docs/app/getting-started/installation
https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites
