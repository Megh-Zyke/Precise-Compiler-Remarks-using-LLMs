"""Structured remarks from LLVM loop-access analysis (task T2.1).

Compiles third_party/TSVC_2/src/tsvc.c with debug info, runs

    opt -passes='print<access-info>'

and writes remarks/generated/<kernel>.txt for every kernel that
results/loop_status.csv marks not_vectorized. The text uses the format in
prompts/remark_writer.txt. A field this pass cannot establish is "unknown".

This does not call an LLM. prompts/remark_writer.txt is the same format
filled by a model, and that pass has not been run.

Run from the repo root:  python3 -m src.remark_gen
"""
import csv
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config

GENERATED_DIR = config.ROOT / "remarks" / "generated"
COVERAGE_CSV = config.ROOT / "results" / "dependence_coverage.csv"

FIX = {
    "write-after-read": (
        "Save the value that is read ahead into a temporary before the "
        "write that overwrites it, then use the temporary."
    ),
    "read-after-write": (
        "A later iteration reads the value this iteration writes. A "
        "temporary of the loaded value does not remove that dependence."
    ),
    "write-after-write": (
        "More than one iteration writes the same element. The store that "
        "is last in scalar order has to be the one that remains."
    ),
}

UNKNOWN_BLOCK = (
    "conflict: unknown\n"
    "kind: unknown\n"
    "distance: unknown\n"
    "loop-carried: unknown\n"
    "suggested fix: unknown\n"
)


def llvm_tools():
    """Return (clang, opt) from one LLVM build. Apple clang does not ship opt."""
    opt = os.environ.get("OPT_BIN")
    candidates = []
    if opt:
        candidates.append(Path(opt))
    found = shutil.which("opt")
    if found:
        candidates.append(Path(found))
    candidates += [
        Path("/opt/homebrew/opt/llvm/bin/opt"),
        Path("/usr/local/opt/llvm/bin/opt"),
    ]
    for path in candidates:
        clang = Path(os.environ["LLVM_CC"]) if os.environ.get("LLVM_CC") else path.with_name("clang")
        if path.exists() and clang.exists():
            return str(clang), str(path)
    raise SystemExit(
        "opt not found. Install LLVM and set OPT_BIN to its opt binary. "
        "Apple clang does not ship opt, so this pass did not run."
    )


def tool_version(path):
    proc = subprocess.run([path, "--version"], capture_output=True, text=True)
    line = (proc.stdout or proc.stderr).splitlines()
    return line[0] if line else path


def expr_at(line, col):
    """Array expression covering a 1-based column, or None."""
    if not line or not col or col < 1:
        return None
    idx = col - 1
    spans = []
    i = 0
    while i < len(line):
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", line[i:])
        if not match:
            i += 1
            continue
        j = i + match.end()
        if j >= len(line) or line[j] != "[":
            i = j
            continue
        k = j
        ok = True
        while k < len(line) and line[k] == "[":
            depth = 0
            closed = False
            while k < len(line):
                if line[k] == "[":
                    depth += 1
                elif line[k] == "]":
                    depth -= 1
                    if depth == 0:
                        k += 1
                        closed = True
                        break
                k += 1
            if not closed:
                ok = False
                break
        if not ok:
            break
        spans.append((i, k, line[i:k]))
        i = k
    def distance(span):
        start, end, _ = span
        if start <= idx < end:
            return (0, 0, end - start)
        if idx >= end:
            # Subscript sits left of the column. Prefer that side on a tie:
            # a store's debug column is often the '=' rather than the array.
            return (idx - (end - 1), 0, end - start)
        return (start - idx, 1, end - start)

    if not spans:
        return None
    start, end, text = min(spans, key=distance)
    if start <= idx < end or distance((start, end, text))[0] <= 6:
        return text
    return None


def _split_semicolons(text):
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def loop_step(lines, line_no):
    """Innermost `for` that encloses line_no. Returns (var, step or None)."""
    i = line_no - 1
    while i >= 0:
        if re.search(r"\bfor\s*\(", lines[i]):
            header = lines[i].strip()
            extra = i
            while header.count("(") > header.count(")") and extra + 1 < len(lines):
                extra += 1
                header += " " + lines[extra].strip()
            return _parse_for(header)
        i -= 1
    return None, None


