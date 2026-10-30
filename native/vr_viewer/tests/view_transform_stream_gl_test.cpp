#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>

static unsigned meshRepeats=25;
static std::string packet(uint32_t version,bool update,float x,uint32_t base=1){
 std::ostringstream out;out.write("NADOCVT1",8);
 uint32_t h[10]={update?7U:6U,version,2048,0,0,0,0,0,1,0};out.write((char*)h,sizeof(h));
 if(update)out.write((char*)&base,4);
 uint32_t counts[2]={update?9U:meshRepeats*3U,update?3U:9U};out.write((char*)counts,8);
 if(!update){VRViewTools::V vertices[3]={{{-.1F,-.1F,0},{1,.2F,.3F,1},{-1,-1},{0,0,1}},{{.1F,-.1F,0},{1,.2F,.3F,1},{-1,-1},{0,0,1}},{{0,.1F,0},{1,.2F,.3F,1},{-1,-1},{0,0,1}}};for(int repeat=0;repeat<int(meshRepeats);++repeat)out.write((char*)vertices,sizeof(vertices));}
 for(int i=0;i<9;i++){
  glm::vec3 position{x+(i%3-1)*.35F,(i/3-1)*.35F,0};
  if(update)out.write((char*)&position,sizeof(position));
  else {VRViewTools::Instance instance{glm::translate(glm::mat4(1),position),{1,1,1,1}};out.write((char*)&instance,sizeof(instance));}
 }
 return out.str();
}
// An opaque foreground surface must occlude normal geometry, but not the
// explicitly tagged, unlit annotation behind it. The same production parser,
// staged buffers, grouped draw paths and renderer are exercised below.
static std::string annotationPacket(uint32_t version,bool annotation,float x=0){
 std::ostringstream out;out.write("NADOCVT1",8);
 uint32_t h[10]={6,version,264,3,0,0,0,0,1,0};out.write((char*)h,sizeof(h));
 VRViewTools::V foreground[3]={{{-1,-1,-.5F},{0,0,1,1},{-1,-1},{}},{{1,-1,-.5F},{0,0,1,1},{-1,-1},{}},{{0,1,-.5F},{0,0,1,1},{-1,-1},{}}};
 out.write((char*)foreground,sizeof(foreground));
 uint32_t counts[2]={meshRepeats*3,9};out.write((char*)counts,sizeof(counts));
 const glm::vec2 uv=annotation?glm::vec2(-2):glm::vec2(-1);
 VRViewTools::V marker[3]={{{-.1F,-.1F,.5F},{1,0,0,.85F},uv,{}},{{.1F,-.1F,.5F},{1,0,0,.85F},uv,{}},{{0,.1F,.5F},{1,0,0,.85F},uv,{}}};
 for(unsigned r=0;r<meshRepeats;r++)out.write((char*)marker,sizeof(marker));
 for(int i=0;i<9;i++){VRViewTools::Instance instance{glm::translate(glm::mat4(1),glm::vec3(x+(i%3-1)*.35F,(i/3-1)*.35F,0)),{1,1,1,1}};out.write((char*)&instance,sizeof(instance));}
 return out.str();
}
static std::string panelPacket(uint32_t version,uint32_t base,bool only){
 auto data=only?std::string("NADOCVT1",8):packet(version,false,0);
 uint32_t h[10]={only?9U:8U,version,2048,0,0,0,768,768,only?0U:1U,19};
 if(only)data.append((char*)h,sizeof(h));else std::memcpy(data.data()+8,h,sizeof(h));
 data.insert(48,(char*)&base,4);data.append(768*768*4,char(127));return data;
}
static std::string compressedPanelPacket(uint32_t version,uint32_t base,bool only){
 auto data=panelPacket(version,base,only);const size_t bytes=768*768*4,offset=data.size()-bytes;
 data.resize(offset);uint32_t run[2]={768*768,0x7f7f7f7f};data.append((char*)run,sizeof(run));
 uint32_t schema=only?11:10;std::memcpy(data.data()+8,&schema,4);return data;
}
static std::string glyphPacket(uint32_t version,float kind){
 std::ostringstream out;out.write("NADOCVT1",8);uint32_t h[10]={6,version,264,0,0,0,0,0,1,0};out.write((char*)h,sizeof(h));
 uint32_t counts[2]={6,1};out.write((char*)counts,sizeof(counts));
 for(auto p:std::array<glm::vec3,6>{{{-.6F,-.6F,0},{.6F,-.6F,0},{-.6F,.6F,0},{-.6F,.6F,0},{.6F,-.6F,0},{.6F,.6F,0}}}){
  VRViewTools::V v{p,{1,.25F,0,1},{-kind,-kind},{}};out.write((char*)&v,sizeof(v));
 }
 VRViewTools::Instance i{glm::mat4(1),{1,1,1,1}};out.write((char*)&i,sizeof(i));return out.str();
}
static void apply(VRViewTools& v,std::string data,const std::string& path){
 auto read=VRViewTools::readView("",v.version,{},1,{},true,v.groupsAvailable(),v.groupLimits,true,v.groupsAvailable(),std::move(data),v.transformBase,v.compactRequested);assert(read);
 v.staging.emplace();v.staging->view=std::move(*read);
 bool applied=false;for(int i=0;i<1000&&!applied;i++){applied=v.poll(path,{},1,{},false);glFinish();}assert(applied);
}
struct Pixels {std::vector<unsigned char> color;std::vector<float> depth;std::vector<GLuint> ids;bool operator==(const Pixels&) const = default;};
static Pixels pixels(VRViewTools& v,bool shadow=false,glm::mat4 model=glm::mat4(1)){
 glViewport(0,0,128,128);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);const GLuint zero=0;glClearBufferuiv(GL_COLOR,1,&zero);
 v.renderScene(glm::mat4(1),model,glm::quat(1,0,0,0),shadow);glFinish();Pixels out;out.color.resize(128*128*4);out.depth.resize(128*128);out.ids.resize(128*128);glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,128,128,GL_RGBA,GL_UNSIGNED_BYTE,out.color.data());glReadPixels(0,0,128,128,GL_DEPTH_COMPONENT,GL_FLOAT,out.depth.data());glReadBuffer(GL_COLOR_ATTACHMENT1);glReadPixels(0,0,128,128,GL_RED_INTEGER,GL_UNSIGNED_INT,out.ids.data());return out;
}
int main(int argc,char** argv){
 if(!glfwInit())return 77;glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
 auto* window=glfwCreateWindow(128,128,"transform parity",nullptr,nullptr);if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
 for(unsigned repeats:{25U,1U}){meshRepeats=repeats;
  GLuint fbo=0;std::array<GLuint,3> outputs{};glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);glGenTextures(3,outputs.data());
  for(unsigned i=0;i<3;++i){glBindTexture(GL_TEXTURE_2D,outputs[i]);glTexImage2D(GL_TEXTURE_2D,0,i==0?GL_RGBA8:i==1?GL_DEPTH_COMPONENT32F:GL_R32UI,128,128,0,i==0?GL_RGBA:i==1?GL_DEPTH_COMPONENT:GL_RED_INTEGER,i==0?GL_UNSIGNED_BYTE:i==1?GL_FLOAT:GL_UNSIGNED_INT,nullptr);glFramebufferTexture2D(GL_FRAMEBUFFER,i==0?GL_COLOR_ATTACHMENT0:i==1?GL_DEPTH_ATTACHMENT:GL_COLOR_ATTACHMENT1,GL_TEXTURE_2D,outputs[i],0);}
  const GLenum attachments[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};glDrawBuffers(2,attachments);assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
  VRViewTools v,full;v.initialize();full.initialize();full.compactRequested=false;const auto path=std::string("transform-test-")+std::to_string(getpid());
  apply(v,packet(1,false,0),path);auto vertex=v.batches[0].vertexBuffer,grouped=v.batches[0].groupedVertexBuffer,originalInstance=v.batches[0].instanceBuffer;
  assert(!v.batches[0].compactGroup.empty());
  GLint packedBytes=0;glBindBuffer(GL_ARRAY_BUFFER,repeats==25?v.batches[0].indexedGroupVertexBuffer:v.batches[0].groupedVertexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&packedBytes);assert(size_t(packedBytes)==v.batches[0].compactGroup.size()*24);
  const auto before=pixels(v);Pixels last;
  for(uint32_t version=2;version<=4;version++){
   apply(v,packet(version,true,.03F*version),path);apply(full,packet(version,false,.03F*version),path+"-full");
   assert(v.opaqueActive()==full.opaqueActive());assert(full.batches[0].compactGroup.empty());
   assert(v.batches[0].vertexBuffer==vertex && v.batches[0].groupedVertexBuffer==grouped);
   if(version==3)assert(v.batches[0].instanceBuffer==originalInstance);
   assert(v.batches[0].instances.size()==full.batches[0].instances.size());
   assert(std::memcmp(v.batches[0].instances.data(),full.batches[0].instances.data(),9*sizeof(VRViewTools::Instance))==0);
   std::vector<VRViewTools::Instance> gpu(9);glBindBuffer(GL_ARRAY_BUFFER,v.batches[0].instanceBuffer);glGetBufferSubData(GL_ARRAY_BUFFER,0,gpu.size()*sizeof(gpu[0]),gpu.data());assert(std::memcmp(gpu.data(),full.batches[0].instances.data(),gpu.size()*sizeof(gpu[0]))==0);
   last=pixels(v);assert(last==pixels(full));assert(pixels(v,true)==pixels(full,true));
  }
  assert(before!=last); // Parity of two blank images is not success.
  assert(v.transformUpdateCount==3 && v.fullSnapshotCount==1);
  assert(!VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,packet(5,true,0,999),v.transformBase));
  // A replacement full snapshot invalidates the old layout/version.
  apply(v,packet(6,false,0),path);assert(!VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,packet(7,true,0,1),v.transformBase));
  const auto sceneBeforePanel=pixels(v);const auto sceneBuffer=v.batches[0].vertexBuffer;
  apply(v,panelPacket(7,6,true),path);assert(v.panelTexture && v.batches[0].vertexBuffer==sceneBuffer);
  assert(v.transformBase->version==6 && v.acknowledged==19 && pixels(v)==sceneBeforePanel);
  std::vector<unsigned char> panel(768*768*4);glBindTexture(GL_TEXTURE_2D,v.panelTexture);glGetTexImage(GL_TEXTURE_2D,0,GL_RGBA,GL_UNSIGNED_BYTE,panel.data());
  assert(std::all_of(panel.begin(),panel.end(),[](auto c){return c==127;}));
  apply(v,panelPacket(8,6,false),path);assert(v.transformBase->version==8 && pixels(v)==sceneBeforePanel);
  assert(!VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,panelPacket(9,6,true),v.transformBase));
  for(bool only:{true,false}){
   const auto compressed=compressedPanelPacket(only?10:11,8,only);
   const auto parsed=VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,compressed,v.transformBase);
   assert(parsed && parsed->pixels==panel && parsed->panelOnly==only);
   for(const auto& bad:{compressed.substr(0,compressed.size()-1),compressed+"trailing"})
    assert(!VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,bad,v.transformBase));
  }
  apply(v,compressedPanelPacket(12,8,true),path);
  glBindTexture(GL_TEXTURE_2D,v.panelTexture);std::vector<unsigned char> decompressed(panel.size());glGetTexImage(GL_TEXTURE_2D,0,GL_RGBA,GL_UNSIGNED_BYTE,decompressed.data());
  assert(decompressed==panel && v.batches[0].vertexBuffer && pixels(v)==sceneBeforePanel);
  apply(v,annotationPacket(18,false),path);const auto occluded=pixels(v);
  apply(v,annotationPacket(19,true),path);const auto annotated=pixels(v);
  assert(v.batches[0].annotation && v.opaqueActive());
  const size_t center=(62*128+64)*4;
  assert(occluded.color[center]<5 && annotated.color[center]>200);
  assert(annotated.depth[center/4]==occluded.depth[center/4]);
  assert(glIsEnabled(GL_DEPTH_TEST));GLboolean depthWrite=0;glGetBooleanv(GL_DEPTH_WRITEMASK,&depthWrite);assert(depthWrite);
  apply(full,annotationPacket(19,true),path+"-full");assert(annotated==pixels(full));
  apply(v,annotationPacket(20,true,4),path);const auto offscreen=pixels(v);
  assert(offscreen.color[center]<5); // An absent annotation must fail visibility.
  assert(annotated.depth==offscreen.depth); // No annotation depth writes, even outside the foreground silhouette.
  std::cout<<"Annotation visible over opaque DNA, unlit, unchanged depth, offscreen negative and compact parity passed (repeats="<<repeats<<")\n";
  apply(v,glyphPacket(21,3),path);const auto ring=pixels(v);
  assert(ring.color[(64*128+64)*4]<5); // A visible hole, not a solid dot.
  assert(ring.color[(64*128+85)*4]>200); // Bright ring core.
  assert(ring.color[(64*128+91)*4]>5 && ring.color[(64*128+91)*4]<180); // Soft outer halo.
  const auto edgeOn=pixels(v,false,glm::rotate(glm::mat4(1),glm::radians(90.F),glm::vec3(0,1,0)));
  assert(edgeOn.color==ring.color); // Model rotation cannot collapse the glyph.
  const auto distant=pixels(v,false,glm::scale(glm::mat4(1),glm::vec3(.02F)));
  size_t bright=0;for(size_t i=0;i<distant.color.size();i+=4)bright+=distant.color[i]>180;assert(bright>=20);
  apply(v,glyphPacket(22,4),path);const auto cross=pixels(v);assert(cross.color[(64*128+64)*4]>200);
  std::cout<<"Atlas patch retention/stale-base rejection and glyph hole/core/halo/edge-on/minimum-size checks passed\n";
  // Optional audit: render an actual browser-exported annotation packet with
  // this same production renderer; retain a small RGB image for human review.
  if(argc==3 && repeats==1){
   std::ifstream input(argv[1],std::ios::binary);assert(input);
   std::string data{std::istreambuf_iterator<char>(input),{}};apply(v,std::move(data),path);
   const auto image=pixels(v);std::ofstream output(argv[2],std::ios::binary);assert(output);output<<"P6\n128 128\n255\n";
   for(int y=127;y>=0;--y)for(int x=0;x<128;++x)output.write((const char*)image.color.data()+(y*128+x)*4,3);
  }
  v.shutdown();full.shutdown();glDeleteTextures(3,outputs.data());glDeleteFramebuffers(1,&fbo);
 }
 glfwDestroyWindow(window);glfwTerminate();std::cout<<"Persistent buffer, compact vertex, color/depth/ID parity passed\n";
}
