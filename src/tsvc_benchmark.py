"""Build and measure one TSVC kernel while retaining the suite's argument setup.

The downloaded suite is never edited. Each build uses a temporary copy with
only the selected kernel called from main. Timing is around the kernel call
(excluding process startup); state snapshots are written after the timer stops.
"""
from array import array
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import config


# Mask comments and literals without moving source offsets or line numbers.
C_TOKENS = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)


def mask_c(text, *, comments_only=False):
    def mask(match):
        value = match.group()
        if comments_only and not value.startswith(("//", "/*")):
            return value
        return "".join("\n" if ch == "\n" else " " for ch in value)
    return C_TOKENS.sub(mask, text)


def function_span(source, name):
    """Exact function extent, excluding following helpers/comments/main."""
    masked = mask_c(source)
    match = re.search(
        rf"(?m)^(?:real_t|int|void)\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        masked,
    )
    if not match:
        raise ValueError(f"Function {name!r} not found")
    opening = masked.index("{", match.start())
    depth = 1
    for end in range(opening + 1, len(masked)):
        depth += (masked[end] == "{") - (masked[end] == "}")
        if depth == 0:
            return match.start(), end + 1
    raise ValueError(f"Unbalanced function {name!r}")


def kernel_source(suite, kernel):
    start, end = function_span(suite, kernel)
    return suite[start:end]


def validate_rewrite(original, rewrite, kernel):
    """Enforce the shared prompt's function and benchmark-scaffold constraints."""
    start, end = function_span(rewrite, kernel)
    masked = mask_c(rewrite)
    if masked[:start].strip() or masked[end:].strip():
        raise ValueError("Return only the target function, without extra declarations/functions")
    signature = lambda text: re.sub(r"\s+", "", mask_c(text).split("{", 1)[0])
    if signature(original) != signature(rewrite):
        raise ValueError("The function signature changed")
    if re.search(r"#|\b(?:asm|__asm__|__asm|_asm)\b|\b_mm\w*\b|\b__m(?:128|256|512)\w*\b", masked):
        raise ValueError("Preprocessor directives, SIMD intrinsics, or assembly are not allowed")
    for name in ("initialise_arrays", "gettimeofday", "calc_checksum", "dummy"):
        def calls(text):
            value = mask_c(text, comments_only=True)
            found = []
            for match in re.finditer(rf"\b{name}\s*\(", mask_c(value)):
                opening = value.index("(", match.start())
                depth = 1
                for pos in range(opening + 1, len(value)):
                    depth += (value[pos] == "(") - (value[pos] == ")")
                    if depth == 0:
                        call = re.sub(r"\s+", "", value[match.start():pos + 1])
                        # 0., 0.0, and 0.f are the same scalar zero in dummy().
                        call = re.sub(r"(?<![\w.])0(?:\.0*)?(?:[eE][+-]?0)?[fFlL]?(?![\w.])", "0", call)
                        found.append(call)
                        break
            return found
        if calls(original) != calls(rewrite):
            raise ValueError(f"Benchmark call(s) to {name} changed")
    repetition = re.compile(r"\bfor\s*\([^;]*\bnl\s*=[^;]*;[^;]*;[^)]*\)")
    def headers(text):
        values = [re.sub(r"\s+", "", h) for h in repetition.findall(mask_c(text))]
        return [value.replace("++nl", "nl++").replace("nl+=1)", "nl++)") for value in values]
    if headers(original) != headers(rewrite):
        raise ValueError("Benchmark repetition loop(s) over nl changed")


@dataclass(frozen=True)
class Workload:
    iterations: int = 100000
    len_1d: int = 32000
    len_2d: int = 256

    def __post_init__(self):
        if self.iterations <= 0 or self.len_1d <= 0 or self.len_1d % 40 or self.len_2d <= 0:
            raise ValueError("Workload needs positive sizes and LEN_1D divisible by 40")
        if self.iterations < max(self.len_1d, self.len_2d):
            raise ValueError("iterations must cover LEN_1D/LEN_2D so benchmark bodies execute")