def _parse_for(header):
    match = re.search(r"\bfor\s*\((.*)\)", header)
    if not match:
        return None, None
    parts = _split_semicolons(match.group(1))
    if len(parts) < 3:
        return None, None
    init = re.search(r"(?:int\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", parts[0])
    if not init:
        return None, None
    var = init.group(1)
    inc = parts[2].strip()
    if re.fullmatch(rf"{var}\s*\+\+", inc) or re.fullmatch(rf"\+\+\s*{var}", inc):
        return var, 1
    step = re.fullmatch(rf"{var}\s*\+=\s*(\d+)", inc)
    if step:
        return var, int(step.group(1))
    return var, None


def _parse_index(inner):
    compact = re.sub(r"\s+", "", inner)
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)([+-]\d+)?", compact)
    if not match:
        return None
    return match.group(1), int(match.group(2) or 0)


def parse_subscript(expr):
    """'aa[j-1][i]' -> ('aa', [('j', -1), ('i', 0)]). None if it is not affine."""
    expr = expr.strip()
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", expr)
    if not match:
        return None
    base, rest, dims = match.group(1), expr[match.end():], []
    while rest.startswith("["):
        depth = 0
        closed_at = None
        for i, ch in enumerate(rest):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    closed_at = i
                    break
        if closed_at is None:
            return None
        parsed = _parse_index(rest[1:closed_at])
        if parsed is None:
            return None
        dims.append(parsed)
        rest = rest[closed_at + 1:]
    if rest.strip() or not dims:
        return None
    return base, dims


def _offset_delta(store_expr, load_expr, loop_var):
    """store index minus load index along loop_var, or None."""
    store = parse_subscript(store_expr)
    load = parse_subscript(load_expr)
    if not store or not load or store[0] != load[0] or len(store[1]) != len(load[1]):
        return None
    delta = None
    for (store_var, store_off), (load_var, load_off) in zip(store[1], load[1]):
        if store_var != load_var:
            return None
        if store_off == load_off:
            continue
        if store_var != loop_var or delta is not None:
            return None
        delta = store_off - load_off
    return 0 if delta is None else delta


def _scale(index_delta, step):
    if step is None or step <= 0 or index_delta % step != 0:
        return None, "unknown"
    distance = index_delta // step
    return distance, ("no" if distance == 0 else "yes")


def classify_pair(op_a, expr_a, op_b, expr_b, loop_var, step):
    """Return (kind, distance or None, loop-carried) for one dependence pair."""
    stores = [(op, expr) for op, expr in ((op_a, expr_a), (op_b, expr_b)) if op == "store"]
    loads = [(op, expr) for op, expr in ((op_a, expr_a), (op_b, expr_b)) if op == "load"]
    if len(stores) == 2:
        delta = _offset_delta(stores[0][1], stores[1][1], loop_var)
        if delta is None:
            return "unknown", None, "unknown"
        distance, carried = _scale(abs(delta), step)
        if distance is None or distance == 0:
            return "unknown", distance, carried
        return "write-after-write", distance, carried
    if len(stores) != 1 or len(loads) != 1:
        return "unknown", None, "unknown"
    signed = _offset_delta(stores[0][1], loads[0][1], loop_var)
    if signed is None:
        return "unknown", None, "unknown"
    if signed > 0:
        kind, index_delta = "read-after-write", signed
    elif signed < 0:
        kind, index_delta = "write-after-read", -signed
    else:
        return "unknown", 0, "no"
    distance, carried = _scale(index_delta, step)
    if distance is None or carried != "yes":
        return "unknown", distance, carried
    return kind, distance, carried


def _self_check():
    assert expr_at("            a[i] *= c[i];", 13) == "a[i]"
    assert expr_at("            a[i] *= c[i];", 18) == "a[i]"
    assert expr_at("            b[i] += a[i + 1] * d[i];", 21) == "a[i + 1]"
    two_d = "                aa[j][i] = aa[j-1][i] + cc[j][i];"
    col = two_d.index("aa[j-1][i]") + 1
    assert expr_at(two_d, col + 3) == "aa[j-1][i]"
    assert classify_pair("store", "a[i]", "load", "a[i + 1]", "i", 1) == (
        "write-after-read", 1, "yes")
    assert classify_pair("store", "a[i]", "load", "a[i-1]", "i", 1) == (
        "read-after-write", 1, "yes")
    assert classify_pair("store", "a[i]", "store", "a[i + 1]", "i", 1) == (
        "write-after-write", 1, "yes")
    assert classify_pair("store", "aa[j][i]", "load", "aa[j-1][i]", "j", 1) == (
        "read-after-write", 1, "yes")
    assert classify_pair("store", "a[i]", "load", "a[i + 1]", "i", 5)[0] == "unknown"
    assert classify_pair("load", "a[i + 5]", "store", "a[i]", "i", 5) == (
        "write-after-read", 1, "yes")
    header = "        for (int i = 0; i < LEN_1D - 5; i += 5) {"
    assert _parse_for(header) == ("i", 5)
    assert _parse_for("        for (int j = 1; j < LEN_2D; j++) {") == ("j", 1)


