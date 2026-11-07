# ADR 0008: Restricted container execution and managed workspaces

Date: 2026-11-07. Scope: M4. The user authorized M4–M6 with a commit per milestone
and a separate `docs/learning/m3-m6.md` guide. M3 is already committed as a472162.
No separate learning checklists or study gates are introduced.

Use the existing Docker CLI through explicit argv; no Docker SDK is needed.
`packages/core/src/kairo_core/execution/sandbox.py` implements workspace creation,
container create/start/inspect/remove, bounded output collection, cancellation and
timeout cleanup. Each invocation has a generated name and execution-owner label.
Never construct Docker options from model-provided strings. Missing local images
fail rather than causing automatic pulls during execution.

Use the repository's `infrastructure/docker/Dockerfile.sandbox`: Python plus Git.
Only the dedicated workspace is mounted. Root is read-only, networking is disabled,
capabilities are dropped, new privileges prohibited, and a nonroot UID is used.
Memory, CPU, process count, file size, temporary storage, output and wall time are
bounded. The CLI itself runs on the host as the developer; no Docker socket or host
credentials are mounted inside the command container. HOME points to container /tmp.

Commands require explicit approval for their exact argv, bound to the executor's
workspace. Approving one command does not approve changed arguments or another
workspace. This is a local backend authorization contract, not the future approval
UI/workflow. The caller can intentionally approve a shell command; the executor
never interpolates a shell string itself. File permissions remain separately enforced.

Alternatives: a host subprocess is simpler but breaks the isolation boundary; a
privileged container or broad home-directory mount defeats the intended boundary;
a VM per command costs more startup/resources and adds management complexity.
Docker containers share a kernel and daemon trust boundary, so this is not a
security guarantee against hostile local users or kernel/container escapes.
Individual files/output are bounded; total workspace storage has no filesystem
quota. Filesystem tools remain synchronous and trusted-local. A daemon outage can
prevent cleanup; cleanup errors are surfaced and owned containers can be stopped
by execution label before another owner is allowed to proceed.

Sources: [Docker create](https://docs.docker.com/reference/cli/docker/container/create/)
and [Docker run](https://docs.docker.com/reference/cli/docker/container/run/).
These document the platform controls; actual Kairo behavior is established by tests.
