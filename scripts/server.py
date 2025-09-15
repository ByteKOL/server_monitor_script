# server.py
import datetime
import time

import asyncio
import json
from aiohttp import web
import os

from .custom_exception import ClientException
from .logger_config import logger
from .monitor import Monitor

try:
    from .. import config  # package mode
except Exception:
    import config  # direct/path mode


class Server:
    """
    HTTP + WebSocket server for real-time monitoring.
    """

    def __init__(self, monitor: Monitor):
        self.monitor = monitor
        self.ws_clients = set()
        self.app = web.Application(middlewares=[self.cors_middleware])
        self.app.router.add_post("/fetch_monitor_data", self.handle_http)
        self.app.router.add_get("/ws", self.ws_handler)
        self.app.router.add_route("OPTIONS", "/{tail:.*}", self.options_handler)

    async def cors_middleware(self, app, handler):
        async def middleware_handler(request):
            response = await handler(request)
            # Thêm header CORS
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = '*'
            return response

        return middleware_handler

    async def options_handler(self, request):
        return web.Response(status=200)

    async def handle_http(self, request):
        start = time.time()
        ip = request.remote
        method = request.method
        path = request.path
        protocol = request.version

        body = await request.json()
        client_timezone = body.get("client_timezone")
        status = 200
        content_length = 0

        try:
            monitor_24h_data = self.monitor.get_last_24h_monitor_data(client_timezone)
            monitor_7days_data = self.monitor.get_last_7days_monitor_data(client_timezone)
            monitor_30days_data = self.monitor.get_last_30days_monitor_data(client_timezone)
            monitor_12months_data = self.monitor.get_last_12months_monitor_data()
            payload = {
                "1_day": monitor_24h_data,
                "1_week": monitor_7days_data,
                "30_days": monitor_30days_data,
                "12_months": monitor_12months_data,
            }
            text = json.dumps(payload)
            content_length = len(text.encode())
            response = web.Response(
                text=text,
                content_type="application/json",
                status=200
            )
        except ClientException as e:
            response = web.Response(text=json.dumps({
                'error': str(e),
            }), status=404, content_type="application/json", )
            status = 404
        except Exception as e:
            response = web.Response(text=json.dumps({
                'error': str(e),
            }), status=500, content_type="application/json", )
            logger.error(str(e), exc_info=True)

        duration = time.time() - start
        logger.info(
            f'{ip} - - [{datetime.datetime.now().strftime("%d/%b/%Y %H:%M:%S")}] '
            f'"{method} {path} HTTP/{protocol.major}.{protocol.minor}" {status} {content_length} {duration:.3f}s'
        )
        return response

    async def ws_handler(self, request):
        """
        Handle WebSocket connections and send realtime stats every second.
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        logger.info(f"WebSocket connected: {request.remote}")

        try:
            while not ws.closed:
                # Send latest sample to client
                await ws.send_json(self.monitor.get_and_update_current_stats())
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            logger.error(str(e), exc_info=True)
        finally:
            self.ws_clients.remove(ws)
            logger.info(f"WebSocket disconnected: {request.remote}")

        return ws
