"""Read-only SteamVR timing sampler; run with `uv run --with openvr python -m ...`.

Uses a background application and never submits images or calls WaitGetPoses.
Writes unique compositor frames, not inferred application drop counts.
"""
import argparse
import ctypes
import json
import signal
import time
from pathlib import Path


def main():
    import openvr
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=300)
    args = parser.parse_args()
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    openvr.init(openvr.VRApplication_Background)
    try:
        compositor = openvr.VRCompositor()
        frames = (openvr.Compositor_FrameTiming * 128)()
        frames[0].m_nSize = ctypes.sizeof(openvr.Compositor_FrameTiming)
        previous = -1
        deadline = time.monotonic() + args.seconds
        with args.output.open('x') as output:
            while running and time.monotonic() < deadline:
                count, values = compositor.getFrameTimings(frames)
                now = time.time() * 1000
                for frame in values[:count]:
                    if frame.m_nFrameIndex <= previous:
                        continue
                    previous = frame.m_nFrameIndex
                    data = {key: getattr(frame, key) for key, _ in frame._fields_ if key != 'm_HmdPose'}
                    data['sample_wall_time_ms'] = now
                    output.write(json.dumps(data) + '\n')
                output.flush()
                time.sleep(.1)
    finally:
        openvr.shutdown()


if __name__ == '__main__':
    main()
