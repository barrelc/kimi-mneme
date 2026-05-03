"""SQLite database schema and initialization with migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Migration system
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        -- Base schema (v1)
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            cwd TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            summary TEXT,
            token_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            tool_name TEXT,
            tool_input TEXT,
            tool_output TEXT,
            error TEXT,
            file_path TEXT,
            prompt TEXT,
            agent_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            observation_ids TEXT,
            content TEXT NOT NULL,
            keywords TEXT,
            embedding_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
            tool_name,
            tool_input,
            tool_output,
            error,
            file_path,
            prompt,
            content='observations',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS observations_fts_insert
        AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, tool_name, tool_input, tool_output, error, file_path, prompt)
            VALUES (new.id, new.tool_name, new.tool_input, new.tool_output, new.error, new.file_path, new.prompt);
        END;

        CREATE TRIGGER IF NOT EXISTS observations_fts_delete
        AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, tool_name, tool_input, tool_output, error, file_path, prompt)
            VALUES ('delete', old.id, old.tool_name, old.tool_input, old.tool_output, old.error, old.file_path, old.prompt);
        END;

        CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(session_id);
        CREATE INDEX IF NOT EXISTS idx_observations_event_type ON observations(event_type);
        CREATE INDEX IF NOT EXISTS idx_observations_tool_name ON observations(tool_name);
        CREATE INDEX IF NOT EXISTS idx_observations_file_path ON observations(file_path);
        CREATE INDEX IF NOT EXISTS idx_observations_created_at ON observations(created_at);
        CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id);
        """,
    ),
    (
        2,
        """
        -- Schema versions tracking
        CREATE TABLE IF NOT EXISTS schema_versions (
            id INTEGER PRIMARY KEY,
            version INTEGER UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
    (
        3,
        """
        -- User prompts history (per-prompt history for UI + search)
        CREATE TABLE IF NOT EXISTS user_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            prompt_number INTEGER NOT NULL,
            prompt_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_user_prompts_session ON user_prompts(session_id);
        CREATE INDEX IF NOT EXISTS idx_user_prompts_created ON user_prompts(created_at);
        CREATE INDEX IF NOT EXISTS idx_user_prompts_lookup ON user_prompts(session_id, prompt_number);
        """,
    ),
    (
        4,
        """
        -- Pending messages queue (persistent work queue)
        CREATE TABLE IF NOT EXISTS pending_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            tool_use_id TEXT,
            message_type TEXT NOT NULL
                CHECK(message_type IN ('observation', 'summarize', 'compress')),
            tool_name TEXT,
            tool_input TEXT,
            tool_response TEXT,
            cwd TEXT,
            last_user_message TEXT,
            last_assistant_message TEXT,
            prompt_number INTEGER,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'processing', 'processed', 'failed')),
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            failed_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pending_messages_session ON pending_messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_pending_messages_status ON pending_messages(status);
        CREATE INDEX IF NOT EXISTS idx_pending_messages_created ON pending_messages(created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_session_tool
            ON pending_messages(session_id, tool_use_id)
            WHERE tool_use_id IS NOT NULL;
        """,
    ),
    (
        5,
        """
        -- Observation feedback (usage-signal tracking for tier routing)
        CREATE TABLE IF NOT EXISTS observation_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            session_id TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_observation ON observation_feedback(observation_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_signal ON observation_feedback(signal_type);
        """,
    ),
    (
        6,
        """
        -- Add content_hash and discovery_tokens to observations for dedup and ranking
        ALTER TABLE observations ADD COLUMN content_hash TEXT;
        ALTER TABLE observations ADD COLUMN discovery_tokens INTEGER DEFAULT 0;
        CREATE INDEX IF NOT EXISTS idx_observations_content_hash ON observations(content_hash, created_at);
        """,
    ),
    (
        7,
        """
        -- Add project column to sessions for better project tracking
        ALTER TABLE sessions ADD COLUMN project TEXT;
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
        """,
    ),
    (
        8,
        """
        -- Session checkpoints for resume after compaction/crash
        CREATE TABLE IF NOT EXISTS session_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            checkpoint_number INTEGER NOT NULL DEFAULT 1,
            checkpoint_type TEXT NOT NULL DEFAULT 'auto'
                CHECK(checkpoint_type IN ('auto', 'manual', 'compaction', 'crash')),
            summary TEXT NOT NULL,
            key_decisions TEXT,
            open_tasks TEXT,
            token_count INTEGER,
            observation_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON session_checkpoints(session_id);
        CREATE INDEX IF NOT EXISTS idx_checkpoints_number ON session_checkpoints(session_id, checkpoint_number);
        CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON session_checkpoints(created_at);
        """,
    ),
    (
        9,
        """
        -- Compaction events tracking (when Kimi CLI compacts context)
        CREATE TABLE IF NOT EXISTS compaction_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            compacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tokens_before INTEGER,
            tokens_after INTEGER,
            observations_dropped INTEGER,
            summary_generated TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_compaction_session ON compaction_events(session_id);
        """,
    ),
    (
        10,
        """
        -- Cross-session patterns (recurring errors, fixes, decisions)
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL
                CHECK(pattern_type IN ('error', 'fix', 'decision', 'preference', 'architecture')),
            pattern_hash TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            first_seen_session_id TEXT,
            last_seen_session_id TEXT,
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            related_files TEXT,
            related_observation_ids TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(pattern_type);
        CREATE INDEX IF NOT EXISTS idx_patterns_hash ON patterns(pattern_hash);
        CREATE INDEX IF NOT EXISTS idx_patterns_updated ON patterns(updated_at);
        """,
    ),
    (
        11,
        """
        -- Truncated tool outputs (store summary when output > 100K)
        CREATE TABLE IF NOT EXISTS truncated_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            original_size INTEGER NOT NULL,
            truncated_size INTEGER NOT NULL,
            summary TEXT,
            head_preview TEXT,
            tail_preview TEXT,
            line_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_truncated_observation ON truncated_outputs(observation_id);
        """,
    ),
    (
        12,
        """
        -- AI-generated session summaries (structured output)
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            title TEXT,
            request TEXT,
            investigated TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            files_read TEXT,
            files_edited TEXT,
            notes TEXT,
            raw_summary TEXT,
            model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_session_summaries_session ON session_summaries(session_id);
        CREATE INDEX IF NOT EXISTS idx_session_summaries_created ON session_summaries(created_at);
        """,
    ),
]


def _get_current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version from database."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()
        return row[0] or 0
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return 0


def _run_migration(conn: sqlite3.Connection, version: int, sql: str) -> None:
    """Run a single migration."""
    logger.info(f"Running migration {version}...")
    conn.executescript(sql)
    # Ensure schema_versions table exists before inserting
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            id INTEGER PRIMARY KEY,
            version INTEGER UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    conn.execute(
        "INSERT OR REPLACE INTO schema_versions (id, version, applied_at) "
        "VALUES ((SELECT id FROM schema_versions WHERE version = ?), ?, CURRENT_TIMESTAMP)",
        (version, version),
    )
    logger.info(f"Migration {version} applied")


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Initialize the database with schema and run pending migrations."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    with conn:
        # Get current version
        current_version = _get_current_version(conn)
        logger.info(f"Current schema version: {current_version}")

        # Run pending migrations
        for version, sql in MIGRATIONS:
            if version > current_version:
                _run_migration(conn, version, sql)

    logger.info(f"Database initialized at {db_path}")
    return conn


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Get a database connection."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
