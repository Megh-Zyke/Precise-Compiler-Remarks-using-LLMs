"""Evaluate vectorization of saved B0 winners. Default is preview; execution needs --run.

No model imports, model calls or new rewrites. Compile originals and saved code
with the same Clang/flags. Count newly vectorized, check-passing saved winners
over originals with no positive work-loop vectorization remark.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import platform
from pathlib import Path
import re
import subprocess
import tempfile

from . import config
from . import tsvc_benchmark as benchmark

INPUT = config.ROOT / "results/results_llm_no_remarks.txt"
OUTPUT = config.ROOT / "results/vectorization_llm_no_remarks.txt"
BOUNDS_FLAGS = ["-O1", "-fsanitize=bounds", "-fsanitize-trap=all"]
PASSED = re.compile(r"(?m)^b0_candidate\.c:(\d+):(\d+): remark: vectorized loop\b[^\n]*\[-Rpass=loop-vectorize\]")


def parse_report(text):
    parts = re.split(r"(?m)^={72}[ \t]*$", text.replace("\r\n", "\n"))
    def fields(value):
        return dict(line.split(": ", 1) for line in value.splitlines() if ": " in line)
    metadata, saved = fields(parts[0]), {}
    if metadata.get("Run status") != "complete":
        raise ValueError("Input must be a completed B0 report")
    for block in parts[1:]:
        header, marker, code = block.partition("\nRewritten code:\n")
        entry = fields(header)
        kernel, status = entry["Kernel"], entry["Status"]
        if kernel in saved:
            raise ValueError(f"Duplicate kernel: {kernel}")
        if status == "correct" and marker and code.strip():
            saved[kernel] = code.strip()
        elif status == "no_correct_rewrite" and not marker:
            saved[kernel] = None
        else:
            raise ValueError(f"Incomplete/unexpected saved result for {kernel}")
    if not saved or int(metadata["Kernels"]) != len(saved):
        raise ValueError("Kernel count does not match the report header")
    if int(metadata["Independent rewrites per kernel"]) != 5:
        raise ValueError("Expected the best-of-five B0 report")
    return metadata, saved


def vectorized_locations(source, diagnostics):
    """Count only positive remarks in the target kernel; exclude nl timing repeats."""
    masked = benchmark.mask_c(source)
    repetition_lines = set()
    for match in re.finditer(r"\bfor\s*\(", masked):
        opening = masked.index("(", match.start())
        depth, end = 1, opening + 1
        while end < len(masked) and depth:
            depth += (masked[end] == "(") - (masked[end] == ")")
            end += 1
        initializer = masked[opening + 1:end].split(";", 1)[0]
        if re.search(r"\bnl\s*=", initializer):
            first, last = (masked.count("\n", 0, offset) + 1 for offset in (match.start(), end - 1))
            repetition_lines.update(range(first, last + 1))
    line_count = len(source.splitlines())
    return sorted({(int(line), int(column)) for line, column in PASSED.findall(diagnostics)
                   if 1 <= int(line) <= line_count and int(line) not in repetition_lines})


def summarize(rows):
    eligible = [row for row in rows if row["original_vectorized"] is False]
    successes = sum(row["new_success"] for row in eligible)
    unknown = sum(row["original_vectorized"] is None for row in rows)
    unchecked = sum(row["status"] == "reference_uncheckable" for row in eligible)
    # A nonvectorizing rewrite cannot be a new-vectorization success, whatever
    # its correctness result. Keep it in the denominator even if checking times out.
    unresolved = sum(row["status"] == "reference_uncheckable" and row["rewrite_vectorized"] is not False
                     for row in eligible)
    return {"processed": len(rows), "eligible": len(eligible), "new_successes": successes,
            "unknown_originals": unknown,
            "unchecked_references": unchecked,
            "unresolved_successes": unresolved,
            "already_vectorized": sum(row["original_vectorized"] is True for row in rows),
            "checked_correct": sum(row["correct"] is True for row in rows),
            "correct_and_vectorized": sum(row["correct"] is True and row["rewrite_vectorized"] is True
                                          for row in rows),
            "rate": successes / len(eligible) if eligible and not unknown and not unresolved else None}


def evaluate_kernel(suite, kernel, code, work, args):
    row = {"kernel": kernel, "original_vectorized": None, "rewrite_vectorized": None,
           "correct": None, "new_success": False, "status": "not_checked", "detail": ""}
    original = benchmark.kernel_source(suite, kernel)
    try:
        reference = benchmark.compile_kernel(suite, kernel, original, work / "original_full",
                                             compiler=args.compiler, timeout=args.timeout)
    except benchmark.BenchmarkError as exc:
        row.update(status="original_compile_error", detail=str(exc))
        return row
    row["original_vectorized"] = bool(vectorized_locations(original, reference.diagnostics))
    if code is None:
        row.update(correct=False, status="no_saved_rewrite")
        return row
    stage = "rewrite"
    try:
        benchmark.validate_rewrite(original, code, kernel)
        candidate = benchmark.compile_kernel(suite, kernel, code, work / "rewrite_full",
                                             compiler=args.compiler, timeout=args.timeout)
        row["rewrite_vectorized"] = bool(vectorized_locations(code, candidate.diagnostics))
        # Bounds checks are separate from the optimized builds used for vectorization.
        flags = [*config.CFLAGS, *BOUNDS_FLAGS]
        stage = "reference"
        reference_check = benchmark.compile_kernel(
            suite, kernel, original, work / "original_bounds", compiler=args.compiler,
            workload=benchmark.CHECK_WORKLOAD, timeout=args.timeout, cflags=flags)
        expected = benchmark.observe(reference_check, timeout=args.timeout)
        valid, detail = benchmark.compare_observations(expected, expected)
        if not valid:
            row.update(status="reference_uncheckable", detail=detail)
            return row
        stage = "rewrite"
        candidate_check = benchmark.compile_kernel(
            suite, kernel, code, work / "rewrite_bounds", compiler=args.compiler,
            workload=benchmark.CHECK_WORKLOAD, timeout=args.timeout, cflags=flags)
        actual = benchmark.observe(candidate_check, timeout=args.timeout)
        match, detail = benchmark.compare_observations(expected, actual)
        if match:
            stage = "reference"
            expected = benchmark.observe(reference, timeout=args.timeout)
            valid, detail = benchmark.compare_observations(expected, expected)
            if not valid:
                row.update(status="reference_uncheckable", detail=detail)
                return row
            stage = "rewrite"
            actual = benchmark.observe(candidate, timeout=args.timeout)
            match, detail = benchmark.compare_observations(expected, actual)
        row.update(correct=match, status="passed_checks" if match else "incorrect", detail=detail)
        row["new_success"] = match and not row["original_vectorized"] and row["rewrite_vectorized"]
    except (benchmark.BenchmarkError, ValueError) as exc:
        row.update(correct=None if stage == "reference" else False,
                   status="reference_uncheckable" if stage == "reference" else "check_failed", detail=str(exc))
    return row


def write_report(path, settings, rows, complete=False):
    stats = summarize(rows)
    rate = stats["rate"] if complete else None
    lines = ["B0: saved best-of-five winner vectorization", ""]
    lines += [f"{key}: {value}" for key, value in settings.items()]
    lines += [f"Processed kernels: {stats['processed']}",
              f"Already vectorized originals (excluded): {stats['already_vectorized']}",
              f"Originals without a positive work-loop vectorization remark: {stats['eligible']}",
              f"Original compilation failures: {stats['unknown_originals']}",
              f"Eligible originals with unavailable reference checks: {stats['unchecked_references']}",
              f"Potential new vectorizations with unavailable checks: {stats['unresolved_successes']}",
              f"Saved winners passing current checks: {stats['checked_correct']}",
              f"Saved winners passing checks and vectorizing (all originals): {stats['correct_and_vectorized']}",
              f"Newly vectorized, check-passing winners: {stats['new_successes']}",
              f"New vectorization rate: {rate:.2%}" if rate is not None else
              "New vectorization rate: N/A (incomplete run, unavailable reference checks, or empty denominator)",
              "", "Kernel\tOriginal vec\tSaved winner vec\tPasses checks\tNew success\tStatus\tDetails"]
    def label(value):
        return "N/A" if value is None else "yes" if value else "no"
    for row in rows:
        detail = " ".join(row["detail"].split())[-600:]
        lines.append("\t".join([row["kernel"], label(row["original_vectorized"]),
                                label(row["rewrite_vectorized"]), label(row["correct"]),
                                label(row["new_success"]), row["status"], detail]))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Compile and evaluate saved code")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--compiler", default=config.CC, help="Clang executable; defaults to CC_BIN/clang")
    parser.add_argument("--kernels", nargs="+", help="Optional subset; reported rate applies only to this subset")
    parser.add_argument("--timeout", type=float, default=120, help="Timeout per compilation/execution in seconds")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    return args


def main(argv=None):
    args = parse_args(argv)
    rows, settings = [], None
    created_output = False
    output = args.output.resolve()
    try:
        report_bytes = args.input.read_bytes()
        report = report_bytes.decode("utf-8")
        metadata, saved = parse_report(report)
        suite = (config.TSVC_SRC / "tsvc.c").read_text(encoding="utf-8")
        if hashlib.sha256(suite.encode("utf-8")).hexdigest() != metadata["Source SHA256"]:
            raise ValueError("TSVC source hash differs from the saved experiment")
        kernels = args.kernels if args.kernels is not None else list(saved)
        if not kernels or len(kernels) != len(set(kernels)) or set(kernels) - set(saved):
            raise ValueError("Kernel subset must contain unique names from the saved report")
        for kernel in kernels:
            benchmark.kernel_source(suite, kernel)
        if not args.run:
            print(f"PREVIEW ONLY: {len(kernels)} originals; {sum(saved[k] is not None for k in kernels)} saved winners")
            print(f"Compiler: {args.compiler}; normal flags: {' '.join(config.CFLAGS)}")
            print(f"Output: {output}")
            print("No compiler, benchmark or model calls. Add --run to evaluate saved code.")
            return 0
        if output.exists():
            raise FileExistsError("Output already exists; choose another --output file")
        version = subprocess.run([args.compiler, "--version"], capture_output=True, text=True, timeout=15)
        if version.returncode or "clang" not in version.stdout.lower():
            raise ValueError("Evaluation requires Clang")
        output.parent.mkdir(parents=True, exist_ok=True)
        settings = {"Run status": "in_progress", "Started (UTC)": datetime.now(timezone.utc).isoformat(),
                    "Input report": str(args.input.resolve()),
                    "Input SHA256": hashlib.sha256(report_bytes).hexdigest(),
                    "Source SHA256": metadata["Source SHA256"], "Saved model": metadata.get("Model", "unknown"),
                    "Saved generation compiler": metadata.get("Compiler", "unknown"),
                    "Evaluation compiler": version.stdout.splitlines()[0], "Platform": platform.platform(),
                    "Compiler flags": " ".join(config.CFLAGS),
                    "Bounds-check flags": " ".join([*config.CFLAGS, *BOUNDS_FLAGS]),
                    "Selected kernels": len(kernels), "Selected subset": args.kernels is not None,
                    "Metric": "Check-passing newly vectorized saved winners / nonvectorized originals",
                    "Vectorization definition": "Any positive Clang work-loop remark in target function; excludes nl repetition headers",
                    "Checks": "Bounds-trapping small workload, then full-workload checksum/array differential checks",
                    "Selection": "One saved fastest winner from five attempts; discarded candidates cannot be recovered"}
        with output.open("x", encoding="utf-8"):
            pass
        created_output = True
        write_report(output, settings, rows)
        for index, kernel in enumerate(kernels, 1):
            with tempfile.TemporaryDirectory(prefix=f"b0_vectorization_{kernel}_") as temp:
                row = evaluate_kernel(suite, kernel, saved[kernel], Path(temp), args)
            rows.append(row)
            write_report(output, settings, rows)
            print(f"{index}/{len(kernels)} {kernel}: {row['status']}; new success={row['new_success']}", flush=True)
            if row["status"] == "original_compile_error":
                raise RuntimeError(f"Original {kernel} did not compile: {row['detail']}")
        settings.update({"Run status": "complete", "Finished (UTC)": datetime.now(timezone.utc).isoformat()})
        write_report(output, settings, rows, complete=True)
        print(f"Results: {output}")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        if created_output:
            settings.update({"Run status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                             "Error": str(exc)})
            write_report(output, settings, rows)
        print(f"Vectorization evaluation stopped: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
