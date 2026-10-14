# Managed simulation ownership

UI requests and headless API calls use the same native job runners and the same
workspace job directories. A caller does not need a private workspace to keep a
headless simulation alive while the UI polls it.

`backend/core/simulation_runtime.py` supplies same-host Linux ownership for CanDo,
SNUPI, mrDNA, oxDNA, LAMMPS, NAMD and BLaDE. A per-job `flock` covers runner
preparation, execution, gaps between child processes, and final result publication.
Thread registries are workspace-scoped and locked. A poll in another process
returns an owned job without writing its manifest; orphan recovery acquires the
same lock before changing status. Process death releases the lock automatically.
The `.runtime.lock` inode must never be replaced or deleted while a job can run.

Start/resume routes reserve ownership before resetting status or stages and pass
the reservation to the native launcher. oxDNA production extension uses the same
reservation. A rejected request restores prior owner metadata and releases its
reservation. New-job package creation retains each engine's existing preparation
lifecycle; the shared execution lease begins at the native runner. Remote NAMD
execution retains its existing scheduler/supervisor lifecycle.

Stop requests are written to a generation-scoped mailbox. An owning thread calls
its ordinary cancellation handler repeatedly until the target exits, including
when a stop arrives before its event loop or task is ready. A later run ignores
old stop messages. Orphan stop publication holds an idle lease; detached stops
check the execution generation after worker exit, so they cannot overwrite a
concurrent restart. Routes delegate local stop status writes to the native runner.
NAMD's mid-run early-stop setting uses generation-scoped,
acknowledged commands so an older command cannot reverse a later setting.

SNUPI and BLaDE workers inherit the lock descriptor across `Popen`. A pipe prevents
worker execution before the launcher publishes the running manifest. Before that
publication, a stop is only a mailbox request; afterward, a verified worker PID
and Linux process start time permit signaling the worker. The launcher/server PID
is never treated as a detached worker to kill. Parent descriptor close does not
unlock the child's inherited descriptor. Launch and worker failures close all
owned descriptors.

Headless oxDNA route wrappers use a context-local workspace override rather than
mutating route globals. Job-read coalescing includes the effective workspace in
its key. Bare job IDs remain convenient for legacy local inspection, but explicit
workspaces distinguish copies of the same job ID.

Regression coverage is in `tests/test_simulation_runtime.py` and
`tests/test_simulation_runtime_api.py`. It uses real subprocesses, kernel locks,
inherited file descriptors and HTTP polling, with controlled numerical work.
Existing CanDo and SNUPI job tests cover the actual FEM solver launch paths.
