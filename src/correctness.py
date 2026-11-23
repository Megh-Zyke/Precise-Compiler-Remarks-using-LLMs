"""T1.5: compare an original TSVC kernel with a rewrite.

Each kernel fills its arrays in initialise_arrays() and returns
calc_checksum(). The rewrite is correct when that checksum matches.
These kernels return float, so the match is

    abs(error) <= ABS_TOL + REL_TOL * abs(original)

with ABS_TOL = 1e-3 and REL_TOL = 1e-4. An integer kernel would be compared
exactly; this suite has none.

The run is not the benchmark. Arrays are LEN_1D=320 and LEN_2D=40, and
iterations is 400, so a loop body still executes (iterations / LEN_2D >= 1)
but the checksum is not the one in results/tsvc_vec_baseline.txt.

test_checker() has to pass before this module is trusted: an unchanged s000
matches and equals 52000, a reassociation of the same statement matches, and
a one-constant edit does not.

Run from the repo root:  python3 -m src.correctness
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config
from .filter_loops import function_ranges

ABS_TOL = 1e-3
REL_TOL = 1e-4
CHECK_ITERATIONS = 400
CHECK_LEN_1D = 320
CHECK_LEN_2D = 40

GLOBALS = """
__attribute__((aligned(ARRAY_ALIGNMENT))) real_t flat_2d_array[LEN_2D*LEN_2D];
__attribute__((aligned(ARRAY_ALIGNMENT))) real_t x[LEN_1D];
__attribute__((aligned(ARRAY_ALIGNMENT))) real_t a[LEN_1D],b[LEN_1D],c[LEN_1D],d[LEN_1D],e[LEN_1D],
                                   aa[LEN_2D][LEN_2D],bb[LEN_2D][LEN_2D],cc[LEN_2D][LEN_2D],tt[LEN_2D][LEN_2D];
