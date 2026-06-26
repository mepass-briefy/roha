"""명세 request_schema -> Pydantic 요청 모델(검증)."""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel


class EpApp001(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None

class EpRes001(BaseModel):
    application_public_key: str
    match_datetime: str
    venue: str
    idempotency_key: Optional[str] = None

class EpRes004(BaseModel):
    public_key: str
    status: Optional[str] = None
    if_match: Optional[str] = None

