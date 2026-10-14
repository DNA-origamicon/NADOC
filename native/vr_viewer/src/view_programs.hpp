#pragma once
#include <stdexcept>
#include <utility>

namespace nadoc_vr::view_programs {
inline const char* selectionSource(const char* value) {return value && *value?"environment":"default";}
struct Optional {unsigned program=0;const char* reason="disabled";};
// Drivers release a failed shader inside compile(); this owns every successful
// shader and the program until a complete link transfers ownership to the view.
template<class Driver> unsigned build(Driver& driver,const char* vertex,const char* fragment) {
    unsigned vs=0,fs=0,program=0;
    try {
        vs=driver.compile(true,vertex);fs=driver.compile(false,fragment);
        program=driver.create();if(!program)throw std::runtime_error("View program allocation failed");
        driver.attach(program,vs);driver.attach(program,fs);driver.link(program);
        if(!driver.linked(program))throw std::runtime_error("View program link failed");
        driver.deleteShader(vs);driver.deleteShader(fs);return program;
    } catch(...) {
        if(program)driver.deleteProgram(program);
        if(vs)driver.deleteShader(vs);
        if(fs)driver.deleteShader(fs);
        throw;
    }
}
template<class Factory> Optional optional(Factory&& factory) noexcept {
    try {if(auto value=std::forward<Factory>(factory)())return {value,"available"};}
    catch(...) {} // Optional optimization failure leaves the required legacy path intact.
    return {0,"shader_build_failed"};
}
inline bool groupsAvailable(bool requested,unsigned legacy,unsigned opaque,unsigned groupLegacy,unsigned groupOpaque) {
    return requested && legacy && groupLegacy && (!opaque || groupOpaque);
}
} // namespace nadoc_vr::view_programs
