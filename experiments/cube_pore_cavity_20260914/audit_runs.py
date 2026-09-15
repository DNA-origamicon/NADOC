from pathlib import Path
import json,re,datetime
root=Path(__file__).resolve().parent;rows={}
paths=list((root/'bulk').glob('*/run.conf'))+list((root/'open_pore').glob('*/run.conf'))+[root/d/'run.conf' for d in ['full_npzat','full_wet_static','full_wet_static_no_enm','full_wet_static_physical']]
for conf in paths:
 d=conf.parent;log=(d/'run.log').read_text(errors='replace') if (d/'run.log').exists() else '';a=[l.split() for l in conf.read_text().splitlines() if l.split()];run=sum(int(x[1]) for x in a if x[0]=='run');mini=sum(int(x[1]) for x in a if x[0]=='minimize');dt=float(next(x[1] for x in a if x[0]=='timestep'));energies=[int(l.split()[1]) for l in log.splitlines() if l.startswith('ENERGY:')];wanted=run+mini;last=energies[-1] if energies else None
 # Final output can be beyond the last configured ENERGY interval.
 finals=[int(x) for x in re.findall(r'WRITING VELOCITIES TO OUTPUT FILE AT STEP (\d+)',log)];final=finals[-1] if finals else last
 rows[str(d.relative_to(root))]={'requested_dynamics_ps':run*dt/1000,'last_energy_step':last,'final_output_step':final,'fatal_error':'FATAL ERROR' in log,'completed':'End of program' in log and 'FATAL ERROR' not in log and final is not None and final>=wanted}
for d in (root/'openmm_full').glob('*/meta.json'):
 p=d.parent;mode=p.name;log=(root/'openmm_validation'/f'{mode}.log').read_text(errors='replace');meta=json.loads(d.read_text());lines=(p/'metrics.jsonl').read_text().splitlines();last=json.loads(lines[-1]) if lines else {}
 rows['openmm_full/'+mode]={'requested_dynamics_ps':meta['duration_ps'],'last_time_ps':last.get('time_ps'),'completed':'\ncompleted\n' in log and last.get('time_ps',-1)>=meta['duration_ps'],'exception':'Traceback' in log}
out={'updated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'runs':rows};(root/'run_audit.json').write_text(json.dumps(out,indent=2)+'\n')
for name,r in rows.items():print(name,'COMPLETE' if r['completed'] else 'PENDING / FAILED',r.get('last_time_ps',r.get('final_output_step')))
