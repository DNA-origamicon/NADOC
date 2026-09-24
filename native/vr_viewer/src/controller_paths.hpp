#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <deque>
#include <fstream>
#include <filesystem>
#include <chrono>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>
#include <optional>

namespace nadoc_vr {
// Opt-in diagnostic geometry, entirely separate from controller visibility IDs.
class ControllerPaths {
    std::array<std::vector<glm::vec3>, 2> intended_;
    std::array<std::deque<glm::vec3>, 2> actual_;
    std::array<bool, 2> connected_{};
    std::array<std::deque<glm::vec3>,2> contacts_;
    std::optional<glm::vec3> plane_;
    glm::vec3 normal_{0,0,1};
    bool enabled_ = false;
    std::string source_;
    std::filesystem::file_time_type modified_{};
    std::chrono::steady_clock::time_point checked_{};
    size_t generation_ = 0;
    void refresh() {
        const auto now = std::chrono::steady_clock::now();
        if (source_.empty() || now - checked_ < std::chrono::milliseconds(250)) return;
        checked_ = now;
        std::error_code error;
        const auto stamp = std::filesystem::last_write_time(source_, error);
        if (!error && stamp != modified_) {
            try { load(source_); } catch (const std::exception&) { /* retain last valid route */ }
        }
    }
  public:
    size_t generation() const { return generation_; }
    void load(const std::string& path) {
        if (path.empty()) return;
        std::ifstream input(path);
        if (!input) throw std::runtime_error("cannot read controller path");
        std::array<std::vector<glm::vec3>, 2> planned;
        std::string row;
        size_t count = 0;
        while (std::getline(input, row)) {
            if (row.empty() || row[0] == '#') continue;
            std::istringstream fields(row);
            int hand; glm::vec3 p; std::string extra;
            if (!(fields >> hand >> p.x >> p.y >> p.z) || fields >> extra ||
                hand < 0 || hand > 1 || !std::isfinite(p.x) || !std::isfinite(p.y) ||
                !std::isfinite(p.z) || glm::any(glm::greaterThan(glm::abs(p), glm::vec3(100))) ||
                ++count > 20000) throw std::runtime_error("invalid controller path row");
            if (!planned[hand].empty() && glm::distance(planned[hand].back(),p) > .5F)
                throw std::runtime_error("controller path must be sampled within 0.5m");
            planned[hand].push_back(p);
        }
        if (count < 2) throw std::runtime_error("controller path is empty");
        source_ = path; modified_ = std::filesystem::last_write_time(path); ++generation_;
        intended_ = std::move(planned); actual_ = {}; contacts_ = {}; connected_ = {}; enabled_ = true;
    }
    template<class Hands> void sample(const Hands& hands, std::optional<glm::vec3> plane = {}, glm::vec3 normal = {0,0,1}) {
        refresh();
        if (!enabled_) return;
        plane_ = plane; normal_ = normal;
        for (size_t h = 0; h < 2; ++h) {
            if (!hands[h].valid) { connected_[h] = false; continue; }
            auto& trail = actual_[h];
            const auto p = hands[h].position;
            // Start a fresh segment after release/tracking loss/teleport, never
            // draw a fictitious bridge. The last completed trail remains on release.
            if (!connected_[h] || (!trail.empty() && glm::distance(trail.back(), p) > .25F)) { trail.clear(); contacts_[h].clear(); }
            connected_[h] = true;
            if (trail.empty() || glm::distance(trail.back(), p) >= .001F) trail.push_back(p);
            if (trail.size() > 4096) trail.pop_front();
            if (plane_) {
                const auto direction = hands[h].orientation * glm::vec3(0,0,-1);
                const auto denominator = glm::dot(direction, normal_);
                if (std::abs(denominator) > .00001F) {
                    const auto t = glm::dot(*plane_-p,normal_)/denominator;
                    if (t >= 0 && t < 2) {
                        const auto hit = p+t*direction;
                        auto& contact = contacts_[h];
                        if (contact.empty() || glm::distance(contact.back(),hit) >= .0005F) contact.push_back(hit);
                        if (contact.size()>4096) contact.pop_front();
                    }
                }
            }
        }
    }
    // Surface traces are diagnostic ray intersections, not controller body poses.
    // The renderer uses a wide ideal underlay, actual trace, then a thin ideal
    // centre line so repeated noisy crossings cannot erase the reference route.
    template<class Line> void drawContact(Line line) const {
        if (!enabled_ || !plane_) return;
        for(size_t h=0;h<2;++h) {
            const auto& route=intended_[h];
            for(size_t i=1;i<route.size();++i) {
                const auto project=[&](glm::vec3 p){return p-normal_*glm::dot(p-*plane_,normal_);};
                line(project(route[i-1]),project(route[i]),glm::vec3(1,.85F,.15F),false);
            }
            const auto& routeActual=contacts_[h];
            for(size_t i=1;i<routeActual.size();++i)
                line(routeActual[i-1],routeActual[i],glm::vec3(1,.18F,.75F),true);
        }
    }
    template<class Line> void draw(Line line) const {
        if (!enabled_) return;
        for (size_t h = 0; h < 2; ++h) {
            const auto& route = intended_[h];
            const glm::vec3 planned = h == 0 ? glm::vec3(.65F,.82F,1) : glm::vec3(1,.85F,.58F);
            float traveled = 0;
            for (size_t i = 1; i < route.size(); ++i) {
                const auto a = route[i-1], b = route[i];
                const float length = glm::distance(a,b);
                // Fixed physical dash lengths, independent of input sample density.
                float d = 0;
                while (d < length) {
                    const float phase = std::fmod(traveled + d, .016F);
                    const float next = std::min(length, d + std::max(.000001F,
                        (phase < .008F ? .008F : .016F) - phase));
                    if (phase < .008F) line(glm::mix(a,b,d/length), glm::mix(a,b,next/length), planned);
                    d = next;
                }
                traveled += length;
            }
            const auto& trail = actual_[h];
            const glm::vec3 observed = h == 0 ? glm::vec3(.05F,1,.65F) : glm::vec3(1,.18F,.75F);
            for (size_t i = 1; i < trail.size(); ++i) line(trail[i-1],trail[i],observed);
        }
    }
};
}  // namespace nadoc_vr
