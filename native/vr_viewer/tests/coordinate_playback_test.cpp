#include "coordinate_playback.hpp"
#include <cassert>
#include <cmath>

int main() {
    nadoc_vr::CoordinatePlayback playback;
    const auto frame = [](unsigned index, float x) {
        nadoc_vr::CoordinateFrame f;
        f.frameIndex = index; f.frameCount = 10; f.positions = {{x, 0, 0}};
        return f;
    };
    const auto at = [&](double time, float x) {
        assert(playback.sample(time));
        assert(std::abs(playback.positions()[0][0] - x) < 0.0001F);
    };
    playback.push(frame(0, 0), true, 0); at(0, 0);
    playback.push(frame(1, 1), true, .1); at(.15, .5F);
    playback.push(frame(2, 2), true, .19);
    // Carry 10 ms beyond the old endpoint into the next 90 ms segment.
    at(.21, 1.0F + 1.0F / 9.0F);
    playback.pause(); at(.22, 2);
    assert(!playback.sample(.3));
    playback.push(frame(5, 5), false, .4); at(.4, 5);
    playback.push(frame(0, 0), true, .5); at(.5, 0); // loop snaps
    playback.push(frame(1, 1), true, .6); at(.7, 1);
    assert(!playback.sample(1)); // starved: no extrapolation
    playback.push(frame(2, 2), true, 2); at(2.25, 1.5F);
    playback.clear(); assert(!playback.sample(3));
    auto changed = frame(0, 9); changed.positions.push_back({4, 5, 6});
    playback.push(changed, true, 3); at(3, 9);
    assert(playback.positions().size() == 2);
}
