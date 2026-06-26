"""명세 response_contract 고정 래퍼. 외부는 이 형상으로만 응답. jsonable_encoder로 datetime/Decimal 직렬화."""
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder


def ok(data, status=200):
    return JSONResponse(status_code=status, content=jsonable_encoder({"success": True, "data": data}))


def fail(code: str, message: str, status: int):
    return JSONResponse(status_code=status, content=jsonable_encoder({"success": False, "error": {"code": code, "message": message}}))
