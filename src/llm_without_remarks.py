"""B0: five independent local-Qwen rewrites; save only the fastest correct one.

Default/--dry-run previews the experiment. Inference requires --run.
The sole persistent output is results/results_llm_no_remarks.txt.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import math
import platform
from pathlib import Path
import subprocess
import tempfile

from . import config, llm_local
from . import tsvc_benchmark as benchmark

NO_FEEDBACK = "No compiler feedback is available."


def make_prompt(source, template):
    # Remove TSVC's descriptive optimization hints; keep code/string literals.
    source = benchmark.mask_c(source, comments_only=True)
    return template.format(LOOP_SOURCE=source, FEEDBACK=NO_FEEDBACK)


def select_kernels(status_file, *, kernels=None, non_vectorized_only=False, limit=None):
    with status_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    names = [row["kernel"] for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate kernels in the status CSV")
    if kernels:
        unknown = set(kernels) - set(names)
        if unknown:
            raise ValueError(f"Unknown kernels: {', '.join(sorted(unknown))}")
        if len(kernels) != len(set(kernels)):
            raise ValueError("A kernel was selected more than once")
        selected = list(kernels)
    else:
        selected = [row["kernel"] for row in rows
                    if not non_vectorized_only or row["status"] == "not_vectorized"]
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("No kernels selected")
    return selected


def compiler_version(compiler):
    try:
        proc = subprocess.run([compiler, "--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise benchmark.BenchmarkError(
            f"Cannot run Clang {compiler!r}. Install a Clang toolchain that builds "
            "TSVC (POSIX headers/runtime required) and set CC_BIN or --compiler."
        ) from exc
    if proc.returncode or "clang" not in proc.stdout.lower():
        raise benchmark.BenchmarkError("B0 requires Clang; compiler --version did not identify Clang")
    return proc.stdout.strip()


def faster_correct(current, candidate):
    """Keep only the lowest measured runtime with passing correctness checks."""
    if candidate.get("status") != "ok" or candidate.get("correct") is not True:
        return current
    seconds = candidate.get("seconds")
    if not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds <= 0:
        return current
    if current is None or seconds < current["seconds"]:
        return candidate
    return current


def write_report(path, settings, kernels, winners, attempted):
    """One text file containing settings and only the current winner per kernel."""
    lines = ["B0: local LLM without compiler remarks", ""]
    lines.extend(f"{key}: {value}" for key, value in settings.items())
    for kernel in kernels:
        lines.extend(["", "=" * 72, f"Kernel: {kernel}"])
        winner = winners.get(kernel)
        if winner is None:
            status = "no_correct_rewrite" if attempted.get(kernel) else "not_run"
            lines.append(f"Status: {status}")
            continue
        lines.extend([
            "Status: correct",
            f"Time (seconds): {winner['seconds']:.9g}",
            f"Checksum: {winner['checksum']:.17g}",
            "Rewritten code:", winner["code"],
        ])
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def assess_rewrite(suite, kernel, rewrite, reference_full, reference_check, work, args):
    """Check both workloads. Use the single full-size check's elapsed time."""
    benchmark.validate_rewrite(benchmark.kernel_source(suite, kernel), rewrite, kernel)
    full = benchmark.compile_kernel(suite, kernel, rewrite, work / "full", compiler=args.compiler)
    smaller = benchmark.compile_kernel(
        suite, kernel, rewrite, work / "check", compiler=args.compiler,
        workload=benchmark.CHECK_WORKLOAD,
    )
    for original, candidate in ((reference_check, smaller), (reference_full, full)):
        expected = benchmark.observe(original, timeout=args.timeout)
        actual = benchmark.observe(candidate, timeout=args.timeout)
        match, detail = benchmark.compare_observations(expected, actual)
        if not match:
            return {"status": "incorrect", "correct": False, "detail": detail}
    # actual is the full-size observation: checksum and runtime are from the
    # same invocation. No timing repetitions, median, or separate sample files.
    return {"status": "ok", "correct": True, "seconds": actual.seconds,
            "checksum": actual.checksum, "code": rewrite}


