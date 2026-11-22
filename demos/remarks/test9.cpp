// Case 9: an opaque function call in the loop body.
// Clang cannot vectorize across a call it knows nothing about.
extern float mystery(float);
void apply(float* a, int n) {
  for (int i = 0; i < n; i++)
    a[i] = mystery(a[i]);
}