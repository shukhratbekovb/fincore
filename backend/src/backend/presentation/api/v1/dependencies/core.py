from typing import Annotated
from fastapi import Depends, Request

from backend.application.share.interfaces.uow import IUnitOfWork
from backend.infrastructure.clock import SystemClock
from backend.infrastructure.db.sqlalchemy.core.uow import SqlAlchemyUnitOfWork
from backend.infrastructure.settings import Settings, get_settings


def get_uow(request: Request) -> IUnitOfWork:
    return SqlAlchemyUnitOfWork(
        session_factory=request.app.state.session_factory
    )


def get_clock() -> SystemClock:
    return SystemClock()


ClockDep = Annotated[SystemClock, Depends(get_clock)]

UowDep = Annotated[IUnitOfWork, Depends(get_uow)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
