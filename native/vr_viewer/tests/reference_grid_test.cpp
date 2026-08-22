#include "reference_grid.hpp"

#include <cstdlib>
#include <iostream>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    const auto grid = nadoc_vr::buildRoomReferenceGrid();
    require(grid.size() == 147,
            "default cage should contain six dense faces, six markers, and axes");
    for (const auto& line : grid) {
        for (int axis = 0; axis < 3; ++axis) {
            require(std::abs(line.first[axis]) <= 2.50001F &&
                        std::abs(line.second[axis]) <= 2.50001F,
                    "every reference line should remain inside the room cage");
        }
    }
    for (const auto& face : nadoc_vr::kReferenceGridFaces) {
        bool foundBrightCenterMarker = false;
        for (const auto& line : grid) {
            if (glm::length(line.color - face.color) < 1.0e-6F &&
                std::abs(line.first[face.axis] - face.sign * 2.5F) < 1.0e-6F &&
                std::abs(line.second[face.axis] - face.sign * 2.5F) < 1.0e-6F) {
                foundBrightCenterMarker = true;
                break;
            }
        }
        require(foundBrightCenterMarker,
                "each cardinal face should have its own bright orientation marker");
    }
    bool rejected = false;
    try {
        (void)nadoc_vr::buildRoomReferenceGrid(2.5F, 0.0F);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    require(rejected, "invalid grid dimensions should fail closed");
    std::cout << "NADOC VR room reference grid tests passed\n";
    return 0;
}
