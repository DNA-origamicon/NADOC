#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cmath>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace nadoc_vr {

struct HandPose {
    bool valid = false;
    bool pressed = false;
    glm::vec3 position{};
    glm::quat orientation{1.0F, 0.0F, 0.0F, 0.0F};
};

inline glm::mat4 poseMatrix(const HandPose& pose);

/** Controller-following menu pose with reversible world-space manipulation.
 *
 * The menu opens on the controller that requested it. Docking freezes the
 * current world pose; a nearby grip can move it, and two border grips resize it
 * uniformly. Returning to Follow transfers it to the controller that pressed
 * the button. Scale is applied by the same world/local conversions used for
 * drawing and hit testing, keeping the controls aligned at every size.
 */
class MenuPlacement {
  public:
    static constexpr float kMinimumScale = 0.55F;
    static constexpr float kMaximumScale = 1.25F;
    static constexpr float kScaleStep = 0.10F;
    static constexpr float kDefaultScale = 0.75F;
    static constexpr float kMenuHalfWidth = 0.33F;
    static constexpr float kBorderGrabDistanceMeters = 0.075F;

    void open(
        size_t hand, const std::array<HandPose, 2>& hands,
        const glm::vec3& fallbackPosition, const glm::quat& fallbackOrientation) {
        anchorHand_ = std::min(hand, hands.size() - 1U);
        worldDocked_ = false;
        dragHand_.reset();
        resizeActive_ = false;
        position_ = fallbackPosition;
        orientation_ = glm::normalize(fallbackOrientation);
        update(hands);
    }

    /** Open already frozen at an explicit world pose.  Tool-created windows use
     * this so they do not spend one frame following a controller or overlap one
     * another before their first render. */
    void openDocked(const glm::vec3& position, const glm::quat& orientation) {
        position_ = position;
        orientation_ = glm::normalize(orientation);
        worldDocked_ = true;
        dragHand_.reset();
        resizeActive_ = false;
    }

    void update(
        const std::array<HandPose, 2>& hands,
        float panelHalfWidth = kMenuHalfWidth) {
        panelHalfWidth_ = std::max(panelHalfWidth, 1.0e-4F);
        if (resizeActive_) {
            if (std::any_of(hands.begin(), hands.end(), [](const HandPose& hand) {
                    return !hand.valid || !hand.pressed;
                })) {
                resizeActive_ = false;
                return;
            }
            const glm::vec3 midpoint = (hands[0].position + hands[1].position) * 0.5F;
            const float distance = glm::length(hands[1].position - hands[0].position);
            scale_ = glm::clamp(
                resizeInitialScale_ * distance / resizeInitialDistance_,
                kMinimumScale, kMaximumScale);
            position_ = midpoint + resizePositionFromMidpoint_ *
                (scale_ / resizeInitialScale_);
            return;
        }
        if (worldDocked_) {
            if (!dragHand_ || !hands[*dragHand_].valid || !hands[*dragHand_].pressed) {
                dragHand_.reset();
                return;
            }
            const HandPose& hand = hands[*dragHand_];
            position_ = hand.position + hand.orientation * dragPositionInHand_;
            orientation_ = glm::normalize(hand.orientation * dragOrientationInHand_);
            return;
        }
        if (!hands[anchorHand_].valid) return;
        const HandPose& hand = hands[anchorHand_];
        orientation_ = glm::normalize(hand.orientation * kTabletTilt);
        const float centerDirection = anchorHand_ == 0U ? 1.0F : -1.0F;
        position_ = hand.position + orientation_ * (
            kControllerOffset
            + glm::vec3(centerDirection * panelHalfWidth_ * scale_, 0.0F, 0.0F));
    }

    void toggleDock(
        size_t hand, const std::array<HandPose, 2>& hands,
        float panelHalfWidth = kMenuHalfWidth) {
        dragHand_.reset();
        resizeActive_ = false;
        if (!worldDocked_) {
            worldDocked_ = true;
            return;
        }
        anchorHand_ = std::min(hand, hands.size() - 1U);
        worldDocked_ = false;
        update(hands, panelHalfWidth);
    }

    [[nodiscard]] bool nearBorder(
        const HandPose& hand, const glm::vec2& minimum,
        const glm::vec2& maximum,
        float maximumDistanceMeters = kBorderGrabDistanceMeters) const {
        if (!hand.valid || maximumDistanceMeters <= 0.0F) return false;
        const glm::vec3 local = localPoint(hand.position);
        auto segmentDistance = [&](const glm::vec2& first, const glm::vec2& second) {
            const glm::vec2 point(local.x, local.y);
            const glm::vec2 edge = second - first;
            const float denominator = glm::dot(edge, edge);
            const float parameter = denominator > 0.0F
                ? glm::clamp(glm::dot(point - first, edge) / denominator, 0.0F, 1.0F)
                : 0.0F;
            return glm::length(point - (first + edge * parameter));
        };
        const float inPlane = std::min({
            segmentDistance({minimum.x, minimum.y}, {maximum.x, minimum.y}),
            segmentDistance({maximum.x, minimum.y}, {maximum.x, maximum.y}),
            segmentDistance({maximum.x, maximum.y}, {minimum.x, maximum.y}),
            segmentDistance({minimum.x, maximum.y}, {minimum.x, minimum.y}),
        });
        return std::hypot(inPlane, local.z) * scale_ <= maximumDistanceMeters;
    }

    [[nodiscard]] bool nearPanel(
        const HandPose& hand, const glm::vec2& minimum,
        const glm::vec2& maximum,
        float maximumDistanceMeters = kBorderGrabDistanceMeters) const {
        if (!hand.valid || maximumDistanceMeters <= 0.0F) return false;
        const glm::vec3 local = localPoint(hand.position);
        return local.x >= minimum.x && local.x <= maximum.x &&
               local.y >= minimum.y && local.y <= maximum.y &&
               std::abs(local.z) * scale_ <= maximumDistanceMeters;
    }

