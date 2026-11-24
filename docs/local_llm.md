# Local Qwen model

The local backend uses Qwen2.5-Coder 7B Instruct through Ollama. The default
`qwen2.5-coder:7b` build is Q4_K_M (approximately 4.7 GB).
It matches the model family and parameter size used by *AI Coding Agents Need
Better Compiler Remarks*. The paper does not specify that quantization, so this
is not an exact reproduction of its inference configuration. Record the local
configuration when reporting results.

The completed B0 report uses FP16 weights and an 8192-token context. The Q4_K_M
laptop default described here is a separate configuration; see [B0 settings](b0.md).

## Start and use

From the project root in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_llm.ps1
python -m src.llm_without_remarks --dry-run --kernels s212 --trials 1
```

The second command only previews the B0 experiment and its existing
`prompts/agent.txt` prompt. It sends no model requests and writes no results.
`llm_local.py` is now a library only: importing it or running it as a module
does not trigger a smoke inference. See [the B0 runner](b0.md).
The execution-policy option applies only to that PowerShell process; it allows
this local script to run without changing the machine's execution policy.

In Python, select this wrapper instead of the Anthropic wrapper:

```python
from src.llm_local import call_llm, extract_code
from src import config

template = (config.ROOT / "prompts" / "agent.txt").read_text(encoding="utf-8")
prompt = template.format(LOOP_SOURCE=source, FEEDBACK=feedback)
result = call_llm(prompt, tag="s114_B0_trial1")
```

`call_llm(prompt, temperature=None, tag="call", *, seed=None, save_response=False, raw_dir=None)`
returns `text`, `code`, `input_tokens`, and `output_tokens`, plus the model digest,
completion reason, and optional raw-response path. It has no imports from the
remote-model wrapper. Generated code and quality can differ between models. It sends the supplied
prompt unchanged, so `prompts/remark_writer.txt` works too. It uses the existing
temperature and output token limit from `src/config.py`. No Anthropic SDK or
API key is needed for this backend. The original wrapper remains available.

Responses stay in memory by default, and B0 saves only the fastest correct
rewrite per kernel in `results/results_llm_no_remarks.txt`. There are no
per-trial logs or result files. For an explicit debugging call only,
`save_response=True` writes a raw JSON response to the ignored `results/raw/`
directory (or the chosen `raw_dir`). B0 does not enable this option.

## Local files and configuration

The portable Ollama executable, model weights, and server logs live in `.local/`,
which is ignored by Git. The startup script binds the server to loopback only.
Only the Q4_K_M model is retained locally. The Q2_K and FP16 model downloads
and transfer archives were removed to reclaim disk space. The completed B0
report remains unchanged. Q4_K_M can use partial CPU offloading on this 4 GB GPU.

Optional environment settings for the Python wrapper:

- `OLLAMA_MODEL`: defaults to `qwen2.5-coder:7b`.
- `OLLAMA_HOST`: defaults to `http://127.0.0.1:11434`.
- `OLLAMA_NUM_CTX`: defaults to `4096` tokens.
- `OLLAMA_TIMEOUT`: defaults to `600` seconds per HTTP request.

These are process environment variables; this project does not automatically
load a `.env` file.

## Recreate the download on another Windows machine

Download the official portable Windows AMD64 archive from
<https://github.com/ollama/ollama/releases>, verify its release SHA-256, and extract
it into `.local/ollama/` so `.local/ollama/ollama.exe` exists. This setup used
Ollama v0.40.17; its archive SHA-256 is
`3dd80f6e3a9699f2eadf4ac418f00529cee594df9557541806eda1f1f3f5588a`.
Then download the model:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_llm.ps1 -Pull
```

Sources: [model distribution](https://ollama.com/library/qwen2.5-coder:7b),
[Windows runtime](https://docs.ollama.com/windows), and
[chat API](https://docs.ollama.com/api/chat).
