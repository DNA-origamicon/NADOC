"""Request schemas shared by connection-version HTTP and headless adapters."""

from typing import Optional

from pydantic import BaseModel


class ConnectionVersionCreateRequest(BaseModel):
    overhang_a_id: str
    overhang_b_id: str
    connection_type: str
    overhang_a_seq: Optional[str] = None
    overhang_b_seq: Optional[str] = None
    bridge_length: int = 0
    bridge_seq: Optional[str] = None
    applied: bool = False
    name: Optional[str] = None


class ConnectionVersionPatchRequest(BaseModel):
    name: Optional[str] = None
    connection_type: Optional[str] = None
    overhang_a_seq: Optional[str] = None
    overhang_b_seq: Optional[str] = None
    bridge_length: Optional[int] = None
    bridge_seq: Optional[str] = None
    applied: Optional[bool] = None
