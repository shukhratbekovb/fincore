from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class SqlAlchemyBaseModel(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }
