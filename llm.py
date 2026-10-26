import json
import os
import re
import time
from typing import Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from config import NEBIUS_BASE_URL
from telemetry import ExecutionTelemetry

T = TypeVar("T", bound=BaseModel)

class PipelineError(RuntimeError):
    """An error the UI can show to the user as-is."""

_client = None

def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("NEBIUS_API_KEY")
        if not api_key:
            raise PipelineError("NEBIUS_API_KEY isn't set. Add it to .env or your Streamlit secrets.")
        _client = OpenAI(base_url=NEBIUS_BASE_URL, api_key=api_key, max_retries=3, timeout=180)
    return _client

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

def extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may carry reasoning tags or markdown fences."""
    text = _THINK_BLOCK.sub("", text or "").strip()
    fenced = _CODE_FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("No JSON object found in model output")
    return json.loads(text[start:end + 1])

def call_structured(*, model: str, prompt: str, schema: Type[T], telemetry: ExecutionTelemetry,
                    step: str, details: str, temperature: float = 0.0, max_attempts: int = 2) -> T:
    """Call a Token Factory model and validate its reply against a Pydantic schema, retrying with the error on failure."""
    messages = [{"role": "user", "content": prompt}]
    last_error = None
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        response = get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        latency = time.perf_counter() - started
        content = response.choices[0].message.content
        try:
            parsed = schema.model_validate(extract_json(content))
        except (ValueError, ValidationError) as e:
            last_error = e
            telemetry.record_step(f"{step} (rejected)", model, response.usage, latency, f"Schema validation failed: {str(e)[:160]}")
            messages = messages + [
                {"role": "assistant", "content": content or ""},
                {"role": "user", "content": f"That reply failed schema validation:\n{e}\nReply with only the corrected JSON object."},
            ]
            continue
        telemetry.record_step(step, model, response.usage, latency, details)
        return parsed
    raise PipelineError(f"{step}: model output failed schema validation after {max_attempts} attempts. Last error: {last_error}")