    [[nodiscard]] bool beginDrag(
        size_t hand, const std::array<HandPose, 2>& hands,
        const glm::vec2& minimum, const glm::vec2& maximum,
        bool allowPanelInterior = false) {
        if (dragHand_ || resizeActive_ || hand >= hands.size() ||
            !hands[hand].pressed ||
            (!nearBorder(hands[hand], minimum, maximum) &&
             !(allowPanelInterior && nearPanel(hands[hand], minimum, maximum)))) {
            return false;
        }
        worldDocked_ = true;
        dragHand_ = hand;
        dragPositionInHand_ = glm::inverse(hands[hand].orientation) *
                              (position_ - hands[hand].position);
        dragOrientationInHand_ = glm::normalize(
            glm::inverse(hands[hand].orientation) * orientation_);
        return true;
    }

    [[nodiscard]] bool beginBorderResize(
        const std::array<HandPose, 2>& hands,
        const glm::vec2& minimum, const glm::vec2& maximum) {
        if (resizeActive_ ||
            std::any_of(hands.begin(), hands.end(), [](const HandPose& hand) {
                return !hand.valid || !hand.pressed;
            }) ||
            !nearBorder(hands[0], minimum, maximum) ||
            !nearBorder(hands[1], minimum, maximum)) {
            return false;
        }
        const float distance = glm::length(hands[1].position - hands[0].position);
        if (distance < 0.04F) return false;
        worldDocked_ = true;
        dragHand_.reset();
        resizeActive_ = true;
        resizeInitialDistance_ = distance;
        resizeInitialScale_ = scale_;
        const glm::vec3 midpoint = (hands[0].position + hands[1].position) * 0.5F;
        resizePositionFromMidpoint_ = position_ - midpoint;
        return true;
    }

    [[nodiscard]] bool adjustScale(int direction) {
        if (resizeActive_) return false;
        const float next = glm::clamp(
            scale_ + (direction < 0 ? -kScaleStep : kScaleStep),
            kMinimumScale, kMaximumScale);
        if (std::abs(next - scale_) < 1.0e-6F) return false;
        if (!worldDocked_) {
            const float centerDirection = anchorHand_ == 0U ? 1.0F : -1.0F;
            position_ += orientation_ * glm::vec3(
                centerDirection * panelHalfWidth_ * (next - scale_), 0.0F, 0.0F);
        }
        scale_ = next;
        return true;
    }

    [[nodiscard]] glm::vec3 worldPoint(const glm::vec3& local) const {
        return position_ + orientation_ * (local * scale_);
    }

    [[nodiscard]] glm::vec3 localPoint(const glm::vec3& world) const {
        return (glm::inverse(orientation_) * (world - position_)) / scale_;
    }

    [[nodiscard]] std::optional<glm::vec3> rayPanelLocalPoint(
        const HandPose& hand, const glm::vec2& minimum,
        const glm::vec2& maximum, float maximumDistance = 5.0F) const {
        if (!hand.valid) return std::nullopt;
        const glm::vec3 direction = hand.orientation * glm::vec3(0, 0, -1);
        const glm::vec3 normal = orientation_ * glm::vec3(0, 0, 1);
        const float denominator = glm::dot(direction, normal);
        if (std::abs(denominator) < 1.0e-5F) return std::nullopt;
        const float distance = glm::dot(position_ - hand.position, normal) / denominator;
        if (distance <= 0.0F || distance > maximumDistance) return std::nullopt;
        const glm::vec3 local = localPoint(hand.position + direction * distance);
        if (local.x < minimum.x || local.x > maximum.x ||
            local.y < minimum.y || local.y > maximum.y) {
            return std::nullopt;
        }
        return local;
    }

    [[nodiscard]] const glm::vec3& position() const { return position_; }
    [[nodiscard]] const glm::quat& orientation() const { return orientation_; }
    [[nodiscard]] float scale() const { return scale_; }
    [[nodiscard]] size_t anchorHand() const { return anchorHand_; }
    [[nodiscard]] bool worldDocked() const { return worldDocked_; }
    [[nodiscard]] std::optional<size_t> dragHand() const { return dragHand_; }
    [[nodiscard]] bool resizeActive() const { return resizeActive_; }

  private:
    // Close enough to feel hand-held, with the top edge tilted farther away like
    // a large tablet rather than a floating head-up display. The horizontal
    // center offset puts the matching side edge over the anchoring controller.
    static inline const glm::quat kTabletTilt = glm::angleAxis(
        glm::radians(-38.0F), glm::vec3(1.0F, 0.0F, 0.0F));
    static constexpr glm::vec3 kControllerOffset{0.0F, 0.18F, -0.13F};

    glm::vec3 position_{};
    glm::quat orientation_{1.0F, 0.0F, 0.0F, 0.0F};
    float scale_ = kDefaultScale;
    size_t anchorHand_ = 0;
    bool worldDocked_ = false;
    float panelHalfWidth_ = kMenuHalfWidth;
    std::optional<size_t> dragHand_;
    glm::vec3 dragPositionInHand_{};
    glm::quat dragOrientationInHand_{1.0F, 0.0F, 0.0F, 0.0F};
    bool resizeActive_ = false;
    float resizeInitialDistance_ = 1.0F;
    float resizeInitialScale_ = kDefaultScale;
    glm::vec3 resizePositionFromMidpoint_{};
};

/** Hold-to-open, world-fixed radial tool palette.
 *
 * Each target is an annular quarter-cylinder rather than a flat angle test.  A
 * controller selection-volume center therefore has to enter the visible depth
 * of a sector before it can highlight.  The menu snapshots its pose on press;
 * subsequent controller motion never changes that pose.
 */
