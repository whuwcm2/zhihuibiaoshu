from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _profile_text(profile: dict[str, Any], key: str) -> str | None:
    value = profile.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    company_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    profile: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    @property
    def contact_person(self) -> str | None:
        return _profile_text(self.profile, "contact_person")

    @property
    def contact_phone(self) -> str | None:
        return _profile_text(self.profile, "contact_phone")


async def create_company(
    session: AsyncSession, company_name: str, profile: dict[str, Any]
) -> Company:
    company = Company(company_name=company_name, profile=profile)
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def list_companies(
    session: AsyncSession,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Company]:
    statement = select(Company).order_by(Company.updated_at.desc())
    if query:
        statement = statement.where(Company.company_name.ilike(f"%{query}%"))
    statement = statement.limit(limit).offset(offset)
    result = await session.scalars(statement)
    return list(result)


async def get_company(
    session: AsyncSession, company_id: uuid.UUID
) -> Company | None:
    return await session.get(Company, company_id)


async def update_company(
    session: AsyncSession,
    company: Company,
    company_name: str,
    profile: dict[str, Any],
) -> Company:
    company.company_name = company_name
    company.profile = profile
    await session.commit()
    await session.refresh(company)
    return company


async def delete_company(session: AsyncSession, company: Company) -> None:
    await session.delete(company)
    await session.commit()
