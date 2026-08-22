#include "scrywrite_evidence.hpp"

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    std::istringstream sceneInput(
        "NADOCVR 6 full strand\n"
        "R full\n"
        "C helix -1 0 0 1 0 0 .1 0 1 1 0 1 1 0 1 1 0 1 1\n"
        "P end -1 0 0 .2 1 1 1 1 1 1 1 1 1 1 1 1 1\n");
    const auto scene = nadoc_vr::scrywrite::loadEvidenceScene(sceneInput);
    require(scene.segments.size() == 1, "evidence parser should retain Full cylinders");
    require(scene.points.size() == 1, "evidence parser should retain Full points");
    require(std::abs(scene.segments[0].start.x + 0.3F) < 1.0e-6F,
            "evidence geometry should use the viewer normalization scale");
    nadoc_vr::scrywrite::WitnessInput actor;
    actor.head.position = {0.0F, 0.0F, 0.0F};
    std::istringstream expectationInput(
        "SCRYWRITE_EVIDENCE 1\n"
        "total_primitives 2\n"
        "min_in_frame_fraction 1\n"
        "min_fully_in_frame_fraction 1\n"
        "max_clipped_primitives 0\n"
        "min_readable_fraction 1\n"
        "min_projected_bounds_fraction .001\n"
        "max_gaze_error_degrees 1\n");
    const auto expectations =
        nadoc_vr::scrywrite::loadEvidenceExpectations(expectationInput);
    const auto evidence = nadoc_vr::scrywrite::renderEvidence(
        scene, actor, "fixture \"quoted\"", &expectations);
    require(evidence.inFramePrimitives == 2, "forward actor should frame both primitives");
    require(evidence.fullyInFramePrimitives == 2,
            "forward actor should fully contain both primitives");
    require(evidence.validationPassed, "strict forward evidence should pass");
    require(std::abs(evidence.gazeTargetErrorDegrees) < 1.0e-5F,
            "forward actor should be aimed at the scene center");
    require(evidence.povSvg.find("SCRYWRITE ACTOR POV") != std::string::npos,
            "POV export should be self-identifying");
    require(evidence.topDownSvg.find("STRUCTURE LONG AXIS YAW") != std::string::npos,
            "top-down export should report structure orientation");
    require(evidence.topDownSvg.find("PITCH") != std::string::npos,
            "top-down export should report headset pitch");
    require(evidence.metricsJson.find("\"in_frame_primitives\": 2") !=
                std::string::npos,
            "metrics should expose the in-frame oracle");
    require(evidence.metricsJson.find("\"status\": \"passed\"") !=
                std::string::npos,
            "metrics should expose strict validation status");
    require(evidence.metricsJson.find("\"relative_axis_yaw_degrees\"") !=
                std::string::npos,
            "metrics should expose the relative orientation");
    require(evidence.metricsJson.find("\"gaze_to_target_error_degrees\"") !=
                std::string::npos,
            "metrics should expose aim error");
    require(evidence.metricsJson.find("fixture \\\"quoted\\\"") !=
                std::string::npos,
            "metrics should JSON-escape the scene label");

    const float halfAngle = glm::radians(55.0F) * 0.5F;
    actor.head.orientation = glm::quat(
        std::cos(halfAngle), 0.0F, std::sin(halfAngle), 0.0F);
    const auto wrongWay = nadoc_vr::scrywrite::renderEvidence(
        scene, actor, "wrong-way mutation", &expectations);
    require(!wrongWay.validationPassed,
            "a large off-axis mutation must fail strict evidence");
    require(wrongWay.inFramePrimitives < wrongWay.totalPrimitives ||
                wrongWay.gazeTargetErrorDegrees > expectations.maxGazeErrorDegrees,
            "wrong-way failure must be supported by spatial evidence");
    std::cout << "ScryWrite evidence tests passed\n";
    return 0;
}