class RadialToolMenu {
  public:
    static constexpr size_t kItemCount = 4;
    static constexpr float kInnerRadius = 0.040F;
    static constexpr float kOuterRadius = 0.155F;
    static constexpr float kHalfDepth = 0.035F;
    static constexpr float kBackwardTiltRadians = glm::quarter_pi<float>();

    void open(const HandPose& hand, const glm::vec3& selectionCenter) {
        if (!hand.valid) return;
        position_ = selectionCenter;
        orientation_ = glm::normalize(
            hand.orientation * glm::angleAxis(
                -kBackwardTiltRadians, glm::vec3(1.0F, 0.0F, 0.0F)));
        open_ = true;
        hovered_.reset();
    }

    void close() {
        open_ = false;
        hovered_.reset();
    }

    [[nodiscard]] std::optional<size_t> update(const glm::vec3& selectionCenter) {
        hovered_ = hit(selectionCenter);
        return hovered_;
    }

    [[nodiscard]] std::optional<size_t> hit(const glm::vec3& worldPoint) const {
        if (!open_) return std::nullopt;
        const glm::vec3 local = glm::inverse(orientation_) * (worldPoint - position_);
        const float radial = std::hypot(local.x, local.y);
        if (radial < kInnerRadius || radial > kOuterRadius ||
            std::abs(local.z) > kHalfDepth) {
            return std::nullopt;
        }
        float angle = std::atan2(local.y, local.x);
        if (angle < 0.0F) angle += glm::two_pi<float>();
        return static_cast<size_t>(std::floor(
            (angle + glm::quarter_pi<float>()) / glm::half_pi<float>()))
            % kItemCount;
    }

    [[nodiscard]] glm::vec3 worldPoint(const glm::vec3& local) const {
        return position_ + orientation_ * local;
    }
    [[nodiscard]] bool open() const { return open_; }
    [[nodiscard]] const glm::vec3& position() const { return position_; }
    [[nodiscard]] const glm::quat& orientation() const { return orientation_; }
    [[nodiscard]] const std::optional<size_t>& hovered() const { return hovered_; }

  private:
    bool open_ = false;
    glm::vec3 position_{};
    glm::quat orientation_{1.0F, 0.0F, 0.0F, 0.0F};
    std::optional<size_t> hovered_;
};

struct LatticeCell {
    int row = 0;
    int column = 0;

    [[nodiscard]] bool operator==(const LatticeCell&) const = default;
    [[nodiscard]] bool forward() const { return ((row + column) & 1) == 0; }
};

inline constexpr float kDnaHelixRadiusNanometers = 1.0F;
inline constexpr float kDnaBasePairRiseNanometers = 0.334F;
inline constexpr float kHoneycombLatticeRadiusNanometers = 1.125F;
inline constexpr float kHoneycombColumnPitchNanometers =
    kHoneycombLatticeRadiusNanometers * 1.7320508075688772F;
inline constexpr float kHoneycombRowPitchNanometers =
    3.0F * kHoneycombLatticeRadiusNanometers;
inline constexpr float kSquareLatticePitchNanometers = 2.25F;

/** Exact desktop/cadnano lattice displacement from origin to cell, in nm. */
inline glm::vec2 latticeCellOffsetNanometers(
    const LatticeCell& cell, const LatticeCell& origin, bool square) {
    if (square) {
        return {
            static_cast<float>(cell.column - origin.column) *
                kSquareLatticePitchNanometers,
            static_cast<float>(cell.row - origin.row) *
                kSquareLatticePitchNanometers,
        };
    }
    auto position = [](const LatticeCell& value) {
        const int parity = ((value.row + value.column) % 2 + 2) % 2;
        return glm::vec2(
            static_cast<float>(value.column) * kHoneycombColumnPitchNanometers,
            static_cast<float>(value.row) * kHoneycombRowPitchNanometers +
                (parity != 0 ? kHoneycombLatticeRadiusNanometers : 0.0F));
    };
    return position(cell) - position(origin);
}

/** Convert a model-space nm length to panel-local units while preserving its
 * world size after both the scene and panel transforms are applied. */
inline float latticePanelUnitsPerNanometer(
    float sourceToNormalizedScale, float sceneScale, float panelScale) {
    if (!std::isfinite(sourceToNormalizedScale) ||
        !std::isfinite(sceneScale) || !std::isfinite(panelScale) ||
        sourceToNormalizedScale <= 0.0F || sceneScale <= 0.0F ||
        panelScale <= 0.0F) {
        return 0.0F;
    }
    return sourceToNormalizedScale * sceneScale / panelScale;
}

inline float latticeExtrusionPanelLength(
    int32_t lengthBp, float sourceToNormalizedScale,
    float sceneScale, float panelScale) {
    if (lengthBp <= 0) return 0.0F;
    return static_cast<float>(lengthBp) * kDnaBasePairRiseNanometers *
        latticePanelUnitsPerNanometer(
            sourceToNormalizedScale, sceneScale, panelScale);
}

inline int32_t latticeBasePairPeriod(bool square) {
    return square ? 8 : 7;
}

inline float strokeTextWidth(size_t characterCount, float scale) {
    if (characterCount == 0U || scale <= 0.0F) return 0.0F;
    return static_cast<float>((characterCount - 1U) * 6U + 5U) * scale;
}

inline float fittedStrokeTextScale(
    size_t characterCount, float maximumScale, float availableWidth) {
    if (characterCount == 0U || maximumScale <= 0.0F || availableWidth <= 0.0F) {
        return 0.0F;
    }
    const float units = static_cast<float>((characterCount - 1U) * 6U + 5U);
    return std::min(maximumScale, availableWidth / units);
}

