from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """SQLAlchemy metadata root for the canonical domain schema."""

    metadata = MetaData(naming_convention=CONVENTION)


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
        pool_pre_ping=True,
    )
