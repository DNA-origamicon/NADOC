"""CPU submodel lifecycle with native output and explicit full-context projection."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

import numpy as np

from backend.core.oxdna_job import OxdnaStatus
from backend.core.oxdna_protocol import render_stage_input, print_conf_interval
from backend.core.oxdna_submodel import installation
from backend.physics.oxdna_submodel import expand_frame, remap_pair_forces


def atomic_text(path, text):
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(text)
    temporary.replace(path)


class Projector:
    """Incrementally publish only complete native frames, preserving source order."""
    def __init__(self, native, stage, recipe, context):
        self.native,self.stage,self.recipe,self.context=native,stage,recipe,context
        self.offset=0
        self.n=len(recipe["retained_source_indices"])
        self.last_signature=None
        self.reference=np.array([[float(x) for x in row.split()] for row in (native/"conf.dat").read_text().splitlines()[3:]])
        # Match oxDNA's configuration-load orthonormalization exactly. The
        # exporter may have written only six decimals; this is not shell motion.
        a1=self.reference[:,3:6];a3=self.reference[:,6:9]
        a1/=np.linalg.norm(a1,axis=1)[:,None]
        a3/=np.linalg.norm(a3,axis=1)[:,None]
        a1-=a3*np.sum(a1*a3,axis=1)[:,None]
        a1/=np.linalg.norm(a1,axis=1)[:,None]
        mobile=set(recipe["mobile_output_indices"])
        self.fixed=np.array([i not in mobile for i in range(self.n)])

    def expand(self, text):
        rows=np.array([[float(x) for x in row.split()] for row in text.splitlines()[3:]])
        if rows.shape!=(self.n,15) or not np.isfinite(rows).all():
            raise ValueError("Invalid native submodel frame")
        if self.fixed.any():
            if not np.array_equal(rows[self.fixed,:3],self.reference[self.fixed,:3]):
                raise ValueError("Fixed shell position changed")
            if not np.allclose(rows[self.fixed,3:9],self.reference[self.fixed,3:9],atol=1e-10,rtol=0):
                raise ValueError("Fixed shell orientation changed")
            if np.any(rows[self.fixed,9:15]!=0):
                raise ValueError("Fixed shell momentum changed")
        return expand_frame(text,self.context,self.recipe)

    def sync(self):
        trajectory=self.native/"trajectory.dat"
        if trajectory.exists():
            with trajectory.open() as src, (self.stage/"trajectory.dat").open("a") as out:
                src.seek(self.offset)
                while True:
                    start=src.tell()
                    lines=[src.readline() for _ in range(self.n+3)]
                    if any(not line.endswith("\n") for line in lines):
                        src.seek(start)
                        break
                    out.write(self.expand("".join(lines)))
                    self.offset=src.tell()
        last=self.native/"last_conf.dat"
        if last.exists():
            stat=last.stat();signature=(stat.st_mtime_ns,stat.st_size)
            if signature!=self.last_signature:
                text=last.read_text()
                if text.endswith("\n") and len(text.splitlines())==self.n+3:
                    atomic_text(self.stage/"last_conf.dat",self.expand(text))
                    self.last_signature=signature
        energy=self.native/"energy.dat"
        if energy.exists():
            text=energy.read_text()
            if "\n" in text:
                atomic_text(self.stage/"energy.dat",text[:text.rfind("\n")+1])


def stage_input(spec, native, engines, parameter_file):
    text=render_stage_input(spec,str(native/"topology.top"),str(native/"conf.dat"),
        forces_name=str(native/"forces.txt") if spec.external_forces else None,
        sequence_parameters_name=str(parameter_file))
    # Suppress every global pose or momentum correction, including native defaults.
    text=re.sub(r"(?m)^fix_diffusion\s*=.*\n","",text)
    text+="\nfix_diffusion = false\nreset_initial_com_momentum = false\nreset_com_momentum = false\nuse_barostat = false\n"
    text=text.replace("interaction_type = DNA2\n", "interaction_type = SubmodelDNA2\n")
    text+=f"plugin_search_path = {engines['plugins']}\nsubmodel_mobile_file = {native/'mobile.txt'}\n"
    if spec.sim_type!="MD":
        text=text.replace("sim_type = MC\n","sim_type = MC2\n")
        text+="\nplugin_move_entry_points = make_move\n"
        text+=f"move_1 = {{\n type = SubmodelTranslation\n delta = {spec.delta_translation}\n prob = 1\n}}\n"
        text+=f"move_2 = {{\n type = SubmodelRotation\n delta = {spec.delta_rotation}\n prob = 1\n}}\n"
    return text


async def health(native, recipe, spec, dnanalysis):
    """Pair retention is scoped to designed pairs touching mobile particles."""
    from backend.core.oxdna_health import OxdnaHealthResult, parse_energy_dat
    res=OxdnaHealthResult()
    energies=parse_energy_dat(native/"energy.dat")
    if energies:res.potential_energy=energies[-1][1]
    grouped={}
    mobile=set(recipe["mobile_output_indices"])
    for new,old in enumerate(recipe["retained_source_indices"]):
        key=recipe["source_keys"][old]
        if len(key)==3 and not key[0].startswith("__"):
            grouped.setdefault(tuple(key[:2]),[]).append(new)
    expected={tuple(sorted(pair)) for pair in grouped.values() if len(pair)==2 and any(i in mobile for i in pair)}
    if expected:
        if not dnanalysis:
            raise ValueError("DNAnalysis is required to verify submodel pair retention")
        text=(native/"input.txt").read_text().replace("trajectory_file = trajectory.dat","trajectory_file = last_conf.dat")
        text+="\nanalysis_data_output_1 = {\n name = hb.dat\n print_every = 1\n col_1 = {\n type = hb_list\n }\n}\n"
        (native/"analysis.input").write_text(text)
        with (native/"analysis.log").open("w") as log:
            process=await asyncio.create_subprocess_exec(dnanalysis,"analysis.input",cwd=native,stdout=log,stderr=asyncio.subprocess.STDOUT)
            try:
                await asyncio.wait_for(process.wait(),60)
            except BaseException:
                process.kill();await process.wait();raise
            if process.returncode:raise ValueError("Submodel native hydrogen-bond analysis failed")
        pairs={tuple(sorted(map(int,line.split()))) for line in (native/"hb.dat").read_text().splitlines() if line.strip() and not line.startswith("#")}
        res.n_pairs=len(expected)
        res.bp_retained_fraction=len(pairs&expected)/len(expected)
        res.passed=res.bp_retained_fraction>=spec.min_bp_retained
        if not res.passed:res.reason=f"Mobile-region pair retention {res.bp_retained_fraction:.1%} below {spec.min_bp_retained:.1%}; enlarge or relax the boundary region before sampling"
    return res


async def retry(job, workspace, specs, idx, *, production=False):
    """Preserve failed attempts and honor the job's existing bounded retry policy."""
    from backend.core.oxdna_protocol import escalate_md_relax_spec
    from backend.core.oxdna_submodel import estimate
    jd=job.job_dir(workspace)
    spec=specs[idx]
    if production:
        if job.production_retries>=job.max_production_retries:
            return False
        job.production_retries+=1
        specs[idx]=replace(spec,dt=spec.dt/2)
    else:
        if spec.kind!="md_relax" or job.relax_retries>=job.max_relax_retries:
            return False
        base_path=jd/"submodel_base_relax.json"
        if not base_path.exists():
            base_path.write_text(json.dumps(asdict(spec)))
        from backend.core.oxdna_protocol import OxdnaStageSpec
        base=OxdnaStageSpec(**json.loads(base_path.read_text()))
        job.relax_retries+=1
        specs[idx]=escalate_md_relax_spec(base,job.relax_retries)
    history=jd/"submodel_attempts";history.mkdir(exist_ok=True)
    for i in range(idx,len(specs)):
        stage=job.stage_dir(workspace,specs[i].name)
        if stage.exists():
            number=1
            while (history/(stage.name+"-"+str(number))).exists():
                number+=1
            shutil.move(stage,history/(stage.name+"-"+str(number)))
        job.stages[i]=specs[i].to_status()
    job.current_stage_idx=idx
    recipe=json.loads((jd/"submodel_plan.json").read_text())
    job.submodel.update(estimate(recipe,specs[idx:]))
    (jd/"stages_spec.json").write_text(json.dumps([asdict(s) for s in specs],indent=2))
    job.save(workspace)
    await _run(job,workspace,specs)
    return True


