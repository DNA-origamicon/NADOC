#pragma once
#include "trajectory.hpp"
#include <algorithm>
#include <optional>

namespace nadoc_vr {
// A bounded receive buffer: two endpoints and the newest pending snapshot.
// Display time carries across ready segments; starvation holds an exact endpoint.
class CoordinatePlayback {
public:
    void push(const CoordinateFrame& frame, bool playing, double now) {
        const double duration = receivedAt_ ? std::clamp(now - *receivedAt_, 0.033, 0.5) : 0.125;
        receivedAt_ = now;
        if (!playing || from_.positions.empty() || frame.positions.size() != from_.positions.size() ||
            frame.frameCount != from_.frameCount || frame.frameIndex < latestIndex_) {
            from_ = frame; output_ = frame.positions; active_ = pendingReady_ = false; dirty_ = true;
        } else {
            pending_ = frame; pendingDuration_ = duration; pendingReady_ = true;
            if (!active_) start(now);
        }
        latestIndex_ = frame.frameIndex;
    }
    void pause() {
        if (pendingReady_) from_ = pending_;
        else if (active_) from_ = to_;
        else return;
        output_ = from_.positions; active_ = pendingReady_ = false; dirty_ = true;
    }
    void clear() { *this = CoordinatePlayback{}; }
    bool sample(double now) {
        if (active_) {
            if (now >= at_ + duration_) {
                const double boundary = at_ + duration_;
                std::swap(from_, to_); active_ = false;
                if (pendingReady_) start(std::max(boundary, now - pendingDuration_));
                else { output_ = from_.positions; dirty_ = true; }
            }
            if (active_) {
                const float t = static_cast<float>(std::clamp((now - at_) / duration_, 0.0, 1.0));
                output_.resize(from_.positions.size());
                for (size_t i = 0; i < output_.size(); ++i)
                    for (size_t j = 0; j < 3; ++j)
                        output_[i][j] = from_.positions[i][j] + (to_.positions[i][j] - from_.positions[i][j]) * t;
                dirty_ = true;
            }
        }
        const bool changed = dirty_; dirty_ = false; return changed;
    }
    const auto& positions() const { return output_; }
private:
    void start(double at) {
        std::swap(to_, pending_); duration_ = pendingDuration_; at_ = at;
        pendingReady_ = false; active_ = true;
    }
    CoordinateFrame from_, to_, pending_;
    std::vector<std::array<float, 3>> output_;
    std::optional<double> receivedAt_;
    std::uint32_t latestIndex_ = 0;
    double at_ = 0, duration_ = 0.125, pendingDuration_ = 0.125;
    bool active_ = false, pendingReady_ = false, dirty_ = false;
};
} // namespace nadoc_vr
