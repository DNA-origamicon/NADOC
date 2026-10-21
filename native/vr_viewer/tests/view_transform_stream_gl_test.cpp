#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>

static std::string packet(uint32_t version,bool update,float x,uint32_t base=1){
 std::ostringstream out;out.write("NADOCVT1",8);
 uint32_t h[10]={update?7U:6U,version,2048,0,0,0,0,0,1,0};out.write((char*)h,sizeof(h));
 if(update)out.write((char*)&base,4);
 uint32_t counts[2]={update?9U:3U,update?3U:9U};out.write((char*)counts,8);
 if(!update){VRViewTools::V vertices[3]={{{-.1F,-.1F,0},{1,.2F,.3F,1},{-1,-1},{0,0,1}},{{.1F,-.1F,0},{1,.2F,.3F,1},{-1,-1},{0,0,1}},{{0,.1F,0},{1,.2F,.3F,1},{-1,-1},{0,0,1}}};out.write((char*)vertices,sizeof(vertices));}
 for(int i=0;i<9;i++){
  glm::vec3 position{x+(i%3-1)*.35F,(i/3-1)*.35F,0};
  if(update)out.write((char*)&position,sizeof(position));
  else {VRViewTools::Instance instance{glm::translate(glm::mat4(1),position),{1,1,1,1}};out.write((char*)&instance,sizeof(instance));}
 }
 return out.str();
}
static void apply(VRViewTools& v,std::string data,const std::string& path){
 auto read=VRViewTools::readView("",v.version,{},1,{},true,v.groupsAvailable(),v.groupLimits,true,v.groupsAvailable(),std::move(data),v.transformBase);assert(read);
 v.staging.emplace();v.staging->view=std::move(*read);
 bool applied=false;for(int i=0;i<1000&&!applied;i++){applied=v.poll(path,{},1,{},false);glFinish();}assert(applied);
}
static std::vector<unsigned char> pixels(VRViewTools& v){
 glViewport(0,0,128,128);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
 v.renderScene(glm::mat4(1),glm::mat4(1),glm::quat(1,0,0,0));glFinish();std::vector<unsigned char> out(128*128*4);glReadPixels(0,0,128,128,GL_RGBA,GL_UNSIGNED_BYTE,out.data());return out;
}
int main(){
 if(!glfwInit())return 77;glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
 auto* window=glfwCreateWindow(128,128,"transform parity",nullptr,nullptr);if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
 {
  VRViewTools v,full;v.initialize();full.initialize();const auto path=std::string("transform-test-")+std::to_string(getpid());
  apply(v,packet(1,false,0),path);auto vertex=v.batches[0].vertexBuffer,grouped=v.batches[0].groupedVertexBuffer,originalInstance=v.batches[0].instanceBuffer;
  const auto before=pixels(v);std::vector<unsigned char> last;
  for(uint32_t version=2;version<=4;version++){
   apply(v,packet(version,true,.03F*version),path);apply(full,packet(version,false,.03F*version),path+"-full");
   assert(v.opaqueActive()==full.opaqueActive());
   assert(v.batches[0].vertexBuffer==vertex && v.batches[0].groupedVertexBuffer==grouped);
   if(version==3)assert(v.batches[0].instanceBuffer==originalInstance);
   assert(v.batches[0].instances.size()==full.batches[0].instances.size());
   assert(std::memcmp(v.batches[0].instances.data(),full.batches[0].instances.data(),9*sizeof(VRViewTools::Instance))==0);
   std::vector<VRViewTools::Instance> gpu(9);glBindBuffer(GL_ARRAY_BUFFER,v.batches[0].instanceBuffer);glGetBufferSubData(GL_ARRAY_BUFFER,0,gpu.size()*sizeof(gpu[0]),gpu.data());assert(std::memcmp(gpu.data(),full.batches[0].instances.data(),gpu.size()*sizeof(gpu[0]))==0);
   last=pixels(v);assert(last==pixels(full));
  }
  assert(before!=last); // Parity of two blank images is not success.
  assert(v.transformUpdateCount==3 && v.fullSnapshotCount==1);
  assert(!VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,packet(5,true,0,999),v.transformBase));
  // A replacement full snapshot invalidates the old layout/version.
  apply(v,packet(6,false,0),path);assert(!VRViewTools::readView("",v.version,{},1,{},true,false,{},false,false,packet(7,true,0,1),v.transformBase));
  v.shutdown();full.shutdown();
 }
 glfwDestroyWindow(window);glfwTerminate();std::cout<<"Persistent buffer, byte and visible pixel parity passed\n";
}
