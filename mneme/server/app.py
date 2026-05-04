"""Web server for kimi-mneme memory viewer."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from mneme import __version__
from mneme.config import load_config
from mneme.core.worker import StructuringWorker
from mneme.db.store import ObservationStore
from mneme.server.routes import router
from mneme.wire.watcher import get_global_watcher, stop_global_watcher


# Global connection manager for WebSocket broadcasting
class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return
        text = json.dumps(message, ensure_ascii=False)
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(text)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    config = load_config()
    logger.info(
        f"kimi-mneme server starting on {config['server']['host']}:{config['server']['port']}"
    )
    loop = asyncio.get_running_loop()
    # Start wire session watcher for indexing Kimi CLI traces
    try:
        watcher = get_global_watcher()

        def _broadcast(sid: str, counts: dict[str, int]) -> None:
            msg = {"type": "wire_update", "session_id": sid, "counts": counts}
            try:
                if loop.is_running() and not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
            except Exception:
                pass  # Loop may be closed during shutdown

        watcher.on_ingest = _broadcast
        watcher.start()
    except Exception:
        logger.exception("Failed to start session watcher")
    # Start background structuring worker
    worker = StructuringWorker(interval=5)
    worker_task = asyncio.create_task(worker.start())

    # Start MCP server in background (B.7)
    mcp_process = None
    if config.get("mcp", {}).get("auto_start", False):
        try:
            import subprocess
            import sys

            mcp_cmd = [sys.executable, "-m", "mneme.mcp_server"]
            mcp_process = subprocess.Popen(
                mcp_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"MCP server started (PID: {mcp_process.pid})")
        except Exception:
            logger.debug("Failed to auto-start MCP server")

    yield

    logger.info("kimi-mneme server shutting down")
    worker.stop()
    worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await worker_task
    stop_global_watcher()

    # Stop MCP server
    if mcp_process:
        try:
            mcp_process.terminate()
            mcp_process.wait(timeout=5)
            logger.info("MCP server stopped")
        except Exception:
            pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = load_config()

    app = FastAPI(
        title="kimi-mneme",
        description="Persistent memory for Kimi Code CLI",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config["server"]["cors_origins"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(router, prefix="/api")

    # Custom StaticFiles with no-cache headers
    class NoCacheStaticFiles(StaticFiles):
        def file_response(self, *args: Any, **kwargs: Any) -> Any:
            response = super().file_response(*args, **kwargs)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

    # Static files
    from pathlib import Path

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(static_dir)), name="static")

    # Serve main UI
    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        from pathlib import Path

        from starlette.responses import Response

        static_dir = Path(__file__).parent / "static"
        index_file = static_dir / "index.html"
        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            return Response(
                content=content,
                media_type="text/html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return _default_html()

    # WebSocket for real-time updates
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    action = msg.get("action", "")

                    if action == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    elif action == "subscribe":
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "subscribed",
                                    "channel": msg.get("channel", "all"),
                                }
                            )
                        )
                    elif action == "stats":
                        store = ObservationStore()
                        stats = store.get_stats()
                        await websocket.send_text(json.dumps({"type": "stats", "data": stats}))
                    else:
                        await websocket.send_text(
                            json.dumps({"type": "error", "message": "Unknown action"})
                        )
                except json.JSONDecodeError:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "Invalid JSON"})
                    )
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    return app


def _default_html() -> str:
    """Default HTML when static files are not available."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>kimi-mneme</title>
    <meta charset="utf-8">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1200px; margin: 0 auto; padding: 2rem; background: #0d1117; color: #c9d1d9; }
        h1 { color: #58a6ff; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 2rem 0; }
        .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.5rem; }
        .stat-value { font-size: 2rem; font-weight: bold; color: #58a6ff; }
        .stat-label { color: #8b949e; margin-top: 0.5rem; }
        .status { padding: 0.5rem 1rem; border-radius: 4px; display: inline-block; margin-top: 1rem; }
        .status.connected { background: #238636; color: white; }
        .status.disconnected { background: #da3633; color: white; }
    </style>
</head>
<body>
    <h1>kimi-mneme</h1>
    <p>Persistent memory for Kimi Code CLI</p>
    <div id="ws-status" class="status disconnected">WebSocket: disconnected</div>
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value" id="sessions">-</div>
            <div class="stat-label">Sessions</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="observations">-</div>
            <div class="stat-label">Observations</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="summaries">-</div>
            <div class="stat-label">Summaries</div>
        </div>
    </div>
    <script>
        const ws = new WebSocket('ws://' + location.host + '/ws');
        const statusEl = document.getElementById('ws-status');

        ws.onopen = () => {
            statusEl.textContent = 'WebSocket: connected';
            statusEl.className = 'status connected';
            ws.send(JSON.stringify({action: 'stats'}));
        };

        ws.onclose = () => {
            statusEl.textContent = 'WebSocket: disconnected';
            statusEl.className = 'status disconnected';
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'stats') {
                document.getElementById('sessions').textContent = msg.data.total_sessions;
                document.getElementById('observations').textContent = msg.data.total_observations;
                document.getElementById('summaries').textContent = msg.data.total_summaries;
            }
        };
    </script>
</body>
</html>"""


def main() -> None:
    """Run the server."""
    import uvicorn

    config = load_config()
    app = create_app()

    uvicorn.run(
        app,
        host=config["server"]["host"],
        port=config["server"]["port"],
        log_level="info",
    )


if __name__ == "__main__":
    main()
