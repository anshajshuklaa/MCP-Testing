"""One function to call an LLM, so the rest of the harness doesn't care which.

Uses litellm, so the model name picks the provider, for example:
    gemini/gemini-2.5-flash        (GEMINI_API_KEY)
    anthropic/claude-sonnet-4-5    (ANTHROPIC_API_KEY)
    openai/gpt-4.1-mini            (OPENAI_API_KEY)
    ollama/qwen2.5-coder:7b        (local Ollama)
Set the model with --model or the AITEST_MODEL environment variable.

Any OpenAI-compatible endpoint works too, via AITEST_API_BASE and
AITEST_API_KEY. For example, Hugging Face Inference Providers:
    AITEST_API_BASE=https://router.huggingface.co/v1
    AITEST_API_KEY=$HF_TOKEN
    --model openai/Qwen/Qwen3-Coder-480B-A35B-Instruct
"""

import os
import time
from typing import Callable, Protocol

DEFAULT_MODEL = "gemini/gemini-2.5-flash"


class Complete(Protocol):
    def __call__(self, system: str, user: str) -> str: ...


def litellm_complete(model: str | None = None, temperature: float = 0.2, retries: int = 3) -> Complete:
    model = model or os.environ.get("AITEST_MODEL") or DEFAULT_MODEL

    def complete(system: str, user: str) -> str:
        import litellm  # imported lazily so tests and evaluation don't need it

        # Providers return transient 5xx and gateway timeouts on long generations.
        transient = (litellm.exceptions.InternalServerError, litellm.exceptions.Timeout,
                     litellm.exceptions.ServiceUnavailableError, litellm.exceptions.APIConnectionError)
        for attempt in range(retries + 1):
            try:
                return _call(litellm, system, user)
            except transient:
                if attempt == retries:
                    raise
                time.sleep(5 * 2**attempt)
        raise AssertionError("unreachable")

    def _call(litellm, system: str, user: str) -> str:
        response = litellm.completion(
            model=model,
            api_base=os.environ.get("AITEST_API_BASE") or None,
            api_key=os.environ.get("AITEST_API_KEY") or None,
            temperature=temperature,
            timeout=600,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        text = response.choices[0].message.content
        if not text:
            raise RuntimeError(f"{model} returned an empty response")
        return text

    complete.model = model  # type: ignore[attr-defined]
    return complete


def fixed_responses(*responses: str) -> Callable[[str, str], str]:
    """A fake LLM that returns ``responses`` in order. For tests and dry runs."""
    queue = list(responses)
    prompts: list[tuple[str, str]] = []

    def complete(system: str, user: str) -> str:
        prompts.append((system, user))
        if not queue:
            raise RuntimeError("fixed_responses ran out of responses")
        return queue.pop(0)

    complete.prompts = prompts  # type: ignore[attr-defined]
    return complete
