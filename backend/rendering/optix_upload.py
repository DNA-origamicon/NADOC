"""Ordered, bounded HTTP pieces of a disposable native graphics payload."""
import asyncio
import hashlib
import time

from fastapi import HTTPException
from .resources import upload_capacity


async def append_upload(session, request):
    source = session.root / 'upload.json'
    try:
        offset = int(request.headers['x-nadoc-upload-offset'])
        total = int(request.headers['x-nadoc-upload-bytes'])
    except (KeyError, ValueError) as error:
        raise HTTPException(422, 'Invalid OptiX upload offset/size') from error
    current = source.stat().st_size if source.exists() else 0
    identity = (total, request.headers.get('x-nadoc-render-id'))
    receipt = getattr(session, 'upload_receipt', None)
    if receipt and receipt['identity'] == identity and receipt['offset'] == offset and receipt['received'] == current:
        # A successful append whose HTTP acknowledgement was lost may be sent
        # again. Verify the bytes before acknowledging; never append them twice.
        digest, size = hashlib.sha256(), 0
        async for chunk in request.stream():
            digest.update(chunk)
            size += len(chunk)
            if size > current - offset:
                raise HTTPException(409, 'Retried OptiX chunk differs from its committed bytes')
        if size != current - offset or digest.hexdigest() != receipt['digest']:
            raise HTTPException(409, 'Retried OptiX chunk differs from its committed bytes')
        session.touched = time.monotonic()
        return {'received': current}
    if offset != current or (current and getattr(session, 'upload_identity', None) != identity):
        raise HTTPException(409, 'OptiX upload offset or frame identity does not match')
    if not 0 <= offset < total:
        raise HTTPException(422, 'Invalid OptiX upload range')
    resources = await asyncio.to_thread(upload_capacity, session.root)
    if total > resources['available_memory_bytes'] or total - offset > resources['scratch_free_bytes']:
        raise HTTPException(413, 'OptiX scene upload exceeds currently available RAM/scratch capacity')
    session.upload_identity = identity
    digest = hashlib.sha256()
    try:
        with source.open('ab') as target:
            async for chunk in request.stream():
                current += len(chunk)
                if current > total:
                    raise HTTPException(422, 'OptiX upload exceeds declared size')
                await asyncio.to_thread(target.write, chunk)
                digest.update(chunk)
                session.touched = time.monotonic()
        session.progress = {'stage': 'prepare', 'label': 'Uploading OptiX scene',
                            'fraction': current / total, 'request_id': identity[1]}
        session.upload_receipt = {'identity': identity, 'offset': offset,
                                  'received': current, 'digest': digest.hexdigest()}
        return {'received': current}
    except BaseException:
        # Roll back only the interrupted piece, preserving acknowledged chunks
        # for retry. Explicit DELETE/lease expiry still owns full cleanup.
        if offset:
            with source.open('r+b') as target:
                target.truncate(offset)
        else:
            source.unlink(missing_ok=True)
        raise


def verify_upload(session, request):
    """A render can consume only the complete, matching upload; never a prefix."""
    total = int(request.headers['x-nadoc-upload-bytes'])
    source = session.root / 'upload.json'
    if (total <= 0 or not source.exists() or source.stat().st_size != total
            or getattr(session, 'upload_identity', None) != (total, request.headers.get('x-nadoc-render-id'))):
        raise ValueError('OptiX scene upload is incomplete or belongs to another frame')
