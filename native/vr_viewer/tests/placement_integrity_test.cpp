#include "placement_integrity.hpp"
#include <cassert>
#include <chrono>
#include <fstream>

int main() {
    const auto root = std::filesystem::temp_directory_path() / ("nadoc-placement-latch-" +
        std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directory(root);
    const auto event = (root / "event").string();
    const auto signal = event + ".placement-error";
    nadoc_vr::PlacementIntegrityLatch latch;
    latch.poll(event); assert(!latch.blocked());
    std::ofstream(signal) << "NADOCVR_PLACEMENT_ERROR 1 incident\nWrong O5 position\nreport.html\n";
    latch.poll(event); assert(latch.blocked()); assert(latch.detail() == "Wrong O5 position");
    std::filesystem::remove(signal);
    latch.poll(event); assert(latch.blocked()); // Deletion/cancel cannot release it.
    nadoc_vr::PlacementIntegrityLatch freshSession;
    freshSession.poll(event); assert(!freshSession.blocked());
    std::ofstream(signal) << "corrupt";
    freshSession.poll(event); assert(freshSession.blocked());
    std::filesystem::remove_all(root);
}
