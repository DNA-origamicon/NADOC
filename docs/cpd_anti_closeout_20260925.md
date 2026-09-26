# Cis-anti-I paused closeout — 2026-09-25

User requested stopping, cleanup and a commit. **No simulations, automatic retries
or fits should resume without an explicit user resume.** A local pause receipt at
`.development-artifacts/cpd-anti-validation-v1/campaign_pause.json` blocks the
campaign launcher. Three older CPD automatic triggers were stopped and disabled:
`nadoc-cpd-efficient-post-qm.path`, `nadoc-cpd-efficient-post-qm.timer`, and
`nadoc-local-qm-reassess.timer`. Their prior states are recorded in that receipt;
unit definitions are retained. No CPD native computation was active at closeout.

## Scientific state

- Additive cis-anti-I remains isolated and unqualified for product use. The existing
  cis-syn preliminary package is unchanged. No anti DNA validation has run.
- Local geometry fits can meet training bond/angle limits and export checks, but
  conformational transfer is not established. Earlier scans missed lower QM/MM
  basins; prior numerical comparisons must retain their reference identities.
- Lower-reference QM and lower−30/−15 constrained points passed independent
  stationarity audits. This does not certify an unconstrained or global minimum.
- The +15 lower-basin branch remains unconverged after60 original evaluations and
  its sole20-new-evaluation fresh-Hessian continuation. Final projected max/RMS
  gradients are2.74580e−4/9.14524e−5au. Shrinking trust radius did not recover progress.
- Directional energy/gradient agreement passed, but repeat-gradient noise narrowly
  failed its preregistered1e−6au limit. Both facts are retained. Read-only TRIC
  checks found full rank and the expected bond graph; the remaining optimizer
  issue is unresolved. Do not authorize another automatic budget extension.
- [Fixed validation v1](cpd_validation_protocol.md) specifies94 records and explicit
  limits; its63-record acquisition gate is not yet complete. Existing native
  audits are not equivalent to a basin-qualified frozen dataset. Fitting is blocked.

## Resume handoff

Read the [campaign chronology](cpd_anti_additive_campaign.md), fixed protocol,
`cpd-anti-lower-profile-restart-v1/method_review.json`, and the associated independent
and coordinate reviews. Start with cached constraint/trust-step analysis, not another
blind optimizer or parameter sweep. Maintain the unresolved +15 branch in coverage.
Complete reference acquisition and basin closure before freezing the dataset;
keep all prospective holdouts unexposed until candidate registration.

An explicit resume may update the local pause receipt with a resume timestamp.
Do not automatically re-enable the legacy timers: inspect their scope and dependencies
first. New jobs use fresh artifact/scratch paths and separate watchers. Recover
cached gradients from archived result files; no deleted integral scratch is required.

## Cleanup and evidence retention

Deleted10 regenerable Psi4 integral scratch files: **4,806,603,888 bytes** (4.81GB).
They belonged to ended glycosidic-v4/v5 runs, had no open handles, and were not
hash-pinned inputs in the CPD artifact manifests. Removed now-empty CPD scratch
directories. Three wavefunction snapshots totaling48,423,162bytes were retained
with verified SHA-256 hashes under `cpd-anti-closeout-20260925/retained-wavefunctions`.
The [cleanup manifest](audits/cpd_anti_cleanup_20260925.json) records their old/new
paths and every deleted file. Historical logs/manifests were not rewritten.

Preserved31,188 existing CPD evidence files totaling16,350,964,461bytes, including
all successful and failed native outputs, geometries, gradients, source snapshots,
plans, watches and audits. Existence/size inventory verified after cleanup.
Evidence remains in the gitignored archive; reusable code, protocol, portable
progress snapshot and concise reports are committed. Unrelated workspace changes
and unattributed top-level diagnostic files are left alone.

Verification:37 scoped Python tests and all3 CPD progress browser checks passed.
No leftover test designs, playback caches, report artifacts or test-port bridge
credentials remain. Final commit identifier is reported with the closeout response.
No cloud spending or push.
