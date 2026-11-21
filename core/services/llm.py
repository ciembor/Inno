"""Wspólne budowanie ustrukturyzowanych żądań do Responses API."""

from typing import Any


def request_structured_response(
    client: Any,
    *,
    model: str,
    instructions: str,
    input: str,
    schema_name: str,
    schema: dict[str, Any],
    reasoning: dict[str, str] | None = None,
) -> Any:
    """Wysyła odpowiedź wymuszoną przez JSON Schema bez zapisywania jej u dostawcy."""
    request = {
        "model": model,
        "instructions": instructions,
        "input": input,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }
    if reasoning is not None:
        request["reasoning"] = reasoning
    return client.responses.create(**request)
