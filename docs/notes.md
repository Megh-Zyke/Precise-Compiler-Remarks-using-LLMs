# Notes

## LLVM dependence output (T2.1)

Ran on this machine with Homebrew clang and opt 23.1.1 (`src/remark_gen.py`).
Apple clang 15 is also installed and does not ship `opt`. The committed
`remarks/clang/` files were produced earlier on another machine (paths under
`/home/meghss`) and were not regenerated.

Command, matching the plan for this file:

    clang -g -O1 -fno-vectorize -fno-slp-vectorize -fstrict-aliasing -emit-llvm -S tsvc.c
    opt -passes='print<access-info>' -disable-output tsvc.ll

`-O1` is required. At `-O0` the loop pointers are still allocas and LoopAccess
has nothing useful to say. `-fno-vectorize` keeps the scalar loop.

What `s212` actually prints:

    Report: unsafe dependent memory operations in loop.
    Backward loop carried data dependence.
    Memory location is the same as accessed at tsvc.c:986:13
    Dependences:
      Backward:
          store float %20, ptr %18, align 4, !dbg !449 ->
          %23 = load float, ptr %22, align 4, !dbg !451
      Forward:
          %19 = load float, ptr %18 ->
          store float %20, ptr %18

The `!dbg` numbers in that dump are not module metadata ids. `opt` renumbers
them when it prints one instruction. `src/remark_gen.py` matches the
instruction text back to the function body in the `.ll` file, then reads that
instruction's real `!DILocation` for the line and column. For `s212` that is
the store of `a[i]` at line 986 and the load of `a[i + 1]` at line 987.

Kind and distance come only from those two subscripts and the innermost `for`
step. Store index minus load index greater than zero is read-after-write;
less than zero is write-after-read; two stores are write-after-write. The
iteration distance is that index gap divided by the step, and only when the
step divides the gap. Anything else, including `a[LEN_1D/2]`, stays `unknown`.
Same-iteration `a[i] *= a[i]` pairs are not emitted.

Of the 66 kernels in `results/loop_status.csv` with status `not_vectorized`,
this run named a dependence for 13 and wrote `unknown` for the other 53.
47 of those 53 are cases where LLVM 23 said the dependences are safe (or safe
up to a stated vector width) and listed no unsafe direction. Those generated
files are `unknown` on purpose. See `results/dependence_coverage.csv`.

## Hand-written remarks

`remarks/handwritten/` is a reviewed subset, not the whole benchmark.
`results/handwritten_categories.csv` records the kind, the lines, and whether
LoopAccess agreed. Columns in the handwritten files are the start of the array
expression. Columns in `remarks/generated/` are LLVM's debug column, which for
a store is often the `=`.

`s221`, `s321`, and `s322` are read-after-write in the source. LLVM 23 did not
call them unsafe (`s322`: safe with a maximum vector width of 64 bits), so
their generated remarks stay `unknown`. The handwritten files still name the
recurrence. That disagreement is the gap, not a measured speedup.

No LLM call was made. `prompts/remark_writer.txt` was not run.

## Correctness checker (T1.5)

`python3 -m src.correctness` passed on this machine:

- unchanged `s000` checksum 52000, match
- `a[i] = (1 + b[i])` checksum 52000, match
- `a[i] = b[i] + 2` checksum 52320, no match

52000 is `sum(3 + i)` for `i` in `0..319`, so the loop body did run. The
checker uses `iterations=400`, `LEN_1D=320`, `LEN_2D=40`. Those checksums are
not the ones in `results/tsvc_vec_baseline.txt`.

## Findings / dead ends

- `print<access-info>` on the whole `tsvc.c` does not use stable `!dbg` ids.
  Matching instruction text is what works.
- LLVM 23 treats many loops the older Clang remarks left unvectorized as
  dependence-safe, including the first-order recurrence `s321`. The generated
  remark does not invent a kind for those.
- The trial driver in `src/run_trial.py` is still unwritten, so there is no
  arm-by-arm speedup table. `results/results.csv` is still only the header.
