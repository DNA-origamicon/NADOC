// Offline GPU experiment only. Does not initialize OpenXR, open a viewer socket,
// submit headset images, or modify the source stream. See README alongside it.
#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>
#include "view_opaque_shader.hpp"
#include "view_instance_groups.hpp"
#include "view_indexed_mesh.hpp"
#include "view_cache_order.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct V {glm::vec3 p;glm::vec4 color;glm::vec2 uv;glm::vec3 normal;};
struct CompactV {glm::vec3 p,normal;};
struct I {glm::mat4 matrix;glm::vec4 color;};
static_assert(sizeof(V)==48 && sizeof(I)==80);
struct Batch {std::vector<V> vertices,grouped;std::vector<I> instances;nadoc_vr::view_indexed::Mesh<V> indexed;GLuint vbo=0,ibo=0,groupVbo=0,tex=0,indexVbo=0,ebo=0,indexGroupVbo=0,indexGroupEbo=0,shortEbo=0,shortGroupEbo=0,reorderEbo=0,reorderGroupEbo=0,compactVbo=0,compactGroupVbo=0;bool compact=false,group=false,uniformSphere=false;};
struct Eye {glm::vec3 position;glm::quat orientation;std::array<float,4> fov;glm::mat4 view,projection;};
struct State {int width=0,height=0;glm::vec3 center,offset;float scale=0,nearPlane=0,farPlane=0;glm::mat4 model;std::array<Eye,2> eyes;};
void require(bool yes,const std::string& message){if(!yes)throw std::runtime_error(message);}
void checkGL(const char* where){const auto e=glGetError();require(e==GL_NO_ERROR,std::string(where)+" GL error "+std::to_string(e));}
template<class T> void read(std::ifstream& f,T& value){require(bool(f.read(reinterpret_cast<char*>(&value),sizeof(value))),"truncated view stream");}
template<class T> void readVector(std::ifstream& f,std::vector<T>& values){require(bool(f.read(reinterpret_cast<char*>(values.data()),values.size()*sizeof(T))),"truncated view array");}
glm::mat4 projection(const Eye& e,float nearPlane,float farPlane){
 const float left=std::tan(e.fov[0]),right=std::tan(e.fov[1]),up=std::tan(e.fov[2]),down=std::tan(e.fov[3]);
 glm::mat4 p(0);p[0][0]=2/(right-left);p[1][1]=2/(up-down);p[2][0]=(right+left)/(right-left);p[2][1]=(up+down)/(up-down);p[2][2]=-(farPlane+nearPlane)/(farPlane-nearPlane);p[2][3]=-1;p[3][2]=-(2*farPlane*nearPlane)/(farPlane-nearPlane);return p;
}
State readState(const std::string& path){
 std::ifstream f(path);std::string magic;State s;f>>magic;require(magic=="NADOC_VIEW_MESH_BENCH_1","bad state format");
 f>>s.width>>s.height>>s.center.x>>s.center.y>>s.center.z>>s.scale>>s.offset.x>>s.offset.y>>s.offset.z>>s.nearPlane>>s.farPlane;
 for(unsigned r=0;r<4;++r)for(unsigned c=0;c<4;++c)f>>s.model[c][r];
 for(auto& e:s.eyes){f>>e.position.x>>e.position.y>>e.position.z>>e.orientation.x>>e.orientation.y>>e.orientation.z>>e.orientation.w;for(auto& a:e.fov)f>>a;e.view=glm::inverse(glm::translate(glm::mat4(1),e.position)*glm::toMat4(e.orientation));e.projection=projection(e,s.nearPlane,s.farPlane);}
 require(bool(f),"truncated state");std::string extra;require(!(f>>extra),"trailing state data");
 require(s.width>0&&s.width<=4096&&s.height>0&&s.height<=4096&&s.scale>0&&s.nearPlane>0&&s.farPlane>s.nearPlane,"invalid state bounds");
 for(unsigned c=0;c<4;++c)for(unsigned r=0;r<4;++r)require(std::isfinite(s.model[c][r]),"nonfinite model");
 return s;
}
std::string literal(const char* file,const char* declaration){std::ifstream f(std::filesystem::path(NADOC_SOURCE_ROOT)/"native/vr_viewer/src"/file);require(bool(f),"missing shader source");std::string s{std::istreambuf_iterator<char>(f),{}};const auto a=s.find(declaration);require(a!=s.npos,"shader declaration not found");const auto b=s.find("R\"GLSL(",a),e=s.find(")GLSL\"",b);require(b!=s.npos&&e!=s.npos,"shader literal not found");return s.substr(b+7,e-b-7);}
GLuint shader(GLenum type,const std::string& source){auto id=glCreateShader(type);const auto* p=source.c_str();glShaderSource(id,1,&p,nullptr);glCompileShader(id);GLint ok=0;glGetShaderiv(id,GL_COMPILE_STATUS,&ok);if(!ok){char log[4096]{};glGetShaderInfoLog(id,sizeof(log),nullptr,log);throw std::runtime_error(log);}return id;}
GLuint program(const std::string& vertex,const std::string& fragment){auto v=shader(GL_VERTEX_SHADER,vertex),f=shader(GL_FRAGMENT_SHADER,fragment),p=glCreateProgram();glAttachShader(p,v);glAttachShader(p,f);glLinkProgram(p);GLint ok=0;glGetProgramiv(p,GL_LINK_STATUS,&ok);if(!ok){char log[4096]{};glGetProgramInfoLog(p,sizeof(log),nullptr,log);throw std::runtime_error(log);}glDeleteShader(v);glDeleteShader(f);return p;}
template<class T> GLuint buffer(const std::vector<T>& data){GLuint b=0;glGenBuffers(1,&b);glBindBuffer(GL_ARRAY_BUFFER,b);glBufferData(GL_ARRAY_BUFFER,data.size()*sizeof(T),data.data(),GL_STATIC_DRAW);return b;}
std::vector<CompactV> compact(const std::vector<V>& values){std::vector<CompactV> out;out.reserve(values.size());for(const auto& v:values)out.push_back({v.p,v.normal});return out;}
std::vector<Batch> load(const std::string& path,const State& s,nadoc_vr::view_groups::Limits limits,std::ostream& report){
 std::ifstream f(path,std::ios::binary);char magic[8];require(bool(f.read(magic,8))&&std::string(magic,8)=="NADOCVT1","bad view stream");std::array<uint32_t,10> h;read(f,h);
 require((h[0]==5||h[0]==6)&&h[3]+uint64_t(h[4])<=4000000&&h[3]%3==0&&h[4]%2==0&&h[5]<=100000&&h[8]<=10000,"unsupported or excessive stream");
 require(h[6]==(h[0]==5?2048U:0U)&&h[7]==h[6],"invalid atlas size");
 f.seekg(uint64_t(h[3]+h[4])*sizeof(V)+uint64_t(h[5])*60,std::ios::cur);require(bool(f),"bad skipped arrays");
 const auto normalization=glm::translate(glm::mat4(1),s.offset)*glm::scale(glm::mat4(1),glm::vec3(s.scale))*glm::translate(glm::mat4(1),-s.center);
 std::vector<Batch> batches;size_t countVertices=h[3]+h[4],countInstances=0,remaining=nadoc_vr::view_groups::maxExpandedBytes,groupBudget=64*1024*1024;
 report<<"\"stream_version\":"<<h[0]<<",\"unrendered_triangle_vertices\":"<<h[3]<<",\"unrendered_line_vertices\":"<<h[4]<<",\"unrendered_sprites\":"<<h[5]<<",\"batches\":[";
 for(uint32_t j=0;j<h[8];++j){std::array<uint32_t,2> counts;read(f,counts);countVertices+=counts[0];countInstances+=counts[1];require(counts[0]&&counts[0]%3==0&&counts[1]&&countVertices<=4000000&&countInstances<=1000000,"invalid batch bounds");Batch b;b.vertices.resize(counts[0]);b.instances.resize(counts[1]);readVector(f,b.vertices);readVector(f,b.instances);
  glm::vec3 lo(1e30F),hi(-1e30F);for(const auto& v:b.vertices){require(nadoc_vr::view_opaque::vertex(v).eligible,"benchmark requires opaque untextured finite vertices");lo=glm::min(lo,v.p);hi=glm::max(hi,v.p);}const auto center=(lo+hi)*.5F;float radius=0;for(const auto& v:b.vertices)radius=std::max(radius,glm::length(v.p-center));
  size_t positive=0,negative=0,singular=0,nonAffine=0,outward=0,inward=0,degenerate=0,cameraMaybeInside=0,depthPlaneMaybeCrossed=0;float maxSimilarityError=0;
  for(size_t k=0;k<b.vertices.size();k+=3){const auto a=b.vertices[k].p,bb=b.vertices[k+1].p,c=b.vertices[k+2].p;const auto n=glm::cross(bb-a,c-a);const float d=glm::dot(n,(a+bb+c)/3.F-center);if(glm::length(n)<1e-12F)++degenerate;else if(d>0)++outward;else ++inward;}
  for(auto& i:b.instances){require(nadoc_vr::view_opaque::instance(i).eligible,"benchmark requires opaque finite instances");i.matrix=normalization*i.matrix;const auto m=s.model*i.matrix;const float det=glm::determinant(glm::mat3(m));const auto gram=glm::transpose(glm::mat3(m))*glm::mat3(m);const float scale2=(gram[0][0]+gram[1][1]+gram[2][2])/3;float residual=0;for(unsigned c=0;c<3;++c)for(unsigned r=0;r<3;++r)residual=std::max(residual,std::abs(gram[c][r]-(c==r?scale2:0.F))/std::max(scale2,1e-30F));maxSimilarityError=std::max(maxSimilarityError,residual);if(det>0)++positive;else if(det<0)++negative;else ++singular;nonAffine+=m[0][3]!=0||m[1][3]!=0||m[2][3]!=0||m[3][3]!=1;const auto c=glm::vec3(m*glm::vec4(center,1));float norm2=0;for(unsigned a=0;a<3;++a)norm2+=glm::dot(glm::vec3(m[a]),glm::vec3(m[a]));const float bound=radius*std::sqrt(norm2);for(const auto& e:s.eyes){cameraMaybeInside+=glm::distance(e.position,c)<=bound;const float depth=-(e.view*glm::vec4(c,1)).z;depthPlaneMaybeCrossed+=depth-bound<=s.nearPlane||depth+bound>=s.farPlane;}}
  b.uniformSphere=negative==0 && singular==0 && nonAffine==0 && maxSimilarityError<=2e-5F;b.indexed=nadoc_vr::view_indexed::build(b.vertices);const auto gp=nadoc_vr::view_groups::plan(b.vertices.size(),b.instances.size(),sizeof(V),limits,remaining);b.group=gp.eligible;if(b.group){remaining-=gp.expandedBytes;b.grouped=nadoc_vr::view_groups::expand(b.vertices);}
  b.compact=std::all_of(b.vertices.begin(),b.vertices.end(),[&](const V& v){return std::memcmp(&v.color,&b.vertices[0].color,sizeof(v.color))==0&&std::memcmp(&v.uv,&b.vertices[0].uv,sizeof(v.uv))==0;});
  if(b.compact){b.compactVbo=buffer(compact(b.indexed.plan.eligible?b.indexed.vertices:b.vertices));if(b.group)b.compactGroupVbo=buffer(compact(b.grouped));}
  b.vbo=buffer(b.vertices);b.ibo=buffer(b.instances);if(b.group)b.groupVbo=buffer(b.grouped);
  if(b.group||b.indexed.plan.eligible){glGenTextures(1,&b.tex);glActiveTexture(GL_TEXTURE9);glBindTexture(GL_TEXTURE_BUFFER,b.tex);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,b.ibo);}
  if(b.indexed.plan.eligible){const auto expandedBytes=64*(b.indexed.vertices.size()*sizeof(V)+b.indexed.indices.size()*sizeof(uint32_t));require(expandedBytes<=groupBudget,"offline grouped mesh budget exceeded");groupBudget-=expandedBytes;b.indexVbo=buffer(b.indexed.vertices);b.ebo=buffer(b.indexed.indices);std::vector<V> groupedVertices;std::vector<uint32_t> groupedIndices;for(unsigned group=0;group<64;++group){groupedVertices.insert(groupedVertices.end(),b.indexed.vertices.begin(),b.indexed.vertices.end());for(auto index:b.indexed.indices)groupedIndices.push_back(index+group*b.indexed.vertices.size());}if(b.compact)b.compactGroupVbo=buffer(compact(groupedVertices));b.indexGroupVbo=buffer(groupedVertices);b.indexGroupEbo=buffer(groupedIndices);
   require(groupedVertices.size()<=65536,"short benchmark index overflow");
   b.shortEbo=buffer(std::vector<uint16_t>(b.indexed.indices.begin(),b.indexed.indices.end()));
   b.shortGroupEbo=buffer(std::vector<uint16_t>(groupedIndices.begin(),groupedIndices.end()));
   const auto reordered=nadoc_vr::benchmark::cacheOrder(b.indexed.indices,b.indexed.vertices.size());
   b.reorderEbo=buffer(reordered);std::vector<uint32_t> reorderedGroups;
   for(unsigned group=0;group<64;++group)for(auto index:reordered)reorderedGroups.push_back(index+group*b.indexed.vertices.size());
   b.reorderGroupEbo=buffer(reorderedGroups);}
  if(j){report<<',';}
  report<<"{\"vertices\":"<<counts[0]<<",\"instances\":"<<counts[1]<<",\"unique_vertices\":"<<b.indexed.plan.uniqueVertices<<",\"indexed_eligible\":"<<(b.indexed.plan.eligible?"true":"false")<<",\"grouped\":"<<(b.group?"true":"false")<<",\"positive_determinants\":"<<positive<<",\"negative_determinants\":"<<negative<<",\"singular_determinants\":"<<singular<<",\"non_affine\":"<<nonAffine<<",\"max_relative_similarity_gram_error\":"<<maxSimilarityError<<",\"diagnostic_direct_normal_eligible\":"<<(b.uniformSphere?"true":"false")<<",\"outward_faces_from_bounds_center\":"<<outward<<",\"inward_faces_from_bounds_center\":"<<inward<<",\"degenerate_faces\":"<<degenerate<<",\"conservative_eye_camera_inside_pairs\":"<<cameraMaybeInside<<",\"conservative_eye_depth_plane_crossings\":"<<depthPlaneMaybeCrossed<<"}";batches.push_back(std::move(b));
 }
 f.seekg(uint64_t(h[6])*h[7]*4,std::ios::cur);require(bool(f)&&f.tellg()==std::streampos(std::filesystem::file_size(path))&&f.peek()==std::char_traits<char>::eof(),"unexpected stream trailing bytes");report<<"],";checkGL("upload");return batches;
}
struct Condition {const char* name;bool index=true,blend=true,cull=false,shadows=true,constant=false,tiny=false,indexGroup=false,directNormal=false;unsigned groupSize=8;bool shortIndices=false,reordered=false,compact=false;};
void vertices(GLuint b){glBindBuffer(GL_ARRAY_BUFFER,b);for(auto a:{0U,1U,2U,8U})glEnableVertexAttribArray(a);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));}
void ppm(const std::filesystem::path& path,const std::vector<unsigned char>& rgba,int width,int height){std::ofstream out(path,std::ios::binary);out<<"P6\n"<<width<<' '<<height<<"\n255\n";for(int y=height-1;y>=0;--y)for(int x=0;x<width;++x)out.write(reinterpret_cast<const char*>(rgba.data()+4*(size_t(y)*width+x)),3);require(bool(out),"image write failed");}
}

