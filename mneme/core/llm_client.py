"""Unified LLM client supporting Kimi, Ollama, and OpenAI-compatible APIs."""

from __future__ import annotations

import json
import os
import platform
import socket
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


def _device_model() -> str:
    """Build device model string like 'Windows 11 AMD64'."""
    system = platform.system()
    release = platform.release()
    machine = platform.machine()
    parts = [p for p in (system, release, machine) if p]
    return " ".join(parts) or "unknown"


def _ascii_header_value(value: str, *, fallback: str = "unknown") -> str:
    try:
        value.encode("ascii")
        return value.strip()
    except UnicodeEncodeError:
        sanitized = value.encode("ascii", errors="ignore").decode("ascii").strip()
        return sanitized or fallback


def _get_device_id() -> str:
    """Get or create stable device ID compatible with kimi-cli."""
    device_id_path = Path.home() / ".kimi" / "device_id"
    if device_id_path.exists():
        return device_id_path.read_text(encoding="utf-8").strip()
    device_id = uuid.uuid4().hex
    device_id_path.parent.mkdir(parents=True, exist_ok=True)
    device_id_path.write_text(device_id, encoding="utf-8")
    return device_id


def _kimi_common_headers() -> dict[str, str]:
    """Build headers required by Kimi Code OAuth API."""
    device_name = platform.node() or socket.gethostname()
    device_model = _device_model()
    headers = {
        "X-Msh-Platform": "kimi_cli",
        "X-Msh-Version": "1.0.0",  # Will be overridden if mneme has version
        "X-Msh-Device-Name": device_name,
        "X-Msh-Device-Model": device_model,
        "X-Msh-Os-Version": platform.version(),
        "X-Msh-Device-Id": _get_device_id(),
    }
    return {key: _ascii_header_value(value) for key, value in headers.items()}


@dataclass
class LLMMessage:
    """A single message in the conversation."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str
    model: str | None = None
    usage: dict[str, int] | None = None
    raw: dict[str, Any] | None = None


class BaseLLMClient(ABC):
    """Abstract base for all LLM clients."""

    def __init__(self, model: str, timeout: float = 60.0, **kwargs: Any) -> None:
        self.model = model
        self.timeout = timeout
        self.extra = kwargs

    @abstractmethod
    async def chat(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse | None:
        """Send messages and return response."""
        ...

    def _merge_kwargs(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        """Merge default extra params with call-specific overrides."""
        merged = dict(self.extra)
        if overrides:
            merged.update(overrides)
        return merged


class KimiClient(BaseLLMClient):
    """Kimi API client — supports both OAuth (kimi-cli) and Moonshot API key."""

    # OAuth endpoint for kimi-cli logged-in users
    KIMI_CODE_URL = "https://api.kimi.com/coding/v1/chat/completions"
    # Moonshot Open Platform endpoint (requires API key from platform.moonshot.cn)
    MOONSHOT_URL = "https://api.moonshot.cn/v1/chat/completions"

    def __init__(
        self,
        model: str = "kimi-k2.5",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, timeout=timeout, **kwargs)

        # Priority: 1) explicit api_key 2) MOONSHOT_API_KEY env 3) OAuth token
        self._explicit_key = api_key
        self._moonshot_key = os.getenv("MOONSHOT_API_KEY")
        self._oauth_token = self._load_oauth_token()

        # Determine which credentials to use
        if api_key:
            self.api_key = api_key
            self.base_url = base_url or self.MOONSHOT_URL
            self._auth_mode = "explicit"
        elif self._moonshot_key:
            self.api_key = self._moonshot_key
            self.base_url = base_url or self.MOONSHOT_URL
            self._auth_mode = "moonshot"
        elif self._oauth_token:
            self.api_key = self._oauth_token
            self.base_url = base_url or self.KIMI_CODE_URL
            self._auth_mode = "oauth"
        else:
            self.api_key = None
            self.base_url = base_url or self.MOONSHOT_URL
            self._auth_mode = "none"

    @staticmethod
    def _load_oauth_token() -> str | None:
        """Load OAuth access token from kimi-cli credentials."""
        creds_path = Path.home() / ".kimi" / "credentials" / "kimi-code.json"
        if not creds_path.exists():
            return None
        try:
            data = json.loads(creds_path.read_text())
            return data.get("access_token")
        except Exception:
            return None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def auth_mode(self) -> str:
        return self._auth_mode

    async def chat(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse | None:
        if not self.enabled:
            return None

        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 800),
        }
        payload.update(self._merge_kwargs(kwargs))

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Add OAuth headers only for kimi-code endpoint
        if self._auth_mode == "oauth":
            headers.update(_kimi_common_headers())

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=data.get("model"),
                usage=data.get("usage"),
                raw=data,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403 and self._auth_mode == "oauth":
                logger.warning(
                    "Kimi OAuth token rejected (403). Kimi Code API is only available "
                    "for official Coding Agents. Please set MOONSHOT_API_KEY env var "
                    "or provide an API key from https://platform.moonshot.cn"
                )
            else:
                logger.warning(f"Kimi API error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Kimi API error: {e}")
            return None


class OllamaClient(BaseLLMClient):
    """Ollama local LLM client."""

    DEFAULT_URL = "http://localhost:11434"

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str | None = None,
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, timeout=timeout, **kwargs)
        self.base_url = (base_url or self.DEFAULT_URL).rstrip("/")

    @property
    def enabled(self) -> bool:
        """Check if Ollama server is reachable."""
        try:
            import httpx

            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def chat(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse | None:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.3),
                "num_predict": kwargs.get("max_tokens", 800),
            },
        }
        # Ollama-specific options
        ollama_opts = self._merge_kwargs(kwargs)
        if "options" in ollama_opts:
            payload["options"].update(ollama_opts["options"])

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            return LLMResponse(
                content=data["message"]["content"],
                model=data.get("model"),
                raw=data,
            )
        except Exception as e:
            logger.warning(f"Ollama API error: {e}")
            return None


class OpenAICompatibleClient(BaseLLMClient):
    """Generic OpenAI-compatible API client (vLLM, LM Studio, etc.)."""

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, timeout=timeout, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    async def chat(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse | None:
        if not self.enabled:
            return None

        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 800),
        }
        payload.update(self._merge_kwargs(kwargs))

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=data.get("model"),
                usage=data.get("usage"),
                raw=data,
            )
        except Exception as e:
            logger.warning(f"OpenAI-compatible API error ({self.base_url}): {e}")
            return None


def create_llm_client(
    provider: str,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> BaseLLMClient | None:
    """Factory: create LLM client from config values.

    Args:
        provider: 'kimi', 'ollama', 'openai_compatible'.
        model: Model name (provider-specific default if None).
        base_url: Custom base URL.
        api_key: API key or token.
        **kwargs: Extra provider-specific options.

    Returns:
        Configured client or None if provider unknown.
    """
    provider = provider.lower().strip()

    if provider == "kimi":
        return KimiClient(
            model=model or "kimi-k2.5",
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    if provider == "ollama":
        return OllamaClient(
            model=model or "llama3.2",
            base_url=base_url,
            **kwargs,
        )

    if provider in ("openai_compatible", "openai-compatible", "openai"):
        if not base_url:
            logger.error("openai_compatible provider requires base_url")
            return None
        return OpenAICompatibleClient(
            model=model or "default",
            base_url=base_url,
            api_key=api_key,
            **kwargs,
        )

    logger.error(f"Unknown LLM provider: {provider}")
    return None
