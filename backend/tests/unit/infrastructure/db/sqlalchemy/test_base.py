from datetime import datetime

from sqlalchemy import MetaData
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from backend.infrastructure.db.sqlalchemy.models.base import SqlAlchemyBaseModel
from backend.infrastructure.db.sqlalchemy.models.mixins import SqlAlchemyTimeActionMixin


class TimestampProbe(SqlAlchemyTimeActionMixin, SqlAlchemyBaseModel):
    # Isolate the test table from production/Alembic metadata.
    metadata = MetaData()
    __tablename__ = 'timestamp_probe'

    id: Mapped[int] = mapped_column(primary_key=True)
    last_login_at: Mapped[datetime | None]


def test_datetime_annotations_use_timezone_aware_columns():
    columns = TimestampProbe.__table__.columns
    for name in ('created_at', 'updated_at', 'last_login_at'):
        assert columns[name].type.timezone is True
    assert columns.created_at.nullable is False
    assert columns.updated_at.nullable is False
    assert columns.last_login_at.nullable is True
    ddl = str(CreateTable(TimestampProbe.__table__).compile(dialect=dialect()))
    assert ddl.count('TIMESTAMP WITH TIME ZONE') == 3
    assert 'timestamp_probe' not in SqlAlchemyBaseModel.metadata.tables
