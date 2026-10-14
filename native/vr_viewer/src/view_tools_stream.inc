// Included inside VRViewTools. File I/O, validation and pose normalization are CPU
// worker work. GL writes use spare buffers in <=256 KiB pieces, with a 1 ms budget.
struct IncomingView {std::array<uint32_t,10> header{};std::vector<V> triangles,lines;std::vector<Sprite> sprites;std::vector<Batch> batches;std::vector<unsigned char> pixels;double parseMs=0;std::optional<nadoc_vr::BoundsSummary> bounds;nadoc_vr::view_opaque::Eligibility opaqueEligibility;bool groupedAny=false;};
struct StagedView {IncomingView view;GLuint triangles=0,lines=0,texture=0;size_t buffer=0,offset=0,textureRow=0;double uploadMs=0;};
std::future<std::optional<IncomingView>> reading;
std::optional<StagedView> staging;
static std::optional<IncomingView> readView(const std::string& path,uint32_t current,glm::vec3 center,float scale,glm::vec3 origin,bool classifyOpaque=false,bool groupInstances=false,nadoc_vr::view_groups::Limits groupLimits={}){
 const auto start=std::chrono::steady_clock::now();std::ifstream in(path,std::ios::binary);char magic[8];IncomingView out;auto& h=out.header;
 if(!in.read(magic,8)||std::string(magic,8)!="NADOCVT1"||!in.read((char*)h.data(),40)||(h[0]!=4&&h[0]!=5&&h[0]!=6)||h[1]==current)return {};
 const bool atlas=h[0]!=6;
 if(h[2]>=4096||(h[2]&(128|512|1024))||h[3]+uint64_t(h[4])>4000000||h[3]%3||h[4]%2||h[5]>100000||h[8]>10000||h[6]!=(atlas?2048U:0U)||h[7]!=(atlas?2048U:0U))return {};
 out.triangles.resize(h[3]);out.lines.resize(h[4]);out.sprites.resize(h[5]);if(atlas)out.pixels.resize(2048*2048*4);
 const auto vertices=[&](auto& values){if(h[0]>=5)return bool(in.read((char*)values.data(),values.size()*sizeof(V)));for(auto& v:values)if(!in.read((char*)&v,36))return false;return true;};
 if(!vertices(out.triangles)||!vertices(out.lines)||!in.read((char*)out.sprites.data(),out.sprites.size()*sizeof(Sprite)))return {};
 uint64_t totalVertices=h[3]+h[4],totalInstances=0;
 const auto normalization=glm::translate(glm::mat4(1),origin)*glm::scale(glm::mat4(1),glm::vec3(scale))*glm::translate(glm::mat4(1),-center);
 for(uint32_t i=0;i<h[8];++i){std::array<uint32_t,2> counts{};if(!in.read((char*)counts.data(),8))return {};totalVertices+=counts[0];totalInstances+=counts[1];
  if(!counts[0]||counts[0]%3||!counts[1]||totalVertices>4000000||totalInstances>1000000)return {};
  Batch b;b.vertices.resize(counts[0]);b.instances.resize(counts[1]);if(!vertices(b.vertices)||!in.read((char*)b.instances.data(),b.instances.size()*sizeof(Instance)))return {};
  for(auto& instance:b.instances)instance.matrix=normalization*instance.matrix;
  out.batches.push_back(std::move(b));}
 if(!in.read((char*)out.pixels.data(),out.pixels.size())||in.peek()!=std::char_traits<char>::eof())return {};
 for(auto* list:{&out.triangles,&out.lines})for(auto& v:*list)v.p=(v.p-center)*scale+origin;
 for(auto& s:out.sprites){s.p=(s.p-center)*scale+origin;s.size*=scale;}
 nadoc_vr::BoundsAccumulator bounds;
 for(const auto* list:{&out.triangles,&out.lines})for(const auto& v:*list)bounds.includePoint(v.p,0);
 for(const auto& b:out.batches){glm::vec3 lo(1e30F),hi(-1e30F);for(const auto& v:b.vertices){lo=glm::min(lo,v.p);hi=glm::max(hi,v.p);}for(const auto& instance:b.instances)for(int i=0;i<8;++i)bounds.includePoint(glm::vec3(instance.matrix*glm::vec4(i&1?hi.x:lo.x,i&2?hi.y:lo.y,i&4?hi.z:lo.z,1)),0);}
 for(const auto& sprite:out.sprites)bounds.includePoint(sprite.p,glm::length(sprite.size)*.5F);
 out.bounds=bounds.summary(glm::mat4(1));
 if(classifyOpaque)out.opaqueEligibility=nadoc_vr::view_opaque::classify(out.triangles,out.batches);
 if(groupInstances){size_t remaining=nadoc_vr::view_groups::maxExpandedBytes;
  for(auto& b:out.batches){b.groupPlan=nadoc_vr::view_groups::plan(b.vertices.size(),b.instances.size(),sizeof(V),groupLimits,remaining);
   if(b.groupPlan.eligible){b.groupedVertices=nadoc_vr::view_groups::expand(b.vertices);remaining-=b.groupPlan.expandedBytes;out.groupedAny=true;}}}
 out.parseMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();return out;
}
bool poll(const std::string& path,glm::vec3 center,float scale,glm::vec3 origin){
 if(path.empty())return false;
 if(reading.valid()&&reading.wait_for(std::chrono::seconds(0))==std::future_status::ready){try{auto next=reading.get();if(next){staging.emplace();staging->view=std::move(*next);}}catch(const std::exception&){} }
 if(staging){auto& s=*staging;const double start=glfwGetTime();const size_t stride=s.view.groupedAny?3:2;const size_t count=2+s.view.batches.size()*stride;
  while(s.buffer<count&&glfwGetTime()-start<.001){GLuint* buffer;const void* data;size_t bytes;
   if(s.buffer<2){auto& list=s.buffer==0?s.view.triangles:s.view.lines;buffer=s.buffer==0?&s.triangles:&s.lines;data=list.data();bytes=list.size()*sizeof(V);}
   else {auto& b=s.view.batches[(s.buffer-2)/stride];const size_t kind=(s.buffer-2)%stride;
    buffer=kind==2?&b.groupedVertexBuffer:kind==1?&b.instanceBuffer:&b.vertexBuffer;
    data=kind==2?(const void*)b.groupedVertices.data():kind==1?(const void*)b.instances.data():(const void*)b.vertices.data();
    bytes=kind==2?b.groupedVertices.size()*sizeof(V):kind==1?b.instances.size()*sizeof(Instance):b.vertices.size()*sizeof(V);}
   if(!bytes){++s.buffer;s.offset=0;continue;}
   if(!*buffer){glGenBuffers(1,buffer);glBindBuffer(GL_ARRAY_BUFFER,*buffer);glBufferData(GL_ARRAY_BUFFER,bytes,nullptr,GL_STREAM_DRAW);}else glBindBuffer(GL_ARRAY_BUFFER,*buffer);
   const size_t n=std::min(size_t(256*1024),bytes-s.offset);if(n)glBufferSubData(GL_ARRAY_BUFFER,s.offset,n,(const char*)data+s.offset);s.offset+=n;
   if(s.offset==bytes){++s.buffer;s.offset=0;}
  }
  if(s.buffer==count&&!s.view.pixels.empty()&&glfwGetTime()-start<.001){
   if(!s.texture){glGenTextures(1,&s.texture);glBindTexture(GL_TEXTURE_2D,s.texture);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,2048,2048,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);}
   glBindTexture(GL_TEXTURE_2D,s.texture);glPixelStorei(GL_UNPACK_ALIGNMENT,1);
   while(s.textureRow<2048&&glfwGetTime()-start<.001){const size_t rows=std::min(size_t(16),2048-s.textureRow);glTexSubImage2D(GL_TEXTURE_2D,0,0,s.textureRow,2048,rows,GL_RGBA,GL_UNSIGNED_BYTE,s.view.pixels.data()+s.textureRow*2048*4);s.textureRow+=rows;}
  }
  s.uploadMs+=(glfwGetTime()-start)*1000;
  if(s.buffer==count&&(s.view.pixels.empty()||s.textureRow==2048)){
   clearBatches();glDeleteBuffers(1,&triangleVbo);glDeleteBuffers(1,&lineVbo);triangleVbo=s.triangles;lineVbo=s.lines;
   if(s.texture){glDeleteTextures(1,&texture);texture=s.texture;}
   if(s.view.groupedAny){GLint active=0;glGetIntegerv(GL_ACTIVE_TEXTURE,&active);glActiveTexture(GL_TEXTURE0+nadoc_vr::view_groups::textureUnit);
    for(auto& b:s.view.batches)if(b.groupPlan.eligible && b.groupedVertexBuffer){glGenTextures(1,&b.instanceTexture);GLint width=0,format=0,vertexBytes=0;
     glBindBuffer(GL_ARRAY_BUFFER,b.groupedVertexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&vertexBytes);
     if(b.instanceTexture){glBindTexture(GL_TEXTURE_BUFFER,b.instanceTexture);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,b.instanceBuffer);glGetTexLevelParameteriv(GL_TEXTURE_BUFFER,0,GL_TEXTURE_WIDTH,&width);glGetTexLevelParameteriv(GL_TEXTURE_BUFFER,0,GL_TEXTURE_INTERNAL_FORMAT,&format);}
     if(vertexBytes!=int(b.groupedVertices.size()*sizeof(V)) || width!=int(b.instances.size()*5) || format!=GL_RGBA32F){if(b.instanceTexture)glDeleteTextures(1,&b.instanceTexture);b.instanceTexture=0;glDeleteBuffers(1,&b.groupedVertexBuffer);b.groupedVertexBuffer=0;std::vector<V>().swap(b.groupedVertices);b.groupPlan={false,"grouped_resource_incomplete"};}}
    glActiveTexture(active);}
   opaqueEligibility=s.view.opaqueEligibility;
   batches=std::move(s.view.batches);triangles=std::move(s.view.triangles);lines=std::move(s.view.lines);sprites=std::move(s.view.sprites);
   cachedSceneBounds=s.view.bounds;version=s.view.header[1];flags=s.view.header[2];acknowledged=s.view.header[9];if(acknowledged>=sequence)waiting=false;parseMs=s.view.parseMs;uploadMs=s.uploadMs;staging.reset();return true;
  }
 }
 if(!reading.valid()&&!staging&&++frames%3==0){reading=std::async(std::launch::async,[=,current=version,classifyOpaque=opaqueRequested,groupInstances=groupsAvailable(),limits=groupLimits]{return readView(path+".viewtools",current,center,scale,origin,classifyOpaque,groupInstances,limits);});}
 return false;
}
void cancelStaging(){if(!staging)return;auto& s=*staging;for(auto& b:s.view.batches){if(b.vertexBuffer)glDeleteBuffers(1,&b.vertexBuffer);if(b.instanceTexture)glDeleteTextures(1,&b.instanceTexture);if(b.groupedVertexBuffer)glDeleteBuffers(1,&b.groupedVertexBuffer);if(b.instanceBuffer)glDeleteBuffers(1,&b.instanceBuffer);}if(s.triangles)glDeleteBuffers(1,&s.triangles);if(s.lines)glDeleteBuffers(1,&s.lines);if(s.texture)glDeleteTextures(1,&s.texture);staging.reset();}
