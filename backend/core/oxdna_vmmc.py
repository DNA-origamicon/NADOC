"""CPU equilibrium duplex melting: persisted protocol, native inputs and analysis."""
from dataclasses import replace
from pathlib import Path
import json
import math
import secrets

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class VmmcMelting(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    temperature_c: float = Field(70, gt=0, le=150)
    start_c: float = Field(60, gt=0, le=150)
    end_c: float = Field(80, gt=0, le=150)
    step_c: float = Field(2, gt=0, le=20)
    tuning_rounds: int = Field(4, ge=1, le=20)
    tuning_steps: int = Field(200000, ge=1000, le=100000000)
    equil_steps: int = Field(200000, ge=1000, le=100000000)
    production_steps: int = Field(2000000, ge=1000, le=1000000000)
    replicas: int = Field(5, ge=3, le=20)

    @model_validator(mode='after')
    def valid_range(self):
        if self.end_c <= self.start_c or math.ceil((self.end_c-self.start_c)/self.step_c) > 40:
            raise ValueError('Choose an increasing temperature range with at most 41 points.')
        if not self.start_c <= self.temperature_c <= self.end_c:
            raise ValueError('The sampling temperature must be inside the analysis range.')
        return self

    def temperatures(self):
        return [min(self.start_c+i*self.step_c, self.end_c)
                for i in range(math.ceil((self.end_c-self.start_c)/self.step_c)+1)]


def duplex_pairs(topology):
    rows = Path(topology).read_text().splitlines()[1:]
    strands = {}
    for i, row in enumerate(rows):
        fields = row.split()
        if len(fields) != 4 or fields[1] not in {'A', 'C', 'G', 'T'} or int(fields[0]) <= 0:
            raise ValueError('VMMC melting requires DNA only, with assigned A/C/G/T sequence.')
        strands.setdefault(fields[0], []).append((i, fields[1]))
    if len(strands) != 2:
        raise ValueError('VMMC melting currently supports one complementary two-strand duplex.')
    a, b = strands.values()
    if len(a) != len(b) or len(a) < 2 or len(a) > 100:
        raise ValueError('VMMC melting supports complementary strands of 2–100 bases each.')
    complement = dict(A='T', T='A', C='G', G='C')
    if any(complement[x[1]] != y[1] for x,y in zip(a, reversed(b))):
        raise ValueError('The two VMMC strands must be fully reverse-complementary.')
    # Classic oxDNA rows follow 3′→5′; verify that exported rows are linear chains.
    for chain in (a,b):
        for j,(idx,_) in enumerate(chain):
            links = list(map(int, rows[idx].split()[2:]))
            if links != [chain[j+1][0] if j+1 < len(chain) else -1, chain[j-1][0] if j else -1]:
                raise ValueError('VMMC melting requires two linear, contiguous DNA strands.')
    return [(x[0],y[0]) for x,y in zip(a,reversed(b))]


def validate_request(body, directory, parent):
    if not body.vmmc_melting:
        return
    if body.thermal_ramp:
        raise ValueError('Choose either a thermal ramp or VMMC equilibrium melting.')
    # The wizard sends {box: null} to explicitly request the whole system.
    if body.field or body.surface or body.anchors or body.surface_anchors or body.surface_strands or (body.submodel is not None and body.submodel.box is not None):
        raise ValueError('VMMC duplex melting uses free solution without fields, surfaces, anchors or submodels.')
    config = parent.run_config or {}
    if config.get('surface_strands') or config.get('mobile_gold') or list(Path(directory).glob('*cpd*')):
        raise ValueError('VMMC melting is validated for undamaged DNA duplexes; CPD and hybrid systems require separate validation.')
    duplex_pairs(Path(directory)/'topology.top')


def configure(child, stage, config):
    cfg = VmmcMelting.model_validate(config)
    tasks = [('tune', i, cfg.tuning_steps) for i in range(cfg.tuning_rounds)]
    for i in range(cfg.replicas):
        tasks.extend([('equil',i,cfg.equil_steps),('sample',i,cfg.production_steps)])
    if child.random_seed is None:
        child.random_seed = secrets.randbelow(2147483646) + 1
    specs = [replace(stage, name=f'{j+1}_vmmc_{kind}_{i+1}', sim_type='VMMC', backend='CPU',
              kind='production', steps=steps, dt=1, temperature=f'{cfg.temperature_c+273.15:.10g}K',
              sequence_dependent=True, external_forces=False, forces_file=None, thermal_ramp=None,
              print_energy_every_override=max(1,min(1000,steps//100)),
              print_conf_interval_override=max(1,min(10000,steps//100)),
              min_bp_retained=0, seed=(child.random_seed-1+j) % 2147483646+1)
             for j,(kind,i,steps) in enumerate(tasks)]
    child.backend='CPU'
    child.salt_concentration=stage.salt_concentration
    child.stages=[s.to_status() for s in specs]
    child.run_config.update(vmmc_melting=cfg.model_dump(), backend='CPU', salt_concentration=stage.salt_concentration)
    child.run_config.pop('thermal_ramp',None)
    child.run_config.pop('vmmc_result',None)
    return specs


def write_order_parameters(root):
    pairs=duplex_pairs(root/'topology.top')
    (root/'vmmc_op.txt').write_text('{\norder_parameter = bond\nname = duplex\n'+
        ''.join(f'pair{i+1} = {a}, {b}\n' for i,(a,b) in enumerate(pairs))+'}\n')
    return len(pairs)


def render_input(root, directory, spec, cfg, conf):
    return f'''backend = CPU
sim_type = VMMC
ensemble = NVT
interaction_type = DNA2
seed = {spec.seed}
steps = {spec.steps}
T = {cfg.temperature_c}C
salt_concentration = {spec.salt_concentration}
use_average_seq = false
seq_dep_file = {root/'oxDNA2_sequence_dependent_parameters.txt'}
delta_translation = 0.22
delta_rotation = 0.22
verlet_skin = 1.0
small_system = 1
umbrella_sampling = 1
safe_weights = 1
op_file = {root/'vmmc_op.txt'}
weights_file = {directory/'weights.txt'}
extrapolate_hist = {', '.join(f'{t:g}C' for t in cfg.temperatures())}
print_traj_hist_file = false
last_hist_file = last_hist.dat
hist_file = last_hist.dat
topology = {root/'topology.top'}
conf_file = {conf}
lastconf_file = last_conf.dat
trajectory_file = trajectory.dat
energy_file = energy.dat
restart_step_counter = true
time_scale = linear
print_conf_interval = {spec.print_conf_interval_override}
print_energy_every = {spec.print_energy_every_override}
max_io = 1000
'''


def histogram(path, n_pairs, n_temperatures):
    data=np.loadtxt(path,comments='#',ndmin=2)
    if data.shape != (n_pairs+1, n_temperatures+3) or not np.array_equal(data[:,0],np.arange(n_pairs+1)):
        raise ValueError('Incomplete VMMC histogram or unexpected order-parameter columns.')
    if not np.all(np.isfinite(data)) or np.any(data < 0):
        raise ValueError('Invalid VMMC histogram values.')
    if np.any(data[:, 1:].sum(axis=0) <= 0):
        raise ValueError('VMMC histogram contains an empty sampling or reweighting column.')
    return data


def tune_weights(weights, counts):
    counts=np.asarray(counts,dtype=float)
    correction=np.clip(np.sqrt((counts.mean()+1)/(counts+1)),.05,20)
    result=np.asarray(weights)*correction
    return np.maximum(result/result.max(),1e-12)


def duplex_yield(ratio):
    # Stable form of 1 + 1/(2r) - sqrt((1 + 1/(2r))**2 - 1).
    if ratio <= 0: return 0.
    if math.isinf(ratio): return 1.
    return 2*ratio/(2*ratio+1+math.sqrt(4*ratio+1))


def melting_point(temperatures, yields):
    for i in range(len(yields)-1):
        if yields[i] >= .5 >= yields[i+1] and yields[i] != yields[i+1]:
            return temperatures[i]+(temperatures[i+1]-temperatures[i])*(yields[i]-.5)/(yields[i]-yields[i+1])
    return None


def analyse(root, specs, cfg, n_pairs):
    from backend.core.oxdna_concentration import configuration_box
    _, box_conditions = configuration_box(root)
    replicas=[]
    for spec in specs:
        if '_sample_' not in spec.name: continue
        directory=root/spec.name
        data=histogram(directory/'last_hist.dat',n_pairs,len(cfg.temperatures()))
        yields=[]
        for column in data[:,3:].T:
            ratio=column[1:].sum()/column[0] if column[0] else float('inf')
            yields.append(duplex_yield(float(ratio)))
        energy=np.loadtxt(directory/'energy.dat',ndmin=2)
        # Native VMMC energy: step, U, translation/rotation/volume acceptance, q, weight.
        if energy.shape[1] != 7 or not np.all(np.isfinite(energy)) or np.any(energy[:, -2] < 0) or np.any(energy[:, -2] > n_pairs):
            raise ValueError('Invalid native VMMC energy/order-parameter data.')
        states=energy[:,-2]>0
        transitions=int(np.count_nonzero(states[1:] != states[:-1]))
        replicas.append({'stage':spec.name,'seed':spec.seed,'tm_c':melting_point(cfg.temperatures(),yields),
          'yields':yields,'observed_bound_unbound_transitions':transitions,
          'visited_pair_counts':int(np.count_nonzero(data[:,1]))})
    mean=np.mean([r['yields'] for r in replicas],axis=0).tolist()
    reasons=[]
    if any(r['observed_bound_unbound_transitions'] < 20 for r in replicas):
        reasons.append('Fewer than 20 recorded bound/unbound transitions in one or more replicas.')
    if any(r['visited_pair_counts'] < n_pairs+1 for r in replicas):
        reasons.append('One or more replicas did not visit every base-pair count.')
    if any(r['tm_c'] is None for r in replicas):
        reasons.append('The analysis temperature range does not bracket 50% duplex yield in every replica.')
    tm=melting_point(cfg.temperatures(),mean)
    estimates=[r['tm_c'] for r in replicas if r['tm_c'] is not None]
    result={'status':'inconclusive' if reasons else 'sampling_checks_passed','reasons':reasons,
      'temperatures_c':cfg.temperatures(),'duplex_yield':mean,'tm_c':tm,
      'replica_tm_sem_c':float(np.std(estimates,ddof=1)/math.sqrt(len(estimates))) if len(estimates)==len(replicas) else None,
      'replicas':replicas,'method':'native histogram reweighting with two-strand finite-size correction',
      'box_conditions':box_conditions, 'salt_concentration_M':specs[0].salt_concentration,
      'sampling_temperature_c':cfg.temperature_c, 'interaction':'sequence-dependent oxDNA2',
      'protocol':cfg.model_dump(),
      'qualification':'Sampling checks are diagnostics, not proof of convergence; replicas share frozen tuned weights.'}
    (root/'vmmc_result.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['temperature_C,duplex_yield']+[f'{t},{y:.10g}' for t,y in zip(cfg.temperatures(),mean)]
    (root/'vmmc_melting.csv').write_text('\n'.join(lines)+'\n')
    return result
