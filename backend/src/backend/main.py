from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from backend.infrastructure.db.sqlalchemy.core.database import create_engine, create_session_factory
from backend.infrastructure.settings import get_settings
from backend.infrastructure.redis import create_redis_client
from backend.infrastructure.security.rate_limiter import RedisRateLimiter
from backend.presentation.api.documentation.router import register_documentation
from backend.presentation.api.errors import register_exception_handlers
from backend.presentation.api.cache_control import AuthCacheControlMiddleware
from backend.presentation.api.v1.routers import v1_router
from backend.presentation.api.health import router as health_router
from backend.presentation.api.request_logging import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    try:
        async with AsyncExitStack() as resources:
            engine = create_engine(settings)
            resources.push_async_callback(engine.dispose)
            redis_client = create_redis_client(settings)
            resources.push_async_callback(redis_client.aclose)
            app.state.engine = engine
            app.state.redis_client = redis_client
            app.state.health_check_timeout = settings.health_check_timeout
            app.state.session_factory = create_session_factory(engine)
            app.state.rate_limiter = RedisRateLimiter(redis_client)
            yield
    finally:
        app.state.engine = None
        app.state.session_factory = None
        app.state.rate_limiter = None
        app.state.redis_client = None


app = FastAPI(
    title="FinCore API",
    description="FinCore API",
    version="0.0.1",
    lifespan=lifespan,
    redoc_url=None,
)

app.add_middleware(AuthCacheControlMiddleware)
app.add_middleware(RequestLoggingMiddleware)

register_exception_handlers(app)
app.include_router(health_router)
app.include_router(v1_router)
register_documentation(app)
