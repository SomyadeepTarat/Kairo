export type Run = {
  id: string;
  task_id: string;
  status: string;
  event_sequence: number;
  output: string | null;
  error: Record<string, unknown> | null;
  created_at: string;
  task?: string;
  configuration?: Record<string, unknown>;
  model_configuration: { adapter?: string };
};
export type ExecutionEvent = {
  sequence_number: number;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  attempt_id: string;
};
export type Task = {
  id: string;
  run_id: string;
  description: string;
  status: string;
  created_at: string;
};
export type Approval = {
  actionable: boolean;
  id: string;
  run_id: string;
  status: string;
  risk: string;
  agent: string;
  fingerprint: string;
  action: Record<string, unknown>;
  requested_at: string;
};
export type Workflow = {
  id: string;
  status: string;
  state: {
    events: Array<{
      kind: string;
      role?: string;
      run_id?: string;
      [key: string]: unknown;
    }>;
    plan?: { tasks: Array<{ key: string; depends_on: string[] }> };
  };
};
export type Evaluation = {
  id: string;
  status: string;
  configuration: Record<string, unknown>;
  summary: {
    scenario_count: number;
    passed_scenarios: number;
    task_completion_rate: number | null;
    task_count: number;
  };
  results?: Array<{
    case: string;
    passed: boolean;
    task_success: boolean | null;
    duration_seconds: number;
    model_kind: string;
    run_ids: string[];
  }>;
};
export type Worker = {
  id: string;
  capacity: number;
  active_claims: number;
  heartbeat_at: string;
};
export type Overview = {
  total: number;
  queued: number;
  blocked: number;
  counts: Record<string, number>;
  recent: Run[];
};
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    cache: "no-store",
    ...(body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(
      typeof problem.detail === "string"
        ? problem.detail
        : `Request rejected (${response.status})`,
    );
  }
  return response.json() as Promise<T>;
}
export const compact = (id: string) => id.slice(0, 8);
export const time = (value: string) => new Date(value).toLocaleString();
export function mergeEvents(
  previous: ExecutionEvent[],
  incoming: ExecutionEvent[],
): ExecutionEvent[] {
  const map = new Map(previous.map((e) => [e.sequence_number, e]));
  incoming.forEach((e) => map.set(e.sequence_number, e));
  return [...map.values()]
    .sort((a, b) => a.sequence_number - b.sequence_number)
    .slice(-1000);
}
