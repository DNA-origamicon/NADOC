"""Human review holds outside timed controller reaches; no validation shortcuts."""
import os
import time
from tools.vr_motion.desktop_check import reveal_viewer


def reveal(live):
    if os.environ.get('NADOC_VR_DEMO') == '1':
        reveal_viewer(live)


def hold(live, label):
    if os.environ.get('NADOC_VR_DEMO') != '1':
        return
    reveal_viewer(live)
    print('Review: '+label,flush=True)
    deadline=time.monotonic()+float(os.environ.get('NADOC_VR_DEMO_HOLD','6'))
    while time.monotonic()<deadline:
        live.frame()
        time.sleep(.1)