inline bool circleIntersectsBounds(
    const glm::vec2& center, float radius,
    const glm::vec2& minimum, const glm::vec2& maximum) {
    if (!std::isfinite(radius) || radius < 0.0F) return false;
    const glm::vec2 nearest = glm::clamp(center, minimum, maximum);
    const glm::vec2 offset = center - nearest;
    return glm::dot(offset, offset) <= radius * radius;
}

inline std::optional<std::pair<glm::vec2, glm::vec2>> clipLineToBounds(
    glm::vec2 first, glm::vec2 second,
    const glm::vec2& minimum, const glm::vec2& maximum) {
    const glm::vec2 delta = second - first;
    float enter = 0.0F;
    float leave = 1.0F;
    const std::array<float, 4> p{-delta.x, delta.x, -delta.y, delta.y};
    const std::array<float, 4> q{
        first.x - minimum.x, maximum.x - first.x,
        first.y - minimum.y, maximum.y - first.y};
    for (size_t edge = 0; edge < p.size(); ++edge) {
        if (std::abs(p[edge]) < 1.0e-7F) {
            if (q[edge] < 0.0F) return std::nullopt;
            continue;
        }
        const float amount = q[edge] / p[edge];
        if (p[edge] < 0.0F) enter = std::max(enter, amount);
        else leave = std::min(leave, amount);
        if (enter > leave) return std::nullopt;
    }
    return std::pair{first + delta * enter, first + delta * leave};
}

/** Bounded VR-only extrusion-footprint draft used by the lattice window. */
class ExtrudeLatticeDraft {
  public:
    // A heavily zoomed-out lattice panel can expose several thousand cells.
    // Keep the draft bounded, but do not silently truncate ordinary paint
    // strokes at the former 9 x 9 preview limit.
    static constexpr size_t kMaximumCells = 16'641;

    [[nodiscard]] bool toggle(const LatticeCell& cell) {
        const auto found = std::lower_bound(
            cells_.begin(), cells_.end(), cell, less);
        if (found != cells_.end()) {
            if (*found == cell) {
                cells_.erase(found);
                return true;
            }
        }
        if (cells_.size() >= kMaximumCells) return false;
        cells_.insert(found, cell);
        return true;
    }

    [[nodiscard]] bool setSelected(const LatticeCell& cell, bool selected) {
        const auto found = std::lower_bound(
            cells_.begin(), cells_.end(), cell, less);
        const bool exists = found != cells_.end() && *found == cell;
        if (selected) {
            if (exists) return false;
            if (cells_.size() >= kMaximumCells) return false;
            cells_.insert(found, cell);
            return true;
        }
        if (!exists) return false;
        cells_.erase(found);
        return true;
    }

    void clear() { cells_.clear(); }
    [[nodiscard]] bool selected(const LatticeCell& cell) const {
        const auto found = std::lower_bound(
            cells_.begin(), cells_.end(), cell, less);
        return found != cells_.end() && *found == cell;
    }
    [[nodiscard]] const std::vector<LatticeCell>& cells() const { return cells_; }

  private:
    static bool less(const LatticeCell& first, const LatticeCell& second) {
        return first.row < second.row ||
               (first.row == second.row && first.column < second.column);
    }

    std::vector<LatticeCell> cells_;
};

/** One held-trigger paint stroke. The first cell chooses add versus erase and
 * each subsequently crossed cell is applied at most once until release. */
class LatticePaintStroke {
  public:
    [[nodiscard]] bool update(
        ExtrudeLatticeDraft& draft, const std::optional<LatticeCell>& cell,
        bool triggerPressed) {
        if (!triggerPressed) {
            reset();
            return false;
        }
        if (!cell) return false;
        if (!active_) {
            active_ = true;
            selecting_ = !draft.selected(*cell);
            visited_.clear();
        }
        if (std::find(visited_.begin(), visited_.end(), *cell) != visited_.end()) {
            return false;
        }
        visited_.push_back(*cell);
        return draft.setSelected(*cell, selecting_);
    }

    void reset() {
        active_ = false;
        selecting_ = true;
        visited_.clear();
    }
    [[nodiscard]] bool active() const { return active_; }
    [[nodiscard]] bool selecting() const { return selecting_; }

  private:
    bool active_ = false;
    bool selecting_ = true;
    std::vector<LatticeCell> visited_;
};

/** Provisional inertial thumbwheel model. Positive/upward travel increments the
 * caller's value. Constants are intentionally centralized for headset tuning. */
class ThumbwheelControl {
  public:
    static constexpr float kNotchTravel = 0.014F;
    static constexpr float kDampingPerSecond = 2.6F;
    static constexpr float kStopVelocity = 0.012F;
    static constexpr float kFlickVelocityThreshold = 0.20F;
    static constexpr float kMaximumVelocity = 1.2F;

    void begin(float localY) {
        dragging_ = true;
        lastY_ = localY;
        velocity_ = 0.0F;
    }

    [[nodiscard]] int drag(float localY, float elapsedSeconds) {
        if (!dragging_ || !std::isfinite(localY)) return 0;
        const float delta = localY - lastY_;
        lastY_ = localY;
        if (std::isfinite(elapsedSeconds) && elapsedSeconds > 1.0e-5F) {
            const float instantaneous = glm::clamp(
                delta / elapsedSeconds, -kMaximumVelocity, kMaximumVelocity);
            velocity_ = glm::mix(velocity_, instantaneous, 0.45F);
        }
        return consume(delta);
    }

    void release() {
        dragging_ = false;
        if (std::abs(velocity_) < kFlickVelocityThreshold) {
            velocity_ = 0.0F;
            settleOnNotch();
        }
    }

    [[nodiscard]] int updateMomentum(float elapsedSeconds) {
        if (dragging_ || !std::isfinite(elapsedSeconds) || elapsedSeconds <= 0.0F) {
            return 0;
        }
        if (std::abs(velocity_) < kStopVelocity) {
            velocity_ = 0.0F;
            settleOnNotch();
            return 0;
        }
        const float delta = velocity_ * elapsedSeconds;
        velocity_ *= std::exp(-kDampingPerSecond * elapsedSeconds);
        return consume(delta);
    }

