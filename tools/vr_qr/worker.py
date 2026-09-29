"""Out-of-process V4L2 capture/QR decoder; writes private atomic preview packets."""
import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import signal
import time

import cv2 as cv
import numpy as np
import openvr

from tools.vr_qr.geometry import marker_spec, solve_marker, StableAnchor


def camera_config(serial):
    root = Path.home() / '.local/share/Steam/config/lighthouse'
    config = json.loads((root / serial.lower() / 'config.json').read_text())['tracked_camera']['intrinsics']
    if config['distort']['type'] != 'DISTORT_FTHETA' or any(config['distort']['coeffs']):
        raise ValueError('Unsupported lens calibration; model not moved')
    intrinsic = np.array([[config['focal_x'], 0, config['center_x']], [0, config['focal_y'], config['center_y']], [0, 0, 1.]], np.float64)
    return config['width'], config['height'], intrinsic


def camera_device():
    # Do not silently open an arbitrary webcam. Original Vive enumerates as HTC.
    for name in sorted(glob.glob('/sys/class/video4linux/video*/name')):
        label = Path(name).read_text().lower()
        if 'htc' in label or 'vive' in label:
            return '/dev/' + Path(name).parent.name
    raise RuntimeError('Vive USB camera unavailable')


def packet(folder, seq, message, image=None, pose=None):
    h, w = image.shape[:2] if image is not None else (0, 0)
    matrix = np.eye(4) if pose is None else pose
    header = f'NADOCQR1\n{seq} {w} {h} {int(pose is not None)} {time.monotonic():.6f}\n'
    header += ' '.join(str(v) for v in matrix.ravel()) + '\n' + message.replace('\n', ' ')[:160] + '\n'
    temp = folder / 'frame.tmp'
    with temp.open('wb') as out:
        out.write(header.encode('ascii', errors='replace'))
        if image is not None:
            out.write(image.tobytes())
    os.replace(temp, folder / 'frame.bin')


def run(folder, duration=90):
    cv.setNumThreads(1)
    camera = None
    initialized = False
    try:
        system = openvr.init(openvr.VRApplication_Background); initialized = True
        serial = system.getStringTrackedDeviceProperty(0, openvr.Prop_SerialNumber_String)
        width, height, intrinsic = camera_config(serial)
        head_from_camera = np.eye(4)
        head_from_camera[:3] = np.array(system.getMatrix34TrackedDeviceProperty(0, openvr.Prop_CameraToHeadTransform_Matrix34).m)
        if not np.isfinite(head_from_camera).all() or abs(np.linalg.det(head_from_camera[:3, :3]) - 1) > .01:
            raise ValueError('Camera-to-head calibration unavailable')
        maps = cv.fisheye.initUndistortRectifyMap(intrinsic, np.zeros(4), np.eye(3), intrinsic, (width, height), cv.CV_16SC2)
        camera = cv.VideoCapture(camera_device(), cv.CAP_V4L2)
        camera.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*'YUYV'))
        camera.set(cv.CAP_PROP_FRAME_WIDTH, width); camera.set(cv.CAP_PROP_FRAME_HEIGHT, height)
        camera.set(cv.CAP_PROP_FPS, 30); camera.set(cv.CAP_PROP_BUFFERSIZE, 1)
        if not camera.isOpened():
            raise RuntimeError('Vive camera busy or unavailable')
        detector = cv.QRCodeDetector(); stable = StableAnchor(); deadline = time.monotonic() + duration
        seq = 0; next_frame = 0.0
        while time.monotonic() < deadline:
            ok, raw = camera.read()
            if not ok or raw.shape[:2] != (height, width):
                raise RuntimeError('Vive camera frame unavailable or wrong size')
            if time.monotonic() < next_frame:
                continue
            next_frame = time.monotonic() + .1
            image = cv.remap(raw, *maps, cv.INTER_LINEAR)
            gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
            edges = cv.Canny(gray, 55, 130)
            overlay = np.zeros((height, width, 4), np.uint8)
            overlay[:, :, :3] = [40, 220, 255]; overlay[:, :, 3] = edges
            data, corners, straight = detector.detectAndDecode(image)
            spec = marker_spec(data) if data else None
            found = None; head = None
            message = 'Camera warming up / needs more light' if gray.max() < 16 else 'Aim at QR; hold headset and target still'
            if spec and corners is not None and straight is not None:
                camera_from_marker = solve_marker(cv, corners, straight.shape[0], spec[0], intrinsic)
                tracked = system.getDeviceToAbsoluteTrackingPose(openvr.TrackingUniverseStanding, 0, 1)[0]
                if tracked.bPoseIsValid and tracked.bDeviceIsConnected and tracked.eTrackingResult == openvr.TrackingResult_Running_OK and camera_from_marker is not None:
                    head = np.eye(4); head[:3] = np.array(tracked.mDeviceToAbsoluteTracking.m)
                    found = head @ head_from_camera @ camera_from_marker @ spec[1]
                    cv.polylines(overlay, [corners.astype(np.int32).reshape(4, 2)], True, (30, 255, 60, 255), 3)
                    message = f'Hold still: {min(len(stable.samples) + 1, 12)}/12'
                else:
                    message = 'Tracking or QR pose uncertain; keep still'
            elif data:
                message = 'Use a NADOC meeting QR or NADOC cube face'
            accepted = stable.update(hashlib.sha256(data.encode()).hexdigest(), found, head)
            seq += 1
            packet(folder, seq, 'QR registered' if accepted is not None else message, overlay, accepted)
            if accepted is not None:
                return
        packet(folder, seq + 1, 'Timed out; retry with a larger, well-lit QR')
    except Exception as error:
        packet(folder, 0, str(error))
    finally:
        if camera is not None:
            camera.release()
        if initialized:
            openvr.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=90)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    run(args.output, args.seconds)
