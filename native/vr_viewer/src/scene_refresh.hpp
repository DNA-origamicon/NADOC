#pragma once
#include <cstdint>
#include <fstream>
#include <sstream>
#include <string>
#include <iostream>

namespace nadoc_vr {
class SceneRefreshInbox {
 public:
    uint64_t revision() const { return revision_; }
    template<class Apply> void poll(const std::string& eventPath, Apply apply) {
        if (eventPath.empty() || (++frames_ % 15) != 0) return;
        std::ifstream input(eventPath + ".scene");
        std::string record; std::getline(input, record);
        if (record.size() > 4096) return;
        std::istringstream fields(record);
        std::string magic, path, trailing; int version = 0; uint64_t revision = 0;
        if (!(fields >> magic >> version >> revision >> path) || fields >> trailing ||
            magic != "NADOCVR_SCENE" || version != 1 || revision <= revision_ ||
            path != eventPath + ".scene-" + std::to_string(revision)) return;
        try {
            apply(path);
            revision_ = revision;
            std::cout << "VR_SCENE_APPLIED revision=" << revision << std::endl;
        } catch (const std::exception& error) {
            // Old scene stays live; a transient rename/read race is retried.
            std::cerr << "VR scene refresh retained previous scene: " << error.what() << std::endl;
        }
    }
 private:
    uint64_t revision_ = 0;
    uint32_t frames_ = 0;
};
}