int main(int argc,char** argv){try{
 require(argc==4||argc==5||argc==6,"usage: nadoc-vr-view-mesh-benchmark VIEWTOOLS STATE.txt NEW_OUTPUT_DIR [iterations=12] [focused|groups|cache]");const auto state=readState(argv[2]);const int iterations=argc>=5?std::stoi(argv[4]):12;require(argc<6||(std::string(argv[5])=="focused"||std::string(argv[5])=="groups"||std::string(argv[5])=="cache"),"unknown condition selection");require(iterations>=3&&iterations<=100,"iterations must be 3..100");const std::filesystem::path out(argv[3]);require(!std::filesystem::exists(out),"output directory already exists");std::filesystem::create_directories(out);
 require(glfwInit(),"GLFW initialization failed");glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);auto* window=glfwCreateWindow(64,64,"Offline view mesh benchmark",nullptr,nullptr);require(window,"hidden GL context unavailable");glfwMakeContextCurrent(window);glfwSwapInterval(0);
 std::ofstream report(out/"result.json");report<<std::setprecision(12)<<"{\"schema\":\"nadoc-view-mesh-benchmark-v1\",\"scope\":\"instanced exported meshes, both saved eyes; no OpenXR, menus, mirror, canonical shadow pass or live compositor submission\",\"shadow_texture\":\"synthetic 2048 square depth pattern, not captured canonical shadow map\",\"constant_fragment_limit\":\"compiler may remove unused vertex outputs; not a fragment-only isolation\",\"direct_normal_limit\":\"diagnostic only on positive sphere similarities with relative Gram residual <=2e-5; not exact floating arithmetic\",\"timing\":\"GL_TIME_ELAPSED includes GPU scheduling gaps and possible other-context contention; alternating condition order; upload/readback excluded\",\"culling_inventory_limit\":\"bounds-center winding and conservative Frobenius sphere bounds do not prove closedness or general culling safety\",\"width\":"<<state.width<<",\"height\":"<<state.height<<",\"iterations\":"<<iterations<<",\"gl_renderer\":\""<<glGetString(GL_RENDERER)<<"\",";
 GLint texels=0,vertexSamplers=0,units=0;glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE,&texels);glGetIntegerv(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS,&vertexSamplers);glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS,&units);auto batches=load(argv[1],state,{uint64_t(std::max(0,texels)),vertexSamplers>0,units>9},report);
 const auto lit=literal("main.cpp","constexpr const char* kLitFragmentSource"),glass=literal("frosted_glass.hpp","inline constexpr const char* frostedGlassShader");const auto fragment=nadoc_vr::view_opaque::fragment(lit,glass,true);const std::string flat="#version 330 core\nlayout(location=0) out vec4 outColor;layout(location=1) out uint outObjectId;void main(){outColor=vec4(.7,.7,.7,1);outObjectId=0u;}";const std::string base=nadoc_vr::view_opaque::vertexSource,grouped=nadoc_vr::view_groups::vertexShader(base);auto directNormal=[](std::string source){const std::string from="transpose(inverse(mat3(worldModel*m)))*normal",to="mat3(worldModel*m)*normal";const auto at=source.find(from);require(at!=source.npos&&source.find(from,at+1)==source.npos,"normal shader anchor changed");source.replace(at,from.size(),to);return source;};std::array<GLuint,6> programs{program(base,fragment),program(grouped,fragment),program(base,flat),program(grouped,flat),program(directNormal(base),fragment),program(directNormal(grouped),fragment)};
 std::array<GLuint,65> sizedPrograms{};for(unsigned n:{1U,2U,4U,8U,16U,32U,64U}){auto source=grouped;const auto at=source.find("gl_InstanceID*8");require(at!=source.npos,"group shader anchor");source.replace(at,15,"gl_InstanceID*"+std::to_string(n));sizedPrograms[n]=program(source,fragment);}
 GLuint vao=0,fbo=0,depth=0,shadow=0;std::array<GLuint,2> color;glGenVertexArrays(1,&vao);glBindVertexArray(vao);glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);glGenTextures(2,color.data());for(unsigned k=0;k<2;++k){glBindTexture(GL_TEXTURE_2D,color[k]);glTexImage2D(GL_TEXTURE_2D,0,k?GL_R32UI:GL_RGBA8,state.width,state.height,0,k?GL_RED_INTEGER:GL_RGBA,k?GL_UNSIGNED_INT:GL_UNSIGNED_BYTE,nullptr);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0+k,GL_TEXTURE_2D,color[k],0);}glGenRenderbuffers(1,&depth);glBindRenderbuffer(GL_RENDERBUFFER,depth);glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH32F_STENCIL8,state.width,state.height);glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,GL_RENDERBUFFER,depth);const GLenum attachments[]{GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};glDrawBuffers(2,attachments);require(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"incomplete benchmark FBO");
 glActiveTexture(GL_TEXTURE0);glGenTextures(1,&shadow);glBindTexture(GL_TEXTURE_2D,shadow);std::vector<float> shadowPixels(2048*2048);for(unsigned y=0;y<2048;++y)for(unsigned x=0;x<2048;++x)shadowPixels[y*2048+x]=(x/64+y/64)%3?.4F:.8F;glTexImage2D(GL_TEXTURE_2D,0,GL_DEPTH_COMPONENT32F,2048,2048,0,GL_DEPTH_COMPONENT,GL_FLOAT,shadowPixels.data());glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_COMPARE_MODE,GL_COMPARE_REF_TO_TEXTURE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_COMPARE_FUNC,GL_LEQUAL);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
 const std::array<Condition,11> allConditions{{{"arrays",false},{"indexed"},{"indexed_no_blend",true,false},{"indexed_cull_sphere_batches",true,true,true},{"indexed_no_blend_cull_sphere_batches",true,false,true},{"indexed_no_shadow",true,true,false,false},{"indexed_constant_fragment",true,true,false,false,true},{"indexed_one_pixel_viewport",true,true,false,true,false,true},{"indexed_group8",true,true,false,true,false,false,true},{"indexed_direct_normal",true,true,false,true,false,false,false,true},{"indexed_group8_direct_normal",true,true,false,true,false,false,true,true}}};
 std::vector<Condition> conditions;if(argc==6&&std::string(argv[5])=="cache"){
 conditions.push_back(allConditions[0]);conditions.push_back(allConditions[8]);
 auto shortIndex=allConditions[8];shortIndex.name="group8_uint16";shortIndex.shortIndices=true;conditions.push_back(shortIndex);
 auto reorder=allConditions[8];reorder.name="group8_cache_order";reorder.reordered=true;conditions.push_back(reorder);
 auto packed=allConditions[8];packed.name="group8_compact_vertices";packed.compact=true;conditions.push_back(packed);
 reorder=allConditions[1];reorder.name="indexed_cache_order";reorder.reordered=true;conditions.push_back(reorder);
 }else if(argc==6&&std::string(argv[5])=="groups"){conditions.push_back(allConditions[0]);conditions.push_back(allConditions[8]);for(unsigned n:{1U,2U,4U,16U,32U,64U}){auto c=allConditions[8];c.name="indexed_group_candidate";c.groupSize=n;conditions.push_back(c);}}else if(argc==6){for(unsigned k:{0U,1U,8U,9U,10U})conditions.push_back(allConditions[k]);}else conditions.assign(allConditions.begin(),allConditions.end());
 auto drawEye=[&](const Condition& c,unsigned eye){glViewport(0,0,c.tiny?1:state.width,c.tiny?1:state.height);glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LESS);glDepthMask(GL_TRUE);glDisable(GL_DITHER);glDisable(GL_SCISSOR_TEST);if(c.blend)glEnable(GL_BLEND);else glDisable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);if(c.cull)glEnable(GL_CULL_FACE);else glDisable(GL_CULL_FACE);glCullFace(GL_BACK);glFrontFace(GL_CCW);glEnable(GL_STENCIL_TEST);glStencilMask(255);glClearStencil(0);glStencilFunc(GL_ALWAYS,1,255);glStencilOp(GL_KEEP,GL_KEEP,GL_REPLACE);glClearColor(0,0,0,1);glClearDepth(1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT);const GLuint sentinel[4]{91,0,0,0};glClearBufferuiv(GL_COLOR,1,sentinel);const auto vp=state.eyes[eye].projection*state.eyes[eye].view*state.model;const glm::mat4 light=glm::scale(glm::mat4(1),glm::vec3(.1F));
  for(const auto& b:batches){if(c.cull&&(b.vertices.size()==420||b.vertices.size()==2160))glEnable(GL_CULL_FACE);else glDisable(GL_CULL_FACE);const bool indexed=c.index&&!b.group&&b.indexed.plan.eligible;const bool indexGroup=indexed&&c.indexGroup;const bool groupedDraw=b.group||indexGroup;const auto p=indexGroup&&!c.directNormal?sizedPrograms[c.groupSize]:programs[(c.constant?2:c.directNormal&&b.uniformSphere?4:0)+(groupedDraw?1:0)];glUseProgram(p);glUniformMatrix4fv(glGetUniformLocation(p,"vp"),1,GL_FALSE,&vp[0][0]);glUniformMatrix4fv(glGetUniformLocation(p,"worldModel"),1,GL_FALSE,&state.model[0][0]);glUniform1i(glGetUniformLocation(p,"instanced"),1);glUniform1i(glGetUniformLocation(p,"uShadowsEnabled"),c.shadows);glUniform1i(glGetUniformLocation(p,"uShadowMap"),0);glUniformMatrix4fv(glGetUniformLocation(p,"uLightViewProjection"),1,GL_FALSE,&light[0][0]);glUniform3f(glGetUniformLocation(p,"uLightDirection"),0,0,1);vertices(indexGroup?b.indexGroupVbo:b.group?b.groupVbo:indexed?b.indexVbo:b.vbo);if(c.compact&&b.compact&&groupedDraw){
    glBindBuffer(GL_ARRAY_BUFFER,groupedDraw?b.compactGroupVbo:b.compactVbo);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(CompactV),(void*)offsetof(CompactV,p));
    glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(CompactV),(void*)offsetof(CompactV,normal));
    glDisableVertexAttribArray(1);glDisableVertexAttribArray(2);
    glVertexAttrib4fv(1,&b.vertices[0].color[0]);glVertexAttrib2fv(2,&b.vertices[0].uv[0]);
   }
   const GLenum indexType=c.shortIndices?GL_UNSIGNED_SHORT:GL_UNSIGNED_INT;glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,indexGroup?(c.shortIndices?b.shortGroupEbo:c.reordered?b.reorderGroupEbo:b.indexGroupEbo):indexed?(c.shortIndices?b.shortEbo:c.reordered?b.reorderEbo:b.ebo):0);
   if(groupedDraw){for(GLuint a=3;a<=7;++a){glVertexAttribDivisor(a,0);glDisableVertexAttribArray(a);}glActiveTexture(GL_TEXTURE9);glBindTexture(GL_TEXTURE_BUFFER,b.tex);glUniform1i(glGetUniformLocation(p,"uGroupedInstances"),9);glUniform1i(glGetUniformLocation(p,"uGroupBaseVertices"),indexGroup?b.indexed.vertices.size():b.vertices.size());
    if(indexGroup){const auto full=b.instances.size()/c.groupSize,remainder=b.instances.size()%c.groupSize;glUniform1i(glGetUniformLocation(p,"uGroupFirstInstance"),0);if(full)glDrawElementsInstanced(GL_TRIANGLES,b.indexed.indices.size()*c.groupSize,indexType,nullptr,full);if(remainder){glUniform1i(glGetUniformLocation(p,"uGroupFirstInstance"),full*c.groupSize);glDrawElementsInstanced(GL_TRIANGLES,b.indexed.indices.size()*remainder,indexType,nullptr,1);}}
    else for(const auto& call:nadoc_vr::view_groups::draws(b.vertices.size(),b.instances.size()))if(call.instances){glUniform1i(glGetUniformLocation(p,"uGroupFirstInstance"),call.firstInstance);glDrawArraysInstanced(GL_TRIANGLES,0,call.vertices,call.instances);}}
   else {glBindBuffer(GL_ARRAY_BUFFER,b.ibo);for(GLuint a=3;a<=7;++a){glEnableVertexAttribArray(a);glVertexAttribDivisor(a,1);glVertexAttribPointer(a,4,GL_FLOAT,GL_FALSE,sizeof(I),(void*)(uintptr_t)((a-3)*sizeof(glm::vec4)));}if(indexed)glDrawElementsInstanced(GL_TRIANGLES,b.indexed.indices.size(),indexType,nullptr,b.instances.size());else glDrawArraysInstanced(GL_TRIANGLES,0,b.vertices.size(),b.instances.size());}
  }
 };
 GLuint query=0;glGenQueries(1,&query);std::vector<std::vector<double>> times(conditions.size());for(unsigned warm=0;warm<3;++warm)for(const auto& c:conditions)for(unsigned e=0;e<2;++e)drawEye(c,e);glFinish();checkGL("warmup");
 for(int r=0;r<iterations;++r){
  for(unsigned step=0;step<conditions.size();++step){
   const unsigned k=r%2?conditions.size()-1-step:step;
   glBeginQuery(GL_TIME_ELAPSED,query);
   for(unsigned e=0;e<2;++e)drawEye(conditions[k],e);
   glEndQuery(GL_TIME_ELAPSED);
   GLuint64 ns=0;glGetQueryObjectui64v(query,GL_QUERY_RESULT,&ns);
   times[k].push_back(double(ns)/1e6);
  }
 }
 checkGL("timing");
 bool parity=true;const size_t pixels=size_t(state.width)*state.height;std::array<std::vector<unsigned char>,2> reference;std::array<std::vector<float>,2> referenceDepth;std::array<std::vector<GLuint>,2> referenceIds;report<<"\"conditions\":[";
 for(unsigned k=0;k<conditions.size();++k){size_t rgbaDifferences=0,depthDifferences=0,idDifferences=0,covered=0;for(unsigned e=0;e<2;++e){drawEye(conditions[k],e);std::vector<unsigned char> rgba(pixels*4);std::vector<float> z(pixels);std::vector<GLuint> ids(pixels);glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,state.width,state.height,GL_RGBA,GL_UNSIGNED_BYTE,rgba.data());glReadPixels(0,0,state.width,state.height,GL_DEPTH_COMPONENT,GL_FLOAT,z.data());glReadBuffer(GL_COLOR_ATTACHMENT1);glReadPixels(0,0,state.width,state.height,GL_RED_INTEGER,GL_UNSIGNED_INT,ids.data());if(k==0){reference[e]=rgba;referenceDepth[e]=z;referenceIds[e]=ids;}for(size_t i=0;i<pixels;++i){covered+=z[i]<1;depthDifferences+=z[i]!=referenceDepth[e][i];idDifferences+=ids[i]!=referenceIds[e][i];}for(size_t i=0;i<rgba.size();++i)rgbaDifferences+=rgba[i]!=reference[e][i];if(k==0||conditions[k].cull||conditions[k].constant||conditions[k].indexGroup||conditions[k].directNormal)ppm(out/(std::string(conditions[k].name)+"-"+std::to_string(conditions[k].groupSize)+(e?"-right.ppm":"-left.ppm")),rgba,state.width,state.height);}
  parity=parity&&covered>100&&rgbaDifferences==0&&depthDifferences==0&&idDifferences==0;
  auto sorted=times[k];std::sort(sorted.begin(),sorted.end());if(k)report<<',';report<<"{\"name\":\""<<conditions[k].name<<"\",\"group_size\":"<<conditions[k].groupSize<<",\"median_both_eye_gpu_ms\":"<<sorted[sorted.size()/2]<<",\"min_both_eye_gpu_ms\":"<<sorted.front()<<",\"max_both_eye_gpu_ms\":"<<sorted.back()<<",\"covered_pixel_eyes\":"<<covered<<",\"rgba_channel_differences_vs_arrays\":"<<rgbaDifferences<<",\"depth_pixel_differences_vs_arrays\":"<<depthDifferences<<",\"id_pixel_differences_vs_arrays\":"<<idDifferences<<",\"samples_ms\":[";for(size_t j=0;j<times[k].size();++j){if(j)report<<',';report<<times[k][j];}report<<"]}";std::cout<<conditions[k].name<<" group_size="<<conditions[k].groupSize<<" median_both_eye_gpu_ms="<<sorted[sorted.size()/2]<<" rgba_differences="<<rgbaDifferences<<" depth_differences="<<depthDifferences<<"\n";
 }
 report<<"]}\n";report.close();require(bool(report),"report write failed");checkGL("readback");if(argc==6&&std::string(argv[5])=="groups")require(parity,"grouping changed pixels or produced blank output");glfwDestroyWindow(window);glfwTerminate();return 0;
}catch(const std::exception& e){std::cerr<<"view mesh benchmark: "<<e.what()<<'\n';return 1;}}