def run_trial(suite, kernel, trial, prompt, model_info, reference_full, reference_check, work, args):
    """Keep this candidate in memory; all compilation files are temporary."""
    try:
        response = llm_local.call_llm(
            prompt, tag=f"{kernel}_B0_trial{trial}", seed=args.seed + trial - 1,
            save_response=False,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return {"status": "llm_error", "correct": False, "detail": str(exc)}
    if response["model_digest"] != model_info["digest"]:
        raise RuntimeError("The installed model changed during the experiment; start a new run")
    if response.get("done_reason") == "length":
        return {"status": "truncated", "correct": False}
    if not response["code"]:
        return {"status": "no_code", "correct": False}
    try:
        return assess_rewrite(
            suite, kernel, response["code"], reference_full, reference_check, work, args,
        )
    except ValueError as exc:
        return {"status": "invalid_rewrite", "correct": False, "detail": str(exc)}
    except benchmark.BenchmarkError as exc:
        return {"status": "evaluation_failed", "correct": False, "detail": str(exc)}


def run_experiment(suite, kernels, template, args):
    output = (args.output or config.ROOT / "results" / "results_llm_no_remarks.txt").resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists; choose another --output file: {output}")
    # Fail on missing infrastructure before making any generation request.
    version = compiler_version(args.compiler)
    model_info = llm_local.get_model_info()
    if not model_info.get("digest"):
        raise RuntimeError("Ollama did not provide the model digest")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the destination exclusively. Later updates replace this one file.
    with output.open("x", encoding="utf-8"):
        pass
    settings = {
        "Run status": "in_progress", "Started (UTC)": datetime.now(timezone.utc).isoformat(),
        "Kernels": len(kernels), "Independent rewrites per kernel": args.trials,
        "Completed kernels": 0, "Completed rewrites": 0, "Correct rewrites": 0,
        "Current kernel": "", "Current rewrite": "",
        "Model": config.LOCAL_MODEL, "Model digest": model_info["digest"],
        "Quantization": model_info.get("details", {}).get("quantization_level", "unknown"),
        "Temperature": config.TEMPERATURE, "Base seed": args.seed,
        "Max output tokens": config.MAX_TOKENS, "Context tokens": config.LOCAL_CONTEXT_TOKENS,
        "Compiler": version.splitlines()[0], "Compiler flags": " ".join(config.CFLAGS),
        "Platform": platform.platform(),
        "Source SHA256": hashlib.sha256(suite.encode("utf-8")).hexdigest(),
        "Prompt SHA256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
        "Timing": "One full-size kernel call per rewrite; keep the fastest correct rewrite",
        "Full workload": str(benchmark.FULL_WORKLOAD), "Check workload": str(benchmark.CHECK_WORKLOAD),
        "Correctness": "Return/checksum and array outputs on both workloads",
        "Float tolerance": f"{benchmark.ABS_TOL} + {benchmark.REL_TOL} * abs(original)",
    }
    winners, attempted = {}, {}
    write_report(output, settings, kernels, winners, attempted)
    try:
        for kernel in kernels:
            source = benchmark.kernel_source(suite, kernel)
            prompt = make_prompt(source, template)
            with tempfile.TemporaryDirectory(prefix=f"b0_{kernel}_") as temporary:
                work = Path(temporary)
                reference_full = benchmark.compile_kernel(
                    suite, kernel, source, work / "original_full", compiler=args.compiler)
                reference_check = benchmark.compile_kernel(
                    suite, kernel, source, work / "original_check", compiler=args.compiler,
                    workload=benchmark.CHECK_WORKLOAD)
                for binary in (reference_full, reference_check):
                    observed = benchmark.observe(binary, timeout=args.timeout)
                    valid, detail = benchmark.compare_observations(observed, observed)
                    if not valid:
                        raise benchmark.BenchmarkError(f"Invalid reference {kernel}: {detail}")
                for trial in range(1, args.trials + 1):
                    with tempfile.TemporaryDirectory(prefix="b0_rewrite_") as trial_work:
                        candidate = run_trial(
                            suite, kernel, trial, prompt, model_info,
                            reference_full, reference_check, Path(trial_work), args)
                    attempted[kernel] = trial
                    winners[kernel] = faster_correct(winners.get(kernel), candidate)
                    settings["Completed rewrites"] += 1
                    settings["Correct rewrites"] += int(candidate.get("correct") is True)
                    settings["Current kernel"] = kernel
                    settings["Current rewrite"] = f"{trial}/{args.trials}"
                    if trial == args.trials:
                        settings["Completed kernels"] += 1
                    write_report(output, settings, kernels, winners, attempted)
                    print(f"{kernel} B0 rewrite {trial}/{args.trials}: {candidate['status']}", flush=True)
                    del candidate
    except BaseException as exc:
        settings["Run status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        settings["Error"] = str(exc)
        write_report(output, settings, kernels, winners, attempted)
        raise
    settings["Run status"] = "complete"
    settings["Finished (UTC)"] = datetime.now(timezone.utc).isoformat()
    write_report(output, settings, kernels, winners, attempted)
    return output


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Actually generate/evaluate rewrites")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--kernels", nargs="+", help="Explicit kernel names, in this order")
    selection.add_argument("--all-kernels", action="store_true", help="All 151 kernels (the default)")
    selection.add_argument("--non-vectorized-only", action="store_true", help="Only the 66 previously nonvectorized kernels")
    parser.add_argument("--limit", type=int, help="Use only the first N selected kernels")
    parser.add_argument("--trials", type=int, default=config.TRIALS, help="Independent rewrites per kernel (default: 5)")
    parser.add_argument("--seed", type=int, default=583)
    parser.add_argument("--timeout", type=float, default=120, help="Seconds per executable invocation")
    parser.add_argument("--compiler", default=config.CC)
    parser.add_argument("--output", type=Path, help="New text output file; existing files are never overwritten")
    args = parser.parse_args(argv)
    if args.trials <= 0 or args.timeout <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error("trials, timeout, and limit must be positive")
    return args


def main(argv=None):
    args = parse_args(argv)
    suite = (config.TSVC_SRC / "tsvc.c").read_text(encoding="utf-8")
    template = (config.ROOT / "prompts" / "agent.txt").read_text(encoding="utf-8")
    kernels = select_kernels(config.ROOT / "results" / "loop_status.csv",
                             kernels=args.kernels, non_vectorized_only=args.non_vectorized_only, limit=args.limit)
    for kernel in kernels:
        benchmark.kernel_source(suite, kernel)
    if not args.run:
        print(f"PREVIEW ONLY: {len(kernels)} kernels x {args.trials} rewrites = {len(kernels) * args.trials} generations")
        print("Kernels:", ", ".join(kernels))
        print(f"Local model: {config.LOCAL_MODEL}; temperature: {config.TEMPERATURE}")
        print("Output: one results_llm_no_remarks.txt file with the fastest correct code/time/checksum per kernel.")
        print("No model requests, compilation, benchmark execution, or result files.")
        print(f"\nExample B0 prompt ({kernels[0]}):\n")
        print(make_prompt(benchmark.kernel_source(suite, kernels[0]), template))
        return 0
    try:
        print("Results:", run_experiment(suite, kernels, template, args))
    except (benchmark.BenchmarkError, RuntimeError, OSError, ValueError) as exc:
        print(f"B0 stopped: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
