# CPD work summary and historical-data cleanup — 2026-10-18

This is the durable handoff for CPD development through the four 1xT relaxation runs. Historical artifact paths in older reports describe evidence available at the time; files listed in `audits/cpd_cleanup_20261018/deletion_manifest.json` were intentionally deleted after this consolidation. Their trajectories cannot now be reanalyzed or their deleted checkpoints resumed. Existing conclusions are retained, not newly independently reproduced by this cleanup.

## Current implementation and user systems

The existing Convert to CPD action supports an isomer-selection popup with a context-specific 3D preview, same-strand and different-strand thymine pairs, including crossover extra bases. The four minimum-viable products are cis-syn-I, trans-syn-I, trans-syn-II and cis-anti-I. Their feature-complete 1xT design copies remain in `workspace/CPD_1xT_isomers`.

Base-only placement produced constrained sugar attachments and unsuitable simulation starts. Six-residue placement moves the two CPD nucleotides and the four flanking sugar/backbone regions while holding the flanking bases rigid. This is the adopted 1xT starting geometry, not proof of equilibrium sampling or transferability to arbitrary origami contexts.

The simulation packages contain explicit product topology and parameters. The provisional MVP uses a pinned CGenFF parent and isomer-specific overlay; numerical usability does not constitute general physical validation. Base-only visual placements remain unsuitable for simulation. Mixed-isomer packages remain restricted because of parameter-type alias collisions. Maintained assets, chemical definitions, seeds, export scripts and their source inputs are preserved.

## Chemistry and historical scientific lessons

- Earlier anti-isomer work used a syn bond graph. Anti products require C5–C6 and C6–C5 crosslinks, rather than C5–C5 and C6–C6. This also changes exclusions and screened Drude pairs. Agreement between engines using the same wrong topology did not validate the chemistry. Compact invalidation and provenance records remain authoritative.
- Corrected Drude training recovered several static response targets, but thermal polarization-domain and transferability failures remained. Charge-only fitting failures were bounded solver outcomes, not a proof of global infeasibility. Training recovery did not restore general model acceptance. The detailed scientific chronology and numerical targets remain in `experiments/cpd_drude_recovery/README.md`.
- The published comparator campaign accumulated 34 ns across 68 blocks. Stability checks passed, while one CPD replica developed persistent lesion-opposing base-pair opening. Periodic-box and starting-state effects mattered. A stable crosslink and a stable global RMSD did not validate the lesion ensemble. See `experiments/cpd_published_comparator/README.md`.
- The historical additive anti/control campaign completed six 10 ns runs, 60 ns total. Its closeout recorded passing native/finite-context checks but explicitly withheld production, equilibrium and minimum certification. Independent replay coverage differed by replica; it was not a universal all-frame chemistry audit. These results belong to that historical model and context, not the current four-isomer validation.
- The corrected 36-atom neutral N1-methyl capped cis-anti-I core had a numerically supported local harmonic minimum at the documented frozen-core DF-MP2/6-31G(d) level: 102 positive internal modes, with the lowest sensitivity estimate about 57.95 cm⁻¹. This certifies neither sugar attachment endpoints nor a solution force field. Its geometry, gradients, Hessian arrays and compact assessment are retained; recomputable integral scratch is discarded.

## Actual desktop relaxation results

All four completed the 21-stage relaxation schedule. Final package audits verified two intended covalent crosslinks, stereochemistry, seven parameter hashes, timesteps at most 2 fs, ordinary masses without HMR, and passing recorded health checks. Convergence-based skip acceleration was enabled and used.

| Isomer | Managed job | Skipped chunks |
| --- | --- | ---: |
| cis-anti-I | 935bbecba8cf | 16 |
| cis-syn-I | 6d6c46163a00 | 16 |
| trans-syn-I | b2b43076da96 | 16 |
| trans-syn-II | 974191dc2e63 | 15 |

The complete audit JSONs remain under `.development-artifacts/cpd-relax-execution/<isomer>/completed-audit.json`. Production and relaxation job packages, trajectories and parent checkpoints are outside this cleanup and remain intact. Production results at the user's planned 20 ns endpoint are still pending.

The initial immediate NAMD failure came from duplicating two PSF covalent CPD bonds in ENM restraints. The ENM builder now excludes existing covalent pairs at every strength and rebuild. The failed managed job was already deleted after diagnosis. Adaptive minimization also needed a numerical-roundoff allowance: improvements as small as -0.0001 to -0.0003 kcal/mol at approximately -2,095,748 kcal/mol should not reset convergence. The tolerance is `abs(previous_energy)*1e-9 + 1e-6`; genuine energy increases, required consecutive intervals and step bounds retain their checks.

CPD jobs use the conservative 2 fs / no-HMR policy. `rigidBonds all` constrains hydrogen-containing bonds and water geometry; it does not freeze the CPD carbon ring or the DNA backbone. The normal fast 4 fs protocol also uses constraints but adds HMR. These remain distinct protocols; no production settings were changed during cleanup.

Desktop harness problems were distinguished from simulation failures: a hidden Run control, an old `completed` versus `done` assertion, and a stalled browser worker. Independent final-package audits established the actual simulation outcome. Monitoring now uses filesystem events for terminal states, stage changes and deadlines rather than periodic status polling.

## Visualization and regression evidence

Coordinate-only exports now use the dedicated coordinate exporter, enabling formed-CPD box details, periodic images, VRAM estimates and trajectory/frame export without bypassing simulation chemistry guards. Explicit formed-pair mapping handles ordinary same-strand bases as well as crossover extras. Formed CPDs show geometry and bonds, not reactant restraint strengths or propensity estimates. Existing products are excluded from new KIMMDY candidate formation. Static overlay coordinate updates and marker lifetime were repaired.

Desktop checks covered all four isomers' box details, static displays, water/ions/periodic cell and formed-pair readouts. Cis-anti trajectory scrubbing, supported representations and RMSF were checked. Focused backend and frontend regression suites passed. Surface/bead/hull restrictions while MD is active are global representation restrictions; a failed attempt to select a representation is not evidence that it rendered. See `audits/cpd_visualization_legacy.md` for the maintained legacy-caller audit.

## Cleanup boundary and retained material

This pass covers CPD artifacts, not unrelated historical VR, PEG or other NADOC campaigns. It deletes historical DCDs, velocities, redundant output/restart coordinates and backups, Psi4/PySCF integral scratch, bytecode caches and disposable desktop screenshots/videos/traces. A per-file deletion manifest records paths, sizes and reasons.

Retained material includes all managed jobs and user designs; maintained code and tests; force-field definitions and provenance; the MVP export source `minimum-viable-candidates-v4`; compact audit JSONs; scientific reference arrays, native QM results and input geometries; and explicitly packaged historical research restart bundles. These contain information a prose summary cannot replace. Historical driver code is retained where dependency removal has not been established. Old reports may say bulk data were preserved: that was true at their writing, and this dated cleanup record supersedes those retention statements.
