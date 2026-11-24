"""T1.8: one loop, one arm, one trial -> one row in results/results.csv.

TODO (not written yet). Steps:
  B0 now has a dedicated implementation in src/llm_without_remarks.py.
  This generic multi-arm entry point remains unimplemented.
  1. Read prompts/agent.txt; fill {LOOP_SOURCE} and {FEEDBACK}
     (B0: "No compiler feedback is available."; B1: remarks/clang/<loop>.txt;
      B2: remarks/handwritten/<loop>.txt; Ours: remarks/generated/<loop>.txt).
     remarks/generated/ is LLVM LoopAccess output from src/remark_gen.py, not
     an LLM. prompts/remark_writer.txt has not been run.
  2. call_llm(...) and take the code block.
  3. Compile it (compile_check), check vectorization, check correctness
     (src/correctness.py), time original vs rewrite, append the CSV row.
"""
raise NotImplementedError("T1.8: agent driver not written yet")
