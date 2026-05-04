"""Background worker for AI structuring queue."""

from __future__ import annotations

import asyncio

from loguru import logger

from mneme.config import load_config
from mneme.core.ai_provider import HybridProvider
from mneme.db.store import ObservationStore
from mneme.db.structured_store import StructuredObservationStore


class StructuringWorker:
    """Process pending observations through AI structuring."""

    def __init__(self, interval: int | None = None) -> None:
        config = load_config()
        struct_cfg = config.get("structuring", {})
        self.store = ObservationStore()
        self.structured_store = StructuredObservationStore()
        self.provider = HybridProvider()
        self.running = False
        self.enabled = struct_cfg.get("enabled", True)
        self.interval = interval or struct_cfg.get("worker_interval_seconds", 5)
        self.batch_size = struct_cfg.get("batch_size", 5)
        self.max_retry = struct_cfg.get("max_retry_count", 3)

    async def start(self) -> None:
        """Start the worker loop."""
        if not self.enabled:
            logger.info("Structuring worker disabled in config")
            return

        self.running = True
        logger.info(
            f"Structuring worker started (interval={self.interval}s, batch={self.batch_size})"
        )

        while self.running:
            try:
                await self._process_batch()
            except Exception as e:
                logger.error(f"Worker error: {e}")

            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        """Stop the worker."""
        self.running = False
        logger.info("Structuring worker stopped")

    async def _process_batch(self, limit: int | None = None) -> None:
        """Process a batch of pending observations."""
        limit = limit or self.batch_size
        messages = self.store.claim_pending_messages(limit=limit, message_type="observation")

        for msg in messages:
            # Skip if exceeded max retries
            if msg.get("retry_count", 0) >= self.max_retry:
                logger.warning(f"Message {msg['id']} exceeded max retries, marking failed")
                self.store.mark_message_failed(msg["id"])
                continue

            try:
                result = await self.provider.structure_observation(
                    tool_name=msg.get("tool_name"),
                    tool_input=msg.get("tool_input"),
                    tool_output=msg.get("tool_response"),
                    error=msg.get("error"),
                )

                if result and not result.skip:
                    self.structured_store.add_structured(
                        result,
                        session_id=msg["session_id"],
                        project=self._extract_project(msg.get("cwd", "")),
                        raw_observation_id=msg.get("raw_observation_id"),
                        source=result.source,
                        model="kimi-k2.5" if result.source == "ai" else None,
                    )

                self.store.mark_message_processed(msg["id"])

            except Exception as e:
                logger.error(f"Failed to structure message {msg['id']}: {e}")
                self.store.mark_message_failed(msg["id"])

    @staticmethod
    def _extract_project(cwd: str) -> str:
        """Extract project name from cwd."""
        from pathlib import PurePath

        # Normalize separators so PurePath works cross-platform
        normalized = cwd.replace("\\", "/")
        return PurePath(normalized).name or cwd
