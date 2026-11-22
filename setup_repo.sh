#!/usr/bin/env bash
# setup_repo.sh: creates the EECS 583 "precise remarks" project repo.
# Usage: bash setup_repo.sh [target_dir]      (default: remarks-project)
set -euo pipefail

mkdir -p third_party loops remarks/clang remarks/handwritten remarks/generated \
         prompts src results/raw docs
touch loops/.gitkeep remarks/handwritten/.gitkeep remarks/generated/.gitkeep results/raw/.gitkeep

git init -q

# ---------------------------------------------------------------- top level
cat > .gitignore <<'EOF'
.env
.venv/
__pycache__/
*.pyc
*.o
*.out
bin/
build/
results/raw/*
!results/raw/.gitkeep
EOF

cat > .env.example <<'EOF'
# Copy to .env (never commit .env). Name matches the Anthropic SDK default.
ANTHROPIC_API_KEY=
# Optional overrides
# LLM_MODEL=claude-sonnet-5-5
# CC_BIN=clang
EOF

cat > requirements.txt <<'EOF'
anthropic
EOF

cat > README.md <<'EOF'
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
EOF

cat > results/results.csv <<'EOF'
loop,arm,trial,vectorized,correct,speedup,input_tokens,output_tokens,clang_version,model,temperature
EOF

cat > docs/notes.md <<'EOF'
# Notes

## LLVM dependence output (T2.1)
How to get it: compile a loop to IR with -g, then run
    opt -passes='print<access-info>' -disable-output file.ll
Write here what the output looks like and how to map it to line and column.

## Findings / dead ends
EOF

# ------------------------------------------------------------------ prompts
cat > prompts/agent.txt <<'EOF'
You are optimizing a C loop so the compiler can auto-vectorize it.
Rewrite the function below so that Clang -O3 vectorizes the loop and the
function computes exactly the same result. Keep the signature unchanged.
Do not use pragmas, intrinsics or inline assembly.

<code>
{LOOP_SOURCE}
</code>

<compiler_feedback>
{FEEDBACK}
</compiler_feedback>

Return only the complete rewritten function in one C code block.
EOF

cat > prompts/remark_writer.txt <<'EOF'
You are a compiler analysis assistant. Do not rewrite or fix the code.
Below are a C loop and LLVM's dependence analysis output for it.
Explain why the loop cannot be vectorized, using exactly this format:

conflict: <expr, line, col> <-> <expr, line, col>
kind: read-after-write | write-after-read | write-after-write | possible alias
distance: <iterations, or unknown>
loop-carried: yes | no (assumed because of possible aliasing)
suggested fix: <one or two sentences in words, no code>

If you cannot determine a field from the input, write "unknown". Do not guess.

<code>
{LOOP_SOURCE}
</code>

<llvm_dependence_output>
{ACCESS_INFO}
</llvm_dependence_output>
EOF

# --------------------------------------------------------------------- src
touch src/__init__.py

cat > src/config.py <<'EOF'
"""Pinned experiment settings. Changing these invalidates earlier runs."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TSVC_SRC = ROOT / "third_party" / "TSVC_2" / "src"

# Compiler (mirrors TSVC_2's Makefile.clang: -O3 -fstrict-aliasing, native arch)
CC = os.environ.get("CC_BIN", "clang")
CFLAGS = ["-O3", "-fstrict-aliasing", "-march=native"]
REMARK_FLAGS = [
    "-Rpass=loop-vectorize",
    "-Rpass-missed=loop-vectorize",
    "-Rpass-analysis=loop-vectorize",
]

# LLM. Model is an open decision: set LLM_MODEL in .env or change the default.
MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5-5")
TEMPERATURE = 0.8
MAX_TOKENS = 4096
TRIALS = 10

RESULTS_CSV = ROOT / "results" / "results.csv"
RAW_DIR = ROOT / "results" / "raw"
CLANG_REMARKS_DIR = ROOT / "remarks" / "clang"
EOF

cat > src/compile_check.py <<'EOF'
"""Compile C with Clang and read vectorization remarks."""
import re
import subprocess
from pathlib import Path

from . import config

PASSED_RE = re.compile(r"^[^:\n]+:(\d+):\d+: remark: vectorized loop")


def compile_c(src, out="/dev/null", extra=None, remarks=True, compile_only=True,
              include_dirs=None):
    """Run clang on src. Returns the CompletedProcess (remarks are in .stderr)."""
    cmd = [config.CC, *config.CFLAGS]
    if remarks:
        cmd += config.REMARK_FLAGS
    for d in include_dirs or []:
        cmd += ["-I", str(d)]
    cmd += list(extra or [])
    if compile_only:
        cmd.append("-c")
    cmd += [str(src), "-o", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True)


def vectorized_lines(stderr):
    """Line numbers of loops that Clang reports as vectorized."""
    return {int(m.group(1)) for line in stderr.splitlines()
            if (m := PASSED_RE.match(line))}


def is_vectorized(stderr, lo=None, hi=None):
    """True if any 'vectorized loop' remark falls in [lo, hi] (inclusive)."""
    lines = vectorized_lines(stderr)
    if lo is not None:
        lines = {n for n in lines if n >= lo}
    if hi is not None:
        lines = {n for n in lines if n <= hi}
    return bool(lines)


if __name__ == "__main__":
    import sys
    p = compile_c(sys.argv[1], include_dirs=[Path(sys.argv[1]).parent])
    print(p.stderr)
    print("vectorized loop lines:", sorted(vectorized_lines(p.stderr)))
EOF

cat > src/filter_loops.py <<'EOF'
"""Which TSVC kernels does Clang fail to vectorize? (tasks T1.1, T1.2)

Compiles tsvc.c once with loop-vectorize remarks, maps each remark to the
kernel function it falls in, and classifies each kernel. A kernel counts as
'vectorized' if ANY loop in it is vectorized, so check candidates by hand
before putting them in the evaluation set (a kernel may have several loops).

Writes results/loop_status.csv and remarks/clang/<kernel>.txt (this is B1).
Run from the repo root:  python3 -m src.filter_loops
"""
import csv
import re
from collections import defaultdict

from . import config
from .compile_check import compile_c

FUNC_RE = re.compile(r"^(?:real_t|int|void)\s+(\w+)\s*\(struct args_t")
REMARK_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+): remark: (?P<msg>.*) "
    r"\[-Rpass(?P<kind>-missed|-analysis)?=loop-vectorize\]\s*$")


def function_ranges(lines):
    starts = [(i + 1, m.group(1)) for i, l in enumerate(lines)
              if (m := FUNC_RE.match(l))]
    out = []
    for k, (start, name) in enumerate(starts):
        end = starts[k + 1][0] - 1 if k + 1 < len(starts) else len(lines)
        out.append((name, start, end))
    return out


def parse_blocks(stderr):
    """Split clang's stderr into remark blocks: (line, kind, full_text)."""
    blocks, cur = [], None
    for raw in stderr.splitlines():
        m = REMARK_RE.match(raw)
        if m:
            if cur:
                blocks.append(cur)
            kind = {"": "passed", "-missed": "missed",
                    "-analysis": "analysis"}[m.group("kind") or ""]
            cur = [int(m.group("line")), kind, [raw]]
        elif cur is not None:
            cur[2].append(raw)
    if cur:
        blocks.append(cur)
    return [(ln, kind, "\n".join(txt)) for ln, kind, txt in blocks]


def main():
    src = config.TSVC_SRC / "tsvc.c"
    if not src.exists():
        raise SystemExit(f"{src} not found; run: git submodule update --init")
    lines = src.read_text().splitlines()
    ranges = function_ranges(lines)

    proc = compile_c(src, include_dirs=[config.TSVC_SRC])
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-2000:])
    blocks = parse_blocks(proc.stderr)

    per_func = defaultdict(list)
    for ln, kind, text in blocks:
        for name, lo, hi in ranges:
            if lo <= ln <= hi:
                per_func[name].append((ln, kind, text))
                break

    config.CLANG_REMARKS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, lo, hi in ranges:
        bl = per_func.get(name, [])
        kinds = {k for _, k, _ in bl}
        status = ("vectorized" if "passed" in kinds
                  else "not_vectorized" if "missed" in kinds
                  else "no_loop_remark")
        rows.append((name, lo, hi, status))
        if status == "not_vectorized":
            text = "\n".join(t for _, k, t in bl if k in ("missed", "analysis"))
            (config.CLANG_REMARKS_DIR / f"{name}.txt").write_text(text + "\n")

    out = config.ROOT / "results" / "loop_status.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kernel", "start_line", "end_line", "status"])
        w.writerows(rows)

    counts = defaultdict(int)
    for *_, status in rows:
        counts[status] += 1
    print(f"clang: {config.CC}  flags: {' '.join(config.CFLAGS)}")
    for status, n in sorted(counts.items()):
        print(f"{status:16s} {n}")
    print(f"wrote {out} and remarks/clang/*.txt")


if __name__ == "__main__":
    main()
EOF

cat > src/timing.py <<'EOF'
"""Repeated timing of a command (T1.7): warm-up runs, then median and spread."""
import statistics
import subprocess
import time


def time_command(cmd, runs=20, warmup=3):
    for _ in range(warmup):
        subprocess.run(cmd, capture_output=True)
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True)
        samples.append(time.perf_counter() - t0)
    return {"median": statistics.median(samples), "min": min(samples),
            "max": max(samples), "runs": runs}


if __name__ == "__main__":
    import sys
    print(time_command(sys.argv[1:] or ["true"]))
EOF

cat > src/llm.py <<'EOF'
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
EOF

cat > src/correctness.py <<'EOF'
"""T1.5: compare original and rewritten loop outputs on random inputs.

TODO (not written yet). Plan:
  1. Wrap each kernel (original and rewrite) in a tiny driver that fills the
     arrays with seeded random data, runs the kernel, prints a checksum or the
     output arrays.
  2. Compare: exact for integers, small stated relative tolerance for floats.
  3. Test the checker on a deliberately broken rewrite (it must fail) and on a
     correct one (it must pass) before trusting it.
"""
raise NotImplementedError("T1.5: correctness checker not written yet")
EOF

cat > src/run_trial.py <<'EOF'
"""T1.8: one loop, one arm, one trial -> one row in results/results.csv.

TODO (not written yet). Steps:
  1. Read prompts/agent.txt; fill {LOOP_SOURCE} and {FEEDBACK}
     (B0: "No compiler feedback is available."; B1: remarks/clang/<loop>.txt;
      B2: remarks/handwritten/<loop>.txt; Ours: remarks/generated/<loop>.txt).
  2. call_llm(...) and take the code block.
  3. Compile it (compile_check), check vectorization, check correctness,
     time original vs rewrite, append the CSV row.
"""
raise NotImplementedError("T1.8: agent driver not written yet")
EOF

# ------------------------------------------------------------ submodule + git
if git submodule add -q --depth 1 https://github.com/UoB-HPC/TSVC_2 third_party/TSVC_2 2>/dev/null; then
  echo "added TSVC_2 as a submodule"
else
  echo "warning: could not add the TSVC_2 submodule (network?). Run later:"
  echo "  git submodule add --depth 1 https://github.com/UoB-HPC/TSVC_2 third_party/TSVC_2"
fi
git add -A

echo
echo "Repo created in: $(pwd)"
echo "Next:"
echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
echo "  cp .env.example .env   # add ANTHROPIC_API_KEY"
echo "  clang --version && opt --version   # record both in README.md"
echo "  python3 -m src.filter_loops"
echo "  git commit -m 'Initial project skeleton'"
