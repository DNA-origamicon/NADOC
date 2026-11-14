"""Validated query dependency shared by all flex representations."""
from fastapi import Query, HTTPException


def flex_range_query(start: int | None = Query(None, ge=1),
                     end: int | None = Query(None, ge=1),
                     interval: int = Query(1, ge=1)):
    if start is not None and end is not None and start > end:
        raise HTTPException(422, 'Start frame must not exceed end frame')
    return dict(start=start, end=end, interval=interval)
