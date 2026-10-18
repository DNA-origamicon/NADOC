"""Discoverable terminal entry for measured origami image positions."""
from tools.vr_tracking.__main__ import main as tracking_main


def main():
    import sys
    if len(sys.argv) == 1:
        print("Origami tracking measures named features in original eye images.\n"
              "Read docs/vr_origami_tracking.md for reference selection, expected-pose comparisons,\n"
              "and the optional pose journal attached to Tools → Record final output.\n"
              "Run python -m tools.vr_tracking --help for export/track/identify-frames/compare-temporal.\n"
              "Opt-in submitted frame markers identify reused images and exact pose-journal rows.\n"
              "Use summarize-interactions --journal PATH [--identities PATH] --output NEW_DIR\n"
              "for a timing review of image reuse, menu hover, texture work and haptic dispatch.\n"
              "NADOC_VR_GPU_PASS_TIMING=1 measures shadow and eye GPU timeline intervals.\n"
              "Use summarize-gpu-passes on the saved viewer log to inspect cost and missing measurements.\n"
              "For a preserved Ball+Stick view, keep indexing enabled and compare\n"
              "NADOC_VR_GROUPED_INDEXED_MESHES=0 and =1 in separate launches. Check indexed_meshes\n"
              "group counters, GPU intervals and final-image reuse; plain indexing also has an opt-out.\n"
              "Confirm molecular held-frame drift/new-frame return with compare-temporal; GPU cost alone\n"
              "does not establish that a visible motion problem is resolved. See the documented workflow.\n"
              "Final distorted pixel positions still require separate lens calibration.\n"
              "This entry never restarts a runtime or changes the scene.")
        return
    tracking_main()


if __name__ == '__main__':
    main()
