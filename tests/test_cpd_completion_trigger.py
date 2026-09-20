from experiments.cpd_published_comparator.trigger_dna_review import terminal_reason


def records():
    return [
        dict(system=s, replica=r, block=b)
        for s in ["cpd", "control"]
        for r in range(1, 4)
        for b in range(1, 6)
    ]


def test_trigger_waits_for_terminal_state_and_checks_unique_blocks():
    complete = records()
    assert terminal_reason(dict(state="running", records=complete), True) is None
    assert (
        terminal_reason(dict(state="complete", records=complete), False) == "complete"
    )
    duplicate = complete[:-1] + complete[:1]
    assert (
        terminal_reason(dict(state="complete", records=duplicate), False)
        == "incomplete terminal manifest"
    )


def test_trigger_also_reviews_failure_or_interruption():
    assert terminal_reason(dict(state="failed", records=[]), True) == "campaign failed"
    assert (
        terminal_reason(dict(state="running", records=[]), False)
        == "supervisor stopped before terminal status"
    )


def test_successful_process_does_not_imply_successful_review():
    from experiments.cpd_published_comparator.trigger_dna_review import review_succeeded

    failed = dict(
        review_completed=False, verified_blocks=0, report_markdown="Filesystem blocked"
    )
    assert not review_succeeded(0, failed, 30)
    complete = dict(
        review_completed=True, verified_blocks=30, report_markdown="Evidence inspected"
    )
    assert review_succeeded(0, complete, 30)
    assert not review_succeeded(0, complete, 29)


def test_atomic_completion_event_and_deadline(tmp_path):
    import json
    from experiments.cpd_published_comparator.completion_events import (
        CompletionEvents,
        deadline_seconds,
    )

    watcher = CompletionEvents(tmp_path)
    try:
        temporary = tmp_path / "status.tmp"
        temporary.write_text(json.dumps({"state": "complete"}))
        temporary.replace(tmp_path / "status.json")
        assert "status" in watcher.wait(1)
        assert watcher.wait(0.01) == {"deadline"}
    finally:
        watcher.close()
    assert deadline_seconds(14400) == 21600
    assert deadline_seconds(420) == 720


def test_completed_campaign_queues_originating_thread_once(tmp_path):
    import json
    from experiments.cpd_published_comparator.trigger_dna_review import run

    (tmp_path / "status.json").write_text(
        json.dumps(dict(state="complete", records=records()))
    )
    fake = tmp_path / "queue"
    fake.write_text(
        '#!/usr/bin/env python3\nimport sys,json\nfrom pathlib import Path\nPath(__file__).with_name("args.json").write_text(json.dumps(sys.argv[1:]))\nprint("Queued")\n'
    )
    fake.chmod(0o700)
    run(tmp_path, str(fake), "exact-origin-thread", 420)
    state = json.loads((tmp_path / "completion_wake.json").read_text())
    args = json.loads((tmp_path / "args.json").read_text())
    assert state["state"] == "queued"
    assert len(state["deliveries"]) == 1
    assert args[:3] == ["queue", "--thread", "exact-origin-thread"]
    assert "completion_wake_ack.json" in args[-1]
    assert not (tmp_path / "completion_wake_ack.json").exists()


def test_pilot_completion_uses_declared_keys():
    expected = [[s, r, 0] for s in ["cpd", "control"] for r in range(1, 4)]
    rows = [dict(system=s, replica=r, block=b) for s, r, b in expected]
    assert (
        terminal_reason(
            dict(state="complete", records=rows, expected_keys=expected), False
        )
        == "complete"
    )
    assert (
        terminal_reason(
            dict(state="complete", records=rows[:-1], expected_keys=expected), False
        )
        == "incomplete terminal manifest"
    )
