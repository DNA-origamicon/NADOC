#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

namespace nadoc_vr {
struct ShadowLightFrame {
    glm::vec3 direction;
    glm::vec3 up;
};

// Rotate the entire light frame with the head. Choosing an up axis from the
// world-space direction introduces a discontinuity when that choice changes.
// These two head-local vectors are never parallel, including at world poles.
inline ShadowLightFrame headRelativeShadowLight(glm::quat orientation) {
    orientation = glm::normalize(orientation);
    return {orientation * glm::normalize(glm::vec3(-1, 1, 1)),
            orientation * glm::vec3(0, 1, 0)};
}
}

namespace nadoc_vr {
inline constexpr int kShadowMapResolution = 2048;

// Capture the light frame at placement, then keep it fixed in tracking space.
// Head jitter must not move either diffuse lighting or the shadow projection.
// Explicit scene placement/recentering establishes a new upper-left light.
// Optional head following restores dynamic lighting; disabling it freezes the
// last rendered frame so the light does not jump back to its initial direction.
class AnchoredShadowLight {
 public:
    bool headFollowing() const { return headFollowing_; }
    void setHeadFollowing(bool enabled) { headFollowing_ = enabled; }
    void anchor(glm::quat orientation) {
        frame_ = headRelativeShadowLight(orientation);
        initialized_ = true;
    }
    ShadowLightFrame update(glm::quat orientation, bool tracked = true) {
        if (tracked && (!initialized_ || headFollowing_)) anchor(orientation);
        return frame_;
    }
 private:
    bool initialized_ = false;
    bool headFollowing_ = false;
    ShadowLightFrame frame_ = headRelativeShadowLight(glm::quat(1,0,0,0));
};
}
