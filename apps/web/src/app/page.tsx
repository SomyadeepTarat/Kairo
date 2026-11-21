"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  compact,
  mergeEvents,
  time,
  type Approval,
  type Evaluation,
  type ExecutionEvent,
  type Overview,
  type Run,
  type Task,
  type Worker,
  type Workflow,
} from "@/lib/api";

const sections = [
  "Overview",
  "Tasks",
  "Run inspector",
  "Agent arena",
  "Approvals",
  "Evaluations",
] as const;
type Section = (typeof sections)[number];
const terminal = ["COMPLETED", "FAILED", "CANCELLED"];
function Status({ value }: { value: string }) {
  return (
    <span className={`status ${value.toLowerCase()}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
function Json({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}
function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export default function Dashboard() {
  const [section, setSection] = useState<Section>("Overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [updated, setUpdated] = useState("");
  const [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [queuedRun, setQueuedRun] = useState(false);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [tab, setTab] = useState("Timeline");
  const [inspection, setInspection] = useState<unknown>(null);
  const [task, setTask] = useState("");
  const [backend, setBackend] = useState("ollama");
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [maxSteps, setMaxSteps] = useState(24);
  const [deadline, setDeadline] = useState(180);
  const [commands, setCommands] = useState("[]");
  const [gate, setGate] = useState(true);
  const [script, setScript] = useState(
    '[{"kind":"tool","name":"write_file","arguments_json":"{\\"path\\":\\"hello.txt\\",\\"content\\":\\"hello Kairo\\"}"},{"kind":"tool","name":"read_file","arguments_json":"{\\"path\\":\\"hello.txt\\"}"},{"kind":"final","text":"Recorded file operations complete."}]',
  );
  const [reason, setReason] = useState("");
  const [evalConfig, setEvalConfig] = useState(
    '{"cases":["tool_use","file_task"],"repetitions":1}',
  );
  const [workflowJson, setWorkflowJson] = useState("");
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");
  const [comparison, setComparison] = useState<unknown>(null);
  const [evalDetail, setEvalDetail] = useState<Evaluation | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [o, t, w, a, f, e] = await Promise.all([
        api<Overview>("/overview"),
        api<Task[]>(`/tasks?limit=50&offset=${offset}`),
        api<Worker[]>("/workers"),
        api<Approval[]>("/approvals"),
        api<Workflow[]>("/workflows"),
        api<Evaluation[]>("/evaluations"),
      ]);
      setOverview(o);
      setTasks(t);
      setWorkers(w);
      setApprovals(a);
      setWorkflows(f);
      setEvaluations(e);
      setUpdated(new Date().toLocaleTimeString());
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }, [offset]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    api<{ available: boolean; models: { name: string }[] }>("/models")
      .then((r) => {
        setModels(r.models.map((m) => m.name));
        setModel(r.models[0]?.name ?? "");
      })
      .catch(() => {});
    const id = new URLSearchParams(location.hash.slice(1)).get("run");
    if (id) {
      setRunId(id);
      setSection("Run inspector");
    }
  }, []);
  const inspect = (id: string) => {
    setRunId(id);
    setRun(null);
    setEvents([]);
    setTab("Timeline");
    setSection("Run inspector");
    history.replaceState(null, "", `#run=${id}`);
  };
  const action = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setNotice("");
    try {
      await operation();
      setNotice(message);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    let stream: EventSource | null = null;
    setQueuedRun(false);
    fetch(`/api/v1/runs/${runId}/queue`, { cache: "no-store" })
      .then((response) => {
        if (response.ok && alive) setQueuedRun(true);
      })
      .catch(() => {});
    api<Run>(`/runs/${runId}`)
      .then((value) => {
        if (alive) setRun(value);
      })
      .catch((err) => setError(err.message));
    api<ExecutionEvent[]>(`/runs/${runId}/events?limit=1000`)
      .then((initial) => {
        if (!alive) return;
        setEvents(initial);
        stream = new EventSource(
          `/api/v1/runs/${runId}/stream?after=${initial.at(-1)?.sequence_number ?? 0}`,
        );
        stream.addEventListener("execution", (event) => {
          const incoming = JSON.parse(
            (event as MessageEvent).data,
          ) as ExecutionEvent;
          setEvents((previous) => mergeEvents(previous, [incoming]));
          if (incoming.event_type === "state_transition") {
            void api<Run>(`/runs/${runId}`).then((value) => {
              if (alive) setRun(value);
            });
          }
        });
        stream.addEventListener("finished", () => stream?.close());
      })
      .catch((err) => setError(err.message));
    return () => {
      alive = false;
      stream?.close();
    };
  }, [runId]);
  useEffect(() => {
    if (!runId || tab === "Timeline") return;
    const suffix: Record<string, string> = {
      Tools: "tools",
      Checkpoints: "checkpoints",
      Trace: "trace",
      Context: "events?limit=1000",
    };
    setInspection(null);
    api<unknown>(`/runs/${runId}/${suffix[tab]}`)
      .then(setInspection)
      .catch((err) => setError(err.message));
  }, [runId, tab, events.length]);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void action(async () => {
      const response = await api<{ run_id: string }>("/runs", {
        task,
        backend,
        model: backend === "ollama" ? model : "",
        steps: backend === "scripted" ? JSON.parse(script) : [],
        max_steps: maxSteps,
        run_timeout_seconds: deadline,
        step_timeout_seconds: 45,
        require_approval: gate,
        approved_commands: JSON.parse(commands),
      });
      inspect(response.run_id);
    }, "Task queued. Execution and approvals are recorded below.");
  };
  const counts = overview?.counts ?? {};
  const active = Object.entries(counts)
    .filter(([status]) => !terminal.includes(status) && status !== "QUEUED")
    .reduce((n, [, count]) => n + count, 0);
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setSection("Overview")}>
          <span className="mark">K</span>Kairo
          <span className="version">local</span>
        </a>
        <p className="nav-label">EXECUTION PLATFORM</p>
        <nav>
          {sections.map((item, index) => (
            <button
              key={item}
              onClick={() => setSection(item)}
              aria-current={section === item ? "page" : undefined}
            >
              <span className="nav-icon" aria-hidden="true">
                {["◫", "▤", "⌘", "◇", "⊙", "▥"][index]}
              </span>
              {item}
              {item === "Approvals" && approvals.some((a) => a.actionable) && (
                <span className="count">
                  {approvals.filter((a) => a.actionable).length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="local-indicator" /> Local execution
          <br />
          <small>PostgreSQL · Docker · Ollama</small>
          <p>Your work stays on this machine.</p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            Kairo <span className="muted">/</span> <strong>{section}</strong>
          </div>
          <div className="top-actions">
            <span className="muted">
              {updated ? `Updated ${updated}` : "Connecting…"}
            </span>
            <button className="quiet" onClick={() => void refresh()}>
              Refresh
            </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <p className="eyebrow">LOCAL CONTROL PLANE</p>
              <h1>{section}</h1>
              <p className="subtitle">
                {
                  {
                    Overview: "Every execution. One clear view.",
                    Tasks: "Define the work. Keep control of the boundaries.",
                    "Run inspector":
                      "Follow the evidence from request to result.",
                    "Agent arena":
                      "Roles, dependencies, and the handoffs between them.",
                    Approvals: "Review the exact action before it can execute.",
                    Evaluations:
                      "Compare measured outcomes under recorded conditions.",
                  }[section]
                }
              </p>
            </div>
            <span className="badge">Trusted local workspace</span>
          </div>
          {error && (
            <div className="alert" role="alert">
              {error} <span>Displayed records may be stale.</span>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          {section === "Overview" && (
            <>
              <div className="metrics">
                {[
                  ["Total runs", overview?.total],
                  ["Active", overview ? active : undefined],
                  ["Queued", overview?.queued],
                  ["Completed", overview ? (counts.COMPLETED ?? 0) : undefined],
                  ["Failed", overview ? (counts.FAILED ?? 0) : undefined],
                  ["Blocked", overview?.blocked],
                ].map(([label, value]) => (
                  <div className="metric" key={label as string}>
                    <span>{label}</span>
                    <strong>{value ?? "—"}</strong>
                  </div>
                ))}
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Recent executions</h2>
                  <button onClick={() => setSection("Tasks")}>New task</button>
                </div>
                <RunTable runs={overview?.recent ?? []} inspect={inspect} />
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Workers</h2>
                  <span className="muted">Six most recent heartbeats</span>
                </div>
                {workers.length ? (
                  <div className="worker-grid">
                    {workers.slice(0, 6).map((w) => (
                      <div className="worker" key={w.id}>
                        <code>{compact(w.id)}</code>
                        <strong>
                          {w.active_claims} / {w.capacity} slots claimed
                        </strong>
                        <small>Heartbeat {time(w.heartbeat_at)}</small>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty>
                    No workers have registered. Start the local platform
                    service.
                  </Empty>
                )}
              </section>
            </>
          )}
          {section === "Tasks" && (
            <>
              <section className="panel">
                <div className="panel-heading">
                  <h2>New task</h2>
                  <span className="muted">
                    Explicit limits. Real execution.
                  </span>
                </div>
                <form className="task-form" onSubmit={submit}>
                  <label className="full">
                    Task description
                    <textarea
                      required
                      value={task}
                      onChange={(e) => setTask(e.target.value)}
                      placeholder="Describe the task and its completion conditions…"
                      maxLength={4096}
                    />
                  </label>
                  <label>
                    Model adapter
                    <select
                      value={backend}
                      onChange={(e) => setBackend(e.target.value)}
                    >
                      <option value="ollama">Local Ollama</option>
                      <option value="scripted">
                        Scripted infrastructure example
                      </option>
                    </select>
                  </label>
                  <label>
                    Installed model
                    <select
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      disabled={backend !== "ollama"}
                    >
                      <option value="">
                        {models.length
                          ? "Select a model"
                          : "Ollama unavailable or no installed models"}
                      </option>
                      {models.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Maximum model steps
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      value={maxSteps}
                      onChange={(e) => setMaxSteps(+e.target.value)}
                    />
                  </label>
                  <label>
                    Run budget (seconds)
                    <input
                      type="number"
                      min={1}
                      max={3600}
                      value={deadline}
                      onChange={(e) => setDeadline(+e.target.value)}
                    />
                  </label>
                  <label className="full">
                    Exact command grants (JSON argv arrays)
                    <textarea
                      className="code-input"
                      rows={2}
                      value={commands}
                      onChange={(e) => setCommands(e.target.value)}
                    />
                  </label>
                  {backend === "scripted" && (
                    <label className="full">
                      Prescribed responses (no inference)
                      <textarea
                        className="code-input"
                        rows={5}
                        value={script}
                        onChange={(e) => setScript(e.target.value)}
                      />
                    </label>
                  )}
                  <label className="check full">
                    <input
                      type="checkbox"
                      checked={gate}
                      onChange={(e) => setGate(e.target.checked)}
                    />{" "}
                    Require approval for each write or command
                  </label>
                  <div className="form-actions full">
                    <small>
                      Commands stay inside the restricted task workspace.
                      Network is disabled.
                    </small>
                    <button disabled={busy || (backend === "ollama" && !model)}>
                      Queue task
                    </button>
                  </div>
                </form>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Task explorer</h2>
                  <span className="muted">
                    Latest first · page {offset / 50 + 1}
                  </span>
                </div>
                {tasks.length ? (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Task</th>
                          <th>Status</th>
                          <th>Created</th>
                          <th>Run</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((t) => (
                          <tr key={t.id}>
                            <td className="description">{t.description}</td>
                            <td>
                              <Status value={t.status} />
                            </td>
                            <td>{time(t.created_at)}</td>
                            <td>
                              <button
                                className="text-button"
                                onClick={() => inspect(t.run_id)}
                              >
                                {compact(t.run_id)}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty>No tasks on this page.</Empty>
                )}
                <div className="pagination">
                  <button
                    className="quiet"
                    disabled={!offset}
                    onClick={() => setOffset(Math.max(0, offset - 50))}
                  >
                    Previous
                  </button>
                  <button
                    className="quiet"
                    disabled={tasks.length < 50}
                    onClick={() => setOffset(offset + 50)}
                  >
                    Next
                  </button>
                </div>
              </section>
            </>
          )}
          {section === "Run inspector" && (
            <>
              {!runId ? (
                <Empty>
                  Select an execution from the overview or task explorer.
                </Empty>
              ) : (
                <>
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <h2>
                          Execution <code>{compact(runId)}</code>
                        </h2>
                        <small className="muted">{runId}</small>
                      </div>
                      {run && (
                        <div className="row">
                          <Status value={run.status} />
                          {queuedRun && (
                            <button
                              className="danger"
                              disabled={busy || terminal.includes(run.status)}
                              onClick={() =>
                                void action(
                                  () => api(`/runs/${runId}/cancel`, {}),
                                  "Cancellation intent accepted.",
                                )
                              }
                            >
                              Cancel run
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="run-summary">
                      <p>{run?.task ?? "Loading execution…"}</p>
                      <small>
                        Adapter: {run?.model_configuration.adapter ?? "unknown"}{" "}
                        · Events: {run?.event_sequence ?? "—"}
                      </small>
                      {run?.output && (
                        <div className="result">
                          <strong>Final output</strong>
                          <p>{run.output}</p>
                        </div>
                      )}
                      {run?.error && <Json value={run.error} />}
                    </div>
                    <div className="tabs">
                      {[
                        "Timeline",
                        "Tools",
                        "Checkpoints",
                        "Trace",
                        "Context",
                      ].map((t) => (
                        <button
                          className={tab === t ? "selected" : ""}
                          key={t}
                          onClick={() => setTab(t)}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                    {tab === "Timeline" ? (
                      <div className="timeline">
                        {events.length ? (
                          events.map((e) => (
                            <details key={e.sequence_number} className="event">
                              <summary>
                                <code className="sequence">
                                  {e.sequence_number
                                    .toString()
                                    .padStart(3, "0")}
                                </code>
                                <span>{e.event_type.replaceAll("_", " ")}</span>
                                <small>
                                  {new Date(e.occurred_at).toLocaleTimeString()}
                                </small>
                                <code className="attempt">
                                  {compact(e.attempt_id)}
                                </code>
                              </summary>
                              <Json value={e.payload} />
                            </details>
                          ))
                        ) : (
                          <Empty>Waiting for durable events…</Empty>
                        )}
                        <small className="muted">
                          Up to 1,000 received events shown. Full history is
                          available through the paginated events API.
                        </small>
                      </div>
                    ) : (
                      <div className="inspection">
                        <Json
                          value={
                            tab === "Context" && Array.isArray(inspection)
                              ? inspection.filter((e) =>
                                  [
                                    "context_assembled",
                                    "model_request",
                                  ].includes(e.event_type),
                                )
                              : inspection
                          }
                        />
                      </div>
                    )}
                  </section>
                </>
              )}
            </>
          )}
          {section === "Approvals" && (
            <>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Action review</h2>
                  <span className="muted">
                    One decision authorizes one invocation
                  </span>
                </div>
                <div className="panel-body">
                  <label>
                    Decision reason
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="Record why you approve or deny this exact action"
                      maxLength={4096}
                    />
                  </label>
                </div>
                {approvals.length ? (
                  approvals.map((a) => (
                    <article className="approval" key={a.id}>
                      <div className="row">
                        <Status value={a.status} />
                        <span>{a.risk.replaceAll("_", " ")}</span>
                        <button
                          className="text-button"
                          onClick={() => inspect(a.run_id)}
                        >
                          Run {compact(a.run_id)}
                        </button>
                      </div>
                      <Json value={a.action} />
                      <small className="muted">
                        {a.agent} · Fingerprint {a.fingerprint}
                      </small>
                      {a.actionable && (
                        <div className="row approval-actions">
                          <button
                            disabled={busy || !reason.trim()}
                            onClick={() =>
                              void action(
                                () =>
                                  api(`/approvals/${a.id}/decision`, {
                                    approved: true,
                                    reason,
                                  }),
                                "Approval recorded for this action.",
                              )
                            }
                          >
                            Approve action
                          </button>
                          <button
                            className="danger"
                            disabled={busy || !reason.trim()}
                            onClick={() =>
                              void action(
                                () =>
                                  api(`/approvals/${a.id}/decision`, {
                                    approved: false,
                                    reason,
                                  }),
                                "Action denied.",
                              )
                            }
                          >
                            Deny action
                          </button>
                        </div>
                      )}
                    </article>
                  ))
                ) : (
                  <Empty>No approvals recorded.</Empty>
                )}
              </section>
            </>
          )}
          {section === "Agent arena" && (
            <>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Role workflows</h2>
                  <span className="muted">
                    Actual delegations and dependency edges
                  </span>
                </div>
                {workflows.length ? (
                  workflows.map((w) => (
                    <article className="workflow" key={w.id}>
                      <div className="row">
                        <code>{compact(w.id)}</code>
                        <Status value={w.status} />
                      </div>
                      {w.state.plan && (
                        <div className="dependencies">
                          {w.state.plan.tasks.map((t) => (
                            <span key={t.key}>
                              {t.key}
                              {t.depends_on.length
                                ? ` depends on ${t.depends_on.join(", ")}`
                                : " · ready at start"}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="role-grid">
                        {w.state.events
                          .filter((e) => e.kind === "delegated")
                          .map((e, i) => (
                            <button
                              className="role-card"
                              key={i}
                              onClick={() => inspect(String(e.run_id))}
                            >
                              <small>{e.role}</small>
                              <strong>Run {compact(String(e.run_id))}</strong>
                              <span>Inspect execution</span>
                            </button>
                          ))}
                      </div>
                      <details>
                        <summary>Handoff history</summary>
                        <Json value={w.state.events} />
                      </details>
                    </article>
                  ))
                ) : (
                  <Empty>
                    No role workflows yet. Submit a workflow specification
                    below.
                  </Empty>
                )}
                <form
                  className="panel-body"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action(
                      () => api("/workflows", JSON.parse(workflowJson)),
                      "Workflow submitted.",
                    );
                  }}
                >
                  <label>
                    Workflow specification
                    <textarea
                      className="code-input"
                      rows={4}
                      required
                      placeholder="Paste a WorkflowSpec JSON (see examples/scripted-workflow.json)"
                      value={workflowJson}
                      onChange={(e) => setWorkflowJson(e.target.value)}
                    />
                  </label>
                  <button disabled={busy || !workflowJson.trim()}>
                    Submit workflow
                  </button>
                </form>
              </section>
            </>
          )}
          {section === "Evaluations" && (
            <>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Evaluation lab</h2>
                  <span className="muted">Fixed suite · measured outcomes</span>
                </div>
                <form
                  className="panel-body"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action(
                      () => api("/evaluations", JSON.parse(evalConfig)),
                      "Evaluation queued for the local consumer.",
                    );
                  }}
                >
                  <label>
                    Configuration
                    <textarea
                      className="code-input"
                      rows={3}
                      value={evalConfig}
                      onChange={(e) => setEvalConfig(e.target.value)}
                    />
                  </label>
                  <button disabled={busy}>Run evaluation</button>
                </form>
                {evaluations.length ? (
                  <div className="evaluation-list">
                    {evaluations.map((e) => (
                      <button
                        className="evaluation-row"
                        key={e.id}
                        onClick={() =>
                          void action(
                            async () =>
                              setEvalDetail(
                                await api<Evaluation>(`/evaluations/${e.id}`),
                              ),
                            "Evaluation loaded.",
                          )
                        }
                      >
                        <code>{compact(e.id)}</code>
                        <Status value={e.status} />
                        <div
                          className="result-bar"
                          aria-label={`${e.summary.passed_scenarios} of ${e.summary.scenario_count} assertions passed`}
                        >
                          <span
                            style={{
                              width: `${e.summary.scenario_count ? (100 * e.summary.passed_scenarios) / e.summary.scenario_count : 0}%`,
                            }}
                          />
                        </div>
                        <span>
                          {e.summary.passed_scenarios}/
                          {e.summary.scenario_count} assertions
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <Empty>No evaluation records yet.</Empty>
                )}
              </section>
              {evalDetail && (
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Case outcomes · {compact(evalDetail.id)}</h2>
                    <Status value={evalDetail.status} />
                  </div>
                  {evalDetail.results?.map((r, i) => (
                    <div className="case-row" key={i}>
                      <strong>{r.case}</strong>
                      <Status value={r.passed ? "COMPLETED" : "FAILED"} />
                      <span>
                        {r.duration_seconds.toFixed(2)} s · {r.model_kind}
                      </span>
                      <div>
                        {r.run_ids.map((id) => (
                          <button
                            className="text-button"
                            key={id}
                            onClick={() => inspect(id)}
                          >
                            {compact(id)}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  <details className="panel-body">
                    <summary>Recorded conditions</summary>
                    <Json value={evalDetail.configuration} />
                  </details>
                </section>
              )}
              <section className="panel">
                <div className="panel-heading">
                  <h2>Compare evaluations</h2>
                </div>
                <form
                  className="compare-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action(
                      async () =>
                        setComparison(
                          await api(
                            `/evaluation-comparisons?left=${compareLeft}&right=${compareRight}`,
                          ),
                        ),
                      "Comparison loaded.",
                    );
                  }}
                >
                  <label>
                    Baseline
                    <select
                      required
                      value={compareLeft}
                      onChange={(e) => setCompareLeft(e.target.value)}
                    >
                      <option value="">Select evaluation</option>
                      {evaluations.map((e) => (
                        <option key={e.id} value={e.id}>
                          {compact(e.id)} · {e.status}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Comparison
                    <select
                      required
                      value={compareRight}
                      onChange={(e) => setCompareRight(e.target.value)}
                    >
                      <option value="">Select evaluation</option>
                      {evaluations.map((e) => (
                        <option key={e.id} value={e.id}>
                          {compact(e.id)} · {e.status}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button disabled={busy}>Compare conditions</button>
                </form>
                {comparison !== null && <Json value={comparison} />}
              </section>
            </>
          )}
          <footer>
            Local-first infrastructure. Every result has an execution behind it.
          </footer>
        </main>
      </div>
    </div>
  );
}
function RunTable({
  runs,
  inspect,
}: {
  runs: Run[];
  inspect: (id: string) => void;
}) {
  return runs.length ? (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Execution</th>
            <th>Status</th>
            <th>Adapter</th>
            <th>Created</th>
            <th>Events</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>
                <button className="text-button" onClick={() => inspect(r.id)}>
                  {compact(r.id)}
                </button>
              </td>
              <td>
                <Status value={r.status} />
              </td>
              <td>{r.model_configuration.adapter ?? "unknown"}</td>
              <td>{time(r.created_at)}</td>
              <td>{r.event_sequence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty>No executions yet. Queue a task to begin.</Empty>
  );
}
