from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from backend.infrastructure.health import check_dependencies


class HealthResponse(BaseModel):
    """Liveness response: the application process can serve HTTP."""
    status: Literal['ok'] = Field(default='ok', description='Application process is running.')


class DependencyChecks(BaseModel):
    """Results of bounded PostgreSQL and Redis probes."""
    postgres: Literal['ok', 'unavailable'] = Field(description='PostgreSQL SELECT 1 probe result.')
    redis: Literal['ok', 'unavailable'] = Field(description='Redis PING probe result.')


class ReadinessResponse(BaseModel):
    """Readiness of the API and its critical dependencies."""
    status: Literal['ok', 'unavailable'] = Field(description='Whether all critical dependencies are available.')
    checks: DependencyChecks = Field(description='Dependency results without connection or credential details.')


router = APIRouter(tags=['health'])


@router.get('/health', response_model=HealthResponse)
@router.get('/health/live', response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse()


@router.get('/health/ready', response_model=ReadinessResponse, responses={503: {'model': ReadinessResponse}})
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    checks = await check_dependencies(
        getattr(request.app.state, 'engine', None),
        getattr(request.app.state, 'redis_client', None),
        timeout=getattr(request.app.state, 'health_check_timeout', 2),
    )
    ready = all(status == 'ok' for status in checks.values())
    response.status_code = 200 if ready else 503
    response.headers['Cache-Control'] = 'no-store'
    return ReadinessResponse(status='ok' if ready else 'unavailable', checks=DependencyChecks(**checks))
