#include "scene_input.hpp"
#include <cassert>
#include <bit>
#include <cstdint>
#include <iomanip>
#include <random>
#include <sstream>

int main() {
    // Decimal scene coordinates/colors must preserve the original float bits.
    std::mt19937 random(42);
    for(int i=0;i<20000;++i) {
        const float expected=std::bit_cast<float>(uint32_t(random()));
        if(!std::isfinite(expected))continue;
        std::ostringstream text;text<<std::setprecision(7)<<expected;
        std::istringstream old(text.str()), fresh(text.str());
        float a=0,b=0;old>>a;nadoc_vr::SceneInput input(fresh);input>>b;
        assert(bool(old)==bool(input));
        assert(std::bit_cast<uint32_t>(a)==std::bit_cast<uint32_t>(b));
    }
    for(const char* text:{"", "garbage", "1e999", "1.2junk", "+-1", "nan", "inf"}) {
        std::istringstream stream(text);nadoc_vr::SceneInput input(stream);float value=123;
        input>>value;assert(!input && value==0);
    }
    std::istringstream stream("P point +1.25\t-0\r\n2e-3 # comment\nR full\n");
    nadoc_vr::SceneInput input(stream);char type;std::string id;float x,y,z;
    input>>type>>id>>x>>y>>z;assert(input && type=='P' && id=="point" && x==1.25F && std::signbit(y) && z==.002F);
    input>>type;assert(type=='#');std::getline(stream,id);assert(id==" comment");
    input>>type>>id;assert(input && type=='R' && id=="full");
    input>>type;assert(!input);
}
