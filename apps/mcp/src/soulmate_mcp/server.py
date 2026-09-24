"""Dependency-light MCP stdio server backed by scoped Soulmate REST endpoints."""

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TextIO
from urllib.parse import quote

import httpx

from soulmate_mcp import __version__

DEFAULT_BASE_URL = "http://127.0.0.1:7432"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

DECISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["domain", "question", "options"],
    "properties": {
        "domain": {"type": "string", "minLength": 1},
        "question": {"type": "string", "minLength": 1},
        "context": {"type": "object", "default": {}},
        "options": {
            "type": "array",
            "minItems": 2,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "description", "features"],
                "properties": {
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string", "minLength": 1},
                    "features": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": {
                            "type": "number",
                            "minimum": -1,
                            "maximum": 1,
                        },
                    },
                },
            },
        },
    },
}

DELEGATION_REQUEST_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision_id", "action_type", "action_label", "external_request_id"],
    "properties": {
        "decision_id": {"type": "string", "minLength": 1},
        "action_type": {"type": "string", "minLength": 1},
        "action_label": {"type": "string", "minLength": 1},
        "external_request_id": {"type": "string", "minLength": 1},
    },
}

DELEGATION_ID_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["request_id"],
    "properties": {"request_id": {"type": "string", "minLength": 1}},
}

