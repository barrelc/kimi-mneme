"""Configuration management for kimi-mneme."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_CONFIG = {
    "db": {
        "path": "~/.kimi/mneme/mneme.db",
        "backup_enabled": True,
        "backup_interval_days": 7,
    },
    "vector": {
        "path": "~/.kimi/mneme/chroma",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "chunk_size": 512,
        "chunk_overlap": 50,
    },
    "llm": {
        # Default LLM provider for all AI features (structuring, compression, etc.)
        # Supported: "kimi", "ollama", "openai_compatible"
        "provider": "kimi",
        "model": "kimi-k2.5",
        # For Ollama: "http://localhost:11434"
        # For openai_compatible: e.g. "http://localhost:8000/v1"
        "base_url": None,
        "api_key": None,  # For Kimi or OpenAI-compatible APIs
        "timeout": 60.0,
        # Provider-specific extra options (passed to the client)
        "options": {},
    },
    "compression": {
        "enabled": True,
        # Override llm.provider if you want different LLM for compression
        "provider": None,  # null = use llm.provider
        "model": None,  # null = use llm.model
        "batch_size": 10,
        "min_observations": 5,
        "trigger": "session_end",
    },
    "structuring": {
        "enabled": True,
        # Override llm.provider if you want different LLM for structuring
        "provider": None,  # null = use llm.provider
        "model": None,  # null = use llm.model
        "fallback_to_heuristic": True,
        "heuristic_threshold_chars": 300,
        "batch_size": 5,
        "worker_interval_seconds": 5,
        "max_retry_count": 3,
    },
    "injection": {
        "enabled": True,
        "max_tokens": 1500,
        "min_relevance": 0.7,
        "max_results": 2,
        "recency_boost_days": 7,
        "format": "markdown",
        "use_vector": False,
    },
    "server": {
        "enabled": True,
        "auto_start": True,
        "host": "127.0.0.1",
        "port": 37777,
        "cors_origins": ["http://localhost:37777", "http://127.0.0.1:37777"],
        # Event loop: "auto" | "asyncio" | "winloop" (Windows only)
        "loop": "auto",
    },
    "mcp": {
        "enabled": True,
        "auto_start": False,  # Set to True to start MCP with FastAPI
        "transport": "stdio",  # "stdio" | "sse"
        "port": 37778,
    },
    "privacy": {
        "exclude_tags": ["<private>", "<secret>"],
        "exclude_patterns": [
            "*.env*",
            "*.env.local",
            "*secret*",
            "*password*",
            "*token*",
            "*api_key*",
            "*private_key*",
        ],
        "max_content_length": 100000,
    },
    "hooks": {
        "fire_and_forget": True,
        "timeout_seconds": 30,
        "batch_writes": True,
        "batch_interval_seconds": 5,
    },
    "logging": {
        "level": "INFO",
        "file": "~/.kimi/mneme/mneme.log",
        "max_size_mb": 10,
        "backup_count": 5,
    },
}


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} and ~ in config values."""
    if isinstance(value, str):
        # Expand environment variables
        result = os.path.expandvars(value)
        # Expand user home
        result = os.path.expanduser(result)
        return result
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def get_config_path() -> Path:
    """Return the path to the config file."""
    return Path.home() / ".kimi" / "mneme" / "config.json"


def _find_project_config() -> dict[str, Any] | None:
    """Find .mneme.json in current directory or git root."""
    cwd = Path.cwd()

    # Check current directory and parents
    for path in [cwd, *cwd.parents]:
        config_file = path / ".mneme.json"
        if config_file.exists():
            try:
                with open(config_file, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load project config from {config_file}: {e}")
                return None

    return None


def load_config() -> dict[str, Any]:
    """Load configuration from file with defaults."""
    config = DEFAULT_CONFIG.copy()
    config_path = get_config_path()

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                user_config = json.load(f)
            _deep_update(config, user_config)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")

    # Apply per-project config
    project_config = _find_project_config()
    if project_config:
        _deep_update(config, project_config)
        logger.debug("Applied project-level .mneme.json config")

    # Apply environment variable overrides
    config = _apply_env_overrides(config)

    # Expand paths and env vars
    config = _expand_env_vars(config)

    return config


def _deep_update(base: dict[str, Any], update: dict[str, Any]) -> None:
    """Recursively update nested dictionaries."""
    for key, value in update.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Override config values from environment variables."""
    env_map = {
        "MNEME_DB_PATH": ("db", "path"),
        "MNEME_CHROMA_PATH": ("vector", "path"),
        "MNEME_SERVER_PORT": ("server", "port"),
        "MNEME_SERVER_HOST": ("server", "host"),
        "MNEME_LOG_LEVEL": ("logging", "level"),
        "MNEME_STRUCTURING_ENABLED": ("structuring", "enabled"),
        "MNEME_LLM_PROVIDER": ("llm", "provider"),
        "MNEME_LLM_MODEL": ("llm", "model"),
        "MNEME_LLM_BASE_URL": ("llm", "base_url"),
        "MNEME_LLM_API_KEY": ("llm", "api_key"),
    }

    for env_var, (section, key) in env_map.items():
        if env_var in os.environ:
            if section not in config:
                config[section] = {}
            config[section][key] = os.environ[env_var]

    return config


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Don't save internal keys
    clean = {k: v for k, v in config.items() if not k.startswith("_")}

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)

    logger.info(f"Config saved to {config_path}")


def ensure_dirs(config: dict[str, Any]) -> None:
    """Ensure all configured directories exist."""
    paths = [
        config["db"]["path"],
        config["vector"]["path"],
        config["logging"]["file"],
    ]
    for path_str in paths:
        path = Path(path_str)
        if path.suffix:  # It's a file path
            path.parent.mkdir(parents=True, exist_ok=True)
        else:  # It's a directory path
            path.mkdir(parents=True, exist_ok=True)
