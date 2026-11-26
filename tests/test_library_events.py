"""Library notifications retain writes without observing read-only traffic."""

from queue import Queue
import sys

import pytest

from watchdog.events import (
    FileCreatedEvent, FileModifiedEvent, FileDeletedEvent, FileMovedEvent,
)
from watchdog.observers.api import ObservedWatch

from backend.api import library_events


@pytest.mark.skipif(sys.platform != "linux", reason="Linux observer subscription contract")
def test_library_watch_does_not_subscribe_to_read_events(monkeypatch, tmp_path):
    from watchdog.observers.inotify import InotifyEmitter
    from watchdog.observers.inotify_c import InotifyConstants
    scheduled = {}

    class Observer:
        def schedule(self, handler, path, **kwargs):
            scheduled.update(kwargs)

        def start(self):
            pass

        def stop(self):
            pass

        def join(self):
            pass

    monkeypatch.setattr(library_events, 'Observer', Observer)
    library_events.start(tmp_path)
    try:
        emitter = InotifyEmitter(Queue(), ObservedWatch(str(tmp_path), recursive=True),
                                 event_filter=scheduled['event_filter'])
        mask = emitter.get_event_mask_from_filter()
        assert not mask & (InotifyConstants.IN_OPEN | InotifyConstants.IN_CLOSE_NOWRITE)
        assert mask & InotifyConstants.IN_MODIFY
        assert mask & InotifyConstants.IN_CREATE
        assert mask & InotifyConstants.IN_DELETE
        assert mask & InotifyConstants.IN_MOVE
        assert scheduled['recursive']
    finally:
        library_events.stop()


def test_library_mutations_and_internal_path_filter(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(library_events, '_push', events.append)
    handler = library_events._WorkspaceHandler(tmp_path)
    # Event paths only: no authored structure files.
    path = str(tmp_path / 'part.nadoc')
    for event in (FileCreatedEvent(path), FileModifiedEvent(path),
                  FileMovedEvent(path, str(tmp_path / 'assembly.nass')), FileDeletedEvent(path)):
        handler.dispatch(event)
    handler.dispatch(FileModifiedEvent(str(tmp_path / '.session' / 'part.nadoc')))
    handler.dispatch(FileModifiedEvent(str(tmp_path / 'analysis.json')))
    assert [(e['type'], e['path']) for e in events] == [
        ('file-changed', 'part.nadoc'), ('file-changed', 'part.nadoc'),
        ('file-changed', 'assembly.nass'), ('file-deleted', 'part.nadoc'),
    ]
