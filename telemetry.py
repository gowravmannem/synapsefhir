import time
from typing import Any, Dict, List
from config import MODEL_PRICING, MODEL_REASONING

def token_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price = MODEL_PRICING.get(model)
    if not price:
        return 0.0
    return (prompt_tokens * price["input"] + completion_tokens * price["output"]) / 1_000_000

class ExecutionTelemetry:
    """Per-step token, cost and latency accounting for one pipeline run."""
    def __init__(self):
        self.start_time = time.time()
        self.step_logs: List[Dict[str, Any]] = []

    def record_step(self, step_name: str, model: str, usage: Any, latency_sec: float, details: str):
        p_tokens = (getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        c_tokens = (getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        self.step_logs.append({
            "step": step_name,
            "model": model,
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "tokens": p_tokens + c_tokens,
            "latency_sec": round(latency_sec, 3),
            "tokens_per_sec": round(c_tokens / latency_sec, 1) if c_tokens and latency_sec else None,
            "cost_usd": token_cost(model, p_tokens, c_tokens),
            # The same tokens priced at Ultra rates: what a single-model design would pay for this work
            "ultra_only_cost_usd": token_cost(MODEL_REASONING, p_tokens, c_tokens) if model in MODEL_PRICING else 0.0,
            "details": details,
        })

    @property
    def prompt_tokens(self) -> int:
        return sum(s["prompt_tokens"] for s in self.step_logs)

    @property
    def completion_tokens(self) -> int:
        return sum(s["completion_tokens"] for s in self.step_logs)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def total_cost(self) -> float:
        return sum(s["cost_usd"] for s in self.step_logs)

    @property
    def ultra_only_cost(self) -> float:
        return sum(s["ultra_only_cost_usd"] for s in self.step_logs)

    @property
    def savings_pct(self) -> float:
        return 100 * (1 - self.total_cost / self.ultra_only_cost) if self.ultra_only_cost else 0.0

    @property
    def total_latency(self) -> float:
        return sum(s["latency_sec"] for s in self.step_logs)
