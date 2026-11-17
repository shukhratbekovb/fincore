import argparse
import asyncio
import json
import signal
import sys
from dataclasses import asdict

from backend.application.maintenance.dtos import CleanupExpiredDataCommand, CleanupReport
from backend.application.maintenance.use_cases.cleanup import CleanupExpiredDataUseCase
from backend.infrastructure.db.sqlalchemy.core.database import create_engine, create_session_factory
from backend.infrastructure.db.sqlalchemy.maintenance import SqlAlchemyMaintenanceStore
from backend.infrastructure.maintenance.settings import CleanupSettings
from backend.infrastructure.settings import get_settings


async def cleanup(*, dry_run: bool, batch_size: int | None = None, max_batches: int | None = None) -> CleanupReport:
    settings = CleanupSettings()
    engine = create_engine(get_settings())
    try:
        return await CleanupExpiredDataUseCase(SqlAlchemyMaintenanceStore(create_session_factory(engine))).execute(
            CleanupExpiredDataCommand(
                policy=settings.policy(), dry_run=dry_run,
                batch_size=settings.cleanup_batch_size if batch_size is None else batch_size,
                max_batches=settings.cleanup_max_batches if max_batches is None else max_batches,
            )
        )
    finally:
        await engine.dispose()


def _print_report(report: CleanupReport) -> None:
    print(json.dumps(asdict(report), default=str, ensure_ascii=False), flush=True)


async def run_loop(*, batch_size: int | None = None, max_batches: int | None = None) -> None:
    interval = CleanupSettings().cleanup_interval_seconds
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            try:
                _print_report(await cleanup(dry_run=False, batch_size=batch_size, max_batches=max_batches))
            except Exception as exc:
                print(f"Cleanup failed ({type(exc).__name__})", file=sys.stderr, flush=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                pass
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean expired service data; preserve financial records and replay receipts")
    parser.add_argument('--dry-run', action='store_true', help='Count eligible rows without deleting or archiving anything')
    parser.add_argument('--batch-size', type=int, choices=range(1, 1001), metavar='1..1000')
    parser.add_argument('--max-batches', type=int, choices=range(1, 1001), metavar='1..1000')
    parser.add_argument('--loop', action='store_true', help='Run immediately, then at CLEANUP_INTERVAL_SECONDS; stop gracefully on SIGTERM')
    args = parser.parse_args()
    if args.loop and args.dry_run:
        parser.error('--loop cannot be combined with --dry-run')
    try:
        if args.loop:
            asyncio.run(run_loop(batch_size=args.batch_size, max_batches=args.max_batches))
            return 0
        report = asyncio.run(cleanup(dry_run=args.dry_run, batch_size=args.batch_size, max_batches=args.max_batches))
    except Exception as exc:
        # Never print connection exception messages or row payloads.
        print(f"Cleanup failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    _print_report(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
