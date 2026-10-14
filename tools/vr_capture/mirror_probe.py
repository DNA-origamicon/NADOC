"""EXPERIMENTAL: SteamVR mirror API probe; disabled unless explicitly opted in.

Two live probes on SteamVR 2.17.10/NVIDIA were followed by compositor watchdog
failures. This code is retained for diagnosis, not approved for ordinary capture.

Run with:
  uv run --no-project --with openvr --with glfw --with PyOpenGL --with pillow \
    python tools/vr_capture/mirror_probe.py --allow-unstable-mirror-api --output /path/to/new-directory

This is a one-shot diagnostic, not a display-cadence recorder. Readback can
stall the caller/GPU and its elapsed cost is included in the report. It never
submits scene images, calls WaitGetPoses, opens a visible window, changes
SteamVR settings, or restarts the runtime. A mirror success does not establish
that its pixels include asynchronous reprojection or match every scanout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import hashlib


def active_compositors() -> list[int]:
    result = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "comm").read_text().strip() == "vrcompositor":
                result.append(int(proc.name))
        except (OSError, UnicodeError):
            pass
    return result


def error_details(error: Exception) -> dict:
    result = {"type": type(error).__name__, "message": str(error)}
    code = getattr(error, "error_code", None)
    if code is not None:
        result["error_code"] = int(code)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-unstable-mirror-api", action="store_true", help="Explicitly run a probe associated with compositor crashes; diagnosis only")
    parser.add_argument("--warmup-ms", type=int, default=150, help="Allow newly registered mirrors to receive images; 0..2000")
    args = parser.parse_args()
    if not args.allow_unstable_mirror_api:
        parser.error("Live mirror probing is disabled: prior probes were followed by compositor crashes. Use --allow-unstable-mirror-api only in an isolated diagnostic session.")
    if not 0 <= args.warmup_ms <= 2000:
        parser.error("--warmup-ms must be between 0 and 2000")
    # Require a new directory so a failed probe cannot overwrite prior evidence.
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "runtime_stability_verified": False,
        "prior_compositor_watchdog_failures_after_probe": True,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "source_boundary": "openvr_compositor_undistorted_mirror",
        "per_scanout_identity_available": False,
        "stereo_pair_synchronized": False,
        "warmup_ms": args.warmup_ms,
        "post_reprojection_verified": False,
        "optical_output_verified": False,
        "application_type": "VRApplication_Background",
        "scene_submitted": False,
        "wait_get_poses_called": False,
        "visible_window_created": False,
        "runtime_restarted": False,
        "settings_modified": False,
        "compositor_pids": active_compositors(),
        "eyes": [],
    }
    window = None
    glfw_started = False
    vr_started = False
    success = False
    try:
        if not report["compositor_pids"]:
            raise RuntimeError("No running SteamVR compositor; refusing to start the runtime")
        import glfw
        import openvr
        from OpenGL import GL
        from PIL import Image

        glfw_errors = []
        glfw.set_error_callback(lambda code, description: glfw_errors.append({
            "code": code,
            "description": description.decode("utf-8", "replace") if isinstance(description, bytes) else str(description),
        }))
        report["glfw_errors"] = glfw_errors
        if not glfw.init():
            raise RuntimeError("glfw.init failed")
        glfw_started = True
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        window = glfw.create_window(16, 16, "NADOC invisible mirror API probe", None, None)
        if not window:
            raise RuntimeError("Could not create hidden OpenGL context")
        glfw.make_context_current(window)
        report["gl"] = {name: GL.glGetString(value).decode("utf-8", "replace") for name, value in (
            ("vendor", GL.GL_VENDOR), ("renderer", GL.GL_RENDERER), ("version", GL.GL_VERSION))}
        system = openvr.init(openvr.VRApplication_Background)
        vr_started = True
        for field, prop in (("headset_model", openvr.Prop_ModelNumber_String),
                            ("runtime_tracking_system", openvr.Prop_TrackingSystemName_String)):
            try:
                report[field] = system.getStringTrackedDeviceProperty(openvr.k_unTrackedDeviceIndex_Hmd, prop)
            except Exception as error:
                report[field + "_error"] = error_details(error)
        compositor = openvr.VRCompositor()
        mirrors = []
        try:
            # Keep BOTH resources registered throughout warmup/readback. A newly
            # created mirror can otherwise read as black before its first update.
            for eye_name, eye_enum in (("left", openvr.Eye_Left), ("right", openvr.Eye_Right)):
                result = {"eye": eye_name, "available": False}
                texture = handle = None
                begin = time.monotonic_ns()
                try:
                    texture, handle = compositor.getMirrorTextureGL(eye_enum)
                    texture = getattr(texture, "value", texture)
                    result["texture_id"] = int(texture)
                    if not texture or not handle:
                        raise RuntimeError("Mirror API returned an empty texture or shared handle")
                    result["available"] = True
                except Exception as error:
                    result["error"] = error_details(error)
                result["api_elapsed_ms"] = (time.monotonic_ns() - begin) / 1e6
                report["eyes"].append(result)
                mirrors.append((result, texture, handle))
            time.sleep(args.warmup_ms / 1000)
            for result, texture, handle in mirrors:
                if not result["available"]:
                    continue
                locked = False
                old_binding = int(GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D))
                read_start = time.monotonic_ns()
                result["read_start_monotonic_ns"] = read_start
                try:
                    try:
                        compositor.lockGLSharedTextureForAccess(handle)
                        locked = True
                        GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
                        width = int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_WIDTH))
                        height = int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_HEIGHT))
                        result.update(width=width, height=height,
                                      internal_format=int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_INTERNAL_FORMAT)))
                        if width <= 0 or height <= 0 or width * height > 128 * 1024 * 1024:
                            raise RuntimeError("Mirror dimensions are empty or exceed the probe limit")
                        pixels = GL.glGetTexImage(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
                    finally:
                        GL.glBindTexture(GL.GL_TEXTURE_2D, old_binding)
                        if locked:
                            compositor.unlockGLSharedTextureForAccess(handle)
                    result["locked_readback_elapsed_ms"] = (time.monotonic_ns() - read_start) / 1e6
                    filename = result["eye"] + ".png"
                    captured = Image.frombytes("RGBA", (width, height), bytes(pixels)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    extrema = captured.convert("RGB").getextrema()
                    result["rgb_channel_extrema"] = extrema
                    result["all_black"] = all(maximum == 0 for _, maximum in extrema)
                    captured.save(args.output / filename)
                    result.update(image=filename, image_orientation="top_down", conversion="RGBA8 readback; vertical row-order reversal only",
                                  pixel_sha256=hashlib.sha256(bytes(pixels)).hexdigest())
                except Exception as error:
                    result["readback_error"] = error_details(error)
                result["readback_and_save_elapsed_ms"] = (time.monotonic_ns() - read_start) / 1e6
        finally:
            for result, texture, handle in mirrors:
                if texture and handle:
                    try:
                        result["shared_texture_released"] = bool(compositor.releaseSharedGLTexture(texture, handle))
                    except Exception as error:
                        result["release_error"] = error_details(error)
        success = len(report["eyes"]) == 2 and all(eye.get("image") and not eye.get("all_black") for eye in report["eyes"])
        report["both_eyes_nonblack"] = success
        report["status"] = "both_mirrors_nonblack" if success else "incomplete_mirror_pixels"
    except Exception as error:
        report["status"] = "probe_failed"
        report["error"] = error_details(error)
    finally:
        if vr_started:
            openvr.shutdown()
        if window:
            glfw.destroy_window(window)
        if glfw_started:
            glfw.terminate()
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        with (args.output / "report.json").open("x") as output:
            json.dump(report, output, indent=2)
            output.write("\n")
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json"), "eyes": report["eyes"]}, indent=2))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
