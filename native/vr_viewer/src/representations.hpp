#pragma once
#include <array>
#include <string_view>

enum class Representation : size_t {
    cylinders, full, ballstick, stick, beads, vdw, hull, surface,
    mrdnaCoarse, mrdnaFine, oxdna, surfaceDetail
};
inline constexpr std::array<std::string_view, 12> kRepresentationNames{
    "cylinders", "full", "ballstick", "stick", "beads", "vdw", "hull-prism",
    "surface", "mrdna-coarse", "mrdna-fine", "oxdna", "surface-detail"};
inline constexpr size_t kRepresentationCount = kRepresentationNames.size();
// Display variants share immutable semantic geometry and ownership indexes.
inline size_t representationSourceIndex(Representation rep) {
    if (rep == Representation::beads) return static_cast<size_t>(Representation::full);
    if (rep == Representation::vdw) return static_cast<size_t>(Representation::ballstick);
    return static_cast<size_t>(rep);
}

inline bool validRepresentation(std::string_view name) {
    for (auto candidate : kRepresentationNames) if (name == candidate) return true;
    return false;
}

inline bool representationCylinderVisible(Representation rep, std::string_view identity) {
    if (rep == Representation::vdw) return identity.starts_with("viewer:");
    return rep != Representation::beads || !identity.ends_with(":slab-connector");
}
inline bool representationBoxVisible(Representation rep, std::string_view identity) {
    return rep != Representation::beads ||
        (!identity.ends_with(":slab") && identity.find(":slab:") == std::string_view::npos);
}
template<class Point> float representationPointRadius(Representation rep, const Point& point) {
    return rep == Representation::vdw && point.vdwSize > 0 ? point.vdwSize : point.size;
}
