__import__('os').environ['TZ'] = 'UTC'

from datetime import datetime, timedelta

import asyncio
from aiohttp import web
from scripts.monitor import Monitor
from scripts.server import Server
from scripts.logger_config import logger
import config
import signal


monitor = Monitor()
server = Server(monitor)

async def monitor_sampling_loop():
    while True:
        monitor.get_and_update_current_stats()
        await asyncio.sleep(1)

async def monitor_hourly_loop():
    while True:
        now = datetime.now()
        next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        sleep_time = (next_hour - now).total_seconds()
        await asyncio.sleep(sleep_time)
        # when wake up it's definitely early
        monitor.push_to_file()

async def start_background_tasks(app):
    app['sampling_task'] = asyncio.create_task(monitor_sampling_loop())
    app['hourly_task'] = asyncio.create_task(monitor_hourly_loop())

async def cleanup_background_tasks(app):
    logger.info("Shutting down, saving last hourly data...")
    monitor.push_to_file()  # Save remaining data
    logger.info("saving last hourly data done.")

    app['sampling_task'].cancel()
    app['hourly_task'].cancel()
    await asyncio.gather(app['sampling_task'], app['hourly_task'], return_exceptions=False)

async def main():
    logger.info("=======================================")
    logger.info("Starting monitor system")
    app = server.app
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # # Register signals (SIGINT = Ctrl+C, SIGTERM = systemctl stop)
    # shutdown_task = lambda : asyncio.create_task(cleanup_background_tasks())
    # for sig in (signal.SIGINT, signal.SIGTERM):
    #     loop.add_signal_handler(sig, shutdown_task)

    app = loop.run_until_complete(main())

    try:
        web.run_app(app, port=config.http_port, handle_signals=False)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Server stopped manually")
