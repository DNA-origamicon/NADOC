#pragma once
#include <algorithm>
#include <cmath>
#include <string>

namespace nadoc_vr {
// Wall time, not frame count: an overloaded or unfocused headset must not
// silently turn a five-second recording into a longer experiment.
struct RecordingClock {
    static constexpr double countdown = 2.0, duration = 5.0;
    double start = 0;
    bool armed = false;
    void arm(double now) { start = now + countdown; armed = true; }
    bool collecting(double now) const { return armed && now >= start && now < start + duration; }
    bool finished(double now) const { return armed && now >= start + duration; }
    std::string label(double now) const {
        if (now < start) return "Starting in " + std::to_string(int(std::ceil(start-now))) + "s";
        return "Recording " + std::to_string(std::max(0,int(std::ceil(start+duration-now)))) + "s";
    }
};
}
