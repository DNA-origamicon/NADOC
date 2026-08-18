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

inline glm::vec3 sourceToNormalizedPoint(
    const glm::vec3& sourcePoint, const glm::vec3& sourceCenter,
    float sourceToNormalizedScale, const glm::vec3& normalizedOffset) {
    return (sourcePoint - sourceCenter) * sourceToNormalizedScale + normalizedOffset;
}

inline glm::vec3 extrusionPreviewEnd(
    const glm::vec3& facePosition, const glm::vec3& outwardNormal,
    int32_t lengthBp, int directionSign, float riseNanometers,
    float sourceToNormalizedScale) {
    return facePosition + glm::normalize(outwardNormal)
        * static_cast<float>(directionSign)
        * static_cast<float>(lengthBp) * riseNanometers
        * sourceToNormalizedScale;
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

struct ToolContextFeedback {
    uint64_t sequence = 0;
    bool resolved = false;
    bool occupied = false;
    bool deformed = false;
    bool footprintResolved = false;
    std::string reason;
    std::string selectionKind = "none";
    std::string identity;
    glm::vec3 facePosition{};
    glm::vec3 faceNormal{};
    glm::vec3 previewOrigin{};
};

struct PlanePickFeedback {
    uint64_t sequence = 0;
    uint64_t toolConfigSequence = 0;
    bool resolved = false;
    std::string reason;
    std::string slot;
    std::string targetSelectionKind = "none";
    std::string targetIdentity;
    std::string pickedIdentity;
    int32_t planeBp = 0;
    bool frameResolved = false;
    glm::vec3 planeCenter{};
    glm::vec3 planeNormal{};
    float planeHalfExtentNanometers = 0.0F;
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
enum class ToolStrandFilter { both, scaffold, staples };
enum class TwistAmountMode { total_degrees, degrees_per_nm };

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

inline const char* toolStrandFilterName(ToolStrandFilter filter) {
    static constexpr std::array<const char*, 3> names = {
        "both", "scaffold", "staples",
    };
    return names[static_cast<size_t>(filter)];
}

inline const char* twistAmountModeName(TwistAmountMode mode) {
    static constexpr std::array<const char*, 2> names = {
        "total_degrees", "degrees_per_nm",
    };
    return names[static_cast<size_t>(mode)];
}

/** Target-bound, non-authoritative settings for parameterized VR tools.
 *
 * Every target change resets the draft. Plane anchors and extrusion footprints
 * intentionally begin unresolved: no controller-side default is allowed to
 * invent design geometry. Numeric limits only bound the private IPC record.
 */
class ToolConfigurationDraft {
  public:
    static constexpr int32_t kMaximumLengthBp = 1'000'000;
    static constexpr double kMaximumTwistMagnitude = 1'000'000.0;

    [[nodiscard]] bool bind(
        ToolMode mode, const std::string& identity, const std::string& selectionKind,
        const std::vector<std::string>& ownerTokens) {
        const bool parameterized = mode == ToolMode::extrude || mode == ToolMode::twist ||
                                   mode == ToolMode::bend;
        if (!parameterized) return clear();
        if (active_ && mode_ == mode && targetIdentity_ == identity &&
            targetSelectionKind_ == selectionKind && targetOwnerTokens_ == ownerTokens) {
            return false;
        }
        active_ = true;
        mode_ = mode;
        targetIdentity_ = identity;
        targetSelectionKind_ = selectionKind.empty() ? "none" : selectionKind;
        targetOwnerTokens_ = ownerTokens;
        lengthBp_ = 0;
        directionSign_ = 1;
        strandFilter_ = ToolStrandFilter::both;
        ligateAdjacent_ = true;
        planeABp_.reset();
        planeBBp_.reset();
        twistAmountMode_ = TwistAmountMode::total_degrees;
        twistAmount_ = 90.0;
        bendAngleDegrees_ = 0.0;
        bendDirectionDegrees_ = 0.0;
        return true;
    }

    [[nodiscard]] bool clear() {
        if (!active_) return false;
        active_ = false;
        targetIdentity_.clear();
        targetSelectionKind_ = "none";
        targetOwnerTokens_.clear();
        return true;
    }

    [[nodiscard]] bool adjustPrimary(int direction) {
        if (!active_ || direction == 0) return false;
        if (mode_ == ToolMode::extrude) {
            const int64_t next = static_cast<int64_t>(lengthBp_) + (direction > 0 ? 1 : -1);
            const int32_t clamped = static_cast<int32_t>(
                std::clamp<int64_t>(next, 0, kMaximumLengthBp));
            if (clamped == lengthBp_) return false;
            lengthBp_ = clamped;
            return true;
        }
        if (mode_ == ToolMode::twist) {
            const double step = twistAmountMode_ == TwistAmountMode::total_degrees
                ? 5.0 : 0.1;
            const double next = std::clamp(
                twistAmount_ + (direction > 0 ? step : -step),
                -kMaximumTwistMagnitude, kMaximumTwistMagnitude);
            if (next == twistAmount_) return false;
            twistAmount_ = next;
            return true;
        }
        if (mode_ == ToolMode::bend) {
            const double next = std::clamp(
                bendAngleDegrees_ + (direction > 0 ? 1.0 : -1.0), 0.0, 360.0);
            if (next == bendAngleDegrees_) return false;
            bendAngleDegrees_ = next;
            return true;
        }
        return false;
    }

    [[nodiscard]] bool adjustSecondary(int direction) {
        if (!active_ || direction == 0) return false;
        if (mode_ == ToolMode::extrude) {
            directionSign_ = directionSign_ > 0 ? -1 : 1;
            return true;
        }
        if (mode_ == ToolMode::bend) {
            bendDirectionDegrees_ += direction > 0 ? 5.0 : -5.0;
            if (bendDirectionDegrees_ < 0.0) bendDirectionDegrees_ += 360.0;
            if (bendDirectionDegrees_ >= 360.0) bendDirectionDegrees_ -= 360.0;
            return true;
        }
        return false;
    }

    [[nodiscard]] bool cycleOption() {
        if (!active_) return false;
        if (mode_ == ToolMode::extrude) {
            strandFilter_ = static_cast<ToolStrandFilter>(
                (static_cast<size_t>(strandFilter_) + 1U) % 3U);
            return true;
        }
        if (mode_ == ToolMode::twist) {
            twistAmountMode_ = twistAmountMode_ == TwistAmountMode::total_degrees
                ? TwistAmountMode::degrees_per_nm : TwistAmountMode::total_degrees;
            twistAmount_ = twistAmountMode_ == TwistAmountMode::total_degrees ? 90.0 : 1.0;
            return true;
        }
        return false;
    }

    [[nodiscard]] bool toggleFlag() {
        if (!active_ || mode_ != ToolMode::extrude) return false;
        ligateAdjacent_ = !ligateAdjacent_;
        return true;
    }

    [[nodiscard]] bool setPlaneBp(const std::string& slot, int32_t bp) {
        if (!active_ || (mode_ != ToolMode::twist && mode_ != ToolMode::bend)) {
            return false;
        }
        std::optional<int32_t>* target = slot == "a" ? &planeABp_
            : slot == "b" ? &planeBBp_ : nullptr;
        if (!target || (*target && **target == bp)) return false;
        *target = bp;
        return true;
    }

    [[nodiscard]] bool active() const { return active_; }
    [[nodiscard]] ToolMode mode() const { return mode_; }
    [[nodiscard]] const std::string& targetIdentity() const { return targetIdentity_; }
    [[nodiscard]] const std::string& targetSelectionKind() const {
        return targetSelectionKind_;
    }
    [[nodiscard]] const std::vector<std::string>& targetOwnerTokens() const {
        return targetOwnerTokens_;
    }
    [[nodiscard]] int32_t lengthBp() const { return lengthBp_; }
    [[nodiscard]] int directionSign() const { return directionSign_; }
    [[nodiscard]] ToolStrandFilter strandFilter() const { return strandFilter_; }
    [[nodiscard]] bool ligateAdjacent() const { return ligateAdjacent_; }
    [[nodiscard]] const std::optional<int32_t>& planeABp() const { return planeABp_; }
    [[nodiscard]] const std::optional<int32_t>& planeBBp() const { return planeBBp_; }
    [[nodiscard]] TwistAmountMode twistAmountMode() const { return twistAmountMode_; }
    [[nodiscard]] double twistAmount() const { return twistAmount_; }
    [[nodiscard]] double bendAngleDegrees() const { return bendAngleDegrees_; }
    [[nodiscard]] double bendDirectionDegrees() const { return bendDirectionDegrees_; }
    [[nodiscard]] const char* unresolvedGeometry() const {
        return mode_ == ToolMode::extrude ? "FOOTPRINT" : "PLANES A/B";
    }

  private:
    bool active_ = false;
    ToolMode mode_ = ToolMode::inspect;
    std::string targetIdentity_;
    std::string targetSelectionKind_ = "none";
    std::vector<std::string> targetOwnerTokens_;
    int32_t lengthBp_ = 0;
    int directionSign_ = 1;
    ToolStrandFilter strandFilter_ = ToolStrandFilter::both;
    bool ligateAdjacent_ = true;
    std::optional<int32_t> planeABp_;
    std::optional<int32_t> planeBBp_;
    TwistAmountMode twistAmountMode_ = TwistAmountMode::total_degrees;
    double twistAmount_ = 90.0;
    double bendAngleDegrees_ = 0.0;
    double bendDirectionDegrees_ = 0.0;
};

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

inline std::optional<ToolContextFeedback> parseToolContextFeedback(
    const std::string& record, uint64_t previousSequence, uint64_t expectedSequence) {
    std::istringstream fields(record);
    std::string magic;
    int version = 0;
    int resolved = 0;
    int occupied = 0;
    int deformed = 0;
    int footprintResolved = 0;
    ToolContextFeedback result;
    if (!(fields >> magic >> version >> result.sequence >> resolved >> occupied >> deformed) ||
        magic != "NADOCVR_TOOL_FEEDBACK" || (version != 1 && version != 2)) {
        return std::nullopt;
    }
    if (version == 2 && !(fields >> footprintResolved)) return std::nullopt;
    if (!(fields >> result.reason >> result.selectionKind >> result.identity) ||
        (resolved != 0 && resolved != 1) || (occupied != 0 && occupied != 1) ||
        (deformed != 0 && deformed != 1) ||
        (footprintResolved != 0 && footprintResolved != 1) ||
        result.sequence <= previousSequence || result.sequence != expectedSequence ||
        result.selectionKind != "end" || result.identity.empty() ||
        result.identity == "-" || result.identity.size() > 2048) {
        return std::nullopt;
    }
    static constexpr std::array<const char*, 12> reasons = {
        "resolved", "end_selection_required", "invalid_end_ref",
        "loop_copy_not_supported", "synthetic_end_not_supported",
        "ambiguous_live_end", "stale_live_end", "not_terminal",
        "helix_not_live", "ambiguous_continuation_face",
        "no_continuation_face", "invalid_continuation_face",
    };
    if (std::find(reasons.begin(), reasons.end(), result.reason) == reasons.end() ||
        (resolved == 1) != (result.reason == "resolved")) {
        return std::nullopt;
    }
    result.resolved = resolved == 1;
    result.occupied = occupied == 1;
    result.deformed = deformed == 1;
    result.footprintResolved = footprintResolved == 1;
    if (result.resolved) {
        if (!(fields >> result.facePosition.x >> result.facePosition.y
                     >> result.facePosition.z >> result.faceNormal.x
                     >> result.faceNormal.y >> result.faceNormal.z) ||
            !std::isfinite(result.facePosition.x) ||
            !std::isfinite(result.facePosition.y) ||
            !std::isfinite(result.facePosition.z) ||
            !std::isfinite(result.faceNormal.x) ||
            !std::isfinite(result.faceNormal.y) ||
            !std::isfinite(result.faceNormal.z) ||
            std::abs(result.facePosition.x) > 1.0e9F ||
            std::abs(result.facePosition.y) > 1.0e9F ||
            std::abs(result.facePosition.z) > 1.0e9F) {
            return std::nullopt;
        }
        if (result.footprintResolved &&
            (!(fields >> result.previewOrigin.x >> result.previewOrigin.y
                      >> result.previewOrigin.z) ||
             !std::isfinite(result.previewOrigin.x) ||
             !std::isfinite(result.previewOrigin.y) ||
             !std::isfinite(result.previewOrigin.z) ||
             std::abs(result.previewOrigin.x) > 1.0e9F ||
             std::abs(result.previewOrigin.y) > 1.0e9F ||
             std::abs(result.previewOrigin.z) > 1.0e9F)) {
            return std::nullopt;
        }
        const double normalLength = std::hypot(
            std::hypot(static_cast<double>(result.faceNormal.x),
                       static_cast<double>(result.faceNormal.y)),
            static_cast<double>(result.faceNormal.z));
        if (normalLength <= 1.0e-9 || normalLength >= 1.0e9) return std::nullopt;
        result.faceNormal = glm::normalize(result.faceNormal);
    } else if (result.occupied || result.deformed || result.footprintResolved) {
        return std::nullopt;
    }
    std::string trailing;
    if (fields >> trailing) return std::nullopt;
    return result;
}

inline std::optional<PlanePickFeedback> parsePlanePickFeedback(
    const std::string& record, uint64_t previousSequence,
    uint64_t expectedPickSequence, uint64_t expectedToolConfigSequence) {
    std::istringstream fields(record);
    std::string magic;
    int version = 0;
    int resolved = 0;
    int64_t planeBp = 0;
    PlanePickFeedback result;
    if (!(fields >> magic >> version >> result.sequence >> result.toolConfigSequence
                 >> resolved >> result.reason >> result.slot
                 >> result.targetSelectionKind >> result.targetIdentity
                 >> result.pickedIdentity) ||
        magic != "NADOCVR_PLANE_FEEDBACK" || (version != 1 && version != 2) ||
        (resolved != 0 && resolved != 1) ||
        result.sequence <= previousSequence ||
        result.sequence != expectedPickSequence ||
        result.toolConfigSequence != expectedToolConfigSequence ||
        (result.slot != "a" && result.slot != "b") ||
        (result.targetSelectionKind != "cluster" &&
         result.targetSelectionKind != "end") ||
        result.targetIdentity.empty() || result.targetIdentity == "-" ||
        result.targetIdentity.size() > 2048 || result.pickedIdentity.empty() ||
        result.pickedIdentity == "-" || result.pickedIdentity.size() > 2048) {
        return std::nullopt;
    }
    static constexpr std::array<const char*, 7> reasons = {
        "resolved", "invalid_primitive", "ambiguous_primitive",
        "synthetic_not_supported", "out_of_range", "plane_frame_unavailable",
        "stale_target",
    };
    if (std::find(reasons.begin(), reasons.end(), result.reason) == reasons.end() ||
        (resolved == 1) != (result.reason == "resolved")) {
        return std::nullopt;
    }
    result.resolved = resolved == 1;
    if (result.resolved) {
        if (!(fields >> planeBp) || planeBp < -(static_cast<int64_t>(1) << 31) + 1 ||
            planeBp > (static_cast<int64_t>(1) << 31) - 1) {
            return std::nullopt;
        }
        result.planeBp = static_cast<int32_t>(planeBp);
        // Version 1 never carried a frame. Do not accept an exact bp without
        // the geometry required to display what will eventually be edited.
        if (version != 2 ||
            !(fields >> result.planeCenter.x >> result.planeCenter.y
                      >> result.planeCenter.z >> result.planeNormal.x
                      >> result.planeNormal.y >> result.planeNormal.z
                      >> result.planeHalfExtentNanometers) ||
            !std::isfinite(result.planeCenter.x) ||
            !std::isfinite(result.planeCenter.y) ||
            !std::isfinite(result.planeCenter.z) ||
            !std::isfinite(result.planeNormal.x) ||
            !std::isfinite(result.planeNormal.y) ||
            !std::isfinite(result.planeNormal.z) ||
            !std::isfinite(result.planeHalfExtentNanometers) ||
            std::abs(result.planeCenter.x) > 1.0e9F ||
            std::abs(result.planeCenter.y) > 1.0e9F ||
            std::abs(result.planeCenter.z) > 1.0e9F ||
            result.planeHalfExtentNanometers <= 0.0F ||
            result.planeHalfExtentNanometers > 1.0e6F) {
            return std::nullopt;
        }
        const double normalLength = std::hypot(
            std::hypot(static_cast<double>(result.planeNormal.x),
                       static_cast<double>(result.planeNormal.y)),
            static_cast<double>(result.planeNormal.z));
        if (normalLength <= 1.0e-9 || normalLength >= 1.0e9) return std::nullopt;
        result.planeNormal = glm::normalize(result.planeNormal);
        result.frameResolved = true;
    }
    std::string trailing;
    if (fields >> trailing) return std::nullopt;
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
