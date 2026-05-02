"""Web server for kimi-mneme memory viewer."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from mneme.config import load_config
from mneme.db.store import ObservationStore
from mneme.server.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    config = load_config()
    logger.info(f"kimi-mneme server starting on {config['server']['host']}:{config['server']['port']}")
    yield
    logger.info("kimi-mneme server shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = load_config()

    app = FastAPI(
        title="kimi-mneme",
        description="Persistent memory for Kimi Code CLI",
        version="1.0.0",
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

    # Static files
    static_dir = __file__.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve main UI
    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        index_file = static_dir / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return _default_html()

    # WebSocket for real-time updates
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                # Keep connection alive, push updates when available
                data = await websocket.receive_text()
                await websocket.send_text(f"Echo: {data}")
        except Exception:
            pass

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
    </style>
</head>
<body>
    <h1>🧠 kimi-mneme</h1>
    <p>Persistent memory for Kimi Code CLI</p>
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value" id="sessions">-</div>
            <div class="stat-label">Sessions</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="observations">-</div>
            <div class="stat-label">Observations</div>
        </div>
    </div>
    <script>
        fetch('/api/stats').then(r => r.json()).then(data => {
            document.getElementById('sessions').textContent = data.total_sessions;
            document.getElementById('observations').textContent = data.total_observations;
        });
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