__attribute__((aligned(ARRAY_ALIGNMENT))) int indx[LEN_1D];
real_t* __restrict__ xx;
real_t* yy;
"""


def kernel_source(name, text=None):
    """Return one TSVC kernel function, including its signature."""
    if text is None:
        path = config.TSVC_SRC / "tsvc.c"
        if not path.exists():
            raise SystemExit(f"{path} not found; run: git submodule update --init")
        text = path.read_text()
    lines = text.splitlines()
    for found, start, end in function_ranges(lines):
        if found == name:
            return "\n".join(lines[start - 1:end]) + "\n"
    raise KeyError(name)


def within_tolerance(original, rewrite):
    abs_err = abs(original - rewrite)
    scale = max(abs(original), 1e-12)
    rel_err = abs_err / scale
    return abs_err <= ABS_TOL + REL_TOL * abs(original), abs_err, rel_err


def _prepare_sources(work):
    """Lay out a copy of the TSVC helpers whose common.h honors -DLEN_* / -Diterations.

    common.c and dummy.c include "common.h" from their own directory, ahead of
    any -I path, so the originals ignore an overlay on the include path and
    keep LEN_1D at 32000. Copies sitting next to the wrapped header do not.
    """
    header = (config.TSVC_SRC / "common.h").read_text()
    replacements = {
        "#define iterations 100000": "#ifndef iterations\n#define iterations 100000\n#endif",
        "#define LEN_1D 32000": "#ifndef LEN_1D\n#define LEN_1D 32000\n#endif",
        "#define LEN_2D 256": "#ifndef LEN_2D\n#define LEN_2D 256\n#endif",
    }
    for old, new in replacements.items():
        if old not in header:
            raise SystemExit(f"common.h no longer contains {old!r}; checker overlay is stale")
        header = header.replace(old, new, 1)
    work.mkdir(parents=True, exist_ok=True)
    (work / "common.h").write_text(header)
    shutil.copy(config.TSVC_SRC / "common.c", work / "common.c")
    shutil.copy(config.TSVC_SRC / "dummy.c", work / "dummy.c")


def _checksum(kernel, source, work):
    """Compile and run one kernel. Return (checksum or None, detail)."""
    name = re.match(r"(?:real_t|int|void)\s+(\w+)\s*\(", source)
    if not name:
        return None, "rewrite has no function signature"
    func = name.group(1)
    if func != kernel:
        return None, f"rewrite defines {func}, expected {kernel}"
    driver = work / f"{kernel}_{abs(hash(source)) & 0xfffffff}.c"
    binary = work / driver.stem
    driver.write_text(
        '#include "common.h"\n#include "array_defs.h"\n#include <stdio.h>\n'
        '#include <string.h>\n'
        f"{GLOBALS}\n{source}\n"
        "int main(void) {\n"
        "    struct args_t args;\n"
        "    memset(&args, 0, sizeof(args));\n"
        f"    real_t sum = {func}(&args);\n"
        '    printf("CHECKSUM %.9g\\n", (double)sum);\n'
        "    return 0;\n"
        "}\n"
    )
    cmd = [
        config.CC, "-O0",
        f"-Diterations={CHECK_ITERATIONS}",
        f"-DLEN_1D={CHECK_LEN_1D}",
        f"-DLEN_2D={CHECK_LEN_2D}",
        "-I", str(work),
        "-I", str(config.TSVC_SRC),
        str(work / "common.c"),
        str(work / "dummy.c"),
        str(driver),
        "-lm", "-o", str(binary),
    ]
    compiled = subprocess.run(cmd, capture_output=True, text=True)
    if compiled.returncode != 0:
        tail = (compiled.stderr or "")[-500:].strip()
        return None, "compile failed: " + tail
    try:
        ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    if ran.returncode != 0:
        return None, f"runtime exit {ran.returncode}"
    found = re.findall(r"CHECKSUM\s+([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", ran.stdout)
    if not found:
        return None, "no checksum printed"
    return float(found[-1]), ""


def check_rewrite(kernel, rewrite_src):
    """Compare rewrite_src to the TSVC original. Always returns a dict."""
    original_src = kernel_source(kernel)
    with tempfile.TemporaryDirectory(prefix="correctness_") as tmp:
        work = Path(tmp)
        _prepare_sources(work)
        original, original_detail = _checksum(kernel, original_src, work)
        rewrite, rewrite_detail = _checksum(kernel, rewrite_src, work)
    if original is None or rewrite is None:
        return {
            "match": False, "original": original, "rewrite": rewrite,
            "abs_err": None, "rel_err": None,
            "detail": original_detail or rewrite_detail,
        }
    match, abs_err, rel_err = within_tolerance(original, rewrite)
    return {
        "match": match, "original": original, "rewrite": rewrite,
        "abs_err": abs_err, "rel_err": rel_err, "detail": "",
    }


def test_checker():
    """Unchanged and reassociated s000 pass; a changed constant fails.

    Also checks the original checksum is 52000, which is sum(3 + i) for
    i in 0..319. That value is only produced when the loop body runs.
    """
    original = kernel_source("s000")
    same = check_rewrite("s000", original)
    if not same["match"] or abs(same["original"] - 52000.0) > ABS_TOL:
        raise AssertionError(f"unchanged s000 should checksum to 52000: {same}")
    moved = original.replace("a[i] = b[i] + 1;", "a[i] = (1 + b[i]);", 1)
    if moved == original:
        raise AssertionError("s000 no longer contains the statement the test rewrites")
    equivalent = check_rewrite("s000", moved)
    if not equivalent["match"]:
        raise AssertionError(f"reassociated s000 should match: {equivalent}")
    broken_src = original.replace("a[i] = b[i] + 1;", "a[i] = b[i] + 2;", 1)
    broken = check_rewrite("s000", broken_src)
    if broken["match"]:
        raise AssertionError(f"broken s000 should not match: {broken}")
    return {"same": same, "equivalent": equivalent, "broken": broken}


if __name__ == "__main__":
    result = test_checker()
    for name, row in result.items():
        print(f"{name}: match={row['match']} original={row['original']} "
              f"rewrite={row['rewrite']} abs_err={row['abs_err']}")
