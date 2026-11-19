"""Labelled HTTP fixtures validate protocol behavior; no live inference in unit tests."""

import asyncio
import json

import httpx
import pytest
from kairo_core.models import Final, Message, ModelRequest
from kairo_core.ollama import OllamaModel


def test_ollama_protocol_and_reported_usage() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["stream"] is False
            assert payload["options"]["seed"] == 4 and payload["options"]["temperature"] == 0
            assert "format" in payload
            return httpx.Response(
                200,
                json={
                    "done": True,
                    "message": {"content": '{"kind":"final","text":"fixture result"}'},
                    "prompt_eval_count": 10,
                    "eval_count": 5,
                },
            )

        model = OllamaModel("fixture-model", seed=4, transport=httpx.MockTransport(handler))
        result = await model.generate(
            ModelRequest((Message("system", "s"), Message("user", "u")), 1)
        )
        assert result == Final("fixture result")
        assert model.last_usage == {"prompt_eval_count": 10, "eval_count": 5}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.example.com",
        "http://192.168.1.2:11434",
        "http://user:password@localhost:11434",
        "http://localhost/evil",
    ],
)
def test_remote_provider_denied(endpoint: str) -> None:
    with pytest.raises(ValueError):
        OllamaModel("fixture", endpoint)


def test_invalid_structured_response_not_faked() -> None:
    async def scenario() -> None:
        model = OllamaModel(
            "fixture",
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json={"done": True, "message": {"content": "not JSON"}}
                )
            ),
        )
        with pytest.raises(ValueError):
            await model.generate(ModelRequest((Message("system", "s"), Message("user", "u")), 1))
        assert model.last_usage is None

    asyncio.run(scenario())
