"""Frozen charge transfer to newly evaluated lower-energy conformer."""
import json,sys
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import unit as u
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from backend.parameterization.photoproduct_qm import parse_xyz
from experiments.cpd_anti_additive.core_baseline import checked,source,write
art=REPO/'.development-artifacts';folder=art/'cpd-anti-remote-esp-v1/endpoint-2';audit=json.loads((folder/'esp_audit.json').read_text());assert audit['passed'];job=json.loads(checked(audit['job_manifest']).read_text());run=json.loads((folder/'run_manifest.json').read_text());assert run['returncode']==0 and run['parsed']['passed_execution_checks'];[checked(s) for s in run['outputs'].values()];assert run['job_manifest_sha256']==source(folder/'job_manifest.json')['sha256'];atoms,_=parse_xyz(checked(job['source_xyz']).read_text());x=np.array([a[1:] for a in atoms]);grid=np.loadtxt(checked(audit['grid']));target=np.loadtxt(checked(audit['potentials']));assert grid.shape==(1274,3) and target.shape==(1274,) and np.isfinite(target).all();A=.529177210903/np.linalg.norm(grid[:,None,:]-x[None,:,:],axis=2);qm=np.array(audit['dipole']['vector']);rows=[]
base=json.loads((art/'cpd-anti-matched-mm-v1/plan.json').read_text())
for c in base['candidates']:
 s=mm.XmlSerializer.deserialize(checked(c['systems']['2']).read_text());nb=next(f for f in s.getForces() if isinstance(f,mm.NonbondedForce));q=np.array([nb.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in range(len(x))]);assert abs(q.sum())<1e-7;err=A@q-target;dip=q@x/.529177210903;rows.append(dict(candidate=c['label'],esp_rmse_au=float(np.sqrt(np.mean(err**2))),esp_relative_rmse=float(np.linalg.norm(err)/np.linalg.norm(target)),dipole_vector_error_debye=float(np.linalg.norm(dip-qm)*2.541746473),system=c['systems']['2']))
write(art/'cpd-anti-remote-esp-v1/independent_review.json',dict(point_count=1274,esp_audit=source(folder/'esp_audit.json'),run_manifest=source(folder/'run_manifest.json'),records=rows,scope='Frozen charges on newly generated conformer targets before refit; no release',simulation_ready=False))
for r in rows:print(r['candidate'],r['esp_relative_rmse'],r['dipole_vector_error_debye'])
