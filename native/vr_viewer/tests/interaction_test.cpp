#include "interaction.hpp"
#include "jobs.hpp"
#include "picking.hpp"
#include "visualization.hpp"

#include <glm/gtc/epsilon.hpp>

#include <array>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>

namespace {

using nadoc_vr::HandPose;
using nadoc_vr::ManipulationMode;
using nadoc_vr::MenuPlacement;
using nadoc_vr::PendingRigidTransform;
using nadoc_vr::SceneManipulator;
using nadoc_vr::SelectionVolumeControl;
using nadoc_vr::SmoothToggle;

void require(bool condition) {
    if (!condition) std::abort();
}

glm::vec3 transformedOrigin(const glm::mat4& matrix) {
    return glm::vec3(matrix * glm::vec4(0, 0, 0, 1));
}

glm::vec3 transformedPoint(const glm::mat4& matrix, const glm::vec3& point) {
    return glm::vec3(matrix * glm::vec4(point, 1));
}

void oneHandGrabFollowsRigidControllerDelta() {
    SceneManipulator manipulator;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, true, {0.2F, 0.1F, -0.4F}, {1, 0, 0, 0}};
    require(manipulator.update(hands) == ManipulationMode::left);
    hands[0].position += glm::vec3(0.3F, -0.2F, 0.1F);
    manipulator.update(hands);
    require(glm::all(glm::epsilonEqual(
        transformedOrigin(manipulator.transform()), glm::vec3(0.3F, -0.2F, 0.1F), 1e-5F)));
}

void twoHandGrabScalesAroundMidpointWithoutJumping() {
    SceneManipulator manipulator;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, true, {-0.2F, 0, -0.5F}, {1, 0, 0, 0}};
    hands[1] = {true, true, {0.2F, 0, -0.5F}, {1, 0, 0, 0}};
    manipulator.update(hands);
    const glm::mat4 initial = manipulator.transform();
    hands[0].position.x = -0.4F;
    hands[1].position.x = 0.4F;
    manipulator.update(hands);
    require(std::abs(manipulator.scale() - 2.0F) < 1e-5F);
    // The midpoint is invariant, hence maps to itself through the scale delta.
    const glm::vec3 midpoint(0, 0, -0.5F);
    const glm::vec3 before = glm::vec3(initial * glm::vec4(midpoint, 1));
    const glm::vec3 after = glm::vec3(manipulator.transform() * glm::vec4(midpoint, 1));
    require(glm::all(glm::epsilonEqual(before, after, 1e-5F)));
}

void oneTwoOneTransitionsStayContinuous() {
    SceneManipulator manipulator;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, true, {-0.2F, 0, -0.5F}, {1, 0, 0, 0}};
    manipulator.update(hands);
    hands[0].position.x += 0.1F;
    hands[1] = {true, true, {0.3F, 0, -0.5F}, {1, 0, 0, 0}};
    manipulator.update(hands);
    const glm::vec3 atTwoHandStart = transformedOrigin(manipulator.transform());
    require(glm::all(glm::epsilonEqual(atTwoHandStart, glm::vec3(0.1F, 0, 0), 1e-5F)));

    hands[1].pressed = false;
    manipulator.update(hands);
    require(glm::all(glm::epsilonEqual(
        transformedOrigin(manipulator.transform()), atTwoHandStart, 1e-5F)));
}

void recenterRestoresUnitScaleInFrontOfHead() {
    SceneManipulator manipulator;
    const glm::quat turn = glm::angleAxis(glm::radians(90.0F), glm::vec3(0, 1, 0));
    manipulator.recenter({1, 2, 3}, turn);
    const glm::vec3 modelCenter(0, 0, -SceneManipulator::kViewDistanceMeters);
    const glm::vec3 actual = glm::vec3(manipulator.transform() * glm::vec4(modelCenter, 1));
    const glm::vec3 expected = glm::vec3(1, 2, 3)
                             + turn * glm::vec3(0, 0, -SceneManipulator::kViewDistanceMeters);
    require(glm::all(glm::epsilonEqual(actual, expected, 1e-5F)));
    require(std::abs(manipulator.scale() - 1.0F) < 1e-5F);
}

void closeInspectionAllowsTheModelToPassThroughTheHead() {
    SceneManipulator manipulator;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, true, {0, 0, -0.4F}, {1, 0, 0, 0}};
    manipulator.update(hands);
    hands[0].position.z += SceneManipulator::kViewDistanceMeters;
    manipulator.update(hands);

    const glm::vec3 modelCenter(0, 0, -SceneManipulator::kViewDistanceMeters);
    require(glm::all(glm::epsilonEqual(
        transformedPoint(manipulator.transform(), modelCenter), glm::vec3(0), 1e-5F)));
}

void menuFollowsItsControllerAndDockingFreezesItsWorldPose() {
    MenuPlacement menu;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, false, {0.1F, 0.2F, -0.3F}, {1, 0, 0, 0}};
    hands[1] = {true, false, {-0.2F, 0.1F, -0.4F}, {1, 0, 0, 0}};
    menu.open(0, hands, {0, 0, -1}, {1, 0, 0, 0});
    const glm::vec3 initial = menu.position();
    require(std::abs(
        menu.localPoint(hands[0].position).x + MenuPlacement::kMenuHalfWidth)
        < 1e-5F);
    const glm::quat expectedTilt = glm::angleAxis(
        glm::radians(-38.0F), glm::vec3(1.0F, 0.0F, 0.0F));
    require(std::abs(glm::dot(menu.orientation(), expectedTilt)) > 1.0F - 1e-5F);

    hands[0].position += glm::vec3(0.25F, -0.10F, 0.05F);
    hands[0].orientation = glm::angleAxis(
        glm::radians(30.0F), glm::vec3(0.0F, 1.0F, 0.0F));
    menu.update(hands);
    require(glm::length(menu.position() - initial) > 0.1F);
    require(glm::dot(
        menu.orientation() * glm::vec3(0.0F, 1.0F, 0.0F),
        hands[0].orientation * glm::vec3(0.0F, 0.0F, -1.0F)) > 0.0F);

    menu.toggleDock(1, hands);
    const glm::vec3 docked = menu.position();
    hands[0].position += glm::vec3(1.0F);
    menu.update(hands);
    require(menu.worldDocked());
    require(glm::all(glm::epsilonEqual(menu.position(), docked, 1e-5F)));

    menu.toggleDock(1, hands);
    require(!menu.worldDocked() && menu.anchorHand() == 1U);
    require(std::abs(
        menu.localPoint(hands[1].position).x - MenuPlacement::kMenuHalfWidth)
        < 1e-5F);
    const glm::vec3 followed = menu.position();
    hands[1].position.x += 0.2F;
    menu.update(hands);
    require(std::abs(menu.position().x - followed.x - 0.2F) < 1e-5F);
}