CHECK_WORKLOAD = Workload(iterations=640, len_1d=320, len_2d=40)
FULL_WORKLOAD = Workload()
FLOAT_ARRAYS = ("flat_2d_array", "x", "a", "b", "c", "d", "e", "aa", "bb", "cc", "tt")
ABS_TOL = 1e-3
REL_TOL = 1e-4

# Keep the timer and observation code outside the model-editable function.
DRIVER = r'''
#ifdef _WIN32
#include <windows.h>
static double b0_now(void) {
    LARGE_INTEGER counter, frequency;
    QueryPerformanceCounter(&counter); QueryPerformanceFrequency(&frequency);
    return (double)counter.QuadPart / (double)frequency.QuadPart;
}
#else
static double b0_now(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value)) exit(2);
    return (double)value.tv_sec + (double)value.tv_nsec / 1e9;
}
#endif
static real_t *b0_allocated_xx;
static int *b0_ip;
static const char *b0_state_path;
static void b0_write(FILE *file, const void *data, size_t size) {
    if (fwrite(data, 1, size, file) != size) exit(2);
}
void time_function(test_function_t vector_func, void *arg_info) {
    struct args_t args = {.arg_info = arg_info};
    double start = b0_now();
    double result = vector_func(&args);
    double elapsed = b0_now() - start;
    printf("\nB0_RESULT %.17g %.17g\n", elapsed, result);
    if (b0_state_path) {
        _Static_assert(sizeof(real_t) == 4 && sizeof(int) == 4, "Expected TSVC float/int32");
        FILE *file = fopen(b0_state_path, "wb");
        if (!file) exit(2);
        B0_GLOBAL_WRITES
        b0_write(file, b0_allocated_xx, LEN_1D * sizeof(real_t));
        b0_write(file, indx, sizeof(indx));
        b0_write(file, b0_ip, LEN_1D * sizeof(int));
        if (fclose(file)) exit(2);
    }
}
'''.replace("B0_GLOBAL_WRITES", "\n".join(
    f"b0_write(file, {name}, sizeof({name}));" for name in FLOAT_ARRAYS
))


def build_source(suite, kernel, rewrite):
    start, end = function_span(suite, kernel)
    restore_line = suite[:end].count("\n") + 2
    source = (suite[:start] + '\n#line 1 "b0_candidate.c"\n' + rewrite +
              f'\n#line {restore_line} "tsvc.c"\n' + suite[end:])
    start, end = function_span(source, "time_function")
    source = source[:start] + DRIVER + source[end:]
    source = source.replace("int main(void)", "int main(int argc, char **argv)", 1)
    source = source.replace(
        "init(&ip, &s1, &s2);",
        "init(&ip, &s1, &s2);\n"
        "    b0_allocated_xx = xx; b0_ip = ip;\n"
        "    memset(b0_allocated_xx, 0, LEN_1D * sizeof(real_t));\n"
        "    b0_state_path = argc == 2 ? argv[1] : NULL;",
        1,
    )
    main_start, main_end = function_span(source, "main")
    main = source[main_start:main_end]
    call_pattern = re.compile(r"(?m)^[ \t]*time_function\(&(?P<name>\w+),[^\n]*\);[ \t]*$")
    if sum(m.group("name") == kernel for m in call_pattern.finditer(main)) != 1:
        raise ValueError(f"Expected exactly one original main call for {kernel}")
    main = call_pattern.sub(lambda m: m.group() if m.group("name") == kernel else "", main)
    return "#define _POSIX_C_SOURCE 200809L\n#include <string.h>\n" + source[:main_start] + main + source[main_end:]


class BenchmarkError(RuntimeError):
    pass


@dataclass
class Binary:
    path: Path
    workload: Workload
    diagnostics: str

    @property
    def vectorized(self):
        # Only this kernel's virtual source, never remarks from other functions.
        return bool(re.search(r"(?m)^b0_candidate\.c:\d+:\d+: remark: vectorized loop", self.diagnostics))


