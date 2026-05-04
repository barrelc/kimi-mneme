"""Extract and process observations from hook events."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from mneme.core.sanitize import clean_observation, extract_file_path
from mneme.db.store import Observation, ObservationStore, PendingMessage


class Extractor:
    """Extract observations from Kimi CLI hook events."""

    def __init__(self) -> None:
        self.store = ObservationStore()

    def handle_session_start(self, data: dict[str, Any]) -> str | None:
        """Handle SessionStart event.

        Args:
            data: Hook input data.

        Returns:
            Context string to inject, or None.
        """
        session_id = data["session_id"]
        cwd = data["cwd"]

        self.store.add_session(session_id, cwd)
        logger.info(f"Session started: {session_id}")

        # Check if this is a resumed session — inject checkpoint context
        resume_context = self._get_resume_context(session_id)

        # 1. Fast local summary of recent activity (reuses store, cached by cwd)
        from mneme.core.summarizer import FastSummarizer

        summarizer = FastSummarizer(store=self.store)
        brief = summarizer.get_project_brief(cwd, max_sessions=1, current_session_id=session_id)

        # 2. Full context injection — semantic search via sqlite-vec (B.5)
        from mneme.core.injector import Injector

        injector = Injector(store=self.store, use_vector=True)
        context = injector.get_context(cwd, current_session_id=session_id)

        parts = []
        if resume_context:
            parts.append(resume_context)
        if brief:
            parts.append(brief)
        if context:
            parts.append(context)

        if parts:
            combined = "\n\n".join(parts)
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "context": combined,
                    }
                }
            )

        return None

    def _get_resume_context(self, session_id: str) -> str | None:
        """Get resume context from latest checkpoint for this session."""
        try:
            checkpoint = self.store.get_latest_checkpoint(session_id)
            if not checkpoint:
                return None

            lines = ["## 📌 Session Resume Context"]
            lines.append(
                f"**Checkpoint #{checkpoint['checkpoint_number']}** ({checkpoint['checkpoint_type']})"
            )
            lines.append("")
            lines.append("### Summary")
            lines.append(checkpoint["summary"])

            decisions = checkpoint.get("key_decisions", [])
            if decisions:
                lines.append("")
                lines.append("### Key Decisions")
                for d in decisions:
                    lines.append(f"- {d}")

            tasks = checkpoint.get("open_tasks", [])
            if tasks:
                lines.append("")
                lines.append("### Open Tasks")
                for t in tasks:
                    lines.append(f"- [ ] {t}")

            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Resume context failed: {e}")
            return None

    def handle_session_end(self, data: dict[str, Any]) -> None:
        """Handle SessionEnd event."""
        session_id = data["session_id"]
        reason = data.get("reason", "unknown")

        self.store.end_session(session_id, reason)
        logger.info(f"Session ended: {session_id} ({reason})")

        # Trigger AI summary generation in background
        self._trigger_session_summary(session_id)

        # Trigger compression in a background thread
        # Hooks are synchronous, so we fire-and-forget
        self._trigger_compression(session_id)

    def _trigger_compression(self, session_id: str) -> None:
        """Trigger AI compression for a session in background."""
        import threading

        def _compress() -> None:
            try:
                from mneme.config import load_config
                from mneme.core.compressor import Compressor

                config = load_config()
                if not config["compression"]["enabled"]:
                    return

                # Get observations for this session
                observations = self.store.get_observations_for_session(session_id, limit=100)

                if len(observations) < config["compression"]["min_observations"]:
                    logger.debug(
                        f"Too few observations ({len(observations)}) to compress for {session_id}"
                    )
                    return

                compressor = Compressor()
                # Run async compress synchronously in thread
                import asyncio

                result = asyncio.run(compressor.compress(observations))

                if result:
                    # Store summary
                    obs_ids = [obs["id"] for obs in observations if obs.get("id")]
                    self.store.add_summary(
                        session_id=session_id,
                        content=result["summary"],
                        observation_ids=obs_ids,
                        keywords=result.get("keywords", []),
                    )
                    logger.info(f"Session {session_id} compressed successfully")
                else:
                    logger.debug(f"Compression returned no result for {session_id}")

            except Exception as e:
                logger.error(f"Background compression failed: {e}")

        thread = threading.Thread(target=_compress, daemon=True)
        thread.start()
        logger.debug(f"Compression triggered for session {session_id}")

    def _trigger_session_summary(self, session_id: str) -> None:
        """Trigger AI session summary generation in background."""
        import threading

        def _generate() -> None:
            try:
                from mneme.core.session_summary import SessionSummaryGenerator

                observations = self.store.get_observations_for_session(session_id, limit=None)

                if len(observations) < 3:
                    logger.debug(
                        f"Too few observations ({len(observations)}) to summarize for {session_id}"
                    )
                    return

                generator = SessionSummaryGenerator()
                result = generator.generate(observations)

                if result:
                    self.store.add_session_summary(
                        session_id=session_id,
                        title=result.get("title"),
                        request=result.get("request"),
                        investigated=result.get("investigated"),
                        learned=result.get("learned"),
                        completed=result.get("completed"),
                        next_steps=result.get("next_steps"),
                        files_read=json.dumps(result.get("files_read", [])),
                        files_edited=json.dumps(result.get("files_edited", [])),
                        notes=result.get("notes"),
                        raw_summary=result.get("raw_summary"),
                        model="moonshot",
                    )
                    logger.info(f"Session summary generated for {session_id}")
                else:
                    logger.debug(f"Session summary generation returned no result for {session_id}")

            except Exception as e:
                logger.error(f"Background session summary generation failed: {e}")

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()
        logger.debug(f"Session summary generation triggered for {session_id}")

    def handle_post_tool_use(self, data: dict[str, Any]) -> None:
        """Handle PostToolUse event."""
        self._store_tool_observation(data, success=True)

    def handle_post_tool_use_failure(self, data: dict[str, Any]) -> None:
        """Handle PostToolUseFailure event."""
        self._store_tool_observation(data, success=False)

    def handle_user_prompt_submit(self, data: dict[str, Any]) -> None:
        """Handle UserPromptSubmit event."""
        session_id = data["session_id"]
        prompt = data.get("prompt", "")

        cleaned, should_skip = clean_observation(prompt)
        if should_skip:
            return

        observation = Observation(
            session_id=session_id,
            event_type="UserPromptSubmit",
            prompt=cleaned,
        )

        self.store.add_observation(observation)
        logger.debug(f"User prompt stored for session {session_id}")

    def _store_tool_observation(self, data: dict[str, Any], success: bool) -> None:
        """Store a tool observation."""
        session_id = data["session_id"]
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        # Extract file path
        file_path = extract_file_path(tool_input)

        # Format tool input
        tool_input_str = json.dumps(tool_input, ensure_ascii=False) if tool_input else None

        # Get output or error
        if success:
            tool_output = data.get("tool_output", "")
            error = None

            # Detect and record truncation
            original_size = len(tool_output) if tool_output else 0
            if original_size > 100000:
                cleaned_output = tool_output[:100000] + "\n...[truncated by Kimi CLI]"
            else:
                cleaned_output = tool_output
                original_size = 0

            cleaned_output, should_skip = clean_observation(cleaned_output, file_path)
            if should_skip:
                return
        else:
            tool_output = None
            error = data.get("error", "")
            cleaned_error, should_skip = clean_observation(error, file_path)
            if should_skip:
                return
            cleaned_output = None
            original_size = 0

        observation = Observation(
            session_id=session_id,
            event_type="PostToolUse" if success else "PostToolUseFailure",
            tool_name=tool_name,
            tool_input=tool_input_str,
            tool_output=cleaned_output if success else None,
            error=cleaned_error if not success else None,
            file_path=file_path,
        )

        obs_id = self.store.add_observation(observation)

        # Queue for background AI structuring
        if obs_id:
            self.store.add_pending_message(
                PendingMessage(
                    session_id=session_id,
                    message_type="observation",
                    tool_name=tool_name,
                    tool_input=tool_input_str,
                    tool_response=cleaned_output if success else None,
                    error=cleaned_error if not success else None,
                )
            )

        # Record truncation if applicable
        if success and original_size > 100000 and obs_id:
            self.store.record_truncated_output(
                observation_id=obs_id,
                original_size=original_size,
                truncated_size=100000,
                head_preview=tool_output[:500] if tool_output else None,
                tail_preview=tool_output[-500:] if tool_output else None,
                line_count=tool_output.count("\n") if tool_output else None,
            )
            logger.info(
                f"Truncated output recorded for {tool_name}: {original_size} → 100000 chars"
            )

        logger.debug(
            f"Tool observation stored: {tool_name} ({'success' if success else 'failure'})"
        )

    def handle_pre_compact(self, data: dict[str, Any]) -> None:
        """Handle PreCompact hook event from Kimi CLI.

        Called before context compaction begins.
        Records the token count before compaction.
        """
        session_id = data.get("session_id", "")
        token_count = data.get("token_count")
        trigger = data.get("trigger", "unknown")

        # Store pre-compaction state temporarily (will be updated by PostCompact)
        # We use a simple in-memory cache or pending message approach
        # For simplicity, store as a pending compaction event
        self._pending_compaction = {
            "session_id": session_id,
            "tokens_before": token_count,
            "trigger": trigger,
        }
        logger.info(f"PreCompact: session={session_id}, tokens={token_count}, trigger={trigger}")

    def handle_post_compact(self, data: dict[str, Any]) -> None:
        """Handle PostCompact hook event from Kimi CLI.

        Called after context compaction completes.
        Records the compaction and creates a checkpoint.
        """
        session_id = data.get("session_id", "")
        estimated_token_count = data.get("estimated_token_count")
        trigger = data.get("trigger", "unknown")

        # Get tokens_before from pending state if available
        tokens_before = None
        if (
            hasattr(self, "_pending_compaction")
            and self._pending_compaction.get("session_id") == session_id
        ):
            tokens_before = self._pending_compaction.get("tokens_before")

        # Record the compaction
        self.store.record_compaction(
            session_id=session_id,
            tokens_before=tokens_before,
            tokens_after=estimated_token_count,
        )

        # Get current observations to generate checkpoint summary
        observations = self.store.get_observations_for_session(session_id, limit=50)

        # Extract key decisions from recent prompts
        key_decisions = []
        open_tasks = []
        for obs in observations:
            prompt = obs.get("prompt", "")
            if prompt:
                # Simple heuristic: look for decision/task indicators
                lower = prompt.lower()
                if any(w in lower for w in ["decide", "decision", "choose", "agreed", "concluded"]):
                    key_decisions.append(prompt[:200])
                if any(
                    w in lower for w in ["todo", "fix", "implement", "add", "need to", "should"]
                ):
                    open_tasks.append(prompt[:200])

        # Deduplicate
        key_decisions = list(dict.fromkeys(key_decisions))[:5]
        open_tasks = list(dict.fromkeys(open_tasks))[:5]

        # Create a simple summary from recent observations
        summary_parts = ["Session checkpoint after context compaction."]
        if tokens_before and estimated_token_count:
            summary_parts.append(f"Tokens reduced from {tokens_before} to {estimated_token_count}.")
        summary_parts.append(f"Recent activity: {len(observations)} observations.")

        self.store.add_checkpoint(
            session_id=session_id,
            summary=" ".join(summary_parts),
            key_decisions=key_decisions,
            open_tasks=open_tasks,
            checkpoint_type="compaction",
            token_count=estimated_token_count,
            observation_count=len(observations),
        )

        # Clear pending state
        if hasattr(self, "_pending_compaction"):
            self._pending_compaction = {}

        logger.info(
            f"PostCompact: session={session_id}, estimated_tokens={estimated_token_count}, trigger={trigger}"
        )

    def detect_and_store_patterns(self, session_id: str) -> None:
        """Detect patterns in session observations and store them.

        Called periodically or on session end to extract reusable knowledge.
        """
        import hashlib

        observations = self.store.get_observations_for_session(session_id, limit=100)

        # Group errors by tool/file
        errors_by_tool: dict[str, list[str]] = {}
        for obs in observations:
            if obs.get("error"):
                tool = obs.get("tool_name", "unknown")
                errors_by_tool.setdefault(tool, []).append(obs["error"])

        # Store error patterns
        for tool, errors in errors_by_tool.items():
            if len(errors) >= 2:
                # Hash the error signature
                signature = f"error:{tool}:{errors[0][:100]}"
                pattern_hash = hashlib.sha256(signature.encode()).hexdigest()[:16]

                self.store.add_or_update_pattern(
                    pattern_type="error",
                    pattern_hash=pattern_hash,
                    title=f"Recurring error in {tool}",
                    description=f"Tool '{tool}' failed {len(errors)} times. Latest: {errors[-1][:200]}",
                    session_id=session_id,
                    related_files=list(
                        {
                            obs.get("file_path", "")
                            for obs in observations
                            if obs.get("file_path") and obs.get("error")
                        }
                    ),
                )

        # Detect fix patterns (error followed by success on same file)
        file_events: dict[str, list[dict]] = {}
        for obs in observations:
            fp = obs.get("file_path")
            if fp:
                file_events.setdefault(fp, []).append(obs)

        for fp, events in file_events.items():
            for i in range(1, len(events)):
                prev = events[i - 1]
                curr = events[i]
                if prev.get("error") and not curr.get("error"):
                    signature = f"fix:{fp}:{prev['error'][:100]}"
                    pattern_hash = hashlib.sha256(signature.encode()).hexdigest()[:16]

                    self.store.add_or_update_pattern(
                        pattern_type="fix",
                        pattern_hash=pattern_hash,
                        title=f"Fix pattern for {fp}",
                        description=f"Fixed error in {fp}: {prev['error'][:200]}",
                        session_id=session_id,
                        related_files=[fp],
                    )

        logger.debug(f"Pattern detection completed for session {session_id}")
