#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <limits>
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

inline glm::mat4 poseMatrix(const HandPose& pose);

inline glm::vec3 weightedTransformPoint(
    const glm::vec3& point, const glm::mat4& transform, float weight) {
    return glm::mix(
        point, glm::vec3(transform * glm::vec4(point, 1.0F)), weight);
}

inline glm::vec3 weightedTransformVector(
    const glm::vec3& vector, const glm::mat4& transform, float weight) {
    return glm::mix(vector, glm::mat3(transform) * vector, weight);
}

inline glm::mat4 normalizedToSourceTransform(
    const glm::mat4& normalizedTransform, const glm::vec3& sourceCenter,
    float sourceToNormalizedScale, const glm::vec3& normalizedOffset) {
    const glm::mat4 normalization =
        glm::translate(glm::mat4(1.0F), normalizedOffset)
        * glm::scale(glm::mat4(1.0F), glm::vec3(sourceToNormalizedScale))
        * glm::translate(glm::mat4(1.0F), -sourceCenter);
    return glm::inverse(normalization) * normalizedTransform * normalization;
}

enum class ManipulationMode { none, left, right, two_hand };

struct SelectionFeedback {
    uint64_t sequence = 0;
    bool accepted = false;
    bool selected = false;
    std::string level;
    std::string selectionKind = "none";
    std::string identity;
    std::vector<std::string> ownerTokens;
};

struct OwnerAliasEntry {
    std::string identity;
    std::vector<std::string> tokens;

    bool operator==(const OwnerAliasEntry&) const = default;
};

struct BoundsSummary {
    glm::vec3 center{};
    float radius = 0.0F;
};

struct TimingSummary {
    size_t samples = 0;
    double p50Milliseconds = 0.0;
    double p95Milliseconds = 0.0;
    double p99Milliseconds = 0.0;
    double maxMilliseconds = 0.0;
};

/** Bounded nearest-rank timing window for headset performance checkpoints. */
class TimingWindow {
  public:
    explicit TimingWindow(size_t capacity) : capacity_(std::max<size_t>(capacity, 1U)) {
        samples_.reserve(capacity_);
    }

    [[nodiscard]] bool add(double milliseconds) {
        if (!std::isfinite(milliseconds) || milliseconds < 0.0) return false;
        samples_.push_back(milliseconds);
        return samples_.size() >= capacity_;
    }

    [[nodiscard]] std::optional<TimingSummary> takeSummary() {
        if (samples_.empty()) return std::nullopt;
        std::sort(samples_.begin(), samples_.end());
        auto percentile = [&](double fraction) {
            const size_t rank = static_cast<size_t>(
                std::ceil(fraction * static_cast<double>(samples_.size())));
            return samples_[std::clamp<size_t>(rank, 1U, samples_.size()) - 1U];
        };
        const TimingSummary result{
            samples_.size(), percentile(0.50), percentile(0.95),
            percentile(0.99), samples_.back(),
        };
        samples_.clear();
        return result;
    }

  private:
    size_t capacity_;
    std::vector<double> samples_;
};

/** Conservative owner-wide local bounds used for tool locators and future pivots. */
class BoundsAccumulator {
  public:
    void includePoint(const glm::vec3& point, float radius = 0.0F) {
        const glm::vec3 extent(std::max(radius, 0.0F));
        minimum_ = glm::min(minimum_, point - extent);
        maximum_ = glm::max(maximum_, point + extent);
        empty_ = false;
    }

    void includeSegment(
        const glm::vec3& start, const glm::vec3& end, float radius = 0.0F) {
        includePoint(start, radius);
        includePoint(end, radius);
    }

    void includeBox(const glm::vec3& center, const glm::vec3& axisX,
                    const glm::vec3& axisY, const glm::vec3& axisZ) {
        for (float x : {-0.5F, 0.5F}) {
            for (float y : {-0.5F, 0.5F}) {
                for (float z : {-0.5F, 0.5F}) {
                    includePoint(center + axisX * x + axisY * y + axisZ * z);
                }
            }
        }
    }

