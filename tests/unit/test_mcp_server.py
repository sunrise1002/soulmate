"""Exercise the MCP stdio protocol without a daemon or network."""

import io
import json
from collections.abc import Mapping

from soulmate_mcp.server import McpServer, resolve_tool_request, run_stdio


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def call(self, tool_name: str, arguments: Mapping[str, object]) -> object:
        self.calls.append((tool_name, arguments))
        return {"predicted_choice": "Quiet laptop", "model_snapshot_version": 4}


def test_mcp_lists_the_scoped_intelligence_and_delegation_tools() -> None:
    server = McpServer(FakeBackend())

    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    tools = result["tools"]
    assert isinstance(tools, list)
    assert {item["name"] for item in tools} == {
        "predict_choice",
        "rank_options",
        "get_preference_summary",
        "find_similar_decisions",
        "record_decision",
        "record_outcome",
        "request_delegation",
        "get_delegation",
        "complete_delegation",
    }


def test_mcp_tool_call_returns_privacy_minimal_daemon_result() -> None:
    backend = FakeBackend()
    server = McpServer(backend)

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {"name": "predict_choice", "arguments": {"domain": "shopping"}},
        }
    )

    assert backend.calls == [("predict_choice", {"domain": "shopping"})]
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    assert result["isError"] is False
    content = result["content"]
    assert isinstance(content, list)
    assert json.loads(content[0]["text"])["predicted_choice"] == "Quiet laptop"


def test_delegation_tool_routes_encode_identifiers_without_forwarding_them() -> None:
    method, path, body = resolve_tool_request("complete_delegation", {"request_id": "delegation/1"})

    assert method == "POST"
    assert path == "/v1/external/delegation-requests/delegation%2F1/complete"
    assert body == {}


def test_stdio_handles_initialize_notifications_and_parse_errors() -> None:
    input_stream = io.StringIO(
        "\n".join(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18"},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                "not-json",
            )
        )
    )
    output_stream = io.StringIO()

    run_stdio(McpServer(FakeBackend()), input_stream, output_stream)

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert responses[1]["error"]["code"] == -32700
