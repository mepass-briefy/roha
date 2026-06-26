"""FastAPI 앱. 명세 엔드포인트 충실 번역. 외부 경로는 public_key만. 식별자 3종 적용."""
from fastapi import FastAPI, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
import models, schemas, coerce
from database import init_db, get_session
from identifiers import next_business_key, new_public_key
from responses import ok, fail


app = FastAPI(title='roha generated backend (spec->code)')

@app.on_event('startup')
def _startup():
    init_db()


@app.post("/api/v1/applications")
def EP_APP_001(payload: schemas.EpApp001, db: Session = Depends(get_session)):
    x = models.Application(business_key=next_business_key("application"), public_key=new_public_key(), name=coerce.to_db(getattr(payload, "name", None), "string"), phone=coerce.to_db(getattr(payload, "phone", None), "string"), email=coerce.to_db(getattr(payload, "email", None), "string"))
    db.add(x); db.commit(); db.refresh(x)
    return ok({ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "name": getattr(x, "name"), "phone": getattr(x, "phone"), "email": getattr(x, "email"), "status": getattr(x, "status"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") }, 201)

@app.get("/api/v1/applications/{public_key}")
def EP_APP_002(public_key: str, db: Session = Depends(get_session)):
    x = db.execute(select(models.Application).where(models.Application.public_key == public_key)).scalar_one_or_none()
    if x is None:
        return fail("NOT_FOUND", "리소스 없음", 404)
    return ok({ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "name": getattr(x, "name"), "phone": getattr(x, "phone"), "email": getattr(x, "email"), "status": getattr(x, "status"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") }, 200)

@app.get("/api/v1/applications")
def EP_APP_003(cursor: int = 0, limit: int = 20, db: Session = Depends(get_session)):
    rows = db.execute(select(models.Application).offset(cursor).limit(limit)).scalars().all()
    items = [{ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "name": getattr(x, "name"), "phone": getattr(x, "phone"), "email": getattr(x, "email"), "status": getattr(x, "status"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") } for x in rows]
    return ok({"items": items, "next_cursor": cursor + len(items)}, 200)

@app.post("/api/v1/reservations")
def EP_RES_001(payload: schemas.EpRes001, db: Session = Depends(get_session)):
    _ref_application = db.execute(select(models.Application).where(models.Application.public_key == payload.application_public_key)).scalar_one_or_none()
    if _ref_application is None:
        return fail("VALIDATION_ERROR", "application_public_key 참조 없음", 400)
    x = models.Reservation(business_key=next_business_key("reservation"), public_key=new_public_key(), application_pk=_ref_application.pk, match_datetime=coerce.to_db(getattr(payload, "match_datetime", None), "datetime"), venue=coerce.to_db(getattr(payload, "venue", None), "string"), idempotency_key=coerce.to_db(getattr(payload, "idempotency_key", None), "string"))
    db.add(x); db.commit(); db.refresh(x)
    return ok({ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "application_pk": getattr(x, "application_pk"), "match_datetime": getattr(x, "match_datetime"), "venue": getattr(x, "venue"), "status": getattr(x, "status"), "idempotency_key": getattr(x, "idempotency_key"), "version": getattr(x, "version"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") }, 201)

@app.get("/api/v1/reservations/{public_key}")
def EP_RES_002(public_key: str, db: Session = Depends(get_session)):
    x = db.execute(select(models.Reservation).where(models.Reservation.public_key == public_key)).scalar_one_or_none()
    if x is None:
        return fail("NOT_FOUND", "리소스 없음", 404)
    return ok({ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "application_pk": getattr(x, "application_pk"), "match_datetime": getattr(x, "match_datetime"), "venue": getattr(x, "venue"), "status": getattr(x, "status"), "idempotency_key": getattr(x, "idempotency_key"), "version": getattr(x, "version"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") }, 200)

@app.get("/api/v1/reservations")
def EP_RES_003(cursor: int = 0, limit: int = 20, db: Session = Depends(get_session)):
    rows = db.execute(select(models.Reservation).offset(cursor).limit(limit)).scalars().all()
    items = [{ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "application_pk": getattr(x, "application_pk"), "match_datetime": getattr(x, "match_datetime"), "venue": getattr(x, "venue"), "status": getattr(x, "status"), "idempotency_key": getattr(x, "idempotency_key"), "version": getattr(x, "version"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") } for x in rows]
    return ok({"items": items, "next_cursor": cursor + len(items)}, 200)

@app.patch("/api/v1/reservations/{public_key}")
def EP_RES_004(public_key: str, db: Session = Depends(get_session)):
    x = db.execute(select(models.Reservation).where(models.Reservation.public_key == public_key)).scalar_one_or_none()
    if x is None:
        return fail("NOT_FOUND", "리소스 없음", 404)
    db.commit()
    return ok({"public_key": public_key}, 200)

@app.get("/api/v1/settlements/{public_key}")
def EP_STL_001(public_key: str, db: Session = Depends(get_session)):
    x = db.execute(select(models.Settlement).where(models.Settlement.public_key == public_key)).scalar_one_or_none()
    if x is None:
        return fail("NOT_FOUND", "리소스 없음", 404)
    return ok({ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "reservation_pk": getattr(x, "reservation_pk"), "amount": getattr(x, "amount"), "currency": getattr(x, "currency"), "status": getattr(x, "status"), "settled_at": getattr(x, "settled_at"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") }, 200)

@app.get("/api/v1/settlements")
def EP_STL_002(cursor: int = 0, limit: int = 20, db: Session = Depends(get_session)):
    rows = db.execute(select(models.Settlement).offset(cursor).limit(limit)).scalars().all()
    items = [{ "business_key": getattr(x, "business_key"), "public_key": getattr(x, "public_key"), "reservation_pk": getattr(x, "reservation_pk"), "amount": getattr(x, "amount"), "currency": getattr(x, "currency"), "status": getattr(x, "status"), "settled_at": getattr(x, "settled_at"), "created_at": getattr(x, "created_at"), "updated_at": getattr(x, "updated_at") } for x in rows]
    return ok({"items": items, "next_cursor": cursor + len(items)}, 200)