void dockedMenuBorderGripMovesOnlyAfterAProximatePress() {
    MenuPlacement menu;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, false, {0, 0, -0.4F}, {1, 0, 0, 0}};
    menu.open(0, hands, {0, 0, -1}, {1, 0, 0, 0});
    menu.toggleDock(0, hands);
    const glm::vec2 minimum(-MenuPlacement::kMenuHalfWidth, -0.545F);
    const glm::vec2 maximum(MenuPlacement::kMenuHalfWidth, 0.33F);

    hands[1] = {true, true, menu.worldPoint({0, 0, 0}), {1, 0, 0, 0}};
    require(!menu.nearBorder(hands[1], minimum, maximum));
    require(!menu.beginDrag(1, hands, minimum, maximum));
    require(menu.beginDrag(1, hands, minimum, maximum, true));
    require(menu.worldDocked());
    hands[1].pressed = false;
    menu.update(hands);

    hands[1].position = menu.worldPoint({maximum.x, 0.0F, 0.01F});
    hands[1].pressed = true;
    require(menu.nearBorder(hands[1], minimum, maximum));
    require(menu.beginDrag(1, hands, minimum, maximum));
    const glm::vec3 before = menu.position();
    hands[1].position += glm::vec3(0.20F, 0.10F, -0.05F);
    hands[1].orientation = glm::angleAxis(
        glm::radians(20.0F), glm::vec3(0.0F, 1.0F, 0.0F));
    menu.update(hands);
    require(menu.worldDocked() && menu.dragHand() == 1U);
    require(glm::length(menu.position() - before) > 0.20F);

    hands[1].pressed = false;
    menu.update(hands);
    require(!menu.dragHand());
}

void secondBorderGripTransitionsMenuDragIntoResize() {
    MenuPlacement menu;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, false, {0, 0, -0.4F}, {1, 0, 0, 0}};
    menu.open(0, hands, {0, 0, -1}, {1, 0, 0, 0});
    menu.toggleDock(0, hands);
    const glm::vec2 minimum(-MenuPlacement::kMenuHalfWidth, -0.545F);
    const glm::vec2 maximum(MenuPlacement::kMenuHalfWidth, 0.33F);

    hands[0] = {true, true, menu.worldPoint({minimum.x, 0, 0}), {1, 0, 0, 0}};
    hands[1] = {true, true, menu.worldPoint({0, 0, 0}), {1, 0, 0, 0}};
    require(!menu.beginBorderResize(hands, minimum, maximum));
    hands[1].pressed = false;
    require(menu.beginDrag(0, hands, minimum, maximum));
    require(menu.dragHand() == 0U);
    hands[1].position = menu.worldPoint({maximum.x, 0, 0});
    hands[1].pressed = true;
    require(menu.beginBorderResize(hands, minimum, maximum));
    require(menu.resizeActive() && !menu.dragHand());

    const float initialScale = menu.scale();
    const glm::vec3 initialPosition = menu.position();
    const glm::vec3 initialMidpoint = (hands[0].position + hands[1].position) * 0.5F;
    hands[0].position = initialMidpoint +
        (hands[0].position - initialMidpoint) * 1.4F + glm::vec3(0.1F, 0, 0);
    hands[1].position = initialMidpoint +
        (hands[1].position - initialMidpoint) * 1.4F + glm::vec3(0.1F, 0, 0);
    menu.update(hands);
    require(std::abs(menu.scale() - initialScale * 1.4F) < 1e-5F);
    require(std::abs(menu.position().x - initialPosition.x - 0.1F) < 1e-5F);

    hands[1].pressed = false;
    menu.update(hands);
    require(!menu.resizeActive() && menu.worldDocked());
}

void desktopMenuBoundsDoubleAreaAndMatchAspect() {
    const glm::vec2 minimum(-MenuPlacement::kMenuHalfWidth, -0.545F);
    const glm::vec2 maximum(MenuPlacement::kMenuHalfWidth, 0.33F);
    const auto desktop = nadoc_vr::aspectScaledMenuBounds(
        minimum, maximum, 16.0F / 10.0F, 2.0F);
    const glm::vec2 normalSize = maximum - minimum;
    const glm::vec2 desktopSize = desktop.maximum - desktop.minimum;
    require(std::abs(
        desktopSize.x * desktopSize.y - normalSize.x * normalSize.y * 2.0F) < 1e-5F);
    require(std::abs(desktopSize.x / desktopSize.y - 1.6F) < 1e-5F);
    require(glm::all(glm::epsilonEqual(
        (desktop.minimum + desktop.maximum) * 0.5F,
        (minimum + maximum) * 0.5F, 1e-5F)));

    MenuPlacement menu;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, false, {0, 0, -0.4F}, {1, 0, 0, 0}};
    menu.open(0, hands, {0, 0, -1}, {1, 0, 0, 0});
    menu.update(hands, desktopSize.x * 0.5F);
    const glm::vec3 handInMenu = menu.localPoint(hands[0].position);
    require(std::abs(handInMenu.x + desktopSize.x * 0.5F) < 1e-5F);
}

void expandedQuickViewEasesAndReversesWithoutSnapping() {
    SmoothToggle transition(0.20F);
    require(transition.value() == 0.0F && transition.settled());
    transition.toggle();
    require(transition.target() && !transition.settled());
    require(transition.update(0.05F));
    const float quarter = transition.value();
    require(quarter > 0.0F && quarter < 0.25F);
    require(transition.update(0.05F));
    const float halfway = transition.value();
    require(std::abs(halfway - 0.5F) < 1e-5F);

    transition.toggle();
    require(!transition.target());
    require(std::abs(transition.value() - halfway) < 1e-5F);
    require(transition.update(0.05F));
    require(std::abs(transition.value() - quarter) < 1e-5F);
    require(transition.update(0.20F));
    require(transition.value() == 0.0F && transition.settled());
}

void vrSelectionLevelCycleMatchesDesktopTabOrder() {
    require(nadoc_vr::nextTabSelectionLevel("default") == "strand");
    require(nadoc_vr::nextTabSelectionLevel("cluster") == "strand");
    require(nadoc_vr::nextTabSelectionLevel("strand") == "domain");
    require(nadoc_vr::nextTabSelectionLevel("domain") == "end");
    require(nadoc_vr::nextTabSelectionLevel("end") == "xover");
    require(nadoc_vr::nextTabSelectionLevel("xover") == "base");
    require(nadoc_vr::nextTabSelectionLevel("base") == "default");
}

void menuHoverHapticsTickOnlyWhenEnteringOrChangingControls() {
    require(!nadoc_vr::menuHoverHapticRequested(-1, -1));
    require(nadoc_vr::menuHoverHapticRequested(-1, 4));
    require(!nadoc_vr::menuHoverHapticRequested(4, 4));
    require(nadoc_vr::menuHoverHapticRequested(4, 5));
    require(!nadoc_vr::menuHoverHapticRequested(5, -1));
    require(nadoc_vr::menuHoverHapticRequested(-1, 5));
}

void selectionVolumeScrollResizesPreciselyAndStaysBounded() {
    SelectionVolumeControl volume;
    require(std::abs(volume.radius() - SelectionVolumeControl::kDefaultRadius) < 1e-6F);
    volume.beginScroll(-0.5F);
    require(volume.updateScroll(0.5F));
    require(volume.radius() > SelectionVolumeControl::kDefaultRadius);
    require(volume.updateScroll(-1.0F));
    require(volume.radius() >= SelectionVolumeControl::kMinimumRadius);
    volume.endScroll();
    require(!volume.scrolling());

    volume.beginScroll(-1.0F);
    (void)volume.updateScroll(1.0F);
    volume.endScroll();
    volume.beginScroll(-1.0F);
    (void)volume.updateScroll(1.0F);
    require(volume.radius() <= SelectionVolumeControl::kMaximumRadius);
}

