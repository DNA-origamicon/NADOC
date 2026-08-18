#include "interaction.hpp"
#include "picking.hpp"

#include <glm/gtc/epsilon.hpp>

#include <array>
#include <cmath>
#include <cstdlib>

namespace {

using nadoc_vr::HandPose;
using nadoc_vr::ManipulationMode;
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

}  // namespace

int main() {
    oneHandGrabFollowsRigidControllerDelta();
    twoHandGrabScalesAroundMidpointWithoutJumping();
    oneTwoOneTransitionsStayContinuous();
    recenterRestoresUnitScaleInFrontOfHead();
    closeInspectionAllowsTheModelToPassThroughTheHead();
    rayPickingHitsVisiblePrimitiveSurfaces();
    rayPickingRejectsMissesAndBehindControllerGeometry();
}
