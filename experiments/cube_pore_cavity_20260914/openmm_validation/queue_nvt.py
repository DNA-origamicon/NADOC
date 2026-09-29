from pathlib import Path
import time,subprocess
root=Path(__file__).resolve().parent
for _ in range(7200):
 log=(root/'npzat.log').read_text(errors='replace')
 if 'Traceback' in log:raise RuntimeError('NPzAT branch failed; do not start paired test')
 if '\ncompleted\n' in log:break
 time.sleep(5)
else:raise RuntimeError('NPzAT branch did not finish within 10 hours')
with (root/'nvt.log').open('w') as f:
 code=subprocess.run([str(root.parents[2]/'.venv/bin/python'),str(root/'run_full_dynamics.py'),'nvt','50'],stdout=f,stderr=subprocess.STDOUT).returncode
print('nvt returncode',code,flush=True)
