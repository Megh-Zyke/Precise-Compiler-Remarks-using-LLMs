# Precise compiler remarks for LLM optimization agents (EECS 583)

Question: how much of the gain from hand-written precise compiler remarks does an
LLM-generated remark recover, when an LLM agent rewrites loops so Clang vectorizes them?

## Arms (same agent, prompt, model, temperature, loops in every arm)
- B0: no remarks
- B1: Clang's standard remarks
- B2: hand-written precise remarks (style of arXiv 2604.13927). A reviewed subset is in remarks/handwritten/; the rest of the kernels are still open.
- Ours: remarks/generated/, filled by src/remark_gen.py from LLVM LoopAccess. prompts/remark_writer.txt is the LLM version of that format and has not been run.

## Pinned settings (see src/config.py; changing them invalidates earlier runs)
- Compiler: clang (record `clang --version` below), flags `-O3 -fstrict-aliasing -march=native`
- Model / temperature / trials: set in src/config.py
- Benchmark: third_party/TSVC_2 (UoB-HPC/TSVC_2)

Recorded versions:
- clang: (fill in)
- opt:   (fill in)

## Quick start
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env        # then add your API key
    git submodule update --init  # if third_party/TSVC_2 is empty
    python3 src/filter_loops.py   # which TSVC kernels does Clang fail to vectorize?
    python3 -m src.remark_gen     # LLVM LoopAccess -> remarks/generated/
    python3 -m src.correctness    # self-test the checksum checker

## Local LLM alternative (no Anthropic access needed)

Use `src.llm_local` for Qwen2.5-Coder 7B through local Ollama, with the same
prompt templates and response interface as `src.llm`. See
[local setup and usage](docs/local_llm.md). On this Windows workspace:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_llm.ps1
    python -m src.llm_without_remarks --dry-run --kernels s212 --trials 1

## B0: LLM without compiler remarks

`src/llm_without_remarks.py` implements independent local-Qwen trials and
`src/tsvc_benchmark.py` compiles, checks, and measures original/rewrite pairs.
The default is a preview of all 151 kernels with 5 independent rewrites each;
generation requires `--run`. Only the fastest correct rewrite per kernel is
saved, with its measured time and checksum, in one file:
`results/results_llm_no_remarks.txt`. Other candidates are discarded. The report's
`Run status` field indicates whether execution is ongoing, failed, or complete.
See [B0 workflow and review notes](docs/b0.md).

The completed run covers 151 kernels and 755 rewrites using Qwen2.5-Coder 7B
Instruct FP16 (five independent attempts per kernel).

- **Vectorization:** 5/68 originally unvectorized kernels (**7.35%**) gained
  vectorization and passed the checks under Clang 18.1.3; 83 already-vectorized
  originals were excluded. This measures saved winners, not per-trial success.
  See [vectorization results](results/vectorization_llm_no_remarks.txt).
- **Originally reported checks:** 387/755 rewrites (**51.3%**) passed;
  136/151 kernels (**90.1%**) had an accepted rewrite, while 15 had none.
  See [B0 results](results/results_llm_no_remarks.txt).
- **Stronger recheck:** 133 saved winners passed; `s175` and `s241` failed bounds
  checks. `s317` timed out but did not vectorize, so it remains unsuccessful in
  the vectorization denominator.

## Status (tick as you go; task IDs refer to the project plan doc)
- [ ] T0.1 LLVM/Clang installed, versions recorded above
- [ ] T0.2 TSVC_2 builds and runs unmodified
- [ ] T0.3 src/llm.py makes one successful call
- [ ] T0.4 results CSV schema agreed
- [ ] T0.5 decisions made: Option 1 vs 2, model, deadline
- [ ] T0.6 smoke test on one loop
- [ ] T1.1/T1.2 filter_loops.py run; list of non-vectorized kernels saved

## Open decisions
- Option 1 (LLM writes remark text) vs Option 2 (LLM writes the LLVM pass)
- Model and temperature
- Evaluation set size and trials per loop
- Floating-point tolerance, or integer versions of loops
