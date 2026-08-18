#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace nadoc_vr {

struct HandPose {
    bool valid = false;
    bool pressed = false;
    glm::vec3 position{};
    glm::quat orientation{1.0F, 0.0F, 0.0F, 0.0F};
};

enum class ManipulationMode { none, left, right, two_hand };

struct SelectionFeedback {
    uint64_t sequence = 0;
    bool accepted = false;
    bool selected = false;
    std::string level;
    std::string identity;
    std::vector<std::string> ownerTokens;
};

struct OwnerAliasEntry {
    std::string identity;
    std::vector<std::string> tokens;

    bool operator==(const OwnerAliasEntry&) const = default;
};

enum class ToolMode { inspect, move_rotate, extrude, twist, bend };
enum class ToolAction { activate, preview, confirm, cancel, undo };

inline const char* toolModeName(ToolMode mode) {
    static constexpr std::array<const char*, 5> names = {
        "inspect", "move_rotate", "extrude", "twist", "bend",
    };
    return names[static_cast<size_t>(mode)];
}

inline const char* toolActionName(ToolAction action) {
    static constexpr std::array<const char*, 5> names = {
        "activate", "preview", "confirm", "cancel", "undo",
    };
    return names[static_cast<size_t>(action)];
}

/** In-headset read-only mirror of the browser-authoritative tool session.
 *
 * It supplies immediate, honest affordance text and emits intents only. It owns no
 * design mutation, commit, or undo implementation.
 */
class ToolShell {
  public:
    void activate(ToolMode mode, bool hasSelection) {
        mode_ = mode;
        previewRequested_ = false;
        status_ = mode == ToolMode::inspect
            ? "VIEW ONLY" : hasSelection ? "READY" : "SELECT TARGET";
    }

    void apply(ToolAction action, bool hasSelection) {
        if (action == ToolAction::activate) {
            activate(mode_, hasSelection);
        } else if (action == ToolAction::preview) {
            if (mode_ == ToolMode::inspect) status_ = "CHOOSE TOOL";
            else if (!hasSelection) status_ = "SELECT TARGET";
            else {
                previewRequested_ = true;
                status_ = "PREVIEW ONLY";
            }
        } else if (action == ToolAction::confirm) {
            status_ = previewRequested_ && hasSelection
                ? "CONFIRM STAGED" : "PREVIEW FIRST";
        } else if (action == ToolAction::cancel) {
            previewRequested_ = false;
            status_ = "CANCELLED";
        } else {
            status_ = "NO VR COMMIT";
        }
    }

    void syncSelection(bool hasSelection) {
        if (mode_ == ToolMode::inspect || previewRequested_) return;
        if (status_ == "READY" || status_ == "SELECT TARGET") {
            status_ = hasSelection ? "READY" : "SELECT TARGET";
        }
    }

    [[nodiscard]] ToolMode mode() const { return mode_; }
    [[nodiscard]] bool previewRequested() const { return previewRequested_; }
    [[nodiscard]] const std::string& status() const { return status_; }

  private:
    ToolMode mode_ = ToolMode::inspect;
    bool previewRequested_ = false;
    std::string status_ = "VIEW ONLY";
};

/** Resolve by feedback specificity, then stable scene order.
 *
 * Feedback tokens are ordered exact→coarse. Scene order makes a coarse Domain,
 * Strand, or Cluster acknowledgement deterministic when many primitives share it.
 */
inline std::optional<std::string> resolveOwnerIdentity(
    const std::vector<OwnerAliasEntry>& entries,
    const std::vector<std::string>& feedbackTokens) {
    for (const std::string& token : feedbackTokens) {
        for (const OwnerAliasEntry& entry : entries) {
            if (std::find(entry.tokens.begin(), entry.tokens.end(), token)
                != entry.tokens.end()) {
                return entry.identity;
            }
        }
    }
    return std::nullopt;
}

inline std::optional<SelectionFeedback> parseSelectionFeedback(
    const std::string& record, uint64_t previousSequence, uint64_t maximumSequence) {
    std::istringstream fields(record);
    std::string magic;
    int version = 0;
    SelectionFeedback result;
    int accepted = 0;
    int selected = 0;
    std::string trailing;
    if (!(fields >> magic >> version >> result.sequence >> accepted >> selected
                >> result.level >> result.identity) ||
        magic != "NADOCVR_FEEDBACK" || (version != 1 && version != 2) ||
        (accepted != 0 && accepted != 1) || (selected != 0 && selected != 1) ||
        result.sequence <= previousSequence || result.sequence > maximumSequence) {
        return std::nullopt;
    }
    if (version == 2) {
        size_t ownerCount = 0;
        if (!(fields >> ownerCount) || ownerCount > 8) return std::nullopt;
        result.ownerTokens.resize(ownerCount);
        for (std::string& token : result.ownerTokens) {
            if (!(fields >> token) || token.size() > 2048) return std::nullopt;
        }
    }
    if (fields >> trailing) return std::nullopt;
    static constexpr std::array<const char*, 7> levels = {
        "default", "cluster", "strand", "domain", "end", "xover", "base",
    };
    if (std::find(levels.begin(), levels.end(), result.level) == levels.end()) {
        return std::nullopt;
    }
    result.accepted = accepted == 1;
    result.selected = selected == 1;
    if (result.identity == "-") result.identity.clear();
    if (!result.selected) result.ownerTokens.clear();
    return result;
}

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
