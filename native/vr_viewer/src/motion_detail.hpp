#pragma once
#include <chrono>
#include <cstdlib>
#include <string_view>
#include <vector>
#include <cstdint>

namespace nadoc_vr {
// Reduce lighting cost only while an edit is changing. Both eyes use the decision
// latched at the shadow pass; the timeout cannot split stereo lighting modes.
class MotionDetail {
    using Clock = std::chrono::steady_clock;
    Clock::time_point changed_{};
    bool enabled_ = [] { const char* value=std::getenv("NADOC_VR_MOTION_DETAIL");
        return !value || std::string_view(value)!="0"; }();
    bool coarse_ = [] { const char* value=std::getenv("NADOC_VR_MOTION_MESH");
        return !value || std::string_view(value)!="0"; }();
public:
    bool coarse() const { return reduced && coarse_; }
    // The existing eight-sided cylinder has 16 wall vertices followed by
    // bottom center/ring (16/17) and top center/ring (25/26).
    static void appendCoarseCylinder(std::vector<unsigned short>& indices) {
        for(unsigned short side=0;side<8;side+=2) {
            const unsigned short next=(side+2)%8;
            for(unsigned short index:{static_cast<unsigned short>(2*side),static_cast<unsigned short>(2*side+1),static_cast<unsigned short>(2*next),
                static_cast<unsigned short>(2*side+1),static_cast<unsigned short>(2*next+1),static_cast<unsigned short>(2*next),
                static_cast<unsigned short>(16),static_cast<unsigned short>(17+next),static_cast<unsigned short>(17+side),
                static_cast<unsigned short>(25),static_cast<unsigned short>(26+side),static_cast<unsigned short>(26+next)})indices.push_back(index);
        }
    }
    bool reduced = false;
    void changed(Clock::time_point now=Clock::now()) { changed_=now; }
    void beginFrame(bool preview, Clock::time_point now=Clock::now()) {
        reduced=enabled_ && preview && changed_!=Clock::time_point{} &&
            now-changed_<std::chrono::milliseconds(180);
    }
};
}
