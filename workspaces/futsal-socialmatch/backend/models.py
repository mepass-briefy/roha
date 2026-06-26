from sqlalchemy import (Column, BigInteger, Integer, String, Text, Numeric, Boolean,
                        DateTime, Date, JSON, ForeignKey)
from database import Base


class Application(Base):
    __tablename__ = "application"
    pk = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)  # 내부 PK(외부 미노출)
    business_key = Column(String(32), unique=True, index=True, nullable=False)  # 운영 키
    public_key = Column(String(16), unique=True, index=True, nullable=False)  # 외부 노출 키
    name = Column(String(255), nullable=True)
    phone = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    status = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

class Reservation(Base):
    __tablename__ = "reservation"
    pk = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)  # 내부 PK(외부 미노출)
    business_key = Column(String(32), unique=True, index=True, nullable=False)  # 운영 키
    public_key = Column(String(16), unique=True, index=True, nullable=False)  # 외부 노출 키
    application_pk = Column(BigInteger, ForeignKey("application.pk"), nullable=True)  # FK
    match_datetime = Column(DateTime, nullable=True)
    venue = Column(String(255), nullable=True)
    status = Column(String(64), nullable=True)
    idempotency_key = Column(String(255), nullable=True)
    version = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

class Settlement(Base):
    __tablename__ = "settlement"
    pk = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)  # 내부 PK(외부 미노출)
    business_key = Column(String(32), unique=True, index=True, nullable=False)  # 운영 키
    public_key = Column(String(16), unique=True, index=True, nullable=False)  # 외부 노출 키
    reservation_pk = Column(BigInteger, ForeignKey("reservation.pk"), nullable=True)  # FK
    amount = Column(Numeric(18, 2), nullable=True)
    currency = Column(String(255), nullable=True)
    status = Column(String(64), nullable=True)
    settled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