TOOLS: tuple[dict[str, object], ...] = (
    {
        "name": "predict_choice",
        "description": (
            "Predict the option the owner would most likely choose from structured features. "
            "Returns a privacy-minimal prediction, not raw evidence or memories."
        ),
        "inputSchema": DECISION_SCHEMA,
    },
    {
        "name": "rank_options",
        "description": (
            "Rank structured options by the owner's learned behavioral preferences without "
            "exposing the underlying personal database."
        ),
        "inputSchema": DECISION_SCHEMA,
    },
    {
        "name": "get_preference_summary",
        "description": (
            "Return derived preference values, confidence, uncertainty, and context. Raw "
            "evidence and memories are never returned."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "find_similar_decisions",
        "description": (
            "Find comparable resolved decisions by privacy-minimal identifier, domain, and score."
        ),
        "inputSchema": DECISION_SCHEMA,
    },
    {
        "name": "record_decision",
        "description": "Record a structured decision for later prediction and outcome tracking.",
        "inputSchema": DECISION_SCHEMA,
    },
    {
        "name": "record_outcome",
        "description": (
            "Report the owner's satisfaction and regret for a resolved decision. The report "
            "is stored as an unconfirmed observation until the owner confirms it."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["decision_id", "satisfaction", "regret"],
            "properties": {
                "decision_id": {"type": "string", "minLength": 1},
                "satisfaction": {"type": "number", "minimum": 0, "maximum": 1},
                "regret": {"type": "boolean"},
                "notes": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "request_delegation",
        "description": (
            "Ask the owner-controlled Policy Engine whether a predicted action may proceed. "
            "The result may be approved automatically or left pending owner confirmation."
        ),
        "inputSchema": DELEGATION_REQUEST_SCHEMA,
    },
    {
        "name": "get_delegation",
        "description": "Check the current approval state of this agent's delegation request.",
        "inputSchema": DELEGATION_ID_SCHEMA,
    },
    {
        "name": "complete_delegation",
        "description": "Mark an approved delegated action as completed exactly once.",
        "inputSchema": DELEGATION_ID_SCHEMA,
    },
)

TOOL_ROUTES = {
    "predict_choice": ("POST", "/v1/external/predict-choice"),
    "rank_options": ("POST", "/v1/external/rank-options"),
    "get_preference_summary": ("GET", "/v1/external/preference-summary"),
    "find_similar_decisions": ("POST", "/v1/external/find-similar-decisions"),
    "record_decision": ("POST", "/v1/external/record-decision"),
    "record_outcome": ("POST", "/v1/external/record-outcome"),
    "request_delegation": ("POST", "/v1/external/delegation-requests"),
    "get_delegation": ("GET", "/v1/external/delegation-requests/{request_id}"),
    "complete_delegation": (
        "POST",
        "/v1/external/delegation-requests/{request_id}/complete",
    ),
}


class McpProtocolError(Exception):
    """A JSON-RPC request cannot be handled safely."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class ToolBackend(Protocol):
    def call(self, tool_name: str, arguments: Mapping[str, object]) -> object: ...


def resolve_tool_request(
    tool_name: str, arguments: Mapping[str, object]
) -> tuple[str, str, dict[str, object]]:
    route = TOOL_ROUTES.get(tool_name)
    if route is None:
        raise McpProtocolError(-32602, f"Unknown tool: {tool_name}")
    method, path = route
    request_body = dict(arguments)
    if "{request_id}" in path:
        request_id = request_body.pop("request_id", None)
        if not isinstance(request_id, str) or not request_id:
            raise McpProtocolError(-32602, "A delegation request ID is required.")
        path = path.format(request_id=quote(request_id, safe=""))
    return method, path, request_body


@dataclass(slots=True)
class SoulmateApiClient:
    base_url: str
    api_key: str
    timeout: float = 30.0

    def call(self, tool_name: str, arguments: Mapping[str, object]) -> object:
        method, path, request_body = resolve_tool_request(tool_name, arguments)
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        with httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout) as client:
            response = client.request(
                method,
                path,
                json=request_body if method != "GET" and request_body else None,
            )
        try:
            payload: object = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Soulmate returned a non-JSON response.") from exc
        if not response.is_success:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            message = (
                detail
                if isinstance(detail, str)
                else f"Soulmate returned HTTP {response.status_code}."
            )
            raise RuntimeError(message)
        return payload


class McpServer:
    """Small MCP JSON-RPC dispatcher for newline-delimited stdio transport."""

    def __init__(self, api: ToolBackend) -> None:
        self._api = api

    def handle(self, message: Mapping[str, Any]) -> dict[str, object] | None:
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                params = message.get("params")
                requested = params.get("protocolVersion") if isinstance(params, dict) else None
                protocol_version = (
                    requested if isinstance(requested, str) else DEFAULT_PROTOCOL_VERSION
                )
                return self._result(
                    request_id,
                    {
                        "protocolVersion": protocol_version,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "soulmate", "version": __version__},
                    },
                )
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": list(TOOLS)})
            if method == "tools/call":
                return self._call_tool(request_id, message.get("params"))
            raise McpProtocolError(-32601, "Method not found")
        except McpProtocolError as exc:
            return self._error(request_id, exc.code, str(exc))

    def _call_tool(self, request_id: object, params: object) -> dict[str, object]:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise McpProtocolError(-32602, "Tool call parameters are invalid.")
        name = params["name"]
        raw_arguments = params.get("arguments", {})
        if not isinstance(raw_arguments, dict):
            raise McpProtocolError(-32602, "Tool arguments must be an object.")
        try:
            result = self._api.call(name, raw_arguments)
        except (httpx.HTTPError, RuntimeError) as exc:
            return self._result(
                request_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        return self._result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                        ),
                    }
                ],
                "isError": False,
            },
        )

    @staticmethod
    def _result(request_id: object, result: object) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: object, code: int, message: str) -> dict[str, object]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def run_stdio(server: McpServer, input_stream: TextIO, output_stream: TextIO) -> None:
    """Serve MCP messages until the client closes stdin."""
    for line in input_stream:
        response: dict[str, object] | None
        try:
            parsed: object = json.loads(line)
            if not isinstance(parsed, dict):
                response = McpServer._error(None, -32600, "Invalid Request")
            else:
                response = server.handle(parsed)
        except json.JSONDecodeError:
            response = McpServer._error(None, -32700, "Parse error")
        if response is not None:
            output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
            output_stream.flush()


def main() -> None:
    api_key = os.environ.get("SOULMATE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("SOULMATE_API_KEY is required.")
    base_url = os.environ.get("SOULMATE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    run_stdio(McpServer(SoulmateApiClient(base_url, api_key)), sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
