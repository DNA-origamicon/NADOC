# R1 graphene force-field correction (2026-09-04) — supporting detail

[Topic head](../../project_md_job_system.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## R1 graphene force-field correction (2026-09-04)

R1 `0a2aaa5638ff` / Slurm `32088967` failed at k=0.1 step 14: unbonded
graphene CA sites experienced enormous mutual LJ repulsion at 1.42 Å. New
packages use dedicated NGRC sites with CA cross LJ and zero NGRC–NGRC NBFIX
in `par_np_thiol.prm`. Geometry, anchor stiffness and 4 fs timestep are unchanged.
`namd_graphene.validate_graphene_wall_package` blocks legacy wall packages before
Alpine submit/resume, local execution and RunPod provisioning. Copy + Run must
rebuild and minimize; old graphene checkpoints are not reusable. Copy remains an
editable draft and does not prepare or submit. See `docs/namd_graphene_wall_failure_audit.md`.

Graphene UI default: the nanopore checkbox starts off and resets off on workspace
file changes and job deselection/removal. Selecting a job restores its inherited
`prep_params.graphene_nanopore`; empty-list polling does not erase a user's manual
choice while configuring a new job.
