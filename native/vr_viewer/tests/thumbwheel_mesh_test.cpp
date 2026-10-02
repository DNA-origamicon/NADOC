#include "thumbwheel_mesh.hpp"
#include <iostream>
#include <stdexcept>

void require(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
int main() {
    using namespace nadoc_vr;
    require(thumbwheelRangeRadius(10)<thumbwheelRangeRadius(100),"100 must imply a larger wheel than 10");
    require(thumbwheelRangeRadius(100)<thumbwheelRangeRadius(1000),"1000 must imply a larger wheel than 100");
    require(thumbwheelRangeRadius(1000)<3*thumbwheelRangeRadius(10),"range compression must keep wheels usable");
    const auto extrude=thumbwheelPreset(1000),bend=thumbwheelPreset(100);
    require(std::abs(extrude.radius-.12F)<1e-6F && std::abs(bend.radius-.0825F)<1e-6F,"approved wheel diameters changed");
    require(extrude.exposure==.35F && bend.exposure==.35F && extrude.width==.09F && bend.width==.09F,"approved exposure/width changed");
    float previous=0;
    for(float exposure:{.20F,.35F,.50F}) {
        ThumbwheelShape s{.12F,.09F,exposure,.0025F,32};
        float maxZ=0,maxRadius=0;int triangles=0;bool cut=false;
        const glm::vec3 center{0,0,.012F};
        thumbwheelMesh(s,.37F,center,[&](auto a,auto b,auto c,auto normal){
            require(std::isfinite(normal.x),"non-finite normal");
            ++triangles;
            for(auto p:{a,b,c}) {
                require(p.z>=center.z-1e-6F,"hidden geometry leaked through panel");
                require(std::abs(p.x)<=s.width/2+1e-6F,"axial dimension changed");
                cut|=std::abs(p.z-center.z)<1e-6F;
                maxZ=std::max(maxZ,p.z);
                maxRadius=std::max(maxRadius,glm::length(glm::vec2(p.y,p.z-center.z-s.centerDepth())));
            }
        });
        require(triangles>50 && cut,"wheel lacks clipped solid surfaces");
        require(maxRadius>s.radius+.002F,"ridges must protrude physically, not be painted lines");
        require(maxZ>previous,"exposure variants must have increasing protrusion");previous=maxZ;
    }
    std::cout<<"Solid ribs, cutoff, exposure and range scale verified\n";
}
