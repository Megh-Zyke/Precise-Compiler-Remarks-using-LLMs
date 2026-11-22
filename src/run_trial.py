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
