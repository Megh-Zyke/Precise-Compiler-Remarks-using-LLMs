// Case 5: dependence distance known only at run time (k).
// Clang still vectorizes. LLVM's analysis says "safe with run-time checks":
// it emits a check on k and falls back to the scalar loop if k is too small.
// Again the remark only says "vectorized loop".
void shifted(float* a, int k, int n) {
  for (int i = 0; i < n; i++)
    a[i + k] = a[i] + 1.0f;
}