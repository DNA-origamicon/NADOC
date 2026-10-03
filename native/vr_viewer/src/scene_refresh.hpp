#pragma once
#include <cstdint>
#include <fstream>
#include <sstream>
#include <string>
#include <iostream>
#include <future>
#include <chrono>

namespace nadoc_vr {
template<class Scene> class SceneRefreshInbox {
 public:
    uint64_t revision() const { return revision_; }
    // Parsing is CPU-only. GL activation and the revision publication remain on
    // the caller's context thread, and the old scene keeps rendering while busy.
    template<class Load, class Apply> void poll(const std::string& eventPath, Load load, Apply apply) {
        pollStaged(eventPath, load, [&](Scene scene) { apply(std::move(scene)); }, [] { return true; });
    }
    // Begin owns the parsed scene; advance performs bounded context-thread work.
    // A revision is acknowledged only after the fully uploaded scene is visible.
    template<class Load, class Begin, class Advance>
    void pollStaged(const std::string& eventPath, Load load, Begin begin, Advance advance) {
        auto progress = [&] {
            try {
                if (!advance()) return;
                revision_ = pendingRevision_;
                std::cout << "VR_SCENE_APPLIED revision=" << revision_ << std::endl;
            } catch (const std::exception& error) {
                std::cerr << "VR scene refresh retained previous scene: " << error.what() << std::endl;
            }
            applying_ = false;
        };
        if (applying_) { progress(); return; }
        if (pending_.valid()) {
            if (pending_.wait_for(std::chrono::seconds(0)) != std::future_status::ready) return;
            try {
                begin(pending_.get());
                applying_ = true;
                progress();
            } catch (const std::exception& error) {
                std::cerr << "VR scene refresh retained previous scene: " << error.what() << std::endl;
            }
            return;
        }
        if (eventPath.empty() || (++frames_ % 15) != 0) return;
        std::ifstream input(eventPath + ".scene");
        std::string record; std::getline(input, record);
        if (record.size() > 4096) return;
        std::istringstream fields(record);
        std::string magic, path, trailing; int version = 0; uint64_t revision = 0;
        if (!(fields >> magic >> version >> revision >> path) || fields >> trailing ||
            magic != "NADOCVR_SCENE" || version != 1 || revision <= revision_ ||
            path != eventPath + ".scene-" + std::to_string(revision)) return;
        pendingRevision_ = revision;
        try { pending_ = std::async(std::launch::async, [load, path] { return load(path); }); }
        catch (const std::exception& error) {
            std::cerr << "VR scene refresh retained previous scene: " << error.what() << std::endl;
        }
    }
 private:
    std::future<Scene> pending_;
    bool applying_ = false;
    uint64_t pendingRevision_ = 0;
    uint64_t revision_ = 0;
    uint32_t frames_ = 0;
};
}
