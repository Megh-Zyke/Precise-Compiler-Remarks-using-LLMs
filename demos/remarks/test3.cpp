// Case 3: write-after-read (anti) dependence, distance 1.
// Iteration i reads a[i+1]; iteration i+1 later overwrites it.
// Loading the old values as a vector first is still correct, so Clang
// vectorizes it. LLVM's analysis calls this dependence "Forward".
void shift(float* a, const float* b, int n) {
  for (int i = 0; i < n - 1; i++)
    a[i] = a[i + 1] + b[i];
}