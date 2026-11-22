// Case 7: floating-point sum. Vectorizing reorders the additions, which
// changes the rounding, so Clang refuses unless -ffast-math (or similar).
float sum(const float* a, int n) {
  float s = 0.0f;
  for (int i = 0; i < n; i++)
    s += a[i];
  return s;
}