void selectionVolumeOverlapMatchesRenderedPrimitiveVolumes() {
    require(nadoc_vr::sphereOverlapsSphere(
        {0.0F, 0.0F, 0.0F}, 0.05F, {0.09F, 0.0F, 0.0F}, 0.04F));
    require(!nadoc_vr::sphereOverlapsSphere(
        {0.0F, 0.0F, 0.0F}, 0.04F, {0.09F, 0.0F, 0.0F}, 0.04F));
    require(nadoc_vr::sphereOverlapsCapsule(
        {0.5F, 0.08F, 0.0F}, 0.04F,
        {0.0F, 0.0F, 0.0F}, {1.0F, 0.0F, 0.0F}, 0.05F));
    require(nadoc_vr::sphereOverlapsBox(
        {0.55F, 0.0F, 0.0F}, 0.06F, {0.0F, 0.0F, 0.0F},
        {1.0F, 0.0F, 0.0F}, {0.0F, 1.0F, 0.0F}, {0.0F, 0.0F, 1.0F}));

    // The rendered half-cylinder occupies +basisX only; a precise small sphere
    // on the absent half must not snap to it.
    require(!nadoc_vr::sphereOverlapsHalfCylinder(
        {-0.08F, 0.0F, 0.5F}, 0.02F,
        {0.0F, 0.0F, 0.0F}, {0.0F, 0.0F, 1.0F}, 0.10F));
    require(nadoc_vr::sphereOverlapsHalfCylinder(
        {0.08F, 0.0F, 0.5F}, 0.02F,
        {0.0F, 0.0F, 0.0F}, {0.0F, 0.0F, 1.0F}, 0.10F));
}

void selectionVolumeUsesDesktopFilterOwner() {
    const std::vector<nadoc_vr::OwnerAliasEntry> aliases = {
        {"primitive:a", {
            "base:a", "domain:a", "strand:a", "xover:a", "cluster:a"}},
    };
    const std::vector<std::pair<std::string, std::string>> kinds = {
        {"base:a", "base"},
        {"domain:a", "domain"},
        {"strand:a", "strand"},
        {"cluster:a", "cluster"},
        {"xover:a", "crossover"},
    };
    require(nadoc_vr::selectionVolumeOwnerToken(
        aliases, kinds, "primitive:a", "domain") == "domain:a");
    require(nadoc_vr::selectionVolumeOwnerToken(
        aliases, kinds, "primitive:a", "default") == "strand:a");
    require(nadoc_vr::selectionVolumeOwnerToken(
        aliases, kinds, "primitive:a", "xover") == "xover:a");
    require(!nadoc_vr::selectionVolumeOwnerToken(
        aliases, kinds, "missing", "strand"));
}

void menuScalingKeepsRenderingAndHitCoordinatesAligned() {
    MenuPlacement menu;
    std::array<HandPose, 2> hands{};
    hands[0] = {true, false, {0.1F, 0.2F, -0.3F}, {1, 0, 0, 0}};
    menu.open(0, hands, {0, 0, -1}, {1, 0, 0, 0});
    const glm::vec3 local(0.22F, -0.505F, 0.002F);
    require(glm::all(glm::epsilonEqual(
        menu.localPoint(menu.worldPoint(local)), local, 1e-5F)));

    const float leftEdgeBefore = menu.localPoint(hands[0].position).x;
    require(std::abs(leftEdgeBefore + MenuPlacement::kMenuHalfWidth) < 1e-5F);
    require(menu.adjustScale(1));
    require(std::abs(
        menu.localPoint(hands[0].position).x + MenuPlacement::kMenuHalfWidth)
        < 1e-5F);

    while (menu.adjustScale(-1)) {}
    require(std::abs(menu.scale() - MenuPlacement::kMinimumScale) < 1e-5F);
    require(!menu.adjustScale(-1));
    while (menu.adjustScale(1)) {}
    require(std::abs(menu.scale() - MenuPlacement::kMaximumScale) < 1e-5F);
    require(!menu.adjustScale(1));
    require(glm::all(glm::epsilonEqual(
        menu.localPoint(menu.worldPoint(local)), local, 1e-5F)));
}

void menuRayPanelHitExistsOnlyInsideTheVisibleTablet() {
    MenuPlacement menu;
    std::array<HandPose, 2> hands{};
    menu.open(0, hands, {0, 0, -1}, {1, 0, 0, 0});
    const glm::vec2 minimum(-MenuPlacement::kMenuHalfWidth, -0.545F);
    const glm::vec2 maximum(MenuPlacement::kMenuHalfWidth, 0.33F);

    HandPose ray{true, false, {0, 0, 0}, {1, 0, 0, 0}};
    const auto center = menu.rayPanelLocalPoint(ray, minimum, maximum);
    require(center && glm::length(*center) < 1e-5F);

    ray.position.x = 1.0F;
    require(!menu.rayPanelLocalPoint(ray, minimum, maximum));
    ray.position.x = 0.0F;
    ray.orientation = glm::angleAxis(
        glm::radians(180.0F), glm::vec3(0.0F, 1.0F, 0.0F));
    require(!menu.rayPanelLocalPoint(ray, minimum, maximum));
}

void pendingToolDragAccumulatesInModelSpaceAndCancelsExactly() {
    PendingRigidTransform pending;
    pending.activate();
    require(pending.isIdentity());

    const glm::mat4 model = glm::translate(glm::mat4(1.0F), {2.0F, 0.0F, 0.0F})
                          * glm::scale(glm::mat4(1.0F), glm::vec3(2.0F));
    HandPose hand{true, true, {0.0F, 0.0F, -0.5F}, {1, 0, 0, 0}};
    require(!pending.update(hand, model, true));
    require(pending.dragging());
    hand.position.x = 0.2F;
    require(pending.update(hand, model, true));
    require(glm::all(glm::epsilonEqual(
        transformedOrigin(pending.transform()), glm::vec3(0.1F, 0.0F, 0.0F), 1e-5F)));

    hand.pressed = false;
    pending.update(hand, model, false);
    require(!pending.dragging());
    hand.pressed = true;
    require(!pending.update(hand, model, true));
    hand.position.x = 0.4F;
    pending.update(hand, model, true);
    require(glm::all(glm::epsilonEqual(
        transformedOrigin(pending.transform()), glm::vec3(0.2F, 0.0F, 0.0F), 1e-5F)));

    pending.cancel();
    require(!pending.dragging());
    require(pending.isIdentity(0.0F));
}

