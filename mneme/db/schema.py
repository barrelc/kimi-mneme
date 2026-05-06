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
            error TEXT,
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
    (
        13,
        """
        -- Wire event stream (full Kimi CLI trace)
        CREATE TABLE IF NOT EXISTS wire_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp REAL,
            event_type TEXT NOT NULL,
            step_number INTEGER,
            turn_number INTEGER,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_wire_events_session ON wire_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_wire_events_type ON wire_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_wire_events_timestamp ON wire_events(timestamp);

        -- Session statistics from StatusUpdate
        CREATE TABLE IF NOT EXISTS session_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp REAL,
            context_tokens INTEGER,
            max_context_tokens INTEGER,
            input_cache_read INTEGER,
            input_cache_creation INTEGER,
            input_other INTEGER,
            output_tokens INTEGER,
            message_id TEXT,
            plan_mode INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_session_stats_session ON session_stats(session_id);
        CREATE INDEX IF NOT EXISTS idx_session_stats_timestamp ON session_stats(timestamp);

        -- Agent thinking blocks
        CREATE TABLE IF NOT EXISTS thinking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_number INTEGER,
            step_number INTEGER,
            content TEXT NOT NULL,
            timestamp REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_thinking_session ON thinking(session_id);

        -- Assistant responses
        CREATE TABLE IF NOT EXISTS assistant_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_number INTEGER,
            step_number INTEGER,
            content TEXT NOT NULL,
            timestamp REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_assistant_messages_session ON assistant_messages(session_id);

        -- Session todos from state.json
        CREATE TABLE IF NOT EXISTS session_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_session_todos_session ON session_todos(session_id);
        """,
    ),
    (
        14,
        """
        -- Deduplication: remove duplicate wire_events and add unique constraint
        -- Step 1: Create temp table with deduplicated data
        CREATE TABLE wire_events_dedup AS
        SELECT MIN(id) as id, session_id, timestamp, event_type,
               MAX(step_number) as step_number, MAX(turn_number) as turn_number,
               MAX(payload_json) as payload_json, MIN(created_at) as created_at
        FROM wire_events
        GROUP BY session_id, timestamp, event_type;

        -- Step 2: Drop original and rename
        DROP TABLE wire_events;
        ALTER TABLE wire_events_dedup RENAME TO wire_events;

        -- Step 3: Recreate indexes and constraints
        CREATE INDEX idx_wire_events_session ON wire_events(session_id);
        CREATE INDEX idx_wire_events_type ON wire_events(event_type);
        CREATE INDEX idx_wire_events_timestamp ON wire_events(timestamp);
        CREATE UNIQUE INDEX ux_wire_events_unique ON wire_events(session_id, timestamp, event_type);

        -- Deduplicate session_stats (same timestamp + session should be unique)
        CREATE TABLE session_stats_dedup AS
        SELECT MIN(id) as id, session_id, timestamp, context_tokens, max_context_tokens,
               input_cache_read, input_cache_creation, input_other, output_tokens,
               message_id, plan_mode, MIN(created_at) as created_at
        FROM session_stats
        GROUP BY session_id, timestamp;
        DROP TABLE session_stats;
        ALTER TABLE session_stats_dedup RENAME TO session_stats;
        CREATE INDEX idx_session_stats_session ON session_stats(session_id);
        CREATE INDEX idx_session_stats_timestamp ON session_stats(timestamp);
        """,
    ),
    (
        15,
        """
        -- Structured observations (AI-generated via Kimi API)
        CREATE TABLE IF NOT EXISTS structured_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            type TEXT NOT NULL
                CHECK(type IN ('bugfix', 'feature', 'refactor', 'change', 'discovery', 'decision')),
            title TEXT NOT NULL,
            subtitle TEXT,
            facts TEXT,
            narrative TEXT,
            concepts TEXT,
            files_read TEXT,
            files_modified TEXT,
            content_hash TEXT NOT NULL,
            discovery_tokens INTEGER DEFAULT 0,
            raw_observation_id INTEGER,
            source TEXT DEFAULT 'ai'
                CHECK(source IN ('ai', 'heuristic', 'manual')),
            model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (raw_observation_id) REFERENCES observations(id) ON DELETE SET NULL,
            UNIQUE(session_id, content_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_structured_session ON structured_observations(session_id);
        CREATE INDEX IF NOT EXISTS idx_structured_project ON structured_observations(project);
        CREATE INDEX IF NOT EXISTS idx_structured_type ON structured_observations(type);
        CREATE INDEX IF NOT EXISTS idx_structured_created ON structured_observations(created_at);
        CREATE INDEX IF NOT EXISTS idx_structured_source ON structured_observations(source);

        -- FTS5 на structured_observations
        CREATE VIRTUAL TABLE IF NOT EXISTS structured_observations_fts USING fts5(
            title,
            subtitle,
            narrative,
            facts,
            concepts,
            content='structured_observations',
            content_rowid='id'
        );

        -- Triggers для FTS5 sync
        CREATE TRIGGER IF NOT EXISTS structured_fts_insert
        AFTER INSERT ON structured_observations BEGIN
            INSERT INTO structured_observations_fts(rowid, title, subtitle, narrative, facts, concepts)
            VALUES (new.id, new.title, new.subtitle, new.narrative, new.facts, new.concepts);
        END;

        CREATE TRIGGER IF NOT EXISTS structured_fts_delete
        AFTER DELETE ON structured_observations BEGIN
            INSERT INTO structured_observations_fts(structured_observations_fts, rowid, title, subtitle, narrative, facts, concepts)
            VALUES ('delete', old.id, old.title, old.subtitle, old.narrative, old.facts, old.concepts);
        END;
        """,
    ),
    (
        16,
        """
        -- sqlite-vec virtual tables for semantic search
        -- Note: vec0 tables are created lazily by SQLiteVecStore when extension is loaded
        CREATE TABLE IF NOT EXISTS vec_sync_state (
            table_name TEXT PRIMARY KEY,
            last_synced_id INTEGER DEFAULT 0,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO vec_sync_state (table_name, last_synced_id) VALUES ('structured_observations', 0);
        """,
    ),
    (
        17,
        """
        -- Soft deduplication links (B.2 Dedup v2)
        -- When a structured observation is deduplicated (same content_hash),
        -- instead of silently dropping it, we create a link to the existing observation.
        -- This preserves the relationship between different raw_observation_ids
        -- and allows tracing all observations that produced the same structured insight.
        CREATE TABLE IF NOT EXISTS structured_observation_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            existing_structured_id INTEGER NOT NULL,
            linked_raw_observation_id INTEGER,
            linked_session_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            link_type TEXT NOT NULL DEFAULT 'dedup'
                CHECK(link_type IN ('dedup', 'related', 'similar')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (existing_structured_id) REFERENCES structured_observations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_structured_links_existing ON structured_observation_links(existing_structured_id);
        CREATE INDEX IF NOT EXISTS idx_structured_links_hash ON structured_observation_links(content_hash);
        CREATE INDEX IF NOT EXISTS idx_structured_links_session ON structured_observation_links(linked_session_id);
        """,
    ),
    (
        18,
        """
        -- Knowledge Collections (thematic groupings of observations)
        -- Позволяет создавать тематические подборки structured observations
        -- и экспортировать их в markdown.
        CREATE TABLE IF NOT EXISTS observation_collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            project TEXT,
            query TEXT,              -- FTS query или пусто (ручная подборка)
            types TEXT,              -- JSON ["decision", "bugfix"]
            concepts TEXT,           -- JSON ["architecture"]
            files TEXT,              -- JSON ["src/api/"]
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_collections_project ON observation_collections(project);
        CREATE INDEX IF NOT EXISTS idx_collections_name ON observation_collections(name);

        -- Many-to-many: collections <-> structured_observations
        CREATE TABLE IF NOT EXISTS collection_items (
            collection_id INTEGER NOT NULL,
            structured_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (collection_id) REFERENCES observation_collections(id) ON DELETE CASCADE,
            FOREIGN KEY (structured_id) REFERENCES structured_observations(id) ON DELETE CASCADE,
            UNIQUE(collection_id, structured_id)
        );

        CREATE INDEX IF NOT EXISTS idx_collection_items_collection ON collection_items(collection_id);
        CREATE INDEX IF NOT EXISTS idx_collection_items_structured ON collection_items(structured_id);
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


def get_connection(db_path: str | Path, timeout: float = 30.0) -> sqlite3.Connection:
    """Get a database connection with WAL mode and busy timeout."""
    conn = sqlite3.connect(str(db_path), timeout=timeout, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")  # 30 seconds
    return conn
