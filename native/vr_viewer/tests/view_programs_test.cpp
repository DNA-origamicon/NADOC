#include "view_programs.hpp"
#include "view_instance_groups.hpp"
#include "view_opaque_shader.hpp"
#include <cassert>
#include <iostream>
#include <set>
#include <string>
struct Driver {
    unsigned next=1;int failure=0;
    std::set<unsigned> shaders,programs;
    unsigned compile(bool vertex,const char*) {
        if(failure==(vertex?1:2))throw std::runtime_error("compile failure");
        shaders.insert(next);return next++;
    }
    unsigned create(){if(failure==3)return 0;programs.insert(next);return next++;}
    void attach(unsigned,unsigned){if(failure==4)throw std::runtime_error("attach failure");}
    void link(unsigned){if(failure==5)throw std::runtime_error("link exception");}
    bool linked(unsigned){return failure!=6;}
    void deleteShader(unsigned value){assert(shaders.erase(value)==1);}
    void deleteProgram(unsigned value){assert(programs.erase(value)==1);}
};
int main() {
    using namespace nadoc_vr::view_programs;
    assert(std::string(selectionSource(nullptr))=="default");
    assert(std::string(selectionSource(""))=="default");
    assert(std::string(selectionSource("0"))=="environment");
    for(int failure=0;failure<=6;++failure) {
        Driver driver;driver.failure=failure;
        const auto result=optional([&]{return build(driver,"vertex","fragment");});
        assert(driver.shaders.empty());
        if(!failure){assert(result.program && std::string(result.reason)=="available");driver.deleteProgram(result.program);}
        else assert(!result.program && std::string(result.reason)=="shader_build_failed");
        assert(driver.programs.empty());
    }
    assert(!optional([]{return 0U;}).program);
    assert(!optional([]()->unsigned{throw 1;}).program);
    Driver required;required.failure=6;bool rejected=false;
    try {build(required,"vertex","fragment");}catch(const std::runtime_error&){rejected=true;}
    assert(rejected && required.shaders.empty() && required.programs.empty());
    for(unsigned mask=0;mask<32;++mask) {
        const bool requested=mask&1,legacy=mask&2,opaque=mask&4,groupLegacy=mask&8,groupOpaque=mask&16;
        assert(groupsAvailable(requested,legacy,opaque,groupLegacy,groupOpaque)==bool(requested && legacy && groupLegacy && (!opaque || groupOpaque)));
    }
    // No opaque program still permits grouped legacy; incomplete grouped opaque
    // set conservatively falls back to ordinary opaque rendering.
    assert(groupsAvailable(true,1,0,2,0));
    assert(!groupsAvailable(true,1,2,3,0));
    for(const char* name:{"NADOC_VR_OPAQUE_VIEW_SHADER","NADOC_VR_GROUPED_VIEW_INSTANCES"}) {
        const char* old=std::getenv(name);const bool hadOld=old;const std::string saved=old?old:"";
        auto enabled=[&]{return name==std::string("NADOC_VR_OPAQUE_VIEW_SHADER")?nadoc_vr::view_opaque::requestedFromEnvironment():nadoc_vr::view_groups::requestedFromEnvironment();};
        unsetenv(name);assert(enabled());setenv(name,"",1);assert(enabled());
        setenv(name,"0",1);assert(!enabled());setenv(name,"1",1);assert(enabled());
        setenv(name,"yes",1);bool bad=false;try{enabled();}catch(const std::runtime_error&){bad=true;}assert(bad);
        if(hadOld)setenv(name,saved.c_str(),1);else unsetenv(name);
    }
    std::cout<<"Default/rollback selection, all optional shader failure cleanup, required failure and 32 program fallback combinations passed\n";
}
