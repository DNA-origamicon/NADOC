// Numerical derivative audit in memory only; never writes molecular coordinates.
#include <string>
#include "Managers/SimManager.h"
#include "Utilities/ConfigInfo.h"
#include "Utilities/Logger.h"
#include "Utilities/Utils.h"
#include "Utilities/Timings.h"
#include "Forces/Metadynamics/LTCoordination.h"
#include "Particles/BaseParticle.h"
#include <iostream>
#include <iomanip>
#include "model.h"

namespace meta { number _f1(number r); number _f1D(number r); }

int main(int argc, char **argv) {
    if(argc != 2) return 2;
    Logger::init();
    TimingManager::init();
    input_file input;
    input.init_from_filename(argv[1]);
    SimManager manager(input);
    manager.load_options();
    manager.init();
    auto info = CONFIG_INFO;
    auto force = std::dynamic_pointer_cast<LTCoordination>(info->forces[0]);
    if(!force) return 3;
    const double delta = 1e-6;
    double max_f_error = 0, max_t_error = 0, max_f = 0, max_t = 0;
    double max_cutoff_jump = 0;
    for(double boundary : {double(HYDR_RCLOW), double(HYDR_RLOW), double(HYDR_RHIGH), double(HYDR_RCHIGH)}) {
        max_cutoff_jump = std::max(max_cutoff_jump, std::abs(meta::_f1(boundary-1e-8)-meta::_f1(boundary+1e-8)));
    }
    long long stamp = 100;
    for(auto p : info->particles()) {
        force->set_current_particle(p);
        auto f = force->force(++stamp, p->pos);
        auto t = force->torque(stamp, p->pos);
        auto energy = [&]() { return force->potential(++stamp, p->pos)*info->N(); };
        for(int k=0; k<3; k++) {
            auto oldpos = p->pos;
            p->pos[k] += delta;
            double plus = energy();
            p->pos[k] -= 2*delta;
            double minus = energy();
            p->pos = oldpos;
            max_f_error = std::max(max_f_error, std::abs(f[k]+(plus-minus)/(2*delta)));
            max_f = std::max(max_f, std::abs(f[k]));
            auto old = p->orientation;
            LR_vector axis(0,0,0); axis[k] = 1;
            p->orientation = Utils::get_rotation_matrix_from_axis_angle(axis, delta)*old;
            p->orientationT = p->orientation.get_transpose();
            p->set_positions();
            plus = energy();
            p->orientation = Utils::get_rotation_matrix_from_axis_angle(axis, -delta)*old;
            p->orientationT = p->orientation.get_transpose();
            p->set_positions();
            minus = energy();
            p->orientation = old;
            p->orientationT = old.get_transpose();
            p->set_positions();
            max_t_error = std::max(max_t_error, std::abs(t[k]+(plus-minus)/(2*delta)));
            max_t = std::max(max_t, std::abs(t[k]));
        }
    }
    std::cout << std::setprecision(15) << "{\"force_error\":" << max_f_error
              << ",\"torque_error\":" << max_t_error << ",\"force_signal\":" << max_f
              << ",\"torque_signal\":" << max_t << ",\"radial_boundary_jump\":" << max_cutoff_jump << "}" << std::endl;
    return (max_f_error > 1e-4 || max_t_error > 1e-4 || max_cutoff_jump > 1e-5) ? 1 : 0;
}
