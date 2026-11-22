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
