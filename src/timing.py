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
