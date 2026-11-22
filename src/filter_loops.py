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