void pendingToolDragRotatesRigidlyWithTheController() {
    PendingRigidTransform pending;
    HandPose hand{true, true, {0.0F, 0.0F, 0.0F}, {1, 0, 0, 0}};
    pending.update(hand, glm::mat4(1.0F), true);
    hand.orientation = glm::angleAxis(
        glm::radians(90.0F), glm::vec3(0.0F, 0.0F, 1.0F));
    pending.update(hand, glm::mat4(1.0F), true);
    require(glm::all(glm::epsilonEqual(
        transformedPoint(pending.transform(), {1.0F, 0.0F, 0.0F}),
        glm::vec3(0.0F, 1.0F, 0.0F), 1e-5F)));
}

void endpointWeightsMoveOnlyTheOwnedBoundaryEndpoint() {
    const glm::mat4 transform = glm::translate(
        glm::mat4(1.0F), {2.0F, 3.0F, 4.0F});
    const glm::vec3 start = nadoc_vr::weightedTransformPoint(
        {0.0F, 0.0F, 0.0F}, transform, 1.0F);
    const glm::vec3 end = nadoc_vr::weightedTransformPoint(
        {1.0F, 0.0F, 0.0F}, transform, 0.0F);
    require(glm::all(glm::epsilonEqual(start, glm::vec3(2.0F, 3.0F, 4.0F), 1e-5F)));
    require(glm::all(glm::epsilonEqual(end, glm::vec3(1.0F, 0.0F, 0.0F), 1e-5F)));

    const glm::mat4 rotation = glm::toMat4(glm::angleAxis(
        glm::radians(90.0F), glm::vec3(0.0F, 0.0F, 1.0F)));
    const glm::vec3 axis = nadoc_vr::weightedTransformVector(
        {1.0F, 0.0F, 0.0F}, rotation, 1.0F);
    require(glm::all(glm::epsilonEqual(axis, glm::vec3(0.0F, 1.0F, 0.0F), 1e-5F)));
}

void normalizedPreviewDeltaReturnsToSourceCoordinates() {
    const glm::vec3 center(10.0F, -2.0F, 4.0F);
    constexpr float scale = 0.1F;
    const glm::vec3 offset(0.0F, 0.0F, -0.8F);
    const glm::mat4 normalizedDelta = glm::translate(
        glm::mat4(1.0F), {0.2F, -0.1F, 0.3F});
    const glm::mat4 sourceDelta = nadoc_vr::normalizedToSourceTransform(
        normalizedDelta, center, scale, offset);
    require(glm::all(glm::epsilonEqual(
        transformedOrigin(sourceDelta), glm::vec3(2.0F, -1.0F, 3.0F), 1e-5F)));

    const glm::vec3 sourcePoint(12.0F, 1.0F, -3.0F);
    const glm::mat4 normalization = glm::translate(glm::mat4(1.0F), offset)
                                  * glm::scale(glm::mat4(1.0F), glm::vec3(scale))
                                  * glm::translate(glm::mat4(1.0F), -center);
    const glm::vec3 viaNormalized = transformedPoint(
        glm::inverse(normalization) * normalizedDelta * normalization, sourcePoint);
    require(glm::all(glm::epsilonEqual(
        transformedPoint(sourceDelta, sourcePoint), viaNormalized, 1e-5F)));
}

void toolLocatorUsesTheSceneNormalizationExactly() {
    const glm::vec3 normalized = nadoc_vr::sourceToNormalizedPoint(
        {3.0F, 5.0F, 7.0F}, {1.0F, 2.0F, 3.0F}, 0.25F,
        {0.0F, 0.0F, -1.30F});
    require(glm::all(glm::epsilonEqual(
        normalized, glm::vec3(0.5F, 0.75F, -0.30F), 1.0e-6F)));
}

void extrusionPreviewUsesBpRiseScaleAndOutwardSign() {
    const glm::vec3 outward = nadoc_vr::extrusionPreviewEnd(
        {1.0F, 2.0F, 3.0F}, {0.0F, 0.0F, 2.0F}, 10, 1, 0.334F, 0.5F);
    require(glm::all(glm::epsilonEqual(
        outward, glm::vec3(1.0F, 2.0F, 4.67F), 1.0e-6F)));
    const glm::vec3 inward = nadoc_vr::extrusionPreviewEnd(
        {1.0F, 2.0F, 3.0F}, {0.0F, 0.0F, 1.0F}, 10, -1, 0.334F, 0.5F);
    require(glm::all(glm::epsilonEqual(
        inward, glm::vec3(1.0F, 2.0F, 1.33F), 1.0e-6F)));
}

void timingWindowReportsBoundedNearestRankPercentiles() {
    nadoc_vr::TimingWindow timing(100);
    for (int sample = 1; sample <= 100; ++sample) {
        const bool full = timing.add(static_cast<double>(sample));
        require(full == (sample == 100));
    }
    const auto summary = timing.takeSummary();
    require(summary && summary->samples == 100);
    require(summary->p50Milliseconds == 50.0);
    require(summary->p95Milliseconds == 95.0);
    require(summary->p99Milliseconds == 99.0);
    require(summary->maxMilliseconds == 100.0);
    require(!timing.takeSummary());
    require(!timing.add(-1.0));
}

void rayPickingHitsVisiblePrimitiveSurfaces() {
    const nadoc_vr::Ray ray{{0, 0, 1}, {0, 0, -1}};
    const auto sphere = nadoc_vr::raySphere(ray, {0, 0, 0}, 0.2F);
    require(sphere && std::abs(*sphere - 0.8F) < 1e-5F);

    const auto capsule = nadoc_vr::rayCapsule(
        nadoc_vr::Ray{{0.1F, 0, 1}, {0, 0, -1}},
        {-0.5F, 0, 0}, {0.5F, 0, 0}, 0.2F);
    require(capsule && *capsule > 0.79F && *capsule < 0.81F);

    const auto box = nadoc_vr::rayBox(
        ray, {0, 0, 0}, {0.4F, 0, 0}, {0, 0.2F, 0}, {0, 0, 0.6F});
    require(box && std::abs(*box - 0.7F) < 1e-5F);
}

void rayPickingRejectsMissesAndBehindControllerGeometry() {
    const nadoc_vr::Ray ray{{0, 0, 1}, {0, 0, -1}};
    require(!nadoc_vr::raySphere(ray, {2, 0, 0}, 0.2F));
    require(!nadoc_vr::rayCapsule(ray, {2, 0, 0}, {3, 0, 0}, 0.2F));
    require(!nadoc_vr::rayBox(
        ray, {0, 0, 2}, {0.4F, 0, 0}, {0, 0.2F, 0}, {0, 0, 0.6F}));
}

void halfCylinderPickingMatchesTheRenderedPositiveHalf() {
    const glm::vec3 start(0, 0, 0);
    const glm::vec3 end(0, 0, 2);
    const auto curved = nadoc_vr::rayHalfCylinder(
        nadoc_vr::Ray{{2, 0, 1}, {-1, 0, 0}}, start, end, 1.0F);
    require(curved && std::abs(*curved - 1.0F) < 1.0e-5F);

    // From the missing -X half, the first visible surface is the flat face at X=0,
    // not the nonexistent negative curved wall at X=-radius.
    const auto flat = nadoc_vr::rayHalfCylinder(
        nadoc_vr::Ray{{-2, 0, 1}, {1, 0, 0}}, start, end, 1.0F);
    require(flat && std::abs(*flat - 2.0F) < 1.0e-5F);
    require(!nadoc_vr::rayHalfCylinder(
        nadoc_vr::Ray{{-2, 0, 1}, {-1, 0, 0}}, start, end, 1.0F));

    const auto cap = nadoc_vr::rayHalfCylinder(
        nadoc_vr::Ray{{0.5F, 0, 3}, {0, 0, -1}}, start, end, 1.0F);
    require(cap && std::abs(*cap - 1.0F) < 1.0e-5F);
}

