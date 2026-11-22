// Case 8: the loop can exit early, so the trip count is not known up front.
int find(const int* a, int n, int x) {
  for (int i = 0; i < n; i++)
    if (a[i] == x)
      return i;
  return -1;
}