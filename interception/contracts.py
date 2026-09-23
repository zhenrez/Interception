"""Explicit V1 protocol subset; unsupported semantics fail before queueing."""

import json

from jsonschema import Draft202012Validator, FormatChecker
from .files import loads


class ContractError(ValueError):
    pass


def check_schema(schema):
    Draft202012Validator.check_schema(schema)

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(child, str) or not child.startswith("#")
                ):
                    raise ContractError("Only local JSON Schema references are supported")
                if key == "$schema" and child not in {
                    "https://json-schema.org/draft/2020-12/schema",
                    "https://json-schema.org/draft/2020-12/schema#",
                }:
                    raise ContractError("Use JSON Schema draft 2020-12")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


def validate_schema(value, schema):
    check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def check_request(body):
    if not isinstance(body, dict):
        raise ContractError("Request must be a JSON object")
    if not isinstance(body.get("model"), str) or not body["model"]:
        raise ContractError("model is required")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise ContractError("messages must be a nonempty list")
    if type(body.get("n", 1)) is not int or body.get("n", 1) != 1:
        raise ContractError("V1 supports n=1 only")
    if not isinstance(body.get("stream", False), bool):
        raise ContractError("stream must be a boolean")
    for name in (
        "audio",
        "modalities",
        "functions",
        "function_call",
        "prediction",
        "web_search_options",
    ):
        if name in body:
            raise ContractError(f"Unsupported V1 field: {name}")
    for message in body["messages"]:
        if not isinstance(message, dict) or message.get("role") not in {
            "system",
            "developer",
            "user",
            "assistant",
            "tool",
        }:
            raise ContractError("Invalid message role")
        content = message.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise ContractError("Message content must be text, content parts, or null")
        if isinstance(content, list):
            for part in content:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "text"
                    or not isinstance(part.get("text"), str)
                ):
                    raise ContractError(
                        "V1 accepts text content parts only; multimodal needs an adapter"
                    )
    fmt = body.get("response_format", {"type": "text"})
    if not isinstance(fmt, dict) or fmt.get("type") not in {"text", "json_object", "json_schema"}:
        raise ContractError("Unsupported response_format")
    if fmt["type"] == "json_schema":
        definition = fmt.get("json_schema")
        if not isinstance(definition, dict) or "schema" not in definition:
            raise ContractError("response_format.json_schema.schema is required")
        check_schema(definition["schema"])
    names = set()
    if not isinstance(body.get("tools", []), list):
        raise ContractError("tools must be a list")
    for tool in body.get("tools", []):
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ContractError("V1 supports function tools only")
        function = tool.get("function", {})
        if not isinstance(function, dict):
            raise ContractError("Tool function must be an object")
        name = function.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ContractError("Tool names must be unique nonempty strings")
        names.add(name)
        check_schema(function.get("parameters", {}))
    choice = body.get("tool_choice", "auto")
    if isinstance(choice, dict):
        if (
            choice.get("type") != "function"
            or not isinstance(choice.get("function"), dict)
            or not isinstance(choice["function"].get("name"), str)
            or choice["function"]["name"] not in names
        ):
            raise ContractError("Named tool_choice must match an offered function")
    elif not isinstance(choice, str) or choice not in {"auto", "none", "required"}:
        raise ContractError("Invalid tool_choice")
    if choice == "required" and not names:
        raise ContractError("tool_choice=required needs tools")


def validate_return(packet, returned):
    if not isinstance(returned, dict) or returned.get("request_id") != packet["request_id"]:
        raise ContractError("RETURN request_id does not match CATCH")
    if returned.get("status") != "COMPLETED":
        raise ContractError("RETURN status must be COMPLETED")
    response = returned.get("response")
    if not isinstance(response, dict) or response.get("role") != "assistant":
        raise ContractError("response.role must be assistant")
    if set(response) - {"role", "content", "tool_calls"}:
        raise ContractError("Unsupported response fields")
    content = response.get("content")
    calls = response.get("tool_calls", [])
    if content is not None and not isinstance(content, str):
        raise ContractError("response.content must be a string or null")
    if not isinstance(calls, list):
        raise ContractError("tool_calls must be a list")
    if content is None and not calls:
        raise ContractError("Response needs content or tool_calls")
    original = packet["original_request"]
    choice = original.get("tool_choice", "auto")
    if choice == "none" and calls:
        raise ContractError("tool_choice=none prohibits calls")
    if (choice == "required" or isinstance(choice, dict)) and not calls:
        raise ContractError("Request requires a tool call")
    if original.get("parallel_tool_calls") is False and len(calls) > 1:
        raise ContractError("Request allows only one tool call")
    offered = {t["function"]["name"]: t["function"] for t in original.get("tools", [])}
    ids = set()
    for call in calls:
        if not isinstance(call, dict) or call.get("type") != "function":
            raise ContractError("Invalid tool call")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id or call_id in ids:
            raise ContractError("Tool call IDs must be unique nonempty strings")
        ids.add(call_id)
        function = call.get("function", {})
        if not isinstance(function, dict):
            raise ContractError("Returned function must be an object")
        name = function.get("name")
        if not isinstance(name, str) or name not in offered:
            raise ContractError("Tool call names an unoffered function")
        if isinstance(choice, dict) and name != choice["function"]["name"]:
            raise ContractError("Tool call does not match tool_choice")
        if not isinstance(function.get("arguments"), str):
            raise ContractError("Tool arguments must be a JSON string")
        arguments = loads(function["arguments"])
        validate_schema(arguments, offered[name].get("parameters", {}))
    fmt = original.get("response_format", {"type": "text"})
    if not calls and fmt["type"] != "text":
        try:
            value = loads(content)
        except (ValueError, TypeError) as exc:
            raise ContractError("Expected JSON in response.content") from exc
        if fmt["type"] == "json_object" and not isinstance(value, dict):
            raise ContractError("Expected a JSON object")
        if fmt["type"] == "json_schema":
            validate_schema(value, fmt["json_schema"]["schema"])
    # Round trip gives us an independent JSON-only object.
    return json.loads(json.dumps(response, allow_nan=False))