void canonicalSelectionFeedbackIsStrictAndSequenced() {
    const auto selected = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 1 4 1 1 base nuc:s1:0:h1:3:FORWARD:0\n", 3, 4);
    require(selected && selected->sequence == 4 && selected->accepted && selected->selected);
    require(selected->level == "base");
    require(selected->identity == "nuc:s1:0:h1:3:FORWARD:0");

    const auto deselected = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 1 5 1 0 domain -\n", 4, 5);
    require(deselected && deselected->identity.empty() && !deselected->selected);
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 1 4 1 1 base stale\n", 4, 5));
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 1 6 1 1 atom future\n", 4, 6));
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 1 6 1 1 base identity trailing\n", 4, 6));

    const auto hierarchical = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 2 6 1 1 base primitive 3 exact base domain\n", 5, 6);
    require(hierarchical && hierarchical->ownerTokens.size() == 3);
    require(hierarchical->ownerTokens[0] == "exact");
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 2 6 1 1 base primitive 2 only-one\n", 5, 6));
    const auto cleared = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 2 7 1 0 base - 2 stale tokens\n", 6, 7);
    require(cleared && cleared->ownerTokens.empty());
    const auto typed = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 3 8 1 1 cluster cluster primitive 1 cluster-token\n", 7, 8);
    require(typed && typed->selectionKind == "cluster");
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 3 9 1 1 cluster atom primitive 1 token\n", 8, 9));
    const auto area = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 4 9 1 0 base none primitive-a 0 3 "
        "primitive-a primitive-b primitive-c\n", 8, 9);
    require(area && area->selectionIdentities.size() == 3);
    require(std::find(
        area->selectionIdentities.begin(), area->selectionIdentities.end(),
        "primitive-b") != area->selectionIdentities.end());
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 4 10 1 0 base none primitive-a 0 2 same same\n", 9, 10));
    const auto grouped = nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 5 11 1 0 strand none primitive-a 0 2 "
        "primitive-a primitive-b 2 strand-a strand-b\n", 10, 11);
    require(grouped && grouped->selectionOwnerTokens.size() == 2);
    require(std::find(
        grouped->selectionOwnerTokens.begin(), grouped->selectionOwnerTokens.end(),
        "strand-b") != grouped->selectionOwnerTokens.end());
    require(!nadoc_vr::parseSelectionFeedback(
        "NADOCVR_FEEDBACK 5 12 1 0 strand none primitive-a 0 1 "
        "primitive-a 2 same same\n", 11, 12));
}

void toolContextFeedbackIsExactSequencedAndFinite() {
    const auto resolved = nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 3 7 1 1 0 1 resolved end nuc:end "
        "1 2 3 0 0 2 4 5 6 7 8 9 0 3 0 10 11 12\n",
        6, 7);
    require(resolved && resolved->resolved && resolved->occupied && !resolved->deformed);
    require(resolved->footprintResolved);
    require(resolved->identity == "nuc:end");
    require(glm::all(glm::epsilonEqual(
        resolved->facePosition, glm::vec3(1, 2, 3), 1e-6F)));
    require(glm::all(glm::epsilonEqual(
        resolved->faceNormal, glm::vec3(0, 0, 1), 1e-6F)));
    require(glm::all(glm::epsilonEqual(
        resolved->previewOrigin, glm::vec3(4, 5, 6), 1e-6F)));
    require(resolved->expandedPoseResolved);
    require(glm::all(glm::epsilonEqual(
        resolved->expandedFacePosition, glm::vec3(7, 8, 9), 1e-6F)));
    require(glm::all(glm::epsilonEqual(
        resolved->expandedFaceNormal, glm::vec3(0, 1, 0), 1e-6F)));
    require(glm::all(glm::epsilonEqual(
        resolved->expandedPreviewOrigin, glm::vec3(10, 11, 12), 1e-6F)));

    const auto naturalOnly = nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 2 8 1 0 0 1 resolved end nuc:end "
        "1 2 3 0 0 1 4 5 6\n",
        7, 8);
    require(naturalOnly && naturalOnly->resolved &&
            !naturalOnly->expandedPoseResolved);

    const auto missing = nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 1 8 0 0 0 no_continuation_face end nuc:end\n",
        7, 8);
    require(missing && !missing->resolved && missing->reason == "no_continuation_face");
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 1 7 1 0 0 resolved end nuc:end 0 0 0 0 0 1\n",
        7, 8));
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 1 9 1 0 0 resolved end nuc:end 0 0 0 0 0 1\n",
        7, 8));
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 1 8 1 0 0 resolved end nuc:end 0 0 0 0 0 0\n",
        7, 8));
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 1 8 0 1 0 no_continuation_face end nuc:end\n",
        7, 8));
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 2 8 0 0 0 1 no_continuation_face end nuc:end\n",
        7, 8));
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 3 8 1 0 0 1 resolved end nuc:end "
        "1 2 3 0 0 1 4 5 6\n",
        7, 8));
    require(!nadoc_vr::parseToolContextFeedback(
        "NADOCVR_TOOL_FEEDBACK 1 8 1 0 0 resolved end nuc:end 1e10 0 0 0 0 1\n",
        7, 8));
}

void toolPreflightFeedbackIsTargetBoundSequencedAndStrict() {
    const auto ok = nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 12 7 ok extrude end nuc:end validated\n", 12, 6);
    require(ok && ok->status == "ok" && ok->mode == "extrude" &&
            ok->preflightSequence == 7 &&
            ok->selectionKind == "end" && ok->identity == "nuc:end" &&
            ok->reason == "validated");
    const auto noTarget = nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 13 8 block bend none - stale_target\n", 13, 7);
    require(noTarget && noTarget->identity.empty());
    const auto waiting = nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 13 9 waiting bend none - design_changed\n", 13, 8);
    require(waiting && waiting->status == "waiting");
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 11 10 ok extrude end nuc:end validated\n", 12, 9));
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 12 10 ok extrude cluster cluster:c1 validated\n", 12, 9));
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 12 10 ready extrude end nuc:end validated\n", 12, 9));
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 12 10 block twist end nuc:end bad-reason\n", 12, 9));
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 12 10 block twist end nuc:end backend_block extra\n", 12, 9));
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 2 12 9 ok extrude end nuc:end validated\n", 12, 9));
    require(!nadoc_vr::parseToolPreflightFeedback(
        "NADOCVR_PREFLIGHT 1 12 ok extrude end nuc:end validated\n", 12));
}

