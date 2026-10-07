#pragma once
#include <filesystem>
#include <fstream>
#include <string>

namespace nadoc_vr {
// A failed molecular check invalidates this entire viewing session. Neither a
// cancelled menu nor an older in-flight upload can release the latch. Recovery
// requires a new viewer and a freshly validated canonical startup snapshot.
class PlacementIntegrityLatch {
 public:
    bool blocked() const { return blocked_; }
    const std::string& detail() const { return detail_; }
    void reject(std::string message) {
        if (!blocked_) detail_ = std::move(message);
        blocked_ = true;
    }
    void poll(const std::string& eventPath) {
        if (blocked_ || eventPath.empty()) return;
        const auto path = eventPath + ".placement-error";
        std::error_code error;
        const bool exists = std::filesystem::exists(path, error);
        if (error) { reject("Cannot verify DNA positioning status"); return; }
        if (!exists) return;
        std::ifstream input(path);
        std::string magic, token, message; int version = 0;
        if (!(input >> magic >> version >> token) || magic != "NADOCVR_PLACEMENT_ERROR" || version != 1) {
            reject("Invalid DNA positioning failure status"); return;
        }
        std::getline(input, message); std::getline(input, message);
        reject(message.empty() ? "DNA positioning check failed" : message);
    }
 private:
    bool blocked_ = false;
    std::string detail_;
};
}
