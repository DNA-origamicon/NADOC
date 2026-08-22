#include "scrywrite.hpp"

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
    {
        std::istringstream script(
            "SCRYWRITE 1\n"
            "select cluster cluster:c1\n"
            "tool move_rotate\n"
            "preview\n"
            "pose right 0 0 -0.5 1 0 0 0\n"
            "grip right down\n"
            "step\n"
            "pose right 0.05 0 -0.5 1 0 0 0\n"
            "step\n"
            "expect pending_translation 0.05 0 0 0.00001\n"
            "cancel\n"
            "expect pending_identity true\n");
        nadoc_vr::scrywrite::Session session;
        const auto result = session.run(script);
        require(result.ok, "valid script should pass");
        require(result.commands == 11, "command count should be deterministic");
        require(result.assertions == 2, "assertion count should be deterministic");
        require(result.frames == 2, "virtual frame count should be deterministic");
        const std::string trace = session.traceJson();
        require(trace.find("\"result\": \"passed\"") != std::string::npos,
                "passing trace should identify its result");
        require(trace.find("\"pending_translation\":[0.050000") != std::string::npos,
                "trace should retain the moved prefix");
    }

    {
        std::istringstream script(
            "SCRYWRITE 1\n"
            "select cluster cluster:c1\n"
            "tool move_rotate\n"
            "expect status CANCELLED\n");
        nadoc_vr::scrywrite::Session session;
        const auto result = session.run(script);
        require(!result.ok, "a false assertion should fail");
        require(result.error.find("line 4") != std::string::npos,
                "failure should identify the exact script line");
        const std::string trace = session.traceJson();
        require(trace.find("\"result\": \"failed\"") != std::string::npos,
                "failed trace should identify its result");
        require(trace.find("\"command\":\"expect\",\"outcome\":\"failed\"") !=
                    std::string::npos,
                "failed trace should identify the failing command");
    }

    {
        std::istringstream script(
            "SCRYWRITE 1\n"
            "pose right 0 0 0 nan 0 0 0\n");
        nadoc_vr::scrywrite::Session session;
        const auto result = session.run(script);
        require(!result.ok, "non-finite input should fail closed");
        require(result.error.find("invalid finite number") != std::string::npos,
                "non-finite input should have a useful diagnostic");
    }

    {
        std::string source = "SCRYWRITE 1\nselect cluster bad";
        source.push_back(static_cast<char>(0xff));
        source.push_back('\n');
        std::istringstream script(source);
        nadoc_vr::scrywrite::Session session;
        const auto result = session.run(script);
        require(!result.ok, "non-portable input should fail closed");
        require(result.error.find("printable ASCII") != std::string::npos,
                "non-portable input should have a useful diagnostic");
    }

    std::cout << "ScryWrite unit tests passed\n";
    return 0;
}
