"""Managed submodel planning and resource projections; source Designs stay intact."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from backend.physics.oxdna_submodel import crop, remap_pair_forces


def installation():
    root = Path(os.environ.get("NADOC_OXDNA_SUBMODEL_ROOT", Path.home()/".local/share/nadoc/engines/oxdna-submodel"))/"current"
    if not (root/"installation.json").is_file():
        raise ValueError("Install the CPU submodel engine with: uv run python -m scripts.build_oxdna_submodel")
    record = json.loads((root/"installation.json").read_text())
    result = dict(md=str((root/"md/oxDNA-submodel").resolve()),
                  mc=record["mc_binary"], plugins=str((root/"mc").resolve()))
    if not all(Path(result[k]).exists() for k in result) or not (root/"mc/SubmodelDNA2.so").is_file():
        raise ValueError("Submodel engine installation is incomplete; rebuild it")
    return result


def selected(job_dir):
    path = Path(job_dir)/"submodel_selection.json"
    return json.loads(path.read_text()).get("box") if path.exists() else None


def fingerprint(box):
    return hashlib.sha256(json.dumps({k:v for k,v in box.items() if k!="visible"},sort_keys=True).encode()).hexdigest()


def starting_conf(job, workspace):
    stages = job.stages if job.status == "completed" else job.stages[:job.current_stage_idx]
    for stage in reversed(stages):
        path = job.stage_dir(workspace,stage.name)/"last_conf.dat"
        if stage.status=="done" and path.is_file():
            return path
    return job.job_dir(workspace)/"conf.dat"


def plan(job, workspace, box=None, conf=None):
    """Resolve exactly the same aligned backbone positions as the job display."""
    from backend.api.routes_oxdna import _design_ref_conf
    from backend.core.models import Design
    from backend.physics.oxdna_interface import (
        _strand_nucleotide_order, read_configuration_unwrapped, oxdna_backbone_site,
        assert_topology_matches_design,
    )
    jd=job.job_dir(workspace)
    box=box if box is not None else selected(jd)
    if not box:
        return None
    design=Design.from_json((jd/"design.json").read_text())
    assert_topology_matches_design(jd/"topology.top",design)
    if design.nanoparticles:
        raise ValueError("Submodels currently support DNA-only jobs without nanoparticles or protein beads")
    conf=Path(conf) if conf else starting_conf(job,workspace)
    full=read_configuration_unwrapped(conf,design,_design_ref_conf(jd,design),
        align=True,copies=True,include_extra_bases=True,include_extensions=True)
    order=_strand_nucleotide_order(design)
    points=np.array([oxdna_backbone_site(full[tuple(k)]["backbone_position"],full[tuple(k)]["a1"],full[tuple(k)]["a3"]) for k in order])
    top, configuration, recipe=crop((jd/"topology.top").read_text(),conf.read_text(),points,box,box.get("shell_nm",3))
    recipe.update(source_configuration=str(conf.resolve()),
        source_configuration_sha256=hashlib.sha256(conf.read_bytes()).hexdigest(),
        source_topology_sha256=hashlib.sha256((jd/"topology.top").read_bytes()).hexdigest(),
        source_design_sha256=hashlib.sha256((jd/"design.json").read_bytes()).hexdigest(),
        source_keys=[list(k) for k in order],selection_fingerprint=fingerprint(box),
        display_policy="Native particles scattered into the full source order; omitted context remains fixed and is not simulated.")
    return top, configuration, recipe


def estimate(recipe, specs=()):
    """Reference-hardware native estimate plus conservative host/output budgets."""
    profile_path=Path(__file__).resolve().parents[1]/"data/oxdna/submodel_cpu_profile.json"
    n=len(recipe["retained_source_indices"]);m=len(recipe["mobile_source_indices"])
    source=recipe["source_particle_count"]
    profile=json.loads(profile_path.read_text()) if profile_path.exists() else None
    if profile:
        rate=profile["anchor_md_steps_per_second"]*(profile["anchor_particles"]/n)**profile["particle_exponent"]
        native_ram=max(profile["peak_rss_bytes"],profile["peak_rss_bytes"]*n/profile["max_particles"])
    else:
        rate=None;native_ram=64*1024**2+n*4096
    # MC rates are observed separately; don't extrapolate MD steps into MC sweeps.
    md_steps=sum(s.steps for s in specs if s.sim_type=="MD")
    mc_steps=sum(s.steps for s in specs if s.sim_type=="MC")
    from backend.core.oxdna_protocol import print_conf_interval
    frames=sum(s.steps//max(1,print_conf_interval(s))+1 for s in specs)
    return dict(source_nucleotides=source,simulated_nucleotides=n,mobile_nucleotides=m,fixed_nucleotides=n-m,
        omitted_nucleotides=source-n,backend="CPU",thermostat="brownian",
        md_steps_per_second=rate,md_seconds=md_steps/rate if rate else None,
        mc_steps=mc_steps,mc_seconds=None,
        native_ram_estimate_bytes=int(native_ram),
        host_ram_budget_bytes=int(512*1024**2+2*native_ram+source*4096),
        simulation_vram_bytes=0,
        output_budget_bytes=int((source+n)*200*frames*1.2),
        reference_cpu=profile.get("cpu_model") if profile else None,
        calibrated_range=profile.get("particle_range") if profile else None,
        extrapolated=bool(profile and not profile["particle_range"][0]<=n<=profile["particle_range"][1]),
        note="CPU reference-hardware estimate; live measurements replace it. RAM includes a 512 MiB worker allowance and full source context. Viewer memory is additional; simulation VRAM is zero. MC ETA awaits measured throughput.")


def preflight(job, workspace, specs):
    """Freeze selection and effective CPU protocol before the detached worker starts."""
    jd=job.job_dir(workspace)
    box=selected(jd)
    if not box:
        if any((job.stage_dir(workspace, s.name)/"submodel/extraction.json").exists() and s.status != "done" for s in job.stages):
            raise ValueError("Copy this partial job to remove its submodel; resume retains the original selection")
        job.submodel=None
        return specs
    if job.execution_target!="local":
        raise ValueError("Submodels currently run locally on CPU; choose Local")
    installation()
    pending=specs[job.current_stage_idx:]
    if any(s.parfile or s.interaction not in (None,"DNA2") or s.sim_type not in ("MC","MD") for s in pending):
        raise ValueError("Submodels currently support DNA2 MC/MD only")
    frozen=jd/"submodel_plan.json"
    prior=json.loads(frozen.read_text()) if frozen.exists() else None
    if prior and prior["selection_fingerprint"]==fingerprint(box):
        recipe=prior
        for filename, key in (("topology.top", "source_topology_sha256"), ("design.json", "source_design_sha256")):
            if hashlib.sha256((jd/filename).read_bytes()).hexdigest() != recipe[key]:
                raise ValueError("Submodel source changed; create a new job")
        top=(jd/"submodel_topology.top").read_text()
    else:
        top,conf,recipe=plan(job,workspace,box)
    for s in pending:
        path=jd/(s.forces_file or "forces.txt")
        if s.external_forces and path.exists():
            remap_pair_forces(path.read_text(),recipe)
    attachments=jd/"attachment_forces.txt"
    if attachments.exists() and attachments.read_text().strip():
        raise ValueError("Submodels do not yet support attachment forces")
    # A partially run stage may only resume its frozen selection.
    stage=job.stages[job.current_stage_idx]
    recorded=job.stage_dir(workspace,stage.name)/"submodel/extraction.json"
    if recorded.exists() and stage.status in ("stopped","failed","running"):
        prior=json.loads(recorded.read_text())
        if prior["selection_fingerprint"]!=fingerprint(box):
            raise ValueError("Copy this partial job to change its submodel; resume retains the original selection")
    effective=[s if i<job.current_stage_idx else replace(s,backend="CPU",absolute_forces=True,
               thermostat="brownian" if s.sim_type=="MD" else s.thermostat,
               diff_coeff=(s.diff_coeff if s.diff_coeff is not None else 2.5) if s.sim_type=="MD" else s.diff_coeff)
               for i,s in enumerate(specs)]
    job.backend="CPU"
    job.submodel={**estimate(recipe,effective[job.current_stage_idx:]),"selection":box,
                  "selection_fingerprint":fingerprint(box),"display_context":True}
    (jd/"submodel_topology.top").write_text(top)
    (jd/"submodel_plan.json").write_text(json.dumps(recipe,indent=2))
    (jd/"stages_spec.json").write_text(json.dumps([asdict(s) for s in effective],indent=2))
    return effective


def attempt_fraction(spec, completed_steps, energy_lines):
    """The first energy row is t=0; resumed attempts keep the original cadence."""
    interval = spec.print_energy_every_override or max(1, spec.steps // 100)
    remaining = max(1, spec.steps - (completed_steps or 0))
    return min(1.0, max(0, energy_lines - 1) * interval / remaining)