void planePickFeedbackIsTargetBoundSequencedAndStrict() {
    const auto accepted = nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 3 9 4 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 2 8 4 5 6 0 3 0 8\n",
        8, 9, 4);
    require(accepted && accepted->resolved && accepted->slot == "a" &&
            accepted->planeBp == 27 && accepted->targetIdentity == "nuc:end" &&
            accepted->pickedIdentity == "nuc:pick" && accepted->frameResolved &&
            glm::all(glm::epsilonEqual(
                accepted->planeCenter, glm::vec3(1, 2, 3), 1e-6F)) &&
            glm::all(glm::epsilonEqual(
                accepted->planeNormal, glm::vec3(0, 0, 1), 1e-6F)) &&
            std::abs(accepted->planeHalfExtentNanometers - 8.0F) < 1e-6F &&
            accepted->expandedFrameResolved &&
            glm::all(glm::epsilonEqual(
                accepted->expandedPlaneCenter, glm::vec3(4, 5, 6), 1e-6F)) &&
            glm::all(glm::epsilonEqual(
                accepted->expandedPlaneNormal, glm::vec3(0, 1, 0), 1e-6F)) &&
            std::abs(accepted->expandedPlaneHalfExtentNanometers - 8.0F) < 1e-6F);
    const auto naturalOnly = nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 10 4 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 1 8\n",
        9, 10, 4);
    require(naturalOnly && naturalOnly->frameResolved &&
            !naturalOnly->expandedFrameResolved);
    const auto rejected = nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 3 11 4 0 ambiguous_primitive b cluster cluster:c1 bond:x\n",
        10, 11, 4);
    require(rejected && !rejected->resolved && rejected->slot == "b");
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 9 4 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 1 8\n",
        9, 9, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 11 5 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 1 8\n",
        10, 11, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 11 4 0 resolved a end nuc:end nuc:pick\n",
        10, 11, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 11 4 1 resolved x end nuc:end nuc:pick "
        "27 1 2 3 0 0 1 8\n",
        10, 11, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 1 11 4 1 resolved a end nuc:end nuc:pick 27\n",
        10, 11, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 3 11 4 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 1 8\n",
        10, 11, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 11 4 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 0 8\n",
        10, 11, 4));
    require(!nadoc_vr::parsePlanePickFeedback(
        "NADOCVR_PLANE_FEEDBACK 2 11 4 1 resolved a end nuc:end nuc:pick "
        "27 1 2 3 0 0 1 -8\n",
        10, 11, 4));
}

void canonicalOwnerFallbackUsesFeedbackSpecificityAndSceneOrder() {
    const std::vector<nadoc_vr::OwnerAliasEntry> entries = {
        {"domain:first", {"domain", "strand"}},
        {"base:exact", {"base", "domain", "strand"}},
        {"domain:second", {"domain", "strand"}},
    };
    const auto exact = nadoc_vr::resolveOwnerIdentity(
        entries, {"missing-primitive", "base", "domain", "strand"});
    require(exact && *exact == "base:exact");
    const auto coarse = nadoc_vr::resolveOwnerIdentity(entries, {"domain", "strand"});
    require(coarse && *coarse == "domain:first");
    require(!nadoc_vr::resolveOwnerIdentity(entries, {"cluster"}));
}

void ownerBoundsAreStableAndFollowTheWorldTransform() {
    nadoc_vr::BoundsAccumulator bounds;
    require(!bounds.summary());
    bounds.includePoint({-1.0F, 0.0F, 0.0F}, 0.2F);
    bounds.includeSegment({1.0F, -0.5F, 0.0F}, {1.0F, 0.5F, 0.0F}, 0.1F);
    bounds.includeBox(
        {0.0F, 0.0F, 1.0F}, {0.4F, 0.0F, 0.0F},
        {0.0F, 0.2F, 0.0F}, {0.0F, 0.0F, 0.6F});
    const auto local = bounds.summary();
    require(local.has_value());
    require(glm::all(glm::epsilonEqual(
        local->center, glm::vec3(-0.05F, 0.0F, 0.55F), 1e-5F)));

    const glm::mat4 transform = glm::translate(glm::mat4(1.0F), {2.0F, 3.0F, 4.0F})
                              * glm::scale(glm::mat4(1.0F), glm::vec3(2.0F));
    const auto world = bounds.summary(transform);
    require(world.has_value());
    require(glm::all(glm::epsilonEqual(
        world->center, glm::vec3(1.9F, 3.0F, 5.1F), 1e-5F)));
    require(std::abs(world->radius - local->radius * 2.0F) < 1e-5F);
}

void toolShellNeverClaimsACommitAndRequiresPreview() {
    nadoc_vr::ToolShell shell;
    shell.activate(nadoc_vr::ToolMode::twist, "none");
    require(shell.status() == "SELECT TARGET");
    shell.syncSelection("cluster");
    require(shell.status() == "CONFIG REQUIRED");
    shell.apply(nadoc_vr::ToolAction::confirm, "cluster");
    require(shell.status() == "CONFIG REQUIRED");
    shell.apply(nadoc_vr::ToolAction::preview, "cluster");
    require(!shell.previewRequested() && shell.status() == "CONFIG REQUIRED");
    shell.apply(nadoc_vr::ToolAction::cancel, "cluster");
    require(!shell.previewRequested() && shell.status() == "CANCELLED");
    shell.apply(nadoc_vr::ToolAction::undo, "cluster");
    require(shell.status() == "NO VR COMMIT");

    require(nadoc_vr::ToolShell::selectionCapability(
        nadoc_vr::ToolMode::extrude, "end") ==
        nadoc_vr::ToolCapability::configuration_required);
    require(nadoc_vr::ToolShell::selectionCapability(
        nadoc_vr::ToolMode::twist, "end") ==
        nadoc_vr::ToolCapability::configuration_required);
    require(nadoc_vr::ToolShell::selectionCapability(
        nadoc_vr::ToolMode::bend, "cluster") ==
        nadoc_vr::ToolCapability::configuration_required);
    require(nadoc_vr::ToolShell::selectionCapability(
        nadoc_vr::ToolMode::extrude, "base") ==
        nadoc_vr::ToolCapability::unsupported);
    require(nadoc_vr::ToolShell::selectionCapability(
        nadoc_vr::ToolMode::bend, "domain") ==
        nadoc_vr::ToolCapability::unsupported);

    shell.activate(nadoc_vr::ToolMode::move_rotate, "base");
    require(shell.status() == "READY");
    shell.apply(nadoc_vr::ToolAction::preview, "base");
    require(shell.previewRequested() && shell.status() == "PREVIEW ONLY");
    shell.apply(nadoc_vr::ToolAction::confirm, "base");
    require(shell.executionPending() && shell.status() == "COMMITTING");
    shell.applyExecutionFeedback(nadoc_vr::ToolExecutionFeedback{
        1, 9, "move_rotate", "confirm", "base", "nuc:s1", "succeeded",
        "committed", "feature:9",
    });
    require(!shell.executionPending() && !shell.previewRequested());
    require(shell.undoAvailable() && shell.status() == "COMMITTED");
    shell.apply(nadoc_vr::ToolAction::undo, "base");
    require(shell.executionPending() && shell.status() == "UNDOING");
    shell.applyExecutionFeedback(nadoc_vr::ToolExecutionFeedback{
        2, 10, "move_rotate", "undo", "base", "nuc:s1", "succeeded",
        "undone", "feature:9",
    });
    require(!shell.executionPending() && !shell.undoAvailable());
    require(shell.status() == "UNDONE");
    shell.apply(nadoc_vr::ToolAction::preview, "base");
    shell.syncSelection("domain", true);
    require(!shell.previewRequested() && shell.status() == "READY");
    shell.apply(nadoc_vr::ToolAction::preview, "cluster");
    shell.syncSelection("cluster", true);
    require(!shell.previewRequested() && shell.status() == "READY");
    shell.apply(nadoc_vr::ToolAction::preview, "cluster");
    shell.syncSelection("bond");
    require(!shell.previewRequested() && shell.status() == "UNSUPPORTED TARGET");
}