async def _run(job, workspace, specs):
    from backend.core.oxdna_runner import (
        _run_oxdna_async, _health_sample, _append_jsonl, find_dnanalysis,
        resume_point, _archive_partial_outputs, conf_is_restartable,
    )
    from backend.core.oxdna_submodel import starting_conf
    jd=job.job_dir(workspace);engines=installation()
    recipe=json.loads((jd/"submodel_plan.json").read_text())
    for idx in range(job.current_stage_idx,len(specs)):
        spec=specs[idx];status=job.stages[idx]
        if status.status=="done":continue
        job.current_stage_idx=idx
        stage=job.stage_dir(workspace,spec.name);stage.mkdir(parents=True,exist_ok=True)
        native=stage/"submodel";native.mkdir(exist_ok=True)
        saved_recipe=native/"extraction.json"
        if saved_recipe.exists():
            recipe=json.loads(saved_recipe.read_text())
        else:
            source=starting_conf(job,workspace)
            context=source.read_text()
            (native/"context.dat").write_text(context)
            source_lines=context.splitlines()
            (native/"conf.dat").write_text("\n".join(source_lines[:3]+[source_lines[3+i] for i in recipe["retained_source_indices"]])+"\n")
            shutil.copy2(jd/"submodel_topology.top",native/"topology.top")
            recipe={**recipe,"stage_source_configuration":str(source),"stage_source_sha256":hashlib.sha256(source.read_bytes()).hexdigest()}
            saved_recipe.write_text(json.dumps(recipe,indent=2))
        context=(native/"context.dat").read_text()
        n=len(recipe["retained_source_indices"])
        consumed=0
        if (native/"last_conf.dat").exists() or (native/"trajectory.dat").exists():
            checkpoint,consumed,_=resume_point(native,spec,n)
            if checkpoint:
                checkpoint_text=checkpoint.read_text()
                _archive_partial_outputs(native);_archive_partial_outputs(stage)
                (native/"conf.dat").write_text(checkpoint_text)
        remaining=max(0,spec.steps-consumed)
        effective=replace(spec,steps=remaining,refresh_vel=spec.refresh_vel if not consumed else False,
            print_conf_interval_override=print_conf_interval(spec),
            print_energy_every_override=spec.print_energy_every_override or max(1,spec.steps//100))
        (native/"mobile.txt").write_text("\n".join(map(str,recipe["mobile_output_indices"]))+"\n")
        if spec.external_forces:
            source=jd/(spec.forces_file or "forces.txt")
            (native/"forces.txt").write_text(remap_pair_forces(source.read_text(),recipe))
        text=stage_input(effective,native,engines,jd/"oxDNA2_average_sequence_parameters.txt")
        (native/"input.txt").write_text(text)
        # Stage settings/progress readers see the effective native input and cadence.
        (stage/"input.txt").write_text(text)
        projection=Projector(native,stage,recipe,context)
        status.status="running";status.started_at=time.time();status.completed_steps=consumed;status.resumed=bool(consumed)
        job.status=OxdnaStatus.running;job.error=None;job.save(workspace)
        def pid(value):
            job.oxdna_pid=value;job.save(workspace)
        binary=engines["md"] if spec.sim_type=="MD" else engines["mc"]
        execution=dict(binary=binary, binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            interaction_plugin=str(Path(engines["plugins"])/"SubmodelDNA2.so"),
            interaction_sha256=hashlib.sha256((Path(engines["plugins"])/"SubmodelDNA2.so").read_bytes()).hexdigest(),
            input_sha256=hashlib.sha256(text.encode()).hexdigest(),
            native_particles=n,mobile_particles=len(recipe["mobile_output_indices"]),steps=remaining,
            energy_policy="Fixed-fixed backbone energy omitted as a constant; topology and mobile-involving forces unchanged")
        atomic_text(native/"execution.json",json.dumps(execution,indent=2))
        started=time.monotonic()
        task=asyncio.create_task(_run_oxdna_async(binary,native/"input.txt",native,stage/"oxdna.log",job.job_id,on_spawn=pid))
        try:
            while not task.done():
                projection.sync()
                await asyncio.sleep(.25)
            rc,_=await task
            projection.sync()
        finally:
            if not task.done():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            # Recover complete output on stop/cancellation too.
            projection.sync()
        elapsed=max(1e-6,time.monotonic()-started)
        execution.update(exit_code=rc,elapsed_seconds=elapsed)
        atomic_text(native/"execution.json",json.dumps(execution,indent=2))
        if rc or not conf_is_restartable(native/"last_conf.dat",n):
            from backend.core.oxdna_runner import _log_indicates_explosion
            if spec.kind=="md_relax" and await retry(job,workspace,specs,idx):
                return
            if spec.kind in ("production","run") and _log_indicates_explosion(stage/"oxdna.log") and await retry(job,workspace,specs,idx,production=True):
                return
            status.status="failed";job.status=OxdnaStatus.failed
            job.error=f"Submodel native stage {spec.name} failed (exit {rc}); see its oxDNA log"
            reasons=[line.strip() for line in (stage/"oxdna.log").read_text(errors="replace").splitlines() if line.startswith("ERROR:")]
            if reasons:job.error += ": " + reasons[-1][6:].strip()[:400]
            job.save(workspace);return
        res=await health(native,recipe,spec,find_dnanalysis())
        sample=_health_sample(spec.name,spec.kind,res,remaining/elapsed if remaining else None)
        job.health_samples.append(sample);_append_jsonl(jd/"health.jsonl",asdict(sample))
        _append_jsonl(jd/"metrics.jsonl",dict(stage=spec.name,kind=spec.kind,steps=remaining,elapsed_s=elapsed,
            steps_per_s=sample.steps_per_s,potential_energy=res.potential_energy,scope="mobile-region pairs; native cropped energy"))
        if not res.passed:
            if await retry(job,workspace,specs,idx):
                return
            status.status="failed";job.status=OxdnaStatus.failed;job.error=res.reason;job.save(workspace);return
        status.status="done";job.save(workspace)
    job.current_stage_idx=len(specs)
    job.status=OxdnaStatus.completed;job.error=None;job.oxdna_pid=None;job.save(workspace)


async def run(job, workspace, specs):
    try:
        await _run(job, workspace, specs)
    except BaseException as exc:
        stopped=isinstance(exc, asyncio.CancelledError)
        if 0<=job.current_stage_idx<len(job.stages):
            job.stages[job.current_stage_idx].status="stopped" if stopped else "failed"
        job.status=OxdnaStatus.stopped if stopped else OxdnaStatus.failed
        job.error=None if stopped else str(exc)
        job.oxdna_pid=None
        job.save(workspace)
        raise
