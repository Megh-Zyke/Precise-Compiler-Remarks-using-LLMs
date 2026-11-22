# Precise compiler remarks for LLM optimization agents (EECS 583)

Question: how much of the gain from hand-written precise compiler remarks does an
LLM-generated remark recover, when an LLM agent rewrites loops so Clang vectorizes them?

## Arms (same agent, prompt, model, temperature, loops in every arm)
- B0: no remarks
- B1: Clang's standard remarks
- B2: hand-written precise remarks (style of arXiv 2604.13927)
- Ours: LLM-generated remarks (LLM writes the remark from LLVM's dependence output)

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
    python3 src/filter_loops.py  # which TSVC kernels does Clang fail to vectorize?

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
