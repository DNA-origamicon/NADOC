#!/usr/bin/env python3
"""VR-menu bridge to an already running, explicitly enabled compositor layer.

No imports from the caller's working directory, runtime launch, system settings,
pixel readback, or application-eye recorder. All monitoring runs in this helper,
outside NADOC's render thread. Saved status requires an acknowledged matching
request and complete accounting; actual scanout and pixel integrity need audit.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import time

if __package__:
    from .pose_journal_client import PoseJournalClient
    from .viewer_provenance import viewer_identity
    from .journal_validation import validate_saved_journal
else:  # Native launches this exact trusted script, independently of caller cwd.
    from pose_journal_client import PoseJournalClient
    from viewer_provenance import viewer_identity
    from journal_validation import validate_saved_journal


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".next")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(temporary, path)


def process_is_compositor(pid):
    try:
        process = Path(f"/proc/{int(pid)}")
        return process.stat().st_uid == os.getuid() and (process / "comm").read_text().strip() == "vrcompositor"
    except (OSError, ValueError):
        return False


def locate_layer(directory):
    matches = []
    for path in directory.glob("events-*.jsonl"):
        try:
            with path.open() as stream:
                first = json.loads(stream.readline(65536))
            if (first.get("event") == "layer_start" and process_is_compositor(first.get("pid"))
                    and time.time() - path.stat().st_mtime < 3):
                matches.append((path, first))
        except (OSError, ValueError, TypeError):
            continue
    if len(matches) != 1:
        raise RuntimeError("No unique live compositor capture layer")
    path, first = matches[0]
    if not first.get("pixel_mode") or first.get("test_surfaces"):
        raise RuntimeError("Capture layer is not configured for final-output pixels")
    return path, first


def available_rows(stream):
    """Keep incomplete appended lines for the next poll; never parse half a row."""
    while True:
        position = stream.tell()
        line = stream.readline(65536)
        if not line:
            return
        if not line.endswith("\n"):
            stream.seek(position)
            if len(line) >= 65536:
                raise RuntimeError("Compositor event exceeds the bridge line limit")
            return
        yield json.loads(line)


def completion_accounting(rows, completion):
    presents = [r for r in rows if r.get("event") == "present" and r.get("armed")]
    saved = [r for r in rows if r.get("event") == "frame_saved"]
    key = lambda r: (r["swapchain"], r["present"])
    pkeys, skeys = [key(r) for r in presents], [key(r) for r in saved]
    active = int(completion.get("active_presents", -1))
    counts = active > 0 and active == completion.get("copied_frames") == completion.get("saved") == len(presents) == len(saved)
    valid = bool(counts and completion.get("pixel_drops") == 0 and completion.get("event_drops") == 0
                 and len(set(pkeys)) == len(pkeys) and len(set(skeys)) == len(skeys)
                 and set(pkeys) == set(skeys)
                 and all(r.get("copied") and r.get("result") in (0, 1000001003)
                         and r.get("image_result", 0) in (0, 1000001003) for r in presents))
    return {"all_requested_presents_saved": valid, "present_count": len(presents),
            "saved_count": len(saved), "pixel_drops": int(completion.get("pixel_drops", 0)),
            "missing_present_count": len(set(pkeys) - set(skeys)),
            "event_drops": int(completion.get("event_drops", 0)),
            "pixel_integrity_verified": False, "refresh_mapping_verified": False,
            "optical_output_verified": False}


def buffered_log_window(header, *, started, preparing, now_ns, ack_deadline_ns):
    """A declared metadata buffer permits silence only within bounded windows."""
    if header.get("deferred_metadata_during_capture") is not True:
        return False
    if started:
        return started["start_ns"] <= now_ns <= started["end_ns"] + 3_000_000_000
    return preparing and now_ns <= ack_deadline_ns


def record(directory, emit, *, context=None, viewer_pid=0, delay=2.0, seconds=5.0,
           ack_timeout=15.0, drain_timeout=60.0):
    if not (math.isfinite(seconds) and 0 < seconds <= 10 and math.isfinite(delay) and 0 <= delay <= 30):
        raise ValueError("Invalid capture interval")
    if not (math.isfinite(ack_timeout) and 0 < ack_timeout <= 60
            and math.isfinite(drain_timeout) and 0 < drain_timeout <= 120):
        raise ValueError("Invalid capture acknowledgement or saving timeout")
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir() or directory.stat().st_uid != os.getuid():
        raise ValueError("Capture directory must belong to this user")
    token = time.monotonic_ns()
    ready_label = f"Record final output {seconds:g}s"
    report_path = directory / f"viewer-request-{token}.json"
    report = {"schema": 1, "request": token, "viewer_pid": viewer_pid, "context": context or {},
              "duration_seconds": seconds, "countdown_seconds": delay,
              "ack_timeout_seconds": ack_timeout, "drain_timeout_seconds": drain_timeout,
              "capture_boundary": "final_swapchain_before_queue_present",
              "application_eye_recording": False, "optical_output_verified": False,
              "headset_identity_verified": False,
              "pixel_file_persistence_verified": False,
              "refresh_mapping_verified": False, "pixel_integrity_verified": False,
              "requested_wall_time_ns": time.time_ns(), "status": "checking_layer"}
    journal = None
    diagnostics_required = (context or {}).get("diagnostics_required") is True
    report["diagnostics_required"] = diagnostics_required
    report["pose_journal"] = {"enabled": False, "status": "not_requested"}

    def journal_step(verb, *arguments):
        previous_error = report["pose_journal"].get("status") == "error"
        if journal is None or (previous_error and verb != "cancel"):
            return
        try:
            status = getattr(journal, verb)(*arguments)
            if previous_error:
                report["pose_journal"]["cancel_result"] = status
            else:
                report["pose_journal"].update(status=status.get("phase", verb), native=status)
        except Exception as error:
            if previous_error:
                report["pose_journal"]["cancel_error"] = str(error)
            else:
                report["pose_journal"].update(status="error", failed_step=verb, error=str(error))

    def update(phase, label, status, saved=0, drops=0):
        report.update(status=phase, label=label, message=status, saved_frames=saved, dropped_frames=drops)
        atomic_json(report_path, report)
        emit({"phase": phase, "label": label, "status": status, "directory": str(directory),
              "request": token, "saved": saved, "drops": drops})

    try:
        try:
            report["viewer_identity"] = viewer_identity(viewer_pid)
        except (OSError, ValueError, RuntimeError) as error:
            report["viewer_identity"] = {"verified": False, "error": str(error)}
            if diagnostics_required:
                raise RuntimeError("Viewer build identity unavailable; recording not started") from error
        if diagnostics_required:
            if (context or {}).get("pose_journal", {}).get("enabled") is not True:
                raise RuntimeError("Pose recording unavailable; recording not started")
            if (context or {}).get("submitted_frame_marker", {}).get("enabled") is not True:
                raise RuntimeError("Frame identity unavailable; recording not started")
        with (directory / ".viewer-record.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another VR-menu recording is active") from error
            path, header = locate_layer(directory)
            report["layer_pid"] = header["pid"]
            report["events_file"] = path.name
            report["deferred_metadata_during_capture"] = header.get("deferred_metadata_during_capture") is True
            report["deferred_pixel_writes"] = header.get("deferred_pixel_writes") is True
            report["durable_pixel_files_requested"] = header.get("durable_pixel_files") is True
            with path.open() as stream:
                surfaces, prepared, pending = {}, set(), set()
                for row in available_rows(stream):
                    event = row.get("event")
                    if event == "swapchain":
                        surfaces[row["swapchain"]] = row
                    elif event == "capture_prepared":
                        prepared.add(row["swapchain"])
                    elif event == "capture_start":
                        pending.add(row["request"])
                    elif event in ("capture_complete", "capture_cancelled"):
                        pending.discard(row["request"])
                direct = {key for key, value in surfaces.items() if value.get("direct_display")
                          and not value.get("test_surface") and value.get("transfer_src")}
                if not direct.intersection(prepared):
                    raise RuntimeError("No prepared direct-display surface")
                if pending:
                    raise RuntimeError("Compositor is recording or saving another request")
                report["surfaces"] = [surfaces[key] for key in sorted(direct)]
                countdown_end = time.monotonic() + delay
                previous = None
                while time.monotonic() < countdown_end:
                    remaining = math.ceil(countdown_end - time.monotonic())
                    if previous != remaining:
                        update("countdown", f"Final output in {remaining}s", "Both eyes - application recorder off")
                        previous = remaining
                    time.sleep(min(.05, max(0, countdown_end-time.monotonic())))
                # Recheck immediately before sending; countdown is not acceptance.
                checked_path, checked_header = locate_layer(directory)
                if checked_path != path or checked_header["pid"] != header["pid"]:
                    raise RuntimeError("Compositor changed during countdown")
                journal_context = (context or {}).get("pose_journal", {})
                if journal_context.get("enabled") is True:
                    report["pose_journal"] = {"enabled": True, "status": "requested"}
                    try:
                        journal = PoseJournalClient(journal_context, viewer_pid)
                        journal_step("arm", token)
                    except Exception as error:
                        report["pose_journal"].update(status="error", failed_step="connect", error=str(error))
                if diagnostics_required:
                    if report["pose_journal"].get("status") != "armed":
                        raise RuntimeError("Pose recording could not arm; recording not started")
                    observation = journal.exchange("observe")
                    marker = observation.get("frame_identity", {})
                    pose = observation.get("pose_journal", {})
                    if marker.get("enabled") is not True or pose.get("clock_mapping_available") is not True:
                        raise RuntimeError("Frame identity or pose clock unavailable; recording not started")
                    report["diagnostic_preflight"] = {"frame_identity": marker, "pose_journal": pose,
                                                       "session": observation.get("session")}
                temporary = directory / f"control-{token}.tmp"
                temporary.write_text(f"{token} {seconds:.9f}\n")
                os.replace(temporary, directory / "control.txt")
                report["control_sent_monotonic_ns"] = time.monotonic_ns()
                update("awaiting_ack", "Waiting for compositor...", "Final capture requested; not yet recording")
                started, ended, complete, preparing = None, False, None, False
                own_rows, timing_failed = [], False
                deadline = time.monotonic() + ack_timeout
                ack_deadline_ns = round(deadline * 1e9)
                last_tick = None
                while time.monotonic() < deadline:
                    for row in available_rows(stream):
                        if row.get("request") == token:
                            own_rows.append(row)
                            event = row.get("event", "")
                            if event.startswith("capture_rejected"):
                                report["rejection_event"] = row
                                if event == "capture_rejected_memory":
                                    memory = {key: row[key] for key in
                                              ("mem_available_bytes", "additional_bytes", "reserve_bytes")
                                              if type(row.get(key)) is int and row[key] >= 0}
                                    if "reserve_bytes" in memory:
                                        memory["required_available_bytes"] = memory["reserve_bytes"] + memory.get("additional_bytes", 0)
                                    report["memory_rejection"] = memory
                                    raise RuntimeError("Low memory - close unused apps and retry")
                                raise RuntimeError("Compositor rejected recording: " + event.removeprefix("capture_rejected_"))
                            if event == "capture_preparing":
                                preparing = True
                                report["acknowledged_preparation"] = row
                                update("awaiting_ack", "Preparing final output...",
                                       "Preparing capture memory; not yet recording")
                            elif event == "capture_start":
                                if started:
                                    raise RuntimeError("Capture acknowledged its start more than once")
                                started = row
                                journal_step("window", row)
                                deadline = time.monotonic() + seconds + drain_timeout
                                report["acknowledged_start"] = row
                                update("recording", f"Final output {math.ceil(seconds)}s", "Both eyes - actual display timing unverified")
                            elif event == "capture_interval_end":
                                ended = True
                                report["acknowledged_interval_end"] = row
                                update("saving", "Saving final output...", "Waiting for capture accounting")
                            elif event == "capture_complete":
                                complete = row
                            elif event == "capture_cancelled":
                                raise RuntimeError("Compositor recording was cancelled")
                            elif event == "capture_persistence_failed":
                                report["persistence_failure"] = row
                                raise RuntimeError("Capture file persistence failed: " + str(row.get("reason", "directory or file sync")))
                        elif started and row.get("event") == "wait_for_present" and row.get("result", 0) != 0:
                            if started["start_ns"] <= row.get("host_ns", 0) <= started["end_ns"]:
                                timing_failed = True
                    if not process_is_compositor(header["pid"]):
                        raise RuntimeError("Compositor exited during recording")
                    if complete is not None:
                        if not started or not ended:
                            raise RuntimeError("Capture completion lacks a matching start or end")
                        accounting = completion_accounting(own_rows, complete)
                        report.update(accounting)
                        report["completion"] = complete
                        report["presentation_timing_failed"] = timing_failed
                        if header.get("durable_pixel_files") is True:
                            saved_rows = [r for r in own_rows if r.get("event") == "frame_saved"]
                            durable = (complete.get("persistence_ok") is True
                                       and complete.get("directory_synced") is True
                                       and bool(saved_rows)
                                       and all(r.get("file_fdatasynced") is True and r.get("file_closed") is True
                                               for r in saved_rows))
                            if not durable:
                                raise RuntimeError("Capture file persistence was not confirmed")
                            report["pixel_file_persistence_verified"] = True
                        requested_surfaces = {r["swapchain"] for r in own_rows if r.get("event") == "present" and r.get("armed")}
                        if not requested_surfaces or not requested_surfaces.issubset(direct):
                            raise RuntimeError("Capture did not match a prepared direct-display surface")
                        journal_step("finish", started)
                        if report["pose_journal"].get("status") == "error":
                            journal_step("cancel")
                        native_journal = report["pose_journal"].get("native", {})
                        diagnostics_complete = (report["pose_journal"].get("status") == "saved"
                            and native_journal.get("frame_count", 0) > 0
                            and native_journal.get("overflow_frames") == 0
                            and native_journal.get("mapping_failures") == 0
                            and native_journal.get("clock_mapping_available") is True)
                        if diagnostics_required:
                            proof = validate_saved_journal(
                                journal_context, native_journal, request=token, viewer_pid=viewer_pid,
                                started=started, marker=(context or {}).get("submitted_frame_marker", {}),
                            )
                            report["pose_journal"]["validation"] = proof
                            diagnostics_complete = diagnostics_complete and proof["valid"]
                        report["diagnostics_complete"] = diagnostics_complete
                        if accounting["all_requested_presents_saved"] and diagnostics_required and not diagnostics_complete:
                            update("partial", ready_label, "Frames saved; pose diagnostics incomplete", accounting["saved_count"], 0)
                        elif accounting["all_requested_presents_saved"]:
                            journal_note = "; pose log failed" if report["pose_journal"].get("status") == "error" else ""
                            update("saved", ready_label, "Saved frames; timing " + ("failed" if timing_failed else "unverified") + journal_note, accounting["saved_count"], 0)
                        else:
                            missing = max(accounting["missing_present_count"], accounting["pixel_drops"])
                            message = f"Partial capture - {missing} frames missing" if missing else "Partial capture - accounting or present failed"
                            update("partial", ready_label, message, accounting["saved_count"], missing)
                        return report
                    now_ns = time.monotonic_ns()
                    quiet_expected = buffered_log_window(header, started=started, preparing=preparing,
                                                         now_ns=now_ns, ack_deadline_ns=ack_deadline_ns)
                    if not quiet_expected and time.time()-path.stat().st_mtime > 3:
                        raise RuntimeError("Compositor capture log stopped updating")
                    if started and not ended:
                        remaining = max(0, math.ceil((started["end_ns"]-now_ns)/1e9))
                        if remaining != last_tick:
                            if remaining:
                                update("recording", f"Final output {remaining}s", "Both eyes - actual display timing unverified")
                            else:
                                update("saving", "Saving final output...",
                                       "Capture interval elapsed; waiting for end acknowledgement")
                            last_tick = remaining
                    time.sleep(.05)
                raise RuntimeError("Capture acknowledgement timed out" if not started else "Capture did not finish saving; partial files retained")
    except Exception as error:
        journal_step("cancel")
        report["error"] = str(error)
        update("error", ready_label, str(error))
        return report


def print_status(state):
    # Quoted ASCII fields match std::quoted in the native helper reader.
    fields = [json.dumps(state[key], ensure_ascii=False) for key in ("phase", "label", "status", "directory")]
    print("NADOC_CAPTURE_UI 1 " + " ".join(fields) + f" {state['request']} {state['saved']} {state['drops']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--viewer-pid", type=int, required=True)
    parser.add_argument("--context", default="{}")
    parser.add_argument("--seconds", type=int, choices=(2, 5), default=5)
    args = parser.parse_args()
    try:
        context = json.loads(args.context)
        if not isinstance(context, dict):
            raise ValueError("Context must be an object")
        report = record(args.directory, print_status, context=context, viewer_pid=args.viewer_pid, seconds=args.seconds)
        return 0 if report["status"] in ("saved", "partial") else 1
    except Exception as error:
        print_status({"phase": "error", "label": f"Record final output {args.seconds}s", "status": str(error),
                      "directory": str(args.directory), "request": 0, "saved": 0, "drops": 0})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
