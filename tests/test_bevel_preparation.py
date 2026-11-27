import asyncio
from threading import Event
from time import sleep
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.bevel_preparation import prepare_until_disconnected, cancel_preparation


def test_connected_preparation_preserves_document_context():
    from contextvars import ContextVar
    owner = ContextVar('bevel_test_owner')
    owner.set('selected-document')
    request = AsyncMock()
    request.is_disconnected.return_value = False
    assert asyncio.run(prepare_until_disconnected(request, lambda check: owner.get())) == 'selected-document'


def test_disconnect_stops_and_joins_worker_before_returning():
    finished = Event()
    request = AsyncMock()
    request.is_disconnected.return_value = True

    def evaluate(check):
        try:
            while True:
                check()
                sleep(.001)
        finally:
            finished.set()

    with pytest.raises(HTTPException) as error:
        asyncio.run(prepare_until_disconnected(request, evaluate))
    assert error.value.status_code == 499
    assert finished.is_set()


def test_failed_preparation_keeps_original_error():
    request = AsyncMock()
    request.is_disconnected.return_value = False

    def evaluate(check):
        raise ValueError('placement failed')

    with pytest.raises(ValueError, match='placement failed'):
        asyncio.run(prepare_until_disconnected(request, evaluate))


def test_explicit_cancel_works_even_if_proxy_never_disconnects():
    from uuid import uuid4
    identity = uuid4().hex
    finished = Event()
    request = AsyncMock()
    request.is_disconnected.return_value = False

    def evaluate(check):
        try:
            while True:
                check()
                sleep(.001)
        finally:
            finished.set()

    async def run():
        task = asyncio.create_task(prepare_until_disconnected(request, evaluate, identity))
        await asyncio.sleep(.02)
        cancel_preparation(identity)
        await asyncio.wait_for(task, 1)

    with pytest.raises(HTTPException) as error:
        asyncio.run(run())
    assert error.value.status_code == 499
    assert finished.is_set()


def test_early_explicit_cancel_prevents_late_request_work():
    from uuid import uuid4
    identity = uuid4().hex
    cancel_preparation(identity)
    request = AsyncMock()
    request.is_disconnected.return_value = False
    work = []

    def evaluate(check):
        check()
        work.append('should never start')

    with pytest.raises(HTTPException) as error:
        asyncio.run(prepare_until_disconnected(request, evaluate, identity))
    assert error.value.status_code == 499
    assert not work


def test_cancellation_is_scoped_to_the_owning_document():
    from uuid import uuid4
    from backend.api import doc_context
    identity = uuid4().hex
    first = doc_context.set_current_doc('bevel-cancel-first')
    try:
        cancel_preparation(identity)
    finally:
        doc_context.reset_current_doc(first)
    second = doc_context.set_current_doc('bevel-cancel-second')
    try:
        request = AsyncMock()
        request.is_disconnected.return_value = False

        def evaluate(check):
            check()
            return 'unaffected'

        assert asyncio.run(prepare_until_disconnected(request, evaluate, identity)) == 'unaffected'
    finally:
        doc_context.reset_current_doc(second)
