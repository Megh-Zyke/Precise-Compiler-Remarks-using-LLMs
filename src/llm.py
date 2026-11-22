"""LLM wrapper: prompt in, text out. Every raw response is saved (T0.3).

Uses the Anthropic SDK. Needs ANTHROPIC_API_KEY in the environment (.env).
Swap this file if you choose another provider; keep the same two functions.
"""
import json
import re
from datetime import datetime, timezone

from . import config

CODE_RE = re.compile(r"```(?:c|cpp|C)?[ \t]*\n(.*?)```", re.DOTALL)


def extract_code(text):
    """First fenced code block in the response, or None."""
    found = CODE_RE.findall(text)
    return found[0].strip() if found else None


def call_llm(prompt, temperature=None, tag="call"):
    import anthropic  # imported here so the rest of the repo works without it
    client = anthropic.Anthropic()
    temp = config.TEMPERATURE if temperature is None else temperature
    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=config.MAX_TOKENS,
        temperature=temp,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "tag": tag, "model": config.MODEL, "temperature": temp,
        "prompt": prompt, "response": text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    (config.RAW_DIR / f"{stamp}_{tag}.json").write_text(json.dumps(record, indent=2))
    return {"text": text, "code": extract_code(text),
            "input_tokens": record["input_tokens"],
            "output_tokens": record["output_tokens"]}


if __name__ == "__main__":
    out = call_llm("Reply with a C code block containing: int main(void){return 0;}",
                   tag="smoke")
    print(out["code"])
    print(out["input_tokens"], out["output_tokens"])
