// Case 2: true loop-carried dependence (read-after-write, distance 1).
// Iteration i reads a[i-1], which iteration i-1 just wrote.
// Expect: not vectorized, "unsafe dependent memory operations".
void prefix(float* a, const float* b, int n) {
  for (int i = 1; i < n; i++)
    a[i] = a[i - 1] + b[i];
}