    void reset() {
        dragging_ = false;
        lastY_ = 0.0F;
        velocity_ = 0.0F;
        accumulatedTravel_ = 0.0F;
        totalTravel_ = 0.0F;
    }

    [[nodiscard]] bool dragging() const { return dragging_; }
    [[nodiscard]] bool moving() const {
        return dragging_ || std::abs(velocity_) >= kStopVelocity;
    }
    [[nodiscard]] float velocity() const { return velocity_; }
    [[nodiscard]] float phase() const {
        const float result = std::fmod(totalTravel_ / kNotchTravel, 1.0F);
        return std::abs(result) < 1.0e-5F ||
               std::abs(std::abs(result) - 1.0F) < 1.0e-5F
            ? 0.0F : result;
    }

  private:
    void settleOnNotch() {
        totalTravel_ = std::round(
            (totalTravel_ - accumulatedTravel_) / kNotchTravel) * kNotchTravel;
        accumulatedTravel_ = 0.0F;
    }

    [[nodiscard]] int consume(float delta) {
        if (!std::isfinite(delta)) return 0;
        accumulatedTravel_ += delta;
        totalTravel_ += delta;
        const int steps = std::clamp(
            static_cast<int>(accumulatedTravel_ / kNotchTravel), -64, 64);
        accumulatedTravel_ -= static_cast<float>(steps) * kNotchTravel;
        return steps;
    }

    bool dragging_ = false;
    float lastY_ = 0.0F;
    float velocity_ = 0.0F;
    float accumulatedTravel_ = 0.0F;
    float totalTravel_ = 0.0F;
};

struct MenuPanelBounds {
    glm::vec2 minimum{};
    glm::vec2 maximum{};
};

/** Resize a panel to a target aspect while multiplying its area around the same
 * center. This keeps Desktop large without assuming a 16:9 workstation. */
inline MenuPanelBounds aspectScaledMenuBounds(
    const glm::vec2& minimum, const glm::vec2& maximum,
    float aspectRatio, float areaMultiplier) {
    const glm::vec2 size = glm::max(maximum - minimum, glm::vec2(1.0e-4F));
    const float safeAspect = glm::clamp(aspectRatio, 0.5F, 4.0F);
    const float safeMultiplier = std::max(areaMultiplier, 1.0e-4F);
    const float area = size.x * size.y * safeMultiplier;
    const float width = std::sqrt(area * safeAspect);
    const float height = width / safeAspect;
    const glm::vec2 center = (minimum + maximum) * 0.5F;
    const glm::vec2 half(width * 0.5F, height * 0.5F);
    return {center - half, center + half};
}

/** Reversible eased 0..1 transition used by Expanded Quick View. */
class SmoothToggle {
  public:
    explicit SmoothToggle(float durationSeconds = 0.24F)
        : durationSeconds_(std::max(durationSeconds, 1.0e-4F)) {}

    void toggle() { target_ = !target_; }
    void setTarget(bool target) { target_ = target; }

    [[nodiscard]] bool update(float elapsedSeconds) {
        if (!std::isfinite(elapsedSeconds) || elapsedSeconds <= 0.0F) return false;
        const float before = progress_;
        const float direction = target_ ? 1.0F : -1.0F;
        progress_ = glm::clamp(
            progress_ + direction * elapsedSeconds / durationSeconds_, 0.0F, 1.0F);
        return std::abs(progress_ - before) > 1.0e-6F;
    }

    [[nodiscard]] float value() const {
        return progress_ * progress_ * (3.0F - 2.0F * progress_);
    }
    [[nodiscard]] bool target() const { return target_; }
    [[nodiscard]] bool settled() const {
        return target_ ? progress_ >= 1.0F : progress_ <= 0.0F;
    }

  private:
    float durationSeconds_ = 0.24F;
    float progress_ = 0.0F;
    bool target_ = false;
};

inline std::string nextTabSelectionLevel(const std::string& current) {
    static constexpr std::array<const char*, 6> cycle = {
        "strand", "domain", "end", "xover", "base", "default",
    };
    const auto found = std::find_if(cycle.begin(), cycle.end(), [&](const char* level) {
        return current == level;
    });
    if (found == cycle.end()) return cycle.front();
    return cycle[(static_cast<size_t>(found - cycle.begin()) + 1U) % cycle.size()];
}

/** A menu hover ticks once on entry or when crossing to another control. */
inline bool menuHoverHapticRequested(int previousTarget, int currentTarget) {
    return currentTarget >= 0 && currentTarget != previousTarget;
}

/** Per-controller Selection Volume radius driven by a vertical trackpad drag. */
class SelectionVolumeControl {
  public:
    static constexpr float kMinimumRadius = 0.008F;
    static constexpr float kMaximumRadius = 0.180F;
    static constexpr float kDefaultRadius = 0.025F;
    static constexpr float kMetersPerTrackpadUnit = 0.080F;

    void beginScroll(float y) {
        scrolling_ = true;
        lastY_ = glm::clamp(y, -1.0F, 1.0F);
    }

    [[nodiscard]] bool updateScroll(float y) {
        y = glm::clamp(y, -1.0F, 1.0F);
        if (!scrolling_) {
            beginScroll(y);
            return false;
        }
        const float next = glm::clamp(
            radius_ + (y - lastY_) * kMetersPerTrackpadUnit,
            kMinimumRadius, kMaximumRadius);
        lastY_ = y;
        if (std::abs(next - radius_) < 1.0e-5F) return false;
        radius_ = next;
        return true;
    }

    void endScroll() { scrolling_ = false; }
    [[nodiscard]] float radius() const { return radius_; }
    [[nodiscard]] bool scrolling() const { return scrolling_; }

