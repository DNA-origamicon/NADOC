# PEG coating setup — frontend and automation

## Current scope (2026-09-11)

In **Simulations → oxDNA → Hard surface**, enable the hard surface and PEG-like
surface, enter the coating parameters, and click **Review oxDNA PEG setup**.
The review validates the draft, shows requested chain/bead counts, and lists
remaining barriers. It creates no job, particles, files, or engine process.
Existing **Store PEG setup in design** and **New job** workflows remain available.
The job wizard carries the coating into its creation request with `autostart:false`.
Actual creation still invokes existing engine preparation and can fail its checks.

PEG numerical inputs now use the sidebar surface, text, and border tokens.
Playwright verifies equality with the neighboring hard-surface input colors and
at least 4.5:1 text contrast. Density, patch size, offsets, and terminal charge
accept fractional input where appropriate; seed accepts unsigned 32-bit integers.
Review rejects invalid or blank raw PEG fields before preview normalization can
silently clamp them. Editing the surface/coating clears the previous review;
a response from before that edit is discarded.

## Setup API

`POST /api/oxdna/peg/setup` is stateless and independent of the selected design
and installed engines. FastAPI exposes the typed schema in `/docs`.
Example body:

```json
{
  "backend": "CPU",
  "execution_target": "local",
  "interaction_type": "DNA2",
  "surface": {"dir": [0, 1, 0], "position_nm": -10, "stiff": 100},
  "surface_strands": {
    "enabled": true, "material": "PEG", "segments": 12,
    "bondLengthNm": 0.8, "beadDiameterNm": 0.6, "terminalChargeE": -0.5,
    "shape": "square", "sizeNm": 20, "densityPerUm2": 10000,
    "offsetXNm": 2.5, "offsetYNm": -1.5, "seed": 42,
    "subjectToField": false
  }
}
```

The response has `schema_version:1`, `status:"setup_only"`, `launch_ready:false`,
`summary` (4 requested chains, 13 beads per chain, 52 requested beads here),
`job_request_fragment` (including `autostart:false`), and stable barrier codes.
The fragment contains coating/surface options, not a complete design-specific
job definition. Merge these options into the existing wizard's job request.
Unknown fields, nonfinite values, invalid ranges, zero rounded chains, more than
100,000 requested beads, and unsupported target/model choices return HTTP 422.
Neither the response nor counts establish physical or scientific validity.

## Automation

- `tests/test_peg_setup_api.py`: 29 fast API cases, including deterministic output,
  no engine preparation, invalid parameters, circle counts and charged-terminal warnings.
- `frontend/src/ui/peg_coating_setup.test.js`: DOM-driven review, validation,
  errors, prerequisite gating and stale-response handling.
- `frontend/e2e/helpers/peg_coating_driver.js`: reusable `PegCoatingDriver` with
  `configure({...})` (real fills/selects) and `review()` (real API response).
- `frontend/e2e/peg_coating_setup.spec.js`: sidebar color/contrast and a complete
  input → review API → New job wizard payload check. Job creation is intercepted;
  the test asserts no start request. No simulation is run.

```sh
just test-file tests/test_peg_setup_api.py
just test-frontend
cd frontend && npx playwright test peg_coating_setup.spec.js
```

Playwright writes only `workspace/playwright_tests/__e2e__peg-coating.nadoc`
outside its configured output directories. `afterAll` removes it, with the
configured global teardown as fallback. Session caching is disabled. No downloads
or job folders are created. Verify fixture absence after each run.

## PEG Live follow-up

Prepared PEG jobs now have an isolated Live worker and browser lifecycle coverage.
Build, usage and remaining execution-validation limits: [PEG Live](peg_live.md).

## Barrier catalogue

| ID | Status / evidence | Next work |
| --- | --- | --- |
| PEG-01 | Experimental DNA2PEG statistical segments are not chemical EO repeats. Coating calibration and force validation are incomplete. | Keep chemical claims separate from UI/setup acceptance; complete the scientific validation campaign. |
| PEG-02 | Existing job creation requires a local DNA2PEG binary, DNA2 model, no protein hybrid, and appropriate CPU/CUDA support. Setup review deliberately does not probe these. | Add an engine capability/preflight adapter when execution wiring is ready. |
| PEG-03 | Builder requires a DNA probe, limits surface beads, and rejects PEG/DNA seed overlap. Requested counts do not prove all grafts fit. | Connect geometry/placement preflight and report achieved count and minimum clearance before preparation. |
| PEG-04 | Terminal charge only contributes through a physical electric field. Setup review does not configure that field. | Validate the field together with the eventual full run configuration. |
| PEG-05 | NAMD research assets exist in `experiments/peg_namd`; the sidebar model cannot be directly translated to atomistic PEG. | Resolve graft/linker chemistry, force-field assets and validation from that directory's `GAPS.md` before an NAMD adapter. |
| PEG-06 | Browser fixture with saved `metadata.peg_surface` reached the Simulations panel with PEG unchecked and disabled. Explicitly enabling the floor and PEG works. | Investigate restoration versus empty-job selection/engine activation ordering; add a dedicated save/reopen lifecycle regression. Current E2E explicitly enables controls and does not claim persistence coverage. |
| PEG-07 | Preview uses JavaScript `Math.round`; engine `strand_count` uses Python `round`. Exact .5 counts can differ (e.g. 2.5 → 3 versus 2). Setup review follows the existing engine. | Unify the rounding contract with a compatibility decision before changing saved placement counts. |
| PEG-08 | Raw preview normalization clamps values. Review rejects invalid raw PEG fields, but legacy Store/New job paths still use the normalized preview. | Share strict raw-field validation across persistence and engine submission. |
| PEG-09 | Existing hard-surface stiffness HTML has min=0.1, step=0.5, but default/saved values such as 5 or 100 are step-invalid. | Align this older control's numeric contract; setup API already accepts any positive finite stiffness. |
| PEG-10 | Review is stateless; it does not certify document/assembly compatibility, existing anchors or job-specific options. | Add design/assembly preflight when integrating complete engine configuration. |

Verification limitations: `just smoke` was refused by the simulation guard
because an oxDNA process was running; no override was used. Full slow validation
requires a user-opened test session. Repository lint currently reports pre-existing
unused `seq` in `backend/api/routes_oxdna.py` and `Path` in `tests/test_oxdna_peg.py`.

Completed checks: 29 focused API tests; 6,252 frontend tests across 400 files;
2 focused Playwright tests (including cleanup verification). Changed Python files
pass Ruff. `main.js` grows by 3 lines: import, factory wiring and spacing.

`just test-smart` selected `FAST` (fast suite only): 8,162 passed, 109 skipped,
11 failed. All 11 failures report missing local workspace fixtures
`BigO.nadoc`, `BigO-poly.nass`, or `smallO-poly.nass` in assembly/CanDo tests.
The selector reported:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```