def compile_kernel(suite, kernel, rewrite, work, *, compiler=None, workload=FULL_WORKLOAD, timeout=120,
                   cflags=None):
    """Compile all translation units separately (no LTO), preserving dummy calls."""
    compiler = compiler or config.CC
    work.mkdir(parents=True, exist_ok=True)
    header = (config.TSVC_SRC / "common.h").read_text(encoding="utf-8")
    for name, value in (("iterations", workload.iterations), ("LEN_1D", workload.len_1d), ("LEN_2D", workload.len_2d)):
        header, count = re.subn(rf"(?m)^#define {name} \d+$", f"#define {name} {value}", header)
        if count != 1:
            raise BenchmarkError(f"Unexpected TSVC header definition: {name}")
    (work / "common.h").write_text(header, encoding="utf-8")
    for name in ("common.c", "dummy.c", "array_defs.h"):
        shutil.copyfile(config.TSVC_SRC / name, work / name)
    source = work / "kernel.c"
    source.write_text(build_source(suite, kernel, rewrite), encoding="utf-8")
    binary = work / ("kernel.exe" if os.name == "nt" else "kernel")
    command = [compiler, *(config.CFLAGS if cflags is None else cflags), *config.REMARK_FLAGS, "-fno-color-diagnostics",
               "-I", str(work), str(source), str(work / "common.c"), str(work / "dummy.c"),
               "-lm", "-o", str(binary)]
    (work / "compile_command.txt").write_text(repr(command), encoding="utf-8")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError(f"Compilation failed: {exc}") from exc
    (work / "compile.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise BenchmarkError(f"Compilation failed:\n{result.stderr[-3000:]}")
    return Binary(binary.resolve(), workload, result.stderr)


@dataclass
class Observation:
    seconds: float
    checksum: float
    floats: dict
    integers: bytes


def read_observation(stdout, state, workload):
    match = re.search(r"(?m)^B0_RESULT (\S+) (\S+)$", stdout)
    if not match:
        raise BenchmarkError("Executable did not report its measurement")
    try:
        seconds, checksum = map(float, match.groups())
    except ValueError as exc:
        raise BenchmarkError("Invalid measurement output") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise BenchmarkError("Nonpositive or invalid elapsed time; increase workload")
    sizes = [workload.len_2d ** 2] + [workload.len_1d] * 6 + [workload.len_2d ** 2] * 4 + [workload.len_1d]
    expected = (sum(sizes) + 2 * workload.len_1d) * 4
    if len(state) != expected:
        raise BenchmarkError(f"Invalid state snapshot: {len(state)} bytes, expected {expected}")
    floats, offset = {}, 0
    for name, size in zip((*FLOAT_ARRAYS, "allocated_xx"), sizes):
        floats[name] = state[offset:offset + size * 4]
        offset += size * 4
    return Observation(seconds, checksum, floats, state[offset:])


def observe(binary, *, timeout=120):
    state_path = binary.path.parent / "state.bin"
    state_path.unlink(missing_ok=True)
    try:
        result = subprocess.run([str(binary.path), str(state_path)], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BenchmarkError(f"Execution failed: {exc}") from exc
    if result.returncode:
        raise BenchmarkError(f"Executable exited {result.returncode}: {result.stderr[-1000:]}")
    if not state_path.exists():
        raise BenchmarkError("Executable did not produce a state snapshot")
    return read_observation(result.stdout, state_path.read_bytes(), binary.workload)


def compare_observations(original, rewrite):
    """Differential testing, including arrays to detect checksum cancellation."""
    def equal(left, right):
        return left == right or (math.isfinite(left) and math.isfinite(right) and
                                abs(left - right) <= ABS_TOL + REL_TOL * abs(left))
    if not equal(original.checksum, rewrite.checksum):
        return False, "Return value/checksum differs"
    if original.integers != rewrite.integers:
        return False, "Integer/index arrays differ"
    if original.floats.keys() != rewrite.floats.keys():
        return False, "State arrays differ"
    for name, data in original.floats.items():
        other = rewrite.floats[name]
        if data == other:
            # NaNs are inconclusive even when their bit patterns match.
            if any(math.isnan(value) for value in array("f", data)):
                return False, f"NaN in reference state: {name}"
            continue
        left, right = array("f", data), array("f", other)
        if len(left) != len(right):
            return False, f"Array size differs: {name}"
        for index, (a, b) in enumerate(zip(left, right)):
            if not equal(a, b):
                return False, f"{name}[{index}] differs: {a} vs {b}"
    return True, ""