  private:
    float radius_ = kDefaultRadius;
    float lastY_ = 0.0F;
    bool scrolling_ = false;
};

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
    std::vector<std::string> selectionIdentities;
    std::vector<std::string> selectionOwnerTokens;
};

struct ToolContextFeedback {
    uint64_t sequence = 0;
    bool resolved = false;
    bool occupied = false;
    bool deformed = false;
    bool footprintResolved = false;
    std::string latticeType = "HONEYCOMB";
    LatticeCell footprintCell{};
    std::string reason;
    std::string selectionKind = "none";
    std::string identity;
    glm::vec3 facePosition{};
    glm::vec3 faceNormal{};
    glm::vec3 previewOrigin{};
    bool expandedPoseResolved = false;
    glm::vec3 expandedFacePosition{};
    glm::vec3 expandedFaceNormal{};
    glm::vec3 expandedPreviewOrigin{};
};

struct ToolPreflightFeedback {
    uint64_t toolConfigSequence = 0;
    uint64_t preflightSequence = 0;
    std::string status;
    std::string mode;
    std::string selectionKind = "none";
    std::string identity;
    std::string reason;
};

struct ToolExecutionFeedback {
    uint64_t sequence = 0;
    uint64_t toolSequence = 0;
    std::string mode;
    std::string action;
    std::string selectionKind = "none";
    std::string identity;
    std::string status;
    std::string reason;
    std::string featureLogEntryId;
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
    bool expandedFrameResolved = false;
    glm::vec3 expandedPlaneCenter{};
    glm::vec3 expandedPlaneNormal{};
    float expandedPlaneHalfExtentNanometers = 0.0F;
};

struct OwnerAliasEntry {
    std::string identity;
    std::vector<std::string> tokens;

    bool operator==(const OwnerAliasEntry&) const = default;
};

/** Resolve one primitive to the canonical owner used by the active desktop filter.
 * Token contents remain opaque; the scene's typed handle table supplies semantics. */
