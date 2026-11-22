// Case 6: two stores to overlapping locations (write-after-write).
// Iteration i writes a[i] then a[i+1]; iteration i+1 writes a[i+1] again.
// In scalar order the LAST write to a[j] is b[j]. Doing all the a[i] stores
// first as a vector, then all the a[i+1] stores, would leave c[j-1] instead.
// Expect: not vectorized, the SAME generic "unsafe dependent memory
// operations" remark as case 2, even though this is write-after-write.
void overlapping_stores(float* a, const float* b, const float* c, int n) {
  for (int i = 0; i < n - 1; i++) {
    a[i]     = b[i];
    a[i + 1] = c[i];
  }
}