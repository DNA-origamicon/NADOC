#pragma once
#include <cstdint>
namespace nadoc_vr {
// A local level choice takes precedence over feedback for earlier selections.
class SelectionLevelGuard {
  public:
    void requested(uint64_t lastSelectSequence) { minimum_ = lastSelectSequence + 1; }
    bool accepts(uint64_t feedbackSequence) const { return feedbackSequence >= minimum_; }
  private:
    uint64_t minimum_ = 0;
};
}
