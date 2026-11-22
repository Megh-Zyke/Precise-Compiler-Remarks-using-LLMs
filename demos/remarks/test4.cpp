// Case 4: two pointers that MIGHT overlap (no __restrict).
// Clang still vectorizes. LLVM's analysis says "safe with run-time checks":
// it can emit a check that a and b do not overlap and fall back otherwise.
// The remark itself says only "vectorized loop"; the check is not mentioned.
void copy_add(float* a, const float* b, int n) {
  for (int i = 0; i < n; i++)
    a[i] = b[i] + 1.0f;
}