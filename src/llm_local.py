"""Send prompts to local Qwen through Ollama; raw logging is opt-in.

Standard library only. Importing or executing this module never starts inference.
The experiment runner supplies prompts; this module does not choose a dataset,
construct experiments, compile C, or evaluate generated code.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from . import config

CODE_RE = re.compile(r"```(?:c\+\+|cpp|c)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text):
    """Return the first C/C++ or unlabelled fenced code block, if present."""
    match = CODE_RE.search(text)
    return match.group(1).strip() if match else None


def _request_json(path, payload=None):
    base_url = config.OLLAMA_URL.rstrip("/")
    if "://" not in base_url:
        base_url = "http://" + base_url
    request = Request(
        base_url + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        # Do not send local inference requests through a configured HTTP proxy.
        with build_opener(ProxyHandler({})).open(
            request, timeout=config.LOCAL_TIMEOUT
        ) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Cannot complete the Ollama request at {base_url}: {exc}. "
            "Start it with: powershell -ExecutionPolicy Bypass "
            "-File scripts/start_local_llm.ps1"
        ) from exc
    if result.get("error"):
        raise RuntimeError(f"Ollama: {result['error']}")
    return result


def get_model_info():
    """Inspect the installed model without running inference."""
    model = config.LOCAL_MODEL
    installed = _request_json("/api/tags").get("models", [])
    model_info = next(
        (entry for entry in installed
         if entry.get("name") == model or entry.get("model") == model), None
    )
    if model_info is None:
        raise RuntimeError(
            f"Local model {model!r} is not downloaded. Run: "
            "powershell -ExecutionPolicy Bypass "
            "-File scripts/start_local_llm.ps1 -Pull"
        )
    return model_info


def call_llm(prompt, temperature=None, tag="call", *, seed=None, save_response=False, raw_dir=None):
    """Send one independent prompt unchanged and return its response.

    seed selects a reproducible sampling seed (not a guarantee across hardware).
    No files are written unless save_response=True is explicitly requested.
    """
    model_info = get_model_info()
    model = config.LOCAL_MODEL
    temp = config.TEMPERATURE if temperature is None else temperature
    options = {
        "temperature": temp,
        "num_predict": config.MAX_TOKENS,
        "num_ctx": config.LOCAL_CONTEXT_TOKENS,
    }
    if seed is not None:
        options["seed"] = seed
    response = _request_json("/api/chat", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": options,
    })
    text = response["message"]["content"]
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "backend": "ollama",
        "model": model,
        "model_digest": model_info.get("digest"),
        "model_details": model_info.get("details", {}),
        "temperature": temp,
        "options": options,
        "prompt": prompt,
        "response": text,
        "input_tokens": response.get("prompt_eval_count", 0),
        "output_tokens": response.get("eval_count", 0),
        "done_reason": response.get("done_reason"),
        "total_duration_ns": response.get("total_duration"),
    }
    raw_path = None
    if save_response:
        raw_dir = config.RAW_DIR if raw_dir is None else Path(raw_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tag)) or "call"
        raw_path = raw_dir / f"{stamp}_local_{safe_tag}.json"
        raw_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {
        "text": text,
        "code": extract_code(text),
        "input_tokens": record["input_tokens"],
        "output_tokens": record["output_tokens"],
        "model_digest": record["model_digest"],
        "done_reason": record["done_reason"],
        "raw_path": str(raw_path) if raw_path else None,
    }
