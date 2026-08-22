#include "scrywrite.hpp"

#include <fstream>
#include <iostream>
#include <memory>
#include <string>

namespace {

void usage() {
    std::cerr << "Usage: nadoc-vr-scrywrite <script.scry|-> [--trace <trace.json|->]\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2 && argc != 4) {
        usage();
        return 2;
    }
    if (argc == 4 && std::string(argv[2]) != "--trace") {
        usage();
        return 2;
    }

    std::ifstream scriptFile;
    std::istream* script = &std::cin;
    if (std::string(argv[1]) != "-") {
        scriptFile.open(argv[1]);
        if (!scriptFile) {
            std::cerr << "ScryWrite error: could not open script " << argv[1] << '\n';
            return 2;
        }
        script = &scriptFile;
    }

    nadoc_vr::scrywrite::Session session;
    const nadoc_vr::scrywrite::RunResult result = session.run(*script);
    const std::string trace = session.traceJson();

    if (argc == 4) {
        const std::string tracePath(argv[3]);
        if (tracePath == "-") {
            std::cout << trace;
        } else {
            std::ofstream output(tracePath, std::ios::trunc);
            if (!output) {
                std::cerr << "ScryWrite error: could not write trace " << tracePath << '\n';
                return 2;
            }
            output << trace;
        }
    } else if (result.ok) {
        std::cout << "ScryWrite passed: " << result.commands << " commands, "
                  << result.assertions << " assertions, " << result.frames
                  << " virtual frames\n";
    }

    if (!result.ok) {
        std::cerr << "ScryWrite failed: " << result.error << '\n';
        return 1;
    }
    return 0;
}
