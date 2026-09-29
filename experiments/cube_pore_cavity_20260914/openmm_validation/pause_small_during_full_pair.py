from pathlib import Path
import os,signal,time,json
root=Path(__file__).resolve().parent;pid=256111
cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode()
assert 'open_pore/fill_96' in cmd and 'namd3' in cmd
record={'paused_pid':pid,'command':cmd,'paused_at':time.time()}
os.kill(pid,signal.SIGSTOP);(root/'gpu_schedule.json').write_text(json.dumps(record,indent=2)+'\n')
try:
 for _ in range(2160):
  logs={name:(root/name).read_text(errors='replace') if (root/name).exists() else '' for name in ['npzat.log','nvt.log','nvt_queue.log']}
  if any('Traceback' in s for s in logs.values()):record['resume_reason']='full-pair exception';break
  if '\ncompleted\n' in logs['nvt.log']:record['resume_reason']='full pair finished';break
  time.sleep(5)
 else:record['resume_reason']='three-hour scheduling limit'
finally:
 try:os.kill(pid,signal.SIGCONT)
 except ProcessLookupError:pass
 record['resumed_at']=time.time();(root/'gpu_schedule.json').write_text(json.dumps(record,indent=2)+'\n');print(record,flush=True)