void toolExecutionFeedbackIsStrictSequencedAndTransactionBound() {
    const auto committed = nadoc_vr::parseToolExecutionFeedback(
        "NADOCVR_TOOL_EXECUTION 1 4 9 move_rotate confirm domain nuc:s1 "
        "succeeded committed feature:9\n",
        3, 9);
    require(committed && committed->sequence == 4 && committed->toolSequence == 9);
    require(committed->selectionKind == "domain");
    require(committed->featureLogEntryId == "feature:9");
    require(!nadoc_vr::parseToolExecutionFeedback(
        "NADOCVR_TOOL_EXECUTION 1 4 9 move_rotate confirm domain nuc:s1 "
        "succeeded committed feature:9\n",
        4, 9));
    require(!nadoc_vr::parseToolExecutionFeedback(
        "NADOCVR_TOOL_EXECUTION 1 5 10 move_rotate undo domain nuc:s1 "
        "succeeded undone -\n",
        4, 10));
    const auto refused = nadoc_vr::parseToolExecutionFeedback(
        "NADOCVR_TOOL_EXECUTION 1 6 10 move_rotate undo domain nuc:s1 "
        "refused undo_stale_desktop_changed -\n",
        4, 10);
    require(refused && refused->featureLogEntryId.empty());
}

void parameterizedToolDraftsResetOnTargetChangesAndStayBounded() {
    nadoc_vr::ToolConfigurationDraft draft;
    require(draft.bind(
        nadoc_vr::ToolMode::extrude, "end:first", "end", {"end-token"}));
    require(draft.active() && draft.lengthBp() == 0);
    require(std::string(draft.unresolvedGeometry()) == "FOOTPRINT");
    require(draft.adjustPrimary(1) && draft.lengthBp() == 1);
    require(draft.adjustSecondary(1) && draft.directionSign() == -1);
    require(draft.cycleOption() &&
            draft.strandFilter() == nadoc_vr::ToolStrandFilter::scaffold);
    require(draft.toggleFlag() && !draft.ligateAdjacent());
    require(!draft.bind(
        nadoc_vr::ToolMode::extrude, "end:first", "end", {"end-token"}));
    require(draft.lengthBp() == 1);  // Same target preserves its draft.

    require(draft.bind(
        nadoc_vr::ToolMode::extrude, "end:second", "end", {"other-token"}));
    require(draft.lengthBp() == 0 && draft.directionSign() == 1 &&
            draft.strandFilter() == nadoc_vr::ToolStrandFilter::both &&
            draft.ligateAdjacent());

    require(draft.bind(
        nadoc_vr::ToolMode::twist, "cluster:c1", "cluster", {"cluster-token"}));
    require(!draft.planeABp() && !draft.planeBBp());
    require(std::string(draft.unresolvedGeometry()) == "PLANES A/B");
    require(draft.twistAmount() == 90.0);
    require(draft.adjustPrimary(-1) && draft.twistAmount() == 85.0);
    require(draft.cycleOption());
    require(draft.twistAmountMode() == nadoc_vr::TwistAmountMode::degrees_per_nm);
    require(draft.twistAmount() == 1.0);
    require(draft.adjustPrimary(-1) && std::abs(draft.twistAmount() - 0.9) < 1e-9);
    require(draft.setPlaneBp("a", 12) && draft.planeABp() == 12);
    require(draft.setPlaneBp("b", 24) && draft.planeBBp() == 24);
    require(!draft.setPlaneBp("b", 24));
    require(!draft.setPlaneBp("x", 30));

    require(draft.bind(
        nadoc_vr::ToolMode::bend, "cluster:c1", "cluster", {"cluster-token"}));
    require(!draft.adjustPrimary(-1));
    require(draft.adjustPrimary(1) && draft.bendAngleDegrees() == 1.0);
    require(draft.adjustSecondary(-1) && draft.bendDirectionDegrees() == 355.0);
    require(draft.clear() && !draft.active());
    require(!draft.clear());
}