inline std::optional<std::string> selectionVolumeOwnerToken(
    const std::vector<OwnerAliasEntry>& aliases,
    const std::vector<std::pair<std::string, std::string>>& tokenKinds,
    const std::string& identity, const std::string& selectionLevel) {
    const std::string targetKind = selectionLevel == "default"
        ? "strand" : selectionLevel == "xover" ? "crossover" : selectionLevel;
    const auto owner = std::find_if(
        aliases.begin(), aliases.end(), [&](const OwnerAliasEntry& candidate) {
            return candidate.identity == identity;
        });
    if (owner == aliases.end()) return std::nullopt;
    for (const std::string& token : owner->tokens) {
        const auto typed = std::find_if(
            tokenKinds.begin(), tokenKinds.end(), [&](const auto& candidate) {
                return candidate.first == token && candidate.second == targetKind;
            });
        if (typed != tokenKinds.end()) return token;
    }
    return std::nullopt;
}

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
            return adjustExtrudeLengthBp(direction > 0 ? 1 : -1);
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

    [[nodiscard]] bool adjustExtrudeLengthBp(int64_t delta) {
        if (!active_ || mode_ != ToolMode::extrude || delta == 0) return false;
        const int64_t next = static_cast<int64_t>(lengthBp_) + delta;
        const int32_t clamped = static_cast<int32_t>(
            std::clamp<int64_t>(next, 0, kMaximumLengthBp));
        if (clamped == lengthBp_) return false;
        lengthBp_ = clamped;
        return true;
    }

    /** Move between lattice-repeat detents. A partial value set by another
     * control first lands on the adjacent repeat rather than skipping it. */
    [[nodiscard]] bool adjustExtrudeLengthDetents(
        int detents, int32_t basePairsPerDetent) {
        if (!active_ || mode_ != ToolMode::extrude || detents == 0 ||
            basePairsPerDetent <= 0) return false;
        const int64_t period = basePairsPerDetent;
        const int64_t anchor = detents > 0
            ? static_cast<int64_t>(lengthBp_) / period
            : (static_cast<int64_t>(lengthBp_) + period - 1) / period;
        const int64_t target = (anchor + detents) * period;
        const int32_t clamped = static_cast<int32_t>(
            std::clamp<int64_t>(target, 0, kMaximumLengthBp));
        if (clamped == lengthBp_) return false;
        lengthBp_ = clamped;
        return true;
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
        if (executionPending_) return;
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
        } else if (executionPending_ && action != ToolAction::confirm &&
                   action != ToolAction::cancel && action != ToolAction::undo) {
            return;
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
            if (capability == ToolCapability::configuration_required) {
                status_ = "CONFIG REQUIRED";
            } else if (previewRequested_ && directPreview && !executionPending_) {
                executionPending_ = true;
                status_ = "COMMITTING";
            } else {
                status_ = executionPending_ ? "COMMITTING" : "PREVIEW FIRST";
            }
        } else if (action == ToolAction::cancel) {
            if (executionPending_) {
                status_ = "COMMITTING";
                return;
            }
            previewRequested_ = false;
            status_ = undoAvailable_ ? "COMMITTED" : "CANCELLED";
        } else {
            if (executionPending_) status_ = "COMMITTING";
            else if (undoAvailable_) {
                executionPending_ = true;
                status_ = "UNDOING";
            } else status_ = "NO VR COMMIT";
        }
    }

    void applyExecutionFeedback(const ToolExecutionFeedback& feedback) {
        if (feedback.mode != toolModeName(mode_)) return;
        const bool succeeded = feedback.status == "succeeded";
        const bool pending = feedback.status == "pending";
        if (feedback.action == "confirm") {
            if (pending) {
                executionPending_ = true;
                status_ = "COMMITTING";
            } else if (succeeded) {
                executionPending_ = false;
                previewRequested_ = false;
                undoAvailable_ = true;
                status_ = "COMMITTED";
            } else {
                executionPending_ = false;
                status_ = feedback.status == "refused" ? "COMMIT REFUSED" : "COMMIT FAILED";
            }
        } else if (feedback.action == "undo") {
            if (pending) {
                executionPending_ = true;
                status_ = "UNDOING";
            } else if (succeeded) {
                executionPending_ = false;
                undoAvailable_ = false;
                status_ = "UNDONE";
            } else {
                executionPending_ = false;
                if (feedback.status == "refused" &&
                    feedback.reason == "undo_stale_desktop_changed") {
                    undoAvailable_ = false;
                }
                status_ = feedback.status == "refused" ? "UNDO REFUSED" : "UNDO FAILED";
            }
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
    [[nodiscard]] bool executionPending() const { return executionPending_; }
    [[nodiscard]] bool undoAvailable() const { return undoAvailable_; }
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
    bool executionPending_ = false;
    bool undoAvailable_ = false;
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
        magic != "NADOCVR_FEEDBACK" || (version < 1 || version > 5) ||
        (accepted != 0 && accepted != 1) || (selected != 0 && selected != 1) ||
        result.sequence <= previousSequence || result.sequence > maximumSequence) {
        return std::nullopt;
    }
    if (version >= 3) {
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
    if (version >= 4) {
        size_t selectionCount = 0;
        if (!(fields >> selectionCount) || selectionCount > 16) return std::nullopt;
        result.selectionIdentities.resize(selectionCount);
        size_t totalBytes = 0;
        for (std::string& identity : result.selectionIdentities) {
            if (!(fields >> identity) || identity.empty() || identity.size() > 2048) {
                return std::nullopt;
            }
            totalBytes += identity.size();
        }
        if (totalBytes > 2048) return std::nullopt;
        std::sort(result.selectionIdentities.begin(), result.selectionIdentities.end());
        if (std::adjacent_find(
                result.selectionIdentities.begin(), result.selectionIdentities.end()) !=
            result.selectionIdentities.end()) {
            return std::nullopt;
        }
    } else if (selected == 1 && result.identity != "-") {
        result.selectionIdentities = {result.identity};
    }
    if (version >= 5) {
        size_t ownerSelectionCount = 0;
        if (!(fields >> ownerSelectionCount) || ownerSelectionCount > 16) {
            return std::nullopt;
        }
        result.selectionOwnerTokens.resize(ownerSelectionCount);
        size_t totalBytes = 0;
        for (std::string& token : result.selectionOwnerTokens) {
            if (!(fields >> token) || token.empty() || token.size() > 2048) {
                return std::nullopt;
            }
            totalBytes += token.size();
        }
        if (totalBytes > 2048) return std::nullopt;
        std::sort(result.selectionOwnerTokens.begin(), result.selectionOwnerTokens.end());
        if (std::adjacent_find(
                result.selectionOwnerTokens.begin(), result.selectionOwnerTokens.end()) !=
            result.selectionOwnerTokens.end()) {
            return std::nullopt;
        }
    } else if (selected == 1 && !result.ownerTokens.empty()) {
        result.selectionOwnerTokens = {result.ownerTokens.front()};
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
    if (version >= 3 && std::find(
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

inline std::optional<ToolExecutionFeedback> parseToolExecutionFeedback(
    const std::string& record, uint64_t previousSequence,
    uint64_t maximumToolSequence) {
    std::istringstream fields(record);
    std::string magic;
    std::string trailing;
    int version = 0;
    ToolExecutionFeedback result;
    if (!(fields >> magic >> version >> result.sequence >> result.toolSequence
                 >> result.mode >> result.action >> result.selectionKind
                 >> result.identity >> result.status >> result.reason
                 >> result.featureLogEntryId) ||
        magic != "NADOCVR_TOOL_EXECUTION" || version != 1 ||
        result.sequence <= previousSequence || result.toolSequence == 0 ||
        result.toolSequence > maximumToolSequence || result.identity.empty() ||
        result.identity == "-" || result.identity.size() > 2048 ||
        fields >> trailing) {
        return std::nullopt;
    }
    static constexpr std::array<const char*, 2> modes = {
        "move_rotate", "extrude",
    };
    static constexpr std::array<const char*, 2> actions = {"confirm", "undo"};
    static constexpr std::array<const char*, 4> statuses = {
        "pending", "succeeded", "failed", "refused",
    };
    static constexpr std::array<const char*, 10> selectionKinds = {
        "cluster", "strand", "domain", "base", "end", "bond",
        "crossover", "overhang", "extension", "protein",
    };
    if (std::find(modes.begin(), modes.end(), result.mode) == modes.end() ||
        std::find(actions.begin(), actions.end(), result.action) == actions.end() ||
        std::find(statuses.begin(), statuses.end(), result.status) == statuses.end() ||
        std::find(selectionKinds.begin(), selectionKinds.end(), result.selectionKind)
            == selectionKinds.end() ||
        result.reason.empty() || result.reason.size() > 64) {
        return std::nullopt;
    }
    if ((result.status == "succeeded") != (result.featureLogEntryId != "-") ||
        result.featureLogEntryId.size() > 128) {
        return std::nullopt;
    }
    if (result.featureLogEntryId == "-") result.featureLogEntryId.clear();
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
        magic != "NADOCVR_TOOL_FEEDBACK" ||
        (version != 1 && version != 2 && version != 3 && version != 4)) {
        return std::nullopt;
    }
    if (version >= 2 && !(fields >> footprintResolved)) return std::nullopt;
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
    if (version >= 4 && result.footprintResolved) {
        if (!(fields >> result.latticeType >> result.footprintCell.row
                     >> result.footprintCell.column) ||
            (result.latticeType != "HONEYCOMB" && result.latticeType != "SQUARE") ||
            std::abs(result.footprintCell.row) > 1'000'000 ||
            std::abs(result.footprintCell.column) > 1'000'000) {
            return std::nullopt;
        }
    }
    if (result.resolved) {
        auto readPose = [&](glm::vec3& position, glm::vec3& normal,
                            glm::vec3& origin) {
            if (!(fields >> position.x >> position.y >> position.z
                         >> normal.x >> normal.y >> normal.z) ||
                !std::isfinite(position.x) || !std::isfinite(position.y) ||
                !std::isfinite(position.z) || !std::isfinite(normal.x) ||
                !std::isfinite(normal.y) || !std::isfinite(normal.z) ||
                std::abs(position.x) > 1.0e9F ||
                std::abs(position.y) > 1.0e9F ||
                std::abs(position.z) > 1.0e9F) {
                return false;
            }
            if (result.footprintResolved &&
                (!(fields >> origin.x >> origin.y >> origin.z) ||
                 !std::isfinite(origin.x) || !std::isfinite(origin.y) ||
                 !std::isfinite(origin.z) || std::abs(origin.x) > 1.0e9F ||
                 std::abs(origin.y) > 1.0e9F || std::abs(origin.z) > 1.0e9F)) {
                return false;
            }
            const double normalLength = std::hypot(
                std::hypot(static_cast<double>(normal.x),
                           static_cast<double>(normal.y)),
                static_cast<double>(normal.z));
            if (normalLength <= 1.0e-9 || normalLength >= 1.0e9) return false;
            normal = glm::normalize(normal);
            return true;
        };
        if (!readPose(
                result.facePosition, result.faceNormal, result.previewOrigin)) {
            return std::nullopt;
        }
        if (version >= 3) {
            if (!readPose(
                    result.expandedFacePosition, result.expandedFaceNormal,
                    result.expandedPreviewOrigin)) {
                return std::nullopt;
            }
            result.expandedPoseResolved = true;
        }
    } else if (result.occupied || result.deformed || result.footprintResolved) {
        return std::nullopt;
    }
    std::string trailing;
    if (fields >> trailing) return std::nullopt;
    return result;
}

inline std::optional<ToolPreflightFeedback> parseToolPreflightFeedback(
    const std::string& record, uint64_t expectedToolConfigSequence,
    uint64_t previousPreflightSequence = 0) {
    std::istringstream fields(record);
    std::string magic;
    int version = 0;
    ToolPreflightFeedback result;
    std::string trailing;
    if (!(fields >> magic >> version >> result.toolConfigSequence
                 >> result.preflightSequence >> result.status
                 >> result.mode >> result.selectionKind >> result.identity
                 >> result.reason) ||
        magic != "NADOCVR_PREFLIGHT" || version != 2 ||
        result.toolConfigSequence != expectedToolConfigSequence ||
        result.preflightSequence <= previousPreflightSequence ||
        result.identity.size() > 2048 || result.reason.empty() ||
        result.reason.size() > 64 || (fields >> trailing)) {
        return std::nullopt;
    }
    static constexpr std::array<const char*, 5> statuses = {
        "waiting", "ok", "warn", "block", "error",
    };
    static constexpr std::array<const char*, 3> modes = {
        "extrude", "twist", "bend",
    };
    if (std::find(statuses.begin(), statuses.end(), result.status) == statuses.end() ||
        std::find(modes.begin(), modes.end(), result.mode) == modes.end() ||
        !std::all_of(result.reason.begin(), result.reason.end(), [](unsigned char value) {
            return std::islower(value) || std::isdigit(value) || value == '_';
        })) {
        return std::nullopt;
    }
    if (result.identity == "-") result.identity.clear();
    const bool noTarget = result.selectionKind == "none" && result.identity.empty();
    const bool compatibleTarget = !result.identity.empty() && (
        (result.mode == "extrude" && result.selectionKind == "end") ||
        ((result.mode == "twist" || result.mode == "bend") &&
         (result.selectionKind == "cluster" || result.selectionKind == "end")));
    if (!noTarget && !compatibleTarget) return std::nullopt;
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
        magic != "NADOCVR_PLANE_FEEDBACK" ||
        (version != 1 && version != 2 && version != 3) ||
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
        auto readFrame = [&](glm::vec3& center, glm::vec3& normal,
                             float& halfExtent) {
            if (!(fields >> center.x >> center.y >> center.z
                         >> normal.x >> normal.y >> normal.z >> halfExtent) ||
                !std::isfinite(center.x) || !std::isfinite(center.y) ||
                !std::isfinite(center.z) || !std::isfinite(normal.x) ||
                !std::isfinite(normal.y) || !std::isfinite(normal.z) ||
                !std::isfinite(halfExtent) || std::abs(center.x) > 1.0e9F ||
                std::abs(center.y) > 1.0e9F || std::abs(center.z) > 1.0e9F ||
                halfExtent <= 0.0F || halfExtent > 1.0e6F) {
                return false;
            }
            const double normalLength = std::hypot(
                std::hypot(static_cast<double>(normal.x),
                           static_cast<double>(normal.y)),
                static_cast<double>(normal.z));
            if (normalLength <= 1.0e-9 || normalLength >= 1.0e9) return false;
            normal = glm::normalize(normal);
            return true;
        };
        // Version 1 never carried a frame. Do not accept an exact bp without
        // the geometry required to display what will eventually be edited.
        if (version < 2 || !readFrame(
                result.planeCenter, result.planeNormal,
                result.planeHalfExtentNanometers)) {
            return std::nullopt;
        }
        result.frameResolved = true;
        if (version >= 3) {
            if (!readFrame(
                    result.expandedPlaneCenter, result.expandedPlaneNormal,
                    result.expandedPlaneHalfExtentNanometers)) {
                return std::nullopt;
            }
            result.expandedFrameResolved = true;
        }
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
