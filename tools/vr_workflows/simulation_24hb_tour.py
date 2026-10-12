"""Temporary Full-representation 24HB simulation/trajectory performance fixture."""
import os
from tools.vr_workflows.tour_catalog import ROOT


def main():
    os.environ.setdefault('NADOC_VR_AUDIT_DESIGN', str(ROOT / 'workspace/24hb_0xT.nadoc'))
    os.environ.setdefault('NADOC_VR_FRAME_AUDIT', '1')
    from tools.vr_workflows.simulation_tour import main as run
    run()


if __name__ == '__main__':
    main()
