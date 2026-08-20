#include "interaction.hpp"
#include "jobs.hpp"
#include "picking.hpp"

#include <glm/gtc/epsilon.hpp>

#include <array>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>

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
    std::filesystem::remove(path);
    require(rejected);
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
}