    [[nodiscard]] std::optional<BoundsSummary> summary(
        const glm::mat4& transform = glm::mat4(1.0F)) const {
        if (empty_) return std::nullopt;
        const glm::vec3 localCenter = (minimum_ + maximum_) * 0.5F;
        const float localRadius = glm::length(maximum_ - minimum_) * 0.5F;
        const float scale = std::max({
            glm::length(glm::vec3(transform[0])),
            glm::length(glm::vec3(transform[1])),
            glm::length(glm::vec3(transform[2])),
        });
        return BoundsSummary{
            glm::vec3(transform * glm::vec4(localCenter, 1.0F)),
            localRadius * scale,
        };
    }

  private:
    bool empty_ = true;
    glm::vec3 minimum_{std::numeric_limits<float>::max()};
    glm::vec3 maximum_{std::numeric_limits<float>::lowest()};
};

enum class ToolMode { inspect, move_rotate, extrude, twist, bend };
enum class ToolAction { activate, preview, confirm, cancel, undo };
enum class ToolCapability {
    view_only, direct_preview, configuration_required, unsupported,
};

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
    [[nodiscard]] static ToolCapability selectionCapability(
        ToolMode mode, const std::string& selectionKind) {
        if (mode == ToolMode::inspect) return ToolCapability::view_only;
        if (selectionKind.empty() || selectionKind == "none") {
            return ToolCapability::unsupported;
        }
        struct CapabilityEntry {
            ToolMode mode;
            const char* selectionKind;
            ToolCapability capability;
        };
        static constexpr std::array<CapabilityEntry, 10> entries = {{
#define NADOC_VR_TOOL_CAPABILITY(tool, kind, capability) \
            {ToolMode::tool, #kind, ToolCapability::capability},
#include "../tool_capabilities.def"
#undef NADOC_VR_TOOL_CAPABILITY
        }};
        for (const CapabilityEntry& entry : entries) {
            if (entry.mode == mode && selectionKind == entry.selectionKind) {
                return entry.capability;
            }
        }
        return ToolCapability::unsupported;
    }

    [[nodiscard]] static bool supportsSelection(
        ToolMode mode, const std::string& selectionKind) {
        return selectionCapability(mode, selectionKind) != ToolCapability::unsupported;
    }

    void activate(ToolMode mode, const std::string& selectionKind) {
        mode_ = mode;
        previewRequested_ = false;
        status_ = targetStatus(mode, selectionKind);
    }

    void apply(ToolAction action, const std::string& selectionKind) {
        const bool hasSelection = !selectionKind.empty() && selectionKind != "none";
        const ToolCapability capability = selectionCapability(mode_, selectionKind);
        const bool directPreview = capability == ToolCapability::direct_preview;
        if (action == ToolAction::activate) {
            activate(mode_, selectionKind);
        } else if (action == ToolAction::preview) {
            if (mode_ == ToolMode::inspect) status_ = "CHOOSE TOOL";
            else if (!hasSelection) status_ = "SELECT TARGET";
            else if (capability == ToolCapability::configuration_required) {
                previewRequested_ = false;
                status_ = "CONFIG REQUIRED";
            } else if (!directPreview) status_ = "UNSUPPORTED TARGET";
            else {
                previewRequested_ = true;
                status_ = "PREVIEW ONLY";
            }
        } else if (action == ToolAction::confirm) {
            status_ = capability == ToolCapability::configuration_required
                ? "CONFIG REQUIRED"
                : previewRequested_ && directPreview ? "CONFIRM STAGED" : "PREVIEW FIRST";
        } else if (action == ToolAction::cancel) {
            previewRequested_ = false;
            status_ = "CANCELLED";
        } else {
            status_ = "NO VR COMMIT";
        }
    }

    void syncSelection(const std::string& selectionKind, bool targetChanged = false) {
        if (mode_ == ToolMode::inspect) return;
        if (targetChanged && previewRequested_) {
            previewRequested_ = false;
            status_ = targetStatus(mode_, selectionKind);
            return;
        }
        if (previewRequested_) {
            if (selectionCapability(mode_, selectionKind) ==
                ToolCapability::direct_preview) return;
            previewRequested_ = false;
            status_ = targetStatus(mode_, selectionKind);
            return;
        }
        if (targetChanged) {
            status_ = targetStatus(mode_, selectionKind);
            return;
        }
        if (status_ == "READY" || status_ == "SELECT TARGET" ||
            status_ == "CONFIG REQUIRED" || status_ == "UNSUPPORTED TARGET") {
            status_ = targetStatus(mode_, selectionKind);
        }
    }

    [[nodiscard]] ToolMode mode() const { return mode_; }
    [[nodiscard]] bool previewRequested() const { return previewRequested_; }
    [[nodiscard]] const std::string& status() const { return status_; }

  private:
    [[nodiscard]] static std::string targetStatus(
        ToolMode mode, const std::string& selectionKind) {
        if (mode == ToolMode::inspect) return "VIEW ONLY";
        if (selectionKind.empty() || selectionKind == "none") return "SELECT TARGET";
        const ToolCapability capability = selectionCapability(mode, selectionKind);
        if (capability == ToolCapability::direct_preview) return "READY";
        if (capability == ToolCapability::configuration_required) {
            return "CONFIG REQUIRED";
        }
        return "UNSUPPORTED TARGET";
    }

    ToolMode mode_ = ToolMode::inspect;
    bool previewRequested_ = false;
    std::string status_ = "VIEW ONLY";
};

