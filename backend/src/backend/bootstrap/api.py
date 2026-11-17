import uvicorn

from backend.infrastructure.logging import logging_config
from backend.infrastructure.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        'backend.main:app', host='0.0.0.0', port=8000,
        workers=settings.api_workers, log_config=logging_config(settings.log_level), access_log=False,
        proxy_headers=True, server_header=False, timeout_graceful_shutdown=40,
    )


if __name__ == '__main__':
    main()
