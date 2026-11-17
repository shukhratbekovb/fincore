from typing import Annotated

from fastapi import Depends

from backend.application.session.queries.active_sessions import GetUserActiveSessionsQuery
from backend.application.session.use_cases.remove_all_sessions import RemoveAllSessionsUseCase
from backend.application.session.use_cases.remove_session import RemoveSessionUseCase
from backend.application.user.queries.get_current_user import GetCurrentUserQuery

from backend.presentation.api.v1.dependencies.core import UowDep, ClockDep


def get_current_user_query(
        uow: UowDep
) -> GetCurrentUserQuery:
    return GetCurrentUserQuery(
        uow=uow
    )


def get_active_sessions_query(
        uow: UowDep,
        clock: ClockDep
) -> GetUserActiveSessionsQuery:
    return GetUserActiveSessionsQuery(
        uow=uow,
        clock=clock
    )


def get_remove_all_sessions_use_case(
        uow: UowDep,
        clock: ClockDep
) -> RemoveAllSessionsUseCase:
    return RemoveAllSessionsUseCase(
        uow=uow,
        clock=clock
    )


def get_remove_session_use_case(
        uow: UowDep,
        clock: ClockDep
) -> RemoveSessionUseCase:
    return RemoveSessionUseCase(
        uow=uow,
        clock=clock
    )


CurrentUserQueryDep = Annotated[GetCurrentUserQuery, Depends(get_current_user_query)]
ActiveSessionsQueryDep = Annotated[GetUserActiveSessionsQuery, Depends(get_active_sessions_query)]
RemoveAllSessionsDep = Annotated[RemoveAllSessionsUseCase, Depends(get_remove_all_sessions_use_case)]
RemoveSessionDep = Annotated[RemoveSessionUseCase, Depends(get_remove_session_use_case)]
