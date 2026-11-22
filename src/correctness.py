"""T1.5: compare original and rewritten loop outputs on random inputs.

TODO (not written yet). Plan:
  1. Wrap each kernel (original and rewrite) in a tiny driver that fills the
     arrays with seeded random data, runs the kernel, prints a checksum or the
     output arrays.
  2. Compare: exact for integers, small stated relative tolerance for floats.
  3. Test the checker on a deliberately broken rewrite (it must fail) and on a
     correct one (it must pass) before trusting it.
"""
raise NotImplementedError("T1.5: correctness checker not written yet")