def _normalize_inst(text):
    text = text.strip()
    text = re.sub(r"\s*->\s*$", "", text)
    text = re.sub(r",?\s*![A-Za-z0-9.]+\s+!\d+", "", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(",")
    return text


def _opcode(inst):
    if inst.startswith("store "):
        return "store"
    if "= load " in f" {inst}" or inst.startswith("load "):
        return "load"
    return None


def parse_ir(ll_text):
    """Map each function's memory instruction (metadata stripped) to (line, col)."""
    locations = {}
    for match in re.finditer(r"(?m)^!(\d+) = (?:distinct )?(!DILocation\(.*)$", ll_text):
        loc = re.search(r"line: (\d+), column: (\d+)", match.group(2))
        if loc and int(loc.group(1)) > 0:
            locations[match.group(1)] = (int(loc.group(1)), int(loc.group(2)))

    functions = {}
    starts = list(re.finditer(r"(?m)^define ", ll_text))
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(ll_text)
        chunk = ll_text[start.start():end]
        name = re.match(r"define [^@]*@([A-Za-z0-9_.]+)\(", chunk)
        if not name:
            continue
        insts = {}
        ambiguous = set()
        for line in chunk.splitlines():
            if line == "}":
                break
            dbg = re.search(r"!dbg !(\d+)", line)
            if not dbg or dbg.group(1) not in locations:
                continue
            key = _normalize_inst(line)
            if key in insts:
                ambiguous.add(key)
            else:
                insts[key] = locations[dbg.group(1)]
        for key in ambiguous:
            insts.pop(key, None)
        functions[name.group(1)] = insts
    return functions


def parse_access_info(text):
    """function name -> list of loop dicts with report text and dependences."""
    parts = re.split(
        r"Printing analysis 'Loop Access Analysis' for function '([^']+)':\n",
        text)
    out = {}
    for name, body in zip(parts[1::2], parts[2::2]):
        loops = []
        for chunk in re.split(r"(?m)^  :\s*$", body):
            if "Report:" not in chunk and "Memory dependences" not in chunk:
                continue
            report = chunk.split("Dependences:", 1)[0].strip()
            deps = []
            for match in re.finditer(
                    r"(?m)^      ([A-Za-z]+):\s*\n          (.+)\n          (.+)$",
                    chunk):
                deps.append({
                    "direction": match.group(1),
                    "earlier": _normalize_inst(match.group(2)),
                    "later": _normalize_inst(match.group(3)),
                })
            loops.append({"report": report, "deps": deps})
        out[name] = loops
    return out


def _wanted_direction(report):
    if re.search(r"\bBackward\b", report):
        return "Backward"
    if re.search(r"\bForward\b", report):
        return "Forward"
    if re.search(r"\bUnknown\b", report):
        return "Unknown"
    return None


def _side(expr, line, col):
    if line is None:
        return "unknown"
    return f"{expr or 'unknown'}, {line}, {col}"


def _block(left, right, kind, distance, carried):
    return (
        f"conflict: {left} <-> {right}\n"
        f"kind: {kind}\n"
        f"distance: {'unknown' if distance is None else distance}\n"
        f"loop-carried: {carried}\n"
        f"suggested fix: {FIX.get(kind, 'unknown')}\n"
    )


def remarks_for_function(loops, insts, source_lines):
    """Return (remark text, kinds, note)."""
    blocks = []
    kinds = []
    notes = []
    saw_unsafe = False
    for loop in loops:
        report = loop["report"]
        direction = _wanted_direction(report)
        if direction is None:
            continue
        saw_unsafe = True
        carried_hint = "yes" if "loop carried" in report.lower() else "unknown"
        for dep in loop["deps"]:
            if dep["direction"] != direction:
                continue
            located = []
            for inst in (dep["earlier"], dep["later"]):
                line_col = insts.get(inst)
                if line_col is None:
                    located.append((None, None, None, _opcode(inst)))
                    continue
                line, col = line_col
                src = source_lines[line - 1] if 1 <= line <= len(source_lines) else ""
                located.append((expr_at(src, col), line, col, _opcode(inst)))
            (expr_a, line_a, col_a, op_a), (expr_b, line_b, col_b, op_b) = located
            if line_a is None and line_b is None:
                notes.append("instruction not found in IR")
                continue
            anchor = line_a or line_b
            loop_var, step = loop_step(source_lines, anchor)
            kind, distance, carried = ("unknown", None, carried_hint)
            if expr_a and expr_b and op_a and op_b:
                kind, distance, carried = classify_pair(
                    op_a, expr_a, op_b, expr_b, loop_var, step)
                if carried == "unknown":
                    carried = carried_hint
                if kind == "unknown":
                    distance = None
            if kind == "unknown" and carried == "no":
                continue
            if expr_a and expr_b and expr_a == expr_b and distance in (0, None) and kind == "unknown":
                continue
            order = sorted(
                [(expr_a, line_a, col_a), (expr_b, line_b, col_b)],
                key=lambda item: (item[1] is None, item[1] or 0, item[2] or 0),
            )
            blocks.append(_block(
                _side(*order[0]), _side(*order[1]), kind, distance, carried))
            kinds.append(kind)
    if not blocks:
        note = "no unsafe dependence listed" if not saw_unsafe else "; ".join(notes)
        return UNKNOWN_BLOCK, ["unknown"], note
    return "\n".join(blocks), kinds, "; ".join(notes)


def _short_report(loops):
    bits = []
    for loop in loops:
        report = re.sub(r"\s+", " ", loop["report"])
        if "not the innermost" in report:
            continue
        bits.append(report[:180])
    return " | ".join(bits)


def not_vectorized_kernels():
    path = config.ROOT / "results" / "loop_status.csv"
    if not path.exists():
        raise SystemExit(f"{path} not found; run python3 -m src.filter_loops first")
    names = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["status"] == "not_vectorized":
                names.append(row["kernel"])
    return names


def build_remarks(clang, opt):
    source = config.TSVC_SRC / "tsvc.c"
    if not source.exists():
        raise SystemExit(f"{source} not found; run: git submodule update --init")
    source_lines = source.read_text().splitlines()
    with tempfile.TemporaryDirectory(prefix="remark_gen_") as tmp:
        ll_path = Path(tmp) / "tsvc.ll"
        compile_cmd = [
            clang, "-g", "-O1", "-fno-vectorize", "-fno-slp-vectorize",
            "-fstrict-aliasing", "-emit-llvm", "-S",
            "-I", str(config.TSVC_SRC), str(source), "-o", str(ll_path),
        ]
        compiled = subprocess.run(compile_cmd, capture_output=True, text=True)
        if compiled.returncode != 0:
            raise SystemExit(compiled.stderr[-2000:])
        analyzed = subprocess.run(
            [opt, "-passes=print<access-info>", "-disable-output", str(ll_path)],
            capture_output=True, text=True)
        if analyzed.returncode != 0:
            raise SystemExit(analyzed.stderr[-2000:])
        functions = parse_ir(ll_path.read_text())
        access = parse_access_info(analyzed.stderr)
    return source_lines, functions, access


def main():
    _self_check()
    clang, opt = llvm_tools()
    print("clang:", tool_version(clang))
    print("opt:  ", tool_version(opt))
    kernels = not_vectorized_kernels()
    source_lines, functions, access = build_remarks(clang, opt)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    named = 0
    for kernel in kernels:
        text, kinds, note = remarks_for_function(
            access.get(kernel, []), functions.get(kernel, {}), source_lines)
        (GENERATED_DIR / f"{kernel}.txt").write_text(text)
        if any(kind != "unknown" for kind in kinds):
            named += 1
        report = _short_report(access.get(kernel, []))
        if kernel not in access:
            note = (note + "; " if note else "") + "no LoopAccess output"
        rows.append((kernel, ";".join(kinds), report, note))

    with COVERAGE_CSV.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["kernel", "kinds", "laa_report", "note"])
        writer.writerows(rows)

    s212 = (GENERATED_DIR / "s212.txt").read_text()
    if ("kind: write-after-read" not in s212 or "distance: 1" not in s212
            or "a[i]" not in s212 or "a[i + 1]" not in s212):
        raise SystemExit("s212 remark did not match the known dependence:\n" + s212)
    s321 = (GENERATED_DIR / "s321.txt").read_text()
    if "kind: read-after-write" in s321 or "kind: write-after-read" in s321:
        raise SystemExit(
            "s321: LLVM reported no unsafe dependence; refusing to invent one:\n" + s321)

    print(f"not_vectorized {len(kernels)}")
    print(f"named_dependence {named}")
    print(f"unknown_only {len(kernels) - named}")
    print(f"wrote {GENERATED_DIR} and {COVERAGE_CSV}")


if __name__ == "__main__":
    main()