/** Reversible controller-space rigid preview expressed in model-local space.
 *
 * The immutable activation value is identity. Each trigger-drag snapshots the
 * accumulated local transform, so multiple grabs compose without drift while
 * Cancel can still restore the activation value exactly. The owning tool decides
 * whether/when this pending value is projected into authoritative desktop state.
 */
class PendingRigidTransform {
  public:
    void activate() {
        transform_ = glm::mat4(1.0F);
        startTransform_ = transform_;
        dragging_ = false;
    }

    void cancel() { activate(); }

    bool update(const HandPose& hand, const glm::mat4& modelTransform, bool enabled) {
        const bool desired = enabled && hand.valid && hand.pressed;
        if (!desired) {
            dragging_ = false;
            return false;
        }
        const glm::mat4 handTransform = poseMatrix(hand);
        if (!dragging_) {
            dragging_ = true;
            startHand_ = handTransform;
            startTransform_ = transform_;
            return false;
        }
        transform_ = glm::inverse(modelTransform)
                   * handTransform * glm::inverse(startHand_)
                   * modelTransform * startTransform_;
        return true;
    }

    [[nodiscard]] bool dragging() const { return dragging_; }
    [[nodiscard]] const glm::mat4& transform() const { return transform_; }
    [[nodiscard]] bool isIdentity(float epsilon = 1.0e-6F) const {
        const glm::mat4 identity(1.0F);
        for (size_t column = 0; column < 4; ++column) {
            for (size_t row = 0; row < 4; ++row) {
                if (std::abs(transform_[column][row] - identity[column][row]) > epsilon) {
                    return false;
                }
            }
        }
        return true;
    }

  private:
    bool dragging_ = false;
    glm::mat4 transform_{1.0F};
    glm::mat4 startTransform_{1.0F};
    glm::mat4 startHand_{1.0F};
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
                >> result.level) ||
        magic != "NADOCVR_FEEDBACK" || (version < 1 || version > 3) ||
        (accepted != 0 && accepted != 1) || (selected != 0 && selected != 1) ||
        result.sequence <= previousSequence || result.sequence > maximumSequence) {
        return std::nullopt;
    }
    if (version == 3) {
        if (!(fields >> result.selectionKind >> result.identity)) return std::nullopt;
    } else if (!(fields >> result.identity)) {
        return std::nullopt;
    }
    if (version >= 2) {
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
    static constexpr std::array<const char*, 11> selectionKinds = {
        "none", "cluster", "strand", "domain", "base", "end", "bond",
        "crossover", "overhang", "extension", "protein",
    };
    if (version == 3 && std::find(
            selectionKinds.begin(), selectionKinds.end(), result.selectionKind)
            == selectionKinds.end()) {
        return std::nullopt;
    }
    result.accepted = accepted == 1;
    result.selected = selected == 1;
    if (result.identity == "-") result.identity.clear();
    if (!result.selected) {
        result.ownerTokens.clear();
        result.selectionKind = "none";
    }
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
