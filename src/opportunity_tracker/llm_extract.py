"""Shared helper for forced structured-JSON extraction via Groq's OpenAI-compatible
tool-calling API. Used by extractor/run.py and digger/run.py, both of which need to force
a single named tool call matching a JSON schema and get back its parsed arguments -- the
same job Anthropic's `tool_choice={"type": "tool", "name": ...}` did before the 2026-08-23
provider swap (see the web-UI design spec's decision log)."""
from __future__ import annotations

import json

from groq import Groq

# openai/gpt-oss-120b is Groq's current large tool-calling-capable model. NOTE: an
# earlier choice here (llama-3.3-70b-versatile, based on Groq's own docs at swap time)
# turned out to be already retired from Groq's actual model lineup -- confirmed via
# client.models.list() directly, not docs, after every real extraction call failed
# with a 404 model_not_found. Verified this one actually works with forced tool
# calling by a live call before committing to it, 2026-08-23. Groq's model lineup
# changes -- if this ever starts 404ing, call client.models.list() to see what is
# REALLY available before guessing a replacement from documentation.
_MODEL = "openai/gpt-oss-120b"
_MAX_TOKENS = 4096


def call_tool_forced(
    prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    api_key: str,
) -> dict | None:
    """Force the model to call `tool_name` exactly once, with arguments matching
    `input_schema`. Returns the parsed arguments dict, or None if the response did not
    contain a well-formed call to the named tool (no matching tool_call, or its
    arguments could not be parsed as JSON) -- mirroring the "unparseable response"
    half of the Anthropic tool-use contract this replaces.

    Raises on a genuine API-level failure (network, auth, rate limit) -- callers are
    responsible for catching that themselves, exactly as they were responsible for
    catching `anthropic.Anthropic(...).messages.create(...)` raising before the swap.
    """
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": input_schema,
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        function = getattr(call, "function", None)
        if function is None or getattr(function, "name", None) != tool_name:
            continue
        try:
            arguments = json.loads(function.arguments)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(arguments, dict):
            continue
        return arguments

    return None
