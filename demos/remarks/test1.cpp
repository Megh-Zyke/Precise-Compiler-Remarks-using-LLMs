// Case 1: the easy case. No dependence, no aliasing (__restrict promises it).
// Expect: "vectorized loop".
void add(float* __restrict a, const float* __restrict b, const float* __restrict c, int n) {
  for (int i = 0; i < n; i++)
    a[i] = b[i] + c[i];
}