#pragma once
#include <string>
#include <istream>
#include <stdexcept>

namespace nadoc_vr {
/** Source-plane selection is independent of the diagnostic tablet pose. */
struct ExtrudePlane {
    std::string plane = "XY";
    std::string lattice = "HONEYCOMB";
    std::string reason = "unknown";
    static bool valid(const std::string& value) {
        return value == "XY" || value == "XZ" || value == "YZ";
    }
    void read(std::istream& input) {
        input >> plane >> lattice >> reason;
        if (!input || !valid(plane) ||
            (lattice != "SQUARE" && lattice != "HONEYCOMB") ||
            (reason != "geometry" && reason != "mixed" &&
             reason != "unknown" && reason != "empty")) {
            throw std::runtime_error("Invalid extrusion source-plane metadata");
        }
    }
    void cycle() {
        plane = plane == "XY" ? "XZ" : plane == "XZ" ? "YZ" : "XY";
        reason = "user";
    }
    std::string label() const { return "EXTRUDE FROM " + plane; }
};
}
