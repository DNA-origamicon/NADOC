#include "view_opaque_shader.hpp"
#include <glm/glm.hpp>
#include <cassert>
#include <cstring>
#include <iostream>
#include <limits>
#include <vector>
struct V {glm::vec3 p;glm::vec4 color;glm::vec2 uv;glm::vec3 normal;};
struct I {glm::mat4 matrix;glm::vec4 color;};
struct B {std::vector<V> vertices;std::vector<I> instances;};
using namespace nadoc_vr::view_opaque;
int main(){
    assert(requested("") && !requested("0") && requested("1"));
    bool bad=false;try{requested("yes");}catch(const std::runtime_error&){bad=true;}assert(bad);
    V v{{.1F,.2F,.3F},{.2F,.6F,.8F,1},{-1,-1},{0,0,1}};
    I i{glm::mat4(1),glm::vec4(1)};
    std::vector<V> triangles;std::vector<B> batches{{{v,v,v},{i,i}}};
    auto e=classify(triangles,batches);assert(e.eligible);
    assert(active(true,e,false) && !active(false,e,false) && !active(true,e,true));
    const auto originalV=v;const auto originalI=i;classify(triangles,batches);
    assert(!std::memcmp(&v,&originalV,sizeof(v)) && !std::memcmp(&i,&originalI,sizeof(i)));
    auto checkV=[&](V test,const char* why){batches[0].vertices[1]=test;auto q=classify(triangles,batches);assert(!q.eligible && std::string(q.reason)==why);batches[0].vertices[1]=v;};
    auto test=v;test.color.a=.99999F;checkV(test,"vertex_alpha_not_one");
    test=v;test.uv.x=0;checkV(test,"textured_vertex");test.uv.x=.4F;checkV(test,"textured_vertex");
    test=v;test.uv.x=-std::numeric_limits<float>::denorm_min();checkV(test,"subnormal_negative_uv");
    for(unsigned field=0;field<12;++field){test=v;float* p=field<3?&test.p[field]:field<7?&test.color[field-3]:field<9?&test.uv[field-7]:&test.normal[field-9];*p=std::numeric_limits<float>::quiet_NaN();checkV(test,"nonfinite_vertex");}
    batches[0].instances[0].color.a=.5F;assert(std::string(classify(triangles,batches).reason)=="instance_alpha_not_one");batches[0].instances[0]=i;
    for(unsigned field=0;field<20;++field){auto& q=batches[0].instances[1];q=i;float* p=field<16?&q.matrix[field/4][field%4]:&q.color[field-16];*p=std::numeric_limits<float>::infinity();assert(std::string(classify(triangles,batches).reason)=="nonfinite_instance");}batches[0].instances[1]=i;
    triangles={v,v,v};assert(classify(triangles, std::vector<B>{}).eligible);triangles[2].uv.x=0;assert(!classify(triangles,batches).eligible);
    assert(std::string(classify(std::vector<V>{},std::vector<B>{}).reason)=="no_surface_geometry");
    const std::string lit="#version330\nfloat sceneLighting(vec3 n){return1.;}\n    void main() {ignored}";
    const auto opaque=fragment(lit,"ignored glass",true),legacy=fragment(lit,"glass retained",false);
    assert(opaque.find("discard")==std::string::npos && opaque.find("atlas")==std::string::npos && opaque.find("shadowPass")==std::string::npos && opaque.find("frostedMenu")==std::string::npos);
    assert(opaque.find("color*=sceneLighting(n)")!=std::string::npos && legacy.find("glass retained")!=std::string::npos && legacy.find("discard")!=std::string::npos);
    bool malformed=false;try{fragment("no main","",true);}catch(const std::runtime_error&){malformed=true;}assert(malformed);
    std::cout<<"Opaque shader eligibility: exact alpha, negative UV, all finite fields, immutable inputs and shadow/default fallback passed\n";
}
