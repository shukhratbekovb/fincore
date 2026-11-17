from typing import Annotated

from fastapi import Depends, HTTPException, Request

from backend.application.share.interfaces.rate_limiter import IRateLimiter
from backend.presentation.api.v1.schemas.errors import ErrorResponse


RATE_LIMIT_RESPONSES = {
    429: {'model': ErrorResponse, 'description': 'Too many requests', 'headers': {
        'Retry-After': {'schema': {'type': 'integer'}, 'description': 'Seconds before retry'},
    }},
    503: {'model': ErrorResponse, 'description': 'Request limit service unavailable'},
}


def check_rate_limit(retry_after: int) -> None:
    if retry_after:
        raise HTTPException(429, 'Too many requests', headers={'Retry-After': str(retry_after)})


def get_rate_limiter(request: Request) -> IRateLimiter:
    return request.app.state.rate_limiter


RateLimiterDep = Annotated[IRateLimiter, Depends(get_rate_limiter)]
