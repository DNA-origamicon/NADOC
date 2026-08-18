#include "interaction.hpp"
#include "picking.hpp"

#include <glm/gtc/epsilon.hpp>

#include <array>
#include <cmath>
#include <cstdlib>

namespace {

using nadoc_vr::HandPose;
using nadoc_vr::ManipulationMode;
using nadoc_vr::PendingRigidTransform;
using nadoc_vr::SceneManipulator;

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
    require(shell.status() == "READY");
    shell.apply(nadoc_vr::ToolAction::confirm, "cluster");
    require(shell.status() == "PREVIEW FIRST");
    shell.apply(nadoc_vr::ToolAction::preview, "cluster");
    require(shell.previewRequested() && shell.status() == "PREVIEW ONLY");
    shell.apply(nadoc_vr::ToolAction::confirm, "cluster");
    require(shell.status() == "CONFIRM STAGED");
    shell.apply(nadoc_vr::ToolAction::cancel, "cluster");
    require(!shell.previewRequested() && shell.status() == "CANCELLED");
    shell.apply(nadoc_vr::ToolAction::undo, "cluster");
    require(shell.status() == "NO VR COMMIT");

    shell.activate(nadoc_vr::ToolMode::move_rotate, "base");
    require(shell.status() == "UNSUPPORTED TARGET");
    shell.apply(nadoc_vr::ToolAction::preview, "base");
    require(!shell.previewRequested() && shell.status() == "UNSUPPORTED TARGET");
    shell.syncSelection("cluster");
    require(shell.status() == "READY");
    shell.apply(nadoc_vr::ToolAction::preview, "cluster");
    shell.syncSelection("base");
    require(!shell.previewRequested() && shell.status() == "UNSUPPORTED TARGET");
}

}  // namespace

int main() {
    oneHandGrabFollowsRigidControllerDelta();
    twoHandGrabScalesAroundMidpointWithoutJumping();
    oneTwoOneTransitionsStayContinuous();
    recenterRestoresUnitScaleInFrontOfHead();
    closeInspectionAllowsTheModelToPassThroughTheHead();
    pendingToolDragAccumulatesInModelSpaceAndCancelsExactly();
    pendingToolDragRotatesRigidlyWithTheController();
    endpointWeightsMoveOnlyTheOwnedBoundaryEndpoint();
    normalizedPreviewDeltaReturnsToSourceCoordinates();
    timingWindowReportsBoundedNearestRankPercentiles();
    rayPickingHitsVisiblePrimitiveSurfaces();
    rayPickingRejectsMissesAndBehindControllerGeometry();
    halfCylinderPickingMatchesTheRenderedPositiveHalf();
    canonicalSelectionFeedbackIsStrictAndSequenced();
    canonicalOwnerFallbackUsesFeedbackSpecificityAndSceneOrder();
    ownerBoundsAreStableAndFollowTheWorldTransform();
    toolShellNeverClaimsACommitAndRequiresPreview();
}
