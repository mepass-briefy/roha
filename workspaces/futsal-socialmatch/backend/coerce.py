"""요청 값 -> DB 컬럼 논리타입 강제 변환(request_schema 타입에 의존하지 않고 컬럼 기준)."""
from datetime import datetime, date
from decimal import Decimal


def to_db(v, kind):
    if v is None:
        return None
    if kind == "datetime" and isinstance(v, str):
        return datetime.fromisoformat(v)
    if kind == "date" and isinstance(v, str):
        return date.fromisoformat(v)
    if kind == "decimal" and not isinstance(v, Decimal):
        return Decimal(str(v))
    return v
