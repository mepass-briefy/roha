"""식별자 3종 생성. business_key=ROHA 순번류(운영), public_key=난수 10~12(외부). pk는 DB autoincrement(내부)."""
import secrets, string
from itertools import count

_PREFIX = "ROHA"
_SEQ = { "application": count(1), "reservation": count(1), "settlement": count(1) }
_ALPHABET = string.ascii_letters + string.digits


def next_business_key(table: str) -> str:
    n = next(_SEQ.get(table, count(1)))
    return f"{_PREFIX}{n:04d}"


def new_public_key() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(secrets.choice([10, 11, 12])))
