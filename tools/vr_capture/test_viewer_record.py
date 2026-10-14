"""No headset/runtime needed: exercise acknowledgement and partial-file evidence."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools.vr_capture import viewer_record as bridge


class ViewerRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nadoc-menu-record-test-")
        self.directory = Path(self.temporary.name)
        self.events = self.directory / "events-1234.jsonl"
        self.append(event="layer_start", pid=1234, pixel_mode=1, test_surfaces=0)
        self.append(event="swapchain", swapchain=1, direct_display=1, test_surface=0, transfer_src=1)
        self.append(event="capture_prepared", swapchain=1)

    def tearDown(self):
        self.temporary.cleanup()

    def append(self, **row):
        with self.events.open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    def set_header(self, **fields):
        rows = self.events.read_text().splitlines()
        header = json.loads(rows[0])
        header.update(fields)
        rows[0] = json.dumps(header)
        self.events.write_text("\n".join(rows)+"\n")

    def run_bridge(self, response=None, *, process_check=None, wall_clock=None, **options):
        (self.directory / "control.txt").unlink(missing_ok=True)
        errors = []
        def compositor():
            try:
                until = time.monotonic() + 2
                while time.monotonic() < until:
                    try:
                        token = int((self.directory / "control.txt").read_text().split()[0])
                        response(token)
                        return
                    except FileNotFoundError:
                        time.sleep(.005)
                raise AssertionError("No request reached the simulated layer")
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=compositor) if response else None
        if worker:
            worker.start()
        states = []
        clock = wall_clock or time.time
        parameters = dict(delay=0, seconds=.05, ack_timeout=.2, drain_timeout=.2)
        parameters.update(options)
        with patch.object(bridge, "process_is_compositor", side_effect=process_check or (lambda pid: True)), \
             patch.object(bridge.time, "time", side_effect=clock):
            result = bridge.record(self.directory, states.append, **parameters)
        if worker:
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
        self.assertFalse(errors, errors)
        return result, states

    def capture(self, token, *, drop=False, duplicate=False, result=0, start=True, end=True,
                durable=False, persistence_ok=True, directory_synced=True,
                file_fdatasynced=True, file_closed=True, seconds=.05):
        now = time.monotonic_ns()
        # An unrelated token must not cause premature success.
        self.append(event="capture_complete", request=token-1, active_presents=2, copied_frames=2,
                    saved=2, pixel_drops=0, event_drops=0)
        if start:
            self.append(event="capture_start", request=token, start_ns=now, end_ns=now+round(seconds*1e9))
        for number in range(2):
            self.append(event="present", request=token, armed=1, swapchain=1, present=number,
                        copied=not (drop and number==1), result=result, image_result=result)
            if not (drop and number==1):
                self.append(event="frame_saved", request=token, swapchain=1,
                            present=0 if duplicate else number, file=f"{number}.bgra.lz4",
                            **({"file_fdatasynced":file_fdatasynced, "file_closed":file_closed} if durable else {}))
        if end:
            self.append(event="capture_interval_end", request=token)
        self.append(event="capture_complete", request=token, active_presents=2,
                    copied_frames=1 if drop else 2, saved=1 if drop else 2,
                    pixel_drops=int(drop), event_drops=0,
                    **({"persistence_ok":persistence_ok, "directory_synced":directory_synced} if durable else {}))

    def test_selected_duration_reaches_control_ack_context_and_ready_label(self):
        for seconds in (2,5):
            with self.subTest(seconds=seconds):
                def response(token):
                    self.assertEqual(float((self.directory / "control.txt").read_text().split()[1]), seconds)
                    self.capture(token, seconds=seconds)
                report, states = self.run_bridge(response, seconds=seconds,
                    context={"duration_seconds":seconds,"representation":"stick"})
                self.assertEqual(report["duration_seconds"],seconds)
                self.assertEqual(report["context"]["duration_seconds"],seconds)
                start=report["acknowledged_start"]
                self.assertEqual(start["end_ns"]-start["start_ns"],seconds*1_000_000_000)
                self.assertEqual(report["status"],"saved")
                self.assertEqual(states[-1]["label"],f"Record final output {seconds}s")
                self.assertTrue(any(state["label"]==f"Final output {seconds}s" for state in states))

    def test_duration_label_survives_rejection(self):
        report, states=self.run_bridge(lambda token:self.append(event="capture_rejected_memory",request=token),seconds=2)
        self.assertEqual(report["status"],"error")
        self.assertEqual(states[-1]["label"],"Record final output 2s")

    def test_cli_duration_is_explicit_and_legacy_default_remains_five(self):
        for arguments, seconds in (([],5),(["--seconds","2"],2),(["--seconds","5"],5)):
            with patch("sys.argv",["viewer_record.py","--directory",str(self.directory),"--viewer-pid","99",*arguments]), \
                 patch.object(bridge,"record",return_value={"status":"saved"}) as record:
                self.assertEqual(bridge.main(),0)
                self.assertEqual(record.call_args.kwargs["seconds"],seconds)

    def test_menu_catalog_duration_row_only_for_final_output(self):
        from tools.vr_workflows.menu_tour import context_catalog
        source={"tabs":[{"side":"right","key":"tools","rows":[
            {"id":"vr-record"},{"id":"vr-record-duration"},{"id":"vr-record-status"}]}]}
        for capture, expected in ((False,["vr-record","vr-record-status"]),
                                  (True,["vr-record","vr-record-duration","vr-record-status"])):
            state={"controls":[],"recording":{"source":"final_compositor_swapchain" if capture else "application_swapchain"}}
            filtered,_=context_catalog(source,state)
            self.assertEqual([r["id"] for r in filtered["tabs"][0]["rows"]],expected)
        self.assertEqual(len(source["tabs"][0]["rows"]),3)

    def test_acknowledged_complete_accounting_keeps_optical_limits(self):
        report, states = self.run_bridge(self.capture)
        self.assertEqual(report["status"], "saved")
        self.assertTrue(report["all_requested_presents_saved"])
        self.assertEqual(report["saved_count"], 2)
        self.assertFalse(report["optical_output_verified"])
        self.assertFalse(report["refresh_mapping_verified"])
        self.assertFalse(report["pixel_integrity_verified"])
        self.assertFalse(report["application_eye_recording"])
        self.assertIn("awaiting_ack", [s["phase"] for s in states])
        self.assertIn("recording", [s["phase"] for s in states])

    def test_missing_duplicate_or_failed_present_is_partial(self):
        for options in ({"drop": True}, {"duplicate": True}, {"result": -4}):
            with self.subTest(options=options):
                report, _ = self.run_bridge(lambda token: self.capture(token, **options))
                self.assertEqual(report["status"], "partial")
                self.assertFalse(report["all_requested_presents_saved"])

    def test_no_acknowledgement_cannot_be_saved(self):
        report, states = self.run_bridge()
        self.assertEqual(report["status"], "error")
        self.assertIn("acknowledgement timed out", report["error"])
        self.assertNotIn("recording", [s["phase"] for s in states])

    def test_rejection_reports_error(self):
        report, _ = self.run_bridge(lambda token: self.append(event="capture_rejected_busy", request=token))
        self.assertEqual(report["status"], "error")
        self.assertIn("rejected", report["error"])
        self.assertEqual(report["rejection_event"], {"event":"capture_rejected_busy", "request":report["request"]})
        self.assertNotIn("memory_rejection",report)

    def test_memory_rejection_retains_exact_allocation_and_reserve_evidence(self):
        fields = {"mem_available_bytes":3_029_000_000, "additional_bytes":1_169_516_544,
                  "reserve_bytes":2_147_483_648, "host_ns":90_000_000_123}
        report, states = self.run_bridge(lambda token:self.append(event="capture_rejected_memory",request=token,**fields))
        self.assertEqual(report["status"],"error")
        self.assertEqual(report["error"],"Low memory - close unused apps and retry")
        self.assertEqual(report["rejection_event"],dict(fields,event="capture_rejected_memory",request=report["request"]))
        self.assertEqual(report["memory_rejection"],{
            "mem_available_bytes":fields["mem_available_bytes"],
            "additional_bytes":fields["additional_bytes"],
            "reserve_bytes":fields["reserve_bytes"],
            "required_available_bytes":3_317_000_192})
        self.assertEqual(states[-1]["status"],report["error"])
        self.assertNotIn("recording",[state["phase"] for state in states])

    def test_memory_rejection_after_prefault_uses_only_reported_reserve(self):
        fields={"mem_available_bytes":1_900_000_000,"reserve_bytes":2_147_483_648}
        report, _ = self.run_bridge(lambda token:self.append(event="capture_rejected_memory",request=token,**fields))
        self.assertEqual(report["status"],"error")
        self.assertEqual(report["memory_rejection"],dict(fields,required_available_bytes=fields["reserve_bytes"]))
        self.assertNotIn("additional_bytes",report["memory_rejection"])

    def test_memory_rejection_does_not_invent_missing_memory_values(self):
        report, _ = self.run_bridge(lambda token:self.append(event="capture_rejected_memory",request=token))
        self.assertEqual(report["status"],"error")
        self.assertEqual(report["memory_rejection"],{})

    def test_existing_capture_is_not_overwritten(self):
        self.append(event="capture_start", request=17, start_ns=1, end_ns=99999999999999999)
        report, _ = self.run_bridge()
        self.assertEqual(report["status"], "error")
        self.assertFalse((self.directory / "control.txt").exists())

    def test_metadata_mode_cannot_claim_a_pixel_recording(self):
        self.set_header(pixel_mode=0)
        report, _ = self.run_bridge()
        self.assertEqual(report["status"], "error")
        self.assertFalse((self.directory / "control.txt").exists())

    def test_buffered_silence_requires_explicit_capability_and_bounded_window(self):
        started = {"start_ns":10_000_000_000, "end_ns":15_000_000_000}
        arguments = dict(started=started, preparing=False, now_ns=17_999_999_999,
                         ack_deadline_ns=12_000_000_000)
        header = {"deferred_metadata_during_capture":True}
        self.assertTrue(bridge.buffered_log_window(header, **arguments))
        self.assertFalse(bridge.buffered_log_window(header, **dict(arguments, now_ns=18_000_000_001)))
        for declared in (None, False, 1, "true"):
            self.assertFalse(bridge.buffered_log_window({"deferred_metadata_during_capture":declared}, **arguments))
        preparing = dict(started=None, preparing=True, now_ns=11_000_000_000,
                         ack_deadline_ns=12_000_000_000)
        self.assertTrue(bridge.buffered_log_window(header, **preparing))
        self.assertFalse(bridge.buffered_log_window(header, **dict(preparing, now_ns=12_000_000_001)))
        self.assertFalse(bridge.buffered_log_window(header, **dict(preparing, preparing=False)))

    def test_deferred_preparation_and_capture_tolerate_silence_then_save(self):
        self.set_header(deferred_metadata_during_capture=True, deferred_pixel_writes=True)
        real_time, offset = time.time, [0]
        def response(token):
            self.append(event="capture_preparing", request=token)
            offset[0] = 4  # Make log freshness fail unless buffering is recognized.
            time.sleep(.1)
            now = time.monotonic_ns()
            self.append(event="capture_start", request=token, start_ns=now, end_ns=now+50_000_000)
            time.sleep(.15)  # End row intentionally arrives after the interval.
            self.capture(token, start=False)
        report, states = self.run_bridge(response, wall_clock=lambda:real_time()+offset[0], drain_timeout=.4)
        self.assertEqual(report["status"], "saved")
        self.assertTrue(report["deferred_metadata_during_capture"])
        self.assertIn("acknowledged_preparation", report)
        self.assertIn("acknowledged_interval_end", report)
        self.assertTrue(any(s["label"] == "Preparing final output..." for s in states))
        self.assertTrue(any(s["phase"] == "saving" and "waiting for end acknowledgement" in s["status"] for s in states))
        self.assertFalse(any(s["label"] == "Final output 0s" for s in states))

    def test_undeclared_layer_still_fails_when_log_is_stale(self):
        real_time, offset = time.time, [0]
        def response(token):
            now = time.monotonic_ns()
            self.append(event="capture_start", request=token, start_ns=now, end_ns=now+50_000_000)
            offset[0] = 4
        report, _ = self.run_bridge(response, wall_clock=lambda:real_time()+offset[0])
        self.assertEqual(report["status"], "error")
        self.assertIn("log stopped updating", report["error"])

    def test_preparation_timeout_remains_bounded_while_log_is_buffered(self):
        self.set_header(deferred_metadata_during_capture=True)
        real_time, offset = time.time, [0]
        def response(token):
            self.append(event="capture_preparing", request=token)
            offset[0] = 4
        report, states = self.run_bridge(response, wall_clock=lambda:real_time()+offset[0])
        self.assertEqual(report["status"], "error")
        self.assertIn("acknowledgement timed out", report["error"])
        self.assertNotIn("recording", [s["phase"] for s in states])

    def test_buffered_capture_still_requires_end_acknowledgement(self):
        self.set_header(deferred_metadata_during_capture=True)
        report, _ = self.run_bridge(lambda token:self.capture(token, end=False))
        self.assertEqual(report["status"], "error")
        self.assertIn("matching start or end", report["error"])

    def test_buffered_capture_drain_timeout_does_not_claim_saved(self):
        self.set_header(deferred_metadata_during_capture=True)
        def response(token):
            now = time.monotonic_ns()
            self.append(event="capture_start", request=token, start_ns=now, end_ns=now+50_000_000)
        report, states = self.run_bridge(response)
        self.assertEqual(report["status"], "error")
        self.assertIn("did not finish saving", report["error"])
        self.assertIn("saving", [s["phase"] for s in states])
        self.assertNotIn("saved", [s["phase"] for s in states])

    def test_compositor_exit_fails_even_inside_buffered_window(self):
        self.set_header(deferred_metadata_during_capture=True)
        alive = [True]
        def response(token):
            now = time.monotonic_ns()
            self.append(event="capture_start", request=token, start_ns=now, end_ns=now+50_000_000)
            alive[0] = False
        report, _ = self.run_bridge(response, process_check=lambda pid:alive[0])
        self.assertEqual(report["status"], "error")
        self.assertIn("exited", report["error"])

    def test_nonfinite_timeouts_are_rejected(self):
        for parameter in ("ack_timeout", "drain_timeout"):
            with self.subTest(parameter=parameter), self.assertRaises(ValueError):
                bridge.record(self.directory, lambda state:None, **{parameter:float("inf")})

    def test_compositor_exit_alongside_completion_is_reported(self):
        alive = [True]
        def response(token):
            self.capture(token)
            alive[0] = False
        report, states = self.run_bridge(response, process_check=lambda pid:alive[0])
        self.assertEqual(report["status"], "error")
        self.assertIn("exited", report["error"])
        self.assertNotIn("saved", [s["phase"] for s in states])

    def test_declared_durable_capture_requires_file_and_directory_evidence(self):
        self.set_header(durable_pixel_files=True)
        report, _ = self.run_bridge(lambda token:self.capture(token,durable=True))
        self.assertEqual(report["status"], "saved")
        self.assertTrue(report["pixel_file_persistence_verified"])

    def test_durable_capture_rejects_any_missing_sync_or_close_evidence(self):
        self.set_header(durable_pixel_files=True)
        for options in ({"persistence_ok":False}, {"directory_synced":False},
                        {"file_fdatasynced":False}, {"file_closed":False}):
            with self.subTest(options=options):
                report, states = self.run_bridge(lambda token:self.capture(token,durable=True,**options))
                self.assertEqual(report["status"], "error")
                self.assertIn("persistence was not confirmed", report["error"])
                self.assertFalse(report["pixel_file_persistence_verified"])
                self.assertNotIn("saved", [s["phase"] for s in states])

    def test_declared_durable_layer_cannot_use_legacy_completion(self):
        self.set_header(durable_pixel_files=True)
        report, _ = self.run_bridge(self.capture)
        self.assertEqual(report["status"], "error")
        self.assertFalse(report["pixel_file_persistence_verified"])

    def test_persistence_failure_event_is_visible(self):
        self.set_header(durable_pixel_files=True)
        report, _ = self.run_bridge(lambda token:self.append(event="capture_persistence_failed",request=token,reason="directory_fsync"))
        self.assertEqual(report["status"], "error")
        self.assertIn("directory_fsync", report["error"])
        self.assertFalse(report["pixel_file_persistence_verified"])

    def test_failed_request_stays_failed_after_late_completion_and_healthy_rearm(self):
        real_time, offset = time.time, [0]
        def stalled(token):
            now = time.monotonic_ns()
            self.append(event="capture_start",request=token,start_ns=now,end_ns=now+50_000_000)
            offset[0] = 4
        failed, _ = self.run_bridge(stalled,wall_clock=lambda:real_time()+offset[0])
        self.assertEqual(failed['status'],'error')
        self.assertIn('log stopped updating',failed['error'])
        failed_path = self.directory/f"viewer-request-{failed['request']}.json"
        original_failure = failed_path.read_bytes()
        # Native completion arrives after the first helper has already failed.
        self.capture(failed['request'],start=False)
        recovered, _ = self.run_bridge(self.capture)
        self.assertEqual(recovered['status'],'saved')
        self.assertNotEqual(recovered['request'],failed['request'])
        self.assertEqual(failed_path.read_bytes(),original_failure)

    def test_partial_log_line_is_retained(self):
        self.events.write_text('{"event":"first"}\n{"event":')
        with self.events.open() as stream:
            self.assertEqual(list(bridge.available_rows(stream)), [{"event": "first"}])
            with self.events.open("a") as output:
                output.write('"second"}\n')
            self.assertEqual(list(bridge.available_rows(stream)), [{"event": "second"}])

    def test_pose_journal_arms_before_control_and_flushes_after_completion(self):
        calls = []
        test = self
        class Journal:
            def __init__(self, context, pid):
                test.assertEqual(pid, 567)
            def arm(self, request):
                test.assertFalse((test.directory / 'control.txt').exists())
                calls.append(('arm', request))
                return {'phase': 'armed'}
            def window(self, started):
                calls.append(('window', started['request']))
                return {'phase': 'recording'}
            def finish(self, started):
                test.assertIn('capture_complete', test.events.read_text())
                calls.append(('finish', started['request']))
                return {'phase': 'saved', 'path': '/journal.jsonl'}
        with patch.object(bridge, 'PoseJournalClient', Journal):
            report, _ = self.run_bridge(self.capture, context={'pose_journal': {'enabled': True}}, viewer_pid=567)
        self.assertEqual([c[0] for c in calls], ['arm', 'window', 'finish'])
        self.assertEqual({c[1] for c in calls}, {report['request']})
        self.assertEqual(report['status'], 'saved')
        self.assertEqual(report['pose_journal']['status'], 'saved')

    def test_journal_failure_keeps_pixels_and_cancels_bounded_journal(self):
        calls = []
        class Journal:
            def __init__(self, context, pid): pass
            def arm(self, request): return {'phase': 'armed'}
            def window(self, started): raise RuntimeError('sequence changed')
            def finish(self, started): raise AssertionError('must not silently resume failed journal')
            def cancel(self):
                calls.append('cancel')
                return {'phase': 'cancelled'}
        with patch.object(bridge, 'PoseJournalClient', Journal):
            report, _ = self.run_bridge(self.capture, context={'pose_journal': {'enabled': True}})
        self.assertEqual(report['status'], 'saved')
        self.assertEqual(report['pose_journal']['status'], 'error')
        self.assertEqual(report['pose_journal']['error'], 'sequence changed')
        self.assertIn('pose log failed', report['message'])
        self.assertEqual(calls, ['cancel'])

    def test_required_diagnostics_refuse_missing_marker_before_capture(self):
        report, _ = self.run_bridge(context={"diagnostics_required": True,
            "pose_journal": {"enabled": True}}, viewer_pid=os.getpid())
        self.assertEqual(report["status"], "error")
        self.assertIn("Frame identity unavailable", report["error"])
        self.assertFalse((self.directory / "control.txt").exists())
        self.assertTrue(report["viewer_identity"]["verified"])
        self.assertEqual(len(report["viewer_identity"]["executable_sha256"]), 64)

    def test_required_diagnostics_failure_cannot_report_saved(self):
        class Journal:
            def __init__(self, context, pid): pass
            def arm(self, request): return {"phase": "armed"}
            def exchange(self, command):
                return {"session": "test", "frame_identity": {"enabled": True},
                        "pose_journal": {"clock_mapping_available": True}}
            def window(self, started): raise RuntimeError("Pose clock lost")
            def cancel(self): return {"phase": "cancelled"}
        with patch.object(bridge, "PoseJournalClient", Journal):
            report, _ = self.run_bridge(self.capture, viewer_pid=os.getpid(), context={
                "diagnostics_required": True, "pose_journal": {"enabled": True},
                "submitted_frame_marker": {"enabled": True}})
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["all_requested_presents_saved"])
        self.assertFalse(report["diagnostics_complete"])
        self.assertIn("diagnostics incomplete", report["message"])

    def test_required_diagnostics_save_with_complete_clock_and_pose_data(self):
        from tools.vr_capture.test_journal_validation import write_journal
        pid = os.getpid()
        journal_context, _, arguments, _ = write_journal(self.directory/"journals", pid=pid)
        marker = arguments["marker"]
        class Journal:
            def __init__(self, context, pid): pass
            def arm(self, request): return {"phase": "armed"}
            def exchange(self, command):
                return {"session": journal_context["session"], "frame_identity": marker,
                        "pose_journal": {"clock_mapping_available": True}}
            def window(self, started): return {"phase": "recording"}
            def finish(self, started):
                return write_journal(journal_context["directory"], pid=pid, request=started["request"],
                                     start=started["start_ns"], end=started["end_ns"])[1]
        with patch.object(bridge, "PoseJournalClient", Journal):
            report, _ = self.run_bridge(self.capture, viewer_pid=pid, context={
                "diagnostics_required": True, "pose_journal": journal_context,
                "submitted_frame_marker": marker})
        self.assertEqual(report["status"], "saved")
        self.assertTrue(report["diagnostics_complete"])
        self.assertEqual(report["viewer_identity"]["pid"], os.getpid())
        self.assertTrue(report["diagnostic_preflight"]["frame_identity"]["enabled"])
        self.assertTrue(report["pose_journal"]["validation"]["receipt_coverage_verified"])
        self.assertFalse(report["pose_journal"]["validation"]["pixel_decoding_verified"])

    def test_saved_counters_without_retained_journal_are_partial(self):
        from tools.vr_capture.test_journal_validation import write_journal
        pid = os.getpid()
        journal_context, _, arguments, _ = write_journal(self.directory/"journals", pid=pid)
        marker = arguments["marker"]
        class Journal:
            def __init__(self, context, pid): pass
            def arm(self, request): return {"phase": "armed"}
            def exchange(self, command):
                return {"session": journal_context["session"], "frame_identity": marker,
                        "pose_journal": {"clock_mapping_available": True}}
            def window(self, started): return {"phase": "recording"}
            def finish(self, started):
                native = write_journal(journal_context["directory"], pid=pid, request=started["request"],
                                       start=started["start_ns"], end=started["end_ns"])[1]
                Path(native["path"]).unlink()
                return native
        with patch.object(bridge, "PoseJournalClient", Journal):
            report, _ = self.run_bridge(self.capture, viewer_pid=pid, context={
                "diagnostics_required": True, "pose_journal": journal_context, "submitted_frame_marker": marker})
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["all_requested_presents_saved"])
        self.assertFalse(report["diagnostics_complete"])
        self.assertIn("error", report["pose_journal"]["validation"])

    def test_required_pose_clock_unavailable_never_starts_capture(self):
        calls = []
        class Journal:
            def __init__(self, context, pid): pass
            def arm(self, request): return {"phase": "armed"}
            def exchange(self, command):
                return {"frame_identity": {"enabled": True},
                        "pose_journal": {"clock_mapping_available": False}}
            def cancel(self): calls.append("cancel"); return {"phase": "cancelled"}
        with patch.object(bridge, "PoseJournalClient", Journal):
            report, _ = self.run_bridge(viewer_pid=os.getpid(), context={
                "diagnostics_required": True, "pose_journal": {"enabled": True},
                "submitted_frame_marker": {"enabled": True}})
        self.assertEqual(report["status"], "error")
        self.assertFalse((self.directory / "control.txt").exists())
        self.assertEqual(calls, ["cancel"])


if __name__ == "__main__":
    unittest.main()
