// Integer metadata only. No molecular coordinates or geometry arithmetic.
#include <cstdint>
extern "C" void nadoc_assign_domains_v1(
    const int64_t* bp, const int64_t* direction, int64_t rows,
    const int64_t* domains, int64_t count, int64_t* owner, uint8_t* opposite) {
  for (int64_t i = 0; i < rows; ++i) {
    owner[i] = -1;
    opposite[i] = 0;
    for (int64_t j = 0; j < count; ++j) {
      const int64_t* d = domains + j * 3;
      if (bp[i] < d[0] || bp[i] > d[1]) continue;
      if (direction[i] == d[2]) owner[i] = j; // existing last-domain-wins rule
      else opposite[i] = 1;
    }
  }
}
