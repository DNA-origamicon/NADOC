#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <cmath>

namespace nadoc_vr {

struct HandPose {
    bool valid = false;
    bool pressed = false;
    glm::vec3 position{};
    glm::quat orientation{1.0F, 0.0F, 0.0F, 0.0F};
};

enum class ManipulationMode { none, left, right, two_hand };

inline glm::mat4 poseMatrix(const HandPose& pose) {
    return glm::translate(glm::mat4(1.0F), pose.position) * glm::toMat4(pose.orientation);
}

/** Model-viewer manipulation with transition snapshots to prevent jumps.
 *
 * One trigger applies the controller's rigid delta to the model. Two triggers
 * scale uniformly around their midpoint while also following that midpoint.
 */
class SceneManipulator {
  public:
    ManipulationMode update(const std::array<HandPose, 2>& hands) {
        const bool left = hands[0].valid && hands[0].pressed;
        const bool right = hands[1].valid && hands[1].pressed;
        const ManipulationMode desired = left && right
            ? ManipulationMode::two_hand
            : left ? ManipulationMode::left
                   : right ? ManipulationMode::right : ManipulationMode::none;

        if (desired != mode_) {
            // Commit the old mode at this frame's poses before taking the new
            // snapshot. This keeps one→two and two→one transitions continuous.
            apply(hands);
            begin(desired, hands);
        }
        apply(hands);
        return mode_;
    }

    void recenter(const glm::vec3& headPosition, const glm::quat& headOrientation) {
        const glm::vec3 target = headPosition
                               + headOrientation * glm::vec3(0.0F, 0.0F, -kViewDistanceMeters);
        transform_ = glm::translate(glm::mat4(1.0F), target - kDefaultModelCenter);
        scale_ = 1.0F;
        mode_ = ManipulationMode::none;
    }

    [[nodiscard]] const glm::mat4& transform() const { return transform_; }
    [[nodiscard]] float scale() const { return scale_; }
    [[nodiscard]] ManipulationMode mode() const { return mode_; }

    static constexpr float kViewDistanceMeters = 1.30F;

  private:
    void apply(const std::array<HandPose, 2>& hands) {
        if (mode_ == ManipulationMode::left || mode_ == ManipulationMode::right) {
            const size_t hand = mode_ == ManipulationMode::left ? 0U : 1U;
            if (!hands[hand].valid) return;
            transform_ = poseMatrix(hands[hand]) * glm::inverse(startHand_) * startModel_;
        } else if (mode_ == ManipulationMode::two_hand) {
            if (!hands[0].valid || !hands[1].valid) return;
            const glm::vec3 midpoint = (hands[0].position + hands[1].position) * 0.5F;
            const float distance = glm::length(hands[1].position - hands[0].position);
            const float rawFactor = startDistance_ > 1.0e-5F ? distance / startDistance_ : 1.0F;
            const float nextScale = std::clamp(startScale_ * rawFactor, kMinScale, kMaxScale);
            const float factor = nextScale / startScale_;
            transform_ = glm::translate(glm::mat4(1.0F), midpoint)
                       * glm::scale(glm::mat4(1.0F), glm::vec3(factor))
                       * glm::translate(glm::mat4(1.0F), -startMidpoint_)
                       * startModel_;
            scale_ = nextScale;
        }
    }

    void begin(ManipulationMode desired, const std::array<HandPose, 2>& hands) {
        mode_ = desired;
        startModel_ = transform_;
        startScale_ = scale_;
        if (desired == ManipulationMode::left || desired == ManipulationMode::right) {
            const size_t hand = desired == ManipulationMode::left ? 0U : 1U;
            startHand_ = poseMatrix(hands[hand]);
        } else if (desired == ManipulationMode::two_hand) {
            startMidpoint_ = (hands[0].position + hands[1].position) * 0.5F;
            startDistance_ = std::max(
                glm::length(hands[1].position - hands[0].position), 1.0e-5F);
        }
    }

    static constexpr float kMinScale = 0.05F;
    static constexpr float kMaxScale = 20.0F;
    static constexpr glm::vec3 kDefaultModelCenter{0.0F, 0.0F, -kViewDistanceMeters};

    ManipulationMode mode_ = ManipulationMode::none;
    glm::mat4 transform_{1.0F};
    glm::mat4 startModel_{1.0F};
    glm::mat4 startHand_{1.0F};
    glm::vec3 startMidpoint_{};
    float startDistance_ = 1.0F;
    float startScale_ = 1.0F;
    float scale_ = 1.0F;
};

}  // namespace nadoc_vr
