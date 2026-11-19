"""Opt-in loopback Ollama JSON adapter. Never downloads models or calls cloud APIs."""

import json
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

import httpx
from pydantic import TypeAdapter

from kairo_core.models import ModelRequest, ModelResponse, require_text
from kairo_core.orchestration.spec import ScriptStep

RESPONSE = TypeAdapter(ScriptStep)


@dataclass
class OllamaModel:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    seed: int = 0
    num_ctx: int = 8192
    num_predict: int = 1024
    transport: httpx.AsyncBaseTransport | None = None  # Explicit HTTP fixture injection in tests.
    last_usage: dict[str, int] | None = None

    def __post_init__(self) -> None:
        require_text(self.model, "model")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Ollama endpoint must be plain loopback HTTP")
        if not 1024 <= self.num_ctx <= 32768 or not 1 <= self.num_predict <= 4096:
            raise ValueError("Invalid local inference limits")

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.last_usage = None
        messages = [asdict(m) for m in request.messages]
        # Use one structured response protocol rather than provider-native tool calls.
        for message in messages:
            if message["role"] == "tool":
                message["role"] = "user"
                message["content"] = "Tool result data: " + message["content"]
        messages[0]["content"] += (
            '\nReturn only JSON: {"kind":"tool","name":"...","arguments_json":"JSON string"}, '
            '{"kind":"continue","text":"..."}, or {"kind":"final","text":"..."}. '
            "Never claim an operation occurred without tool evidence. Available tool schemas: "
            + request.tool_schemas_json
        )
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": RESPONSE.json_schema(),
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120,
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 1048576:
                        raise ValueError("Ollama response exceeds 1 MiB")
        parsed = json.loads(data)
        if parsed.get("done") is not True:
            raise ValueError("Incomplete Ollama response")
        result = RESPONSE.validate_json(parsed["message"]["content"]).response()
        counts = {
            key: parsed[key]
            for key in ("prompt_eval_count", "eval_count")
            if type(parsed.get(key)) is int and parsed[key] >= 0
        }
        self.last_usage = counts or None
        return result
