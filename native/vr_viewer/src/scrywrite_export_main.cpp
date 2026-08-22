#include "scrywrite_evidence.hpp"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void writeFile(const std::string& path, const std::string& contents) {
    std::ofstream output(path, std::ios::trunc);
    if (!output) throw std::runtime_error("could not write " + path);
    output << contents;
    if (!output) throw std::runtime_error("failed while writing " + path);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4 && argc != 6) {
        std::cerr << "Usage: nadoc-vr-scrywrite-export <scene.nadocvr> "
                     "<witness.scry> <output-prefix> "
                     "[--expect <expectations.scry-evidence>]\n";
        return 2;
    }
    try {
        if (argc == 6 && std::string(argv[4]) != "--expect") {
            throw std::runtime_error("expected --expect before expectation path");
        }
        std::ifstream sceneInput(argv[1]);
        if (!sceneInput) throw std::runtime_error("could not open scene");
        const auto scene = nadoc_vr::scrywrite::loadEvidenceScene(sceneInput);
        std::ifstream witnessInput(argv[2]);
        if (!witnessInput) throw std::runtime_error("could not open witness script");
        auto witness = nadoc_vr::scrywrite::WitnessReplay::load(witnessInput);
        witness.advance({});
        std::optional<nadoc_vr::scrywrite::EvidenceExpectations> expectations;
        if (argc == 6) {
            std::ifstream expectationInput(argv[5]);
            if (!expectationInput) throw std::runtime_error("could not open expectations");
            expectations = nadoc_vr::scrywrite::loadEvidenceExpectations(expectationInput);
        }
        const auto evidence = nadoc_vr::scrywrite::renderEvidence(
            scene, witness.input(), argv[1], expectations ? &*expectations : nullptr);
        const std::string prefix(argv[3]);
        writeFile(prefix + "_pov.svg", evidence.povSvg);
        writeFile(prefix + "_topdown.svg", evidence.topDownSvg);
        writeFile(prefix + "_evidence.json", evidence.metricsJson);
        std::cout << "ScryWrite evidence exported: " << evidence.inFramePrimitives
                  << '/' << evidence.totalPrimitives << " primitives in frame; actor yaw="
                  << evidence.headsetYawDegrees << " deg; actor pitch="
                  << evidence.headsetPitchDegrees << " deg; structure axis yaw="
                  << evidence.origamiYawDegrees << " deg; gaze error="
                  << evidence.gazeTargetErrorDegrees << " deg; validation="
                  << (!evidence.validationEvaluated ? "NOT_EVALUATED"
                                                    : evidence.validationPassed ? "PASSED" : "FAILED")
                  << '\n';
        return evidence.validationEvaluated && !evidence.validationPassed ? 1 : 0;
    } catch (const std::exception& error) {
        std::cerr << "ScryWrite export error: " << error.what() << '\n';
        return 1;
    }
}