void jobSnapshotParserPreservesIdentityStatusAndRejectsAmbiguity() {
    const auto path = std::filesystem::temp_directory_path() /
                      "nadoc-vr-job-snapshot-test.txt";
    {
        std::ofstream output(path);
        output << "NADOCVR_JOBS 1 2 1 9\n"
               << "J 0 1000 1 1 0 oxdna completed relax - Six%20helix%20bundle "
                  "oxDNA%20-%20completed%20-%20100.0%25\n"
               << "J 1 125 0 0 1 oxdna running production relax Production "
                  "oxDNA%20-%20running%20-%2012.5%25\n";
    }
    const auto snapshot = nadoc_vr::loadJobSnapshot(path.string());
    const auto& rows = snapshot.rows;
    require(snapshot.available && snapshot.total == 9);
    require(rows.size() == 2);
    require(rows[0].jobId == "relax" && rows[0].label == "Six helix bundle");
    require(rows[0].viewable && rows[0].stale && rows[0].progressPermille == 1000);
    require(rows[1].parentJobId == "relax" && rows[1].depth == 1);
    require(rows[1].archived && rows[1].statusText == "oxDNA - running - 12.5%");

    {
        std::ofstream output(path);
        output << "NADOCVR_JOBS 2 7 1 1 4 1700000001500\n"
               << "J 0 425 1 0 0 namd running run%2017 - Production "
                  "NAMD%20-%20running%20-%2042.5%25\n";
    }
    const auto live = nadoc_vr::loadJobSnapshot(path.string());
    require(live.sequence == 7 && live.updatedAtMs == 1'700'000'001'500ULL);
    require(live.total == 4 && live.rows.size() == 1);

    {
        std::ofstream output(path);
        output << "NADOCVR_JOBS 3 8 1 1 1 1700000002000 namd run%2017 stick cpk\n"
               << "J 0 425 1 0 0 namd running run%2017 - Production "
                  "NAMD%20-%20running%20-%2042.5%25\n";
    }
    const auto companion = nadoc_vr::loadJobSnapshot(path.string());
    require(companion.activeEngine == "namd" && companion.activeJobId == "run 17");
    require(companion.representation == "stick" && companion.coloring == "cpk");

    {
        std::ofstream output(path);
        output << "NADOCVR_JOBS 1 2 1 2\n"
               << "J 0 0 0 0 0 namd queued duplicate - First waiting\n"
               << "J 0 0 0 0 0 namd queued duplicate - Second waiting\n";
    }
    bool rejected = false;
    try {
        (void)nadoc_vr::loadJobSnapshot(path.string());
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    require(rejected);

    {
        std::ofstream output(path);
        output << "NADOCVR_JOBS 3 9 0 1 0 1700000003000 namd missing full strand\n";
    }
    rejected = false;
    try {
        (void)nadoc_vr::loadJobSnapshot(path.string());
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    std::filesystem::remove(path);
    require(rejected);
}

void visualizationSnapshotParserPreservesPositionsColorsAndRejectsDuplicates() {
    const auto path = std::filesystem::temp_directory_path() /
                      "nadoc-vr-visualization-test.txt";
    {
        std::ofstream output(path);
        output << "NADOCVR_VISUALIZATION 3 7 namd_rmsf ballstick cpk 2\n"
               << "F %5B%22base%22%2C%22h0%3A4%3AFORWARD%22%5D 1 2 3 12abef "
                  "1.5 2.5 3.5 0.3 0 0 0 0.06 0 0 0 0.7\n"
               << "V %5B%22base%22%2C%22h0%3A5%3AFORWARD%22%5D -1 0.5 8 -\n";
    }
    const auto snapshot = nadoc_vr::loadVisualizationSnapshot(path.string());
    require(snapshot.sequence == 7 && snapshot.mode == "namd_rmsf");
    require(snapshot.representation == "ballstick" && snapshot.coloring == "cpk");
    require(snapshot.points.size() == 2 && snapshot.points[0].hasColor);
    require(glm::all(glm::epsilonEqual(
        snapshot.points[0].position, glm::vec3(1, 2, 3), 1.0e-6F)));
    require(glm::all(glm::epsilonEqual(
        snapshot.points[0].color,
        glm::vec3(0x12 / 255.0F, 0xab / 255.0F, 0xef / 255.0F), 1.0e-6F)));
    require(!snapshot.points[1].hasColor);
    require(snapshot.points[0].hasSlabFrame);
    require(glm::all(glm::epsilonEqual(
        snapshot.points[0].slabCenter, glm::vec3(1.5F, 2.5F, 3.5F), 1.0e-6F)));

    {
        std::ofstream output(path);
        output << "NADOCVR_VISUALIZATION 2 8 legacy 0\n";
    }
    const auto legacy = nadoc_vr::loadVisualizationSnapshot(path.string());
    require(legacy.representation.empty() && legacy.coloring.empty());

    {
        std::ofstream output(path);
        output << "NADOCVR_VISUALIZATION 1 9 flex 2\n"
               << "V duplicate 1 2 3 -\n"
               << "V duplicate 4 5 6 ffffff\n";
    }
    bool rejected = false;
    try {
        (void)nadoc_vr::loadVisualizationSnapshot(path.string());
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    std::filesystem::remove(path);
    require(rejected);
}

void atomVisualizationOffsetsReplaceCoarseBaseOffsets() {
    const std::array<nadoc_vr::VisualizationOffsetContribution, 2> values{{
        {{10.0F, 20.0F, 30.0F}, 1.0F, 0.0F, false},
        {{1.0F, 2.0F, 3.0F}, 1.0F, 0.0F, true},
    }};
    const auto [start, end] = nadoc_vr::aggregateVisualizationOffsets(
        values.data(), values.size());
    require(glm::all(glm::epsilonEqual(start, glm::vec3(1, 2, 3), 1.0e-6F)));
    require(glm::all(glm::epsilonEqual(end, glm::vec3(0), 1.0e-6F)));
}

void liveSlabConnectorUsesTheDisplayedSlabCorner() {
    const glm::vec3 center(2.0F, 3.0F, 4.0F);
    const glm::vec3 axisX(0.0F, 0.30F, 0.0F);
    const glm::vec3 axisZ(0.0F, 0.0F, 0.70F);
    require(glm::all(glm::epsilonEqual(
        nadoc_vr::visualizationSlabConnectionCorner(
            center, axisX, axisZ, glm::vec3(2.0F, 3.0F, 3.0F)),
        glm::vec3(2.0F, 3.15F, 3.65F), 1.0e-6F)));
    require(glm::all(glm::epsilonEqual(
        nadoc_vr::visualizationSlabConnectionCorner(
            center, axisX, axisZ, glm::vec3(2.0F, 3.0F, 5.0F)),
        glm::vec3(2.0F, 3.15F, 4.35F), 1.0e-6F)));
}

}  // namespace

int main() {
    oneHandGrabFollowsRigidControllerDelta();
    twoHandGrabScalesAroundMidpointWithoutJumping();
    oneTwoOneTransitionsStayContinuous();
    recenterRestoresUnitScaleInFrontOfHead();
    closeInspectionAllowsTheModelToPassThroughTheHead();
    menuFollowsItsControllerAndDockingFreezesItsWorldPose();
    dockedMenuBorderGripMovesOnlyAfterAProximatePress();
    secondBorderGripTransitionsMenuDragIntoResize();
    desktopMenuBoundsDoubleAreaAndMatchAspect();
    menuScalingKeepsRenderingAndHitCoordinatesAligned();
    menuRayPanelHitExistsOnlyInsideTheVisibleTablet();
    expandedQuickViewEasesAndReversesWithoutSnapping();
    vrSelectionLevelCycleMatchesDesktopTabOrder();
    menuHoverHapticsTickOnlyWhenEnteringOrChangingControls();
    selectionVolumeScrollResizesPreciselyAndStaysBounded();
    selectionVolumeOverlapMatchesRenderedPrimitiveVolumes();
    selectionVolumeUsesDesktopFilterOwner();
    pendingToolDragAccumulatesInModelSpaceAndCancelsExactly();
    pendingToolDragRotatesRigidlyWithTheController();
    endpointWeightsMoveOnlyTheOwnedBoundaryEndpoint();
    normalizedPreviewDeltaReturnsToSourceCoordinates();
    toolLocatorUsesTheSceneNormalizationExactly();
    extrusionPreviewUsesBpRiseScaleAndOutwardSign();
    timingWindowReportsBoundedNearestRankPercentiles();
    rayPickingHitsVisiblePrimitiveSurfaces();
    rayPickingRejectsMissesAndBehindControllerGeometry();
    halfCylinderPickingMatchesTheRenderedPositiveHalf();
    canonicalSelectionFeedbackIsStrictAndSequenced();
    toolContextFeedbackIsExactSequencedAndFinite();
    toolPreflightFeedbackIsTargetBoundSequencedAndStrict();
    planePickFeedbackIsTargetBoundSequencedAndStrict();
    canonicalOwnerFallbackUsesFeedbackSpecificityAndSceneOrder();
    ownerBoundsAreStableAndFollowTheWorldTransform();
    toolShellNeverClaimsACommitAndRequiresPreview();
    toolExecutionFeedbackIsStrictSequencedAndTransactionBound();
    parameterizedToolDraftsResetOnTargetChangesAndStayBounded();
    jobSnapshotParserPreservesIdentityStatusAndRejectsAmbiguity();
    visualizationSnapshotParserPreservesPositionsColorsAndRejectsDuplicates();
    atomVisualizationOffsetsReplaceCoarseBaseOffsets();
    liveSlabConnectorUsesTheDisplayedSlabCorner();
}
