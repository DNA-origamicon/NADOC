// Included inside VRViewTools. File I/O, validation and pose normalization are CPU
// worker work. GL writes use spare buffers in <=256 KiB pieces, with a 1 ms budget.
struct TransformTemplate {std::vector<Instance> instances;glm::vec3 lo,hi;};
struct TransformBase {uint32_t version=0,flags=0;std::vector<TransformTemplate> batches;nadoc_vr::view_opaque::Eligibility opaqueEligibility;};
std::shared_ptr<const TransformBase> transformBase;
uint64_t transformUpdateCount=0,fullSnapshotCount=0;
struct IncomingView {bool transformsOnly=false,panelOnly=false,panelPatch=false;std::shared_ptr<const TransformBase> transformBase;std::array<uint32_t,10> header{};std::vector<V> triangles,lines;std::vector<Sprite> sprites;std::vector<Batch> batches;std::vector<unsigned char> pixels;double parseMs=0,readEpochMs=0;std::optional<nadoc_vr::BoundsSummary> bounds;nadoc_vr::view_opaque::Eligibility opaqueEligibility;bool groupedAny=false,indexedAny=false,indexedGroupedAny=false;};
struct StagedView {IncomingView view;GLuint triangles=0,lines=0,texture=0;size_t buffer=0,offset=0,textureRow=0;double uploadMs=0;};
std::unique_ptr<nadoc_vr::ViewSnapshotInbox> inbox;
std::future<std::optional<IncomingView>> reading;
std::optional<StagedView> staging;
static std::optional<IncomingView> readView(const std::string& path,uint32_t current,glm::vec3 center,float scale,glm::vec3 origin,bool classifyOpaque=false,bool groupInstances=false,nadoc_vr::view_groups::Limits groupLimits={},bool indexMeshes=false,bool groupIndexedMeshes=false,std::optional<std::string> packet={},std::shared_ptr<const TransformBase> base={},bool compactMeshes=true){
 const auto epoch=std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count();
 const auto start=std::chrono::steady_clock::now();std::ifstream file;std::istringstream memory;
 if(packet)memory.str(std::move(*packet));else file.open(path,std::ios::binary);
 std::istream& in=packet?static_cast<std::istream&>(memory):static_cast<std::istream&>(file);char magic[8];IncomingView out;auto& h=out.header;
 if(!in.read(magic,8)||std::string(magic,8)!="NADOCVT1"||!in.read((char*)h.data(),40)||(h[0]<4||h[0]>11)||h[1]==current)return {};
 const bool atlas=h[0]<6;out.transformsOnly=h[0]==7;out.panelOnly=h[0]==9||h[0]==11;out.panelPatch=h[0]>=8;
 std::shared_ptr<TransformBase> fresh;
 if(h[0]>=7){uint32_t baseVersion=0;if(!in.read((char*)&baseVersion,4)||!base||baseVersion!=base->version||baseVersion>=h[1])return {};
  if((out.transformsOnly || out.panelOnly) && h[2]!=base->flags)return {};
  if(out.transformsOnly && h[8]!=base->batches.size())return {};
  if(out.panelOnly && (h[3]||h[4]||h[5]||h[8]))return {};
  out.transformBase=base;
 }
 if(!out.transformsOnly && !out.panelOnly){fresh=std::make_shared<TransformBase>();fresh->version=h[1];fresh->flags=h[2];out.transformBase=fresh;}
 if(h[2]>=4096||(h[2]&(128|512|1024))||h[3]+uint64_t(h[4])>4000000||h[3]%3||h[4]%2||h[5]>100000||h[8]>10000||h[6]!=(out.panelPatch?768U:atlas?2048U:0U)||h[7]!=(out.panelPatch?768U:atlas?2048U:0U))return {};
 out.triangles.resize(h[3]);out.lines.resize(h[4]);out.sprites.resize(h[5]);if(atlas || out.panelPatch)out.pixels.resize(size_t(h[6])*h[7]*4);
 const auto vertices=[&](auto& values){if(h[0]>=5)return bool(in.read((char*)values.data(),values.size()*sizeof(V)));for(auto& v:values)if(!in.read((char*)&v,36))return false;return true;};
 if(!vertices(out.triangles)||!vertices(out.lines)||!in.read((char*)out.sprites.data(),out.sprites.size()*sizeof(Sprite)))return {};
 uint64_t totalVertices=h[3]+h[4],totalInstances=0;
 const auto normalization=glm::translate(glm::mat4(1),origin)*glm::scale(glm::mat4(1),glm::vec3(scale))*glm::translate(glm::mat4(1),-center);
 for(uint32_t i=0;i<h[8];++i){
  if(out.transformsOnly){Batch b;if(!nadoc_vr::view_transforms::read(in,base->batches[i].instances,normalization,b.instances))return {};out.batches.push_back(std::move(b));continue;}
  std::array<uint32_t,2> counts{};if(!in.read((char*)counts.data(),8))return {};totalVertices+=counts[0];totalInstances+=counts[1];
  if(!counts[0]||counts[0]%3||!counts[1]||totalVertices>4000000||totalInstances>1000000)return {};
  Batch b;b.vertices.resize(counts[0]);b.instances.resize(counts[1]);if(!vertices(b.vertices)||!in.read((char*)b.instances.data(),b.instances.size()*sizeof(Instance)))return {};
  TransformTemplate retained;retained.instances=b.instances;retained.lo=glm::vec3(1e30F);retained.hi=glm::vec3(-1e30F);
  for(const auto& v:b.vertices){retained.lo=glm::min(retained.lo,v.p);retained.hi=glm::max(retained.hi,v.p);}fresh->batches.push_back(std::move(retained));
  for(auto& instance:b.instances)instance.matrix=normalization*instance.matrix;
  b.annotation=nadoc_vr::view_opaque::annotation(b.vertices);
  out.batches.push_back(std::move(b));}
 if(h[0]>=10){
  // Bound exact RGBA run expansion; no image resampling or partial decode.
  std::vector<unsigned char> packed(out.pixels.size());in.read((char*)packed.data(),packed.size());
  const auto bytes=in.gcount();if(bytes<=0||size_t(bytes)>=packed.size())return {};
  if(bytes%8)return {};size_t output=0;
  for(size_t i=0;i<size_t(bytes);i+=8){
   uint32_t count=0;std::memcpy(&count,packed.data()+i,4);
   if(!count || count>(out.pixels.size()-output)/4)return {};
   for(uint32_t n=0;n<count;++n){std::memcpy(out.pixels.data()+output,packed.data()+i+4,4);output+=4;}
  }
  if(output!=out.pixels.size())return {};
 }else if(!in.read((char*)out.pixels.data(),out.pixels.size())||in.peek()!=std::char_traits<char>::eof())return {};
 if(out.panelOnly){out.readEpochMs=epoch;out.parseMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();return out;}
 for(auto* list:{&out.triangles,&out.lines})for(auto& v:*list)v.p=(v.p-center)*scale+origin;
 for(auto& s:out.sprites){s.p=(s.p-center)*scale+origin;s.size*=scale;}
 nadoc_vr::BoundsAccumulator bounds;
 for(const auto* list:{&out.triangles,&out.lines})for(const auto& v:*list)bounds.includePoint(v.p,0);
 for(size_t batch=0;batch<out.batches.size();++batch){const auto& b=out.batches[batch];const auto lo=out.transformBase->batches[batch].lo,hi=out.transformBase->batches[batch].hi;for(const auto& instance:b.instances)for(int i=0;i<8;++i)bounds.includePoint(glm::vec3(instance.matrix*glm::vec4(i&1?hi.x:lo.x,i&2?hi.y:lo.y,i&4?hi.z:lo.z,1)),0);}
 for(const auto& sprite:out.sprites)bounds.includePoint(sprite.p,glm::length(sprite.size)*.5F);
 out.bounds=bounds.summary(glm::mat4(1));
 if(classifyOpaque)out.opaqueEligibility=nadoc_vr::view_opaque::classify(out.triangles,out.batches);
 if(out.transformsOnly){out.opaqueEligibility=base->opaqueEligibility;
  if(classifyOpaque && out.opaqueEligibility.eligible){
   for(const auto& v:out.triangles){const auto e=nadoc_vr::view_opaque::vertex(v);if(!e.eligible){out.opaqueEligibility=e;break;}}
   if(out.opaqueEligibility.eligible)for(const auto& b:out.batches)for(const auto& i:b.instances){const auto e=nadoc_vr::view_opaque::instance(i);if(!e.eligible){out.opaqueEligibility=e;break;}}
  }
  out.readEpochMs=epoch;out.parseMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();return out;}
 fresh->opaqueEligibility=out.opaqueEligibility;
 if(groupInstances){size_t remaining=nadoc_vr::view_groups::maxExpandedBytes;
  for(auto& b:out.batches){b.groupPlan=nadoc_vr::view_groups::plan(b.vertices.size(),b.instances.size(),sizeof(V),groupLimits,remaining);
   if(b.groupPlan.eligible){b.groupedVertices=nadoc_vr::view_groups::expand(b.vertices);remaining-=b.groupPlan.expandedBytes;out.groupedAny=true;}}}
 if(indexMeshes){size_t remaining=nadoc_vr::view_indexed::maxDerivedBytes;
  for(auto& b:out.batches){auto indexed=nadoc_vr::view_indexed::build(b.vertices,remaining);b.indexPlan=indexed.plan;
   if(indexed.plan.eligible){remaining-=indexed.plan.derivedBytes;
    if(groupIndexedMeshes){auto grouped=nadoc_vr::view_indexed::expandGroups(indexed.vertices,indexed.indices,nadoc_vr::view_indexed::planGroups(indexed.plan,b.instances.size(),sizeof(V),groupLimits,remaining),remaining);
     b.indexedGroupPlan=grouped.plan;if(grouped.plan.eligible){remaining-=grouped.plan.derivedBytes;b.indexedGroupVertices=std::move(grouped.vertices);b.indexedGroupIndices=std::move(grouped.indices);out.indexedGroupedAny=true;}}
    else b.indexedGroupPlan.reason="disabled_or_grouped_program_unavailable";
    b.indexedVertices=std::move(indexed.vertices);b.indices=std::move(indexed.indices);out.indexedAny=true;}
   else b.indexedGroupPlan.reason="indexed_mesh_unavailable";}}
 else for(auto& b:out.batches){b.indexPlan.reason="disabled";b.indexPlan.originalVertices=b.vertices.size();b.indexedGroupPlan.reason="indexing_disabled";}
 if(compactMeshes && out.opaqueEligibility.eligible){size_t remaining=nadoc_vr::view_compact::maxBytes;
  for(auto& b:out.batches)if(b.indexedGroupPlan.eligible || b.groupPlan.eligible){
   b.compactGroup=nadoc_vr::view_compact::pack(b.indexedGroupPlan.eligible?b.indexedGroupVertices:b.groupedVertices,remaining);
   remaining-=b.compactGroup.capacity()*sizeof(nadoc_vr::view_compact::Vertex);}}
 out.readEpochMs=epoch;out.parseMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();return out;
}
static void discardIndexedGroups(Batch& b,const char* reason){
 if(b.indexedGroupVertexBuffer)glDeleteBuffers(1,&b.indexedGroupVertexBuffer);
 if(b.indexedGroupIndexBuffer)glDeleteBuffers(1,&b.indexedGroupIndexBuffer);
 if(b.instanceTexture && !b.groupPlan.eligible){glDeleteTextures(1,&b.instanceTexture);b.instanceTexture=0;}
 b.indexedGroupVertexBuffer=b.indexedGroupIndexBuffer=0;b.indexedGroupPlan.eligible=false;b.indexedGroupPlan.reason=reason;b.indexedGroupPlan.derivedBytes=0;
 std::vector<nadoc_vr::view_compact::Vertex>().swap(b.compactGroup);std::vector<V>().swap(b.indexedGroupVertices);std::vector<uint32_t>().swap(b.indexedGroupIndices);
}
static void discardIndexed(Batch& b,const char* reason){
 discardIndexedGroups(b,"indexed_base_unavailable");
 if(b.indexedVertexBuffer)glDeleteBuffers(1,&b.indexedVertexBuffer);
 if(b.indexBuffer)glDeleteBuffers(1,&b.indexBuffer);
 b.indexedVertexBuffer=b.indexBuffer=0;b.indexPlan.eligible=false;b.indexPlan.reason=reason;b.indexPlan.derivedBytes=0;
 std::vector<V>().swap(b.indexedVertices);std::vector<uint32_t>().swap(b.indices);
}
bool poll(const std::string& path,glm::vec3 center,float scale,glm::vec3 origin,bool continuous=false){
 if(path.empty())return false;
 if(!inbox)inbox=std::make_unique<nadoc_vr::ViewSnapshotInbox>(path);
 bool applied=false;
 if(reading.valid()&&reading.wait_for(std::chrono::seconds(0))==std::future_status::ready){try{auto next=reading.get();if(next){staging.emplace();staging->view=std::move(*next);}}catch(const std::exception&){} }
 if(staging){auto& s=*staging;const double start=glfwGetTime();const size_t indexKind=s.view.groupedAny?3:2;const size_t indexedGroupKind=indexKind+(s.view.indexedAny?2:0);const size_t stride=indexedGroupKind+(s.view.indexedGroupedAny?2:0);const size_t count=s.view.panelOnly?0:2+s.view.batches.size()*(s.view.transformsOnly?1:stride);
  while(s.buffer<count&&glfwGetTime()-start<.001){GLuint* buffer;const void* data;size_t bytes;Batch* optionalIndexed=nullptr;bool optionalGroup=false;
   if(s.buffer<2){auto& list=s.buffer==0?s.view.triangles:s.view.lines;buffer=s.buffer==0?&s.triangles:&s.lines;data=list.data();bytes=list.size()*sizeof(V);}
   else if(s.view.transformsOnly){auto& b=s.view.batches[s.buffer-2];auto& active=batches[s.buffer-2];
    if(!b.instanceBuffer && active.spareInstanceFence){const auto ready=glClientWaitSync(active.spareInstanceFence,0,0);if(ready!=GL_ALREADY_SIGNALED && ready!=GL_CONDITION_SATISFIED)break;glDeleteSync(active.spareInstanceFence);active.spareInstanceFence=nullptr;}
    if(!b.instanceBuffer){b.instanceBuffer=active.spareInstanceBuffer;active.spareInstanceBuffer=0;}
    buffer=&b.instanceBuffer;data=b.instances.data();bytes=b.instances.size()*sizeof(Instance);
   }
   else {auto& b=s.view.batches[(s.buffer-2)/stride];const size_t kind=(s.buffer-2)%stride;
    if(kind>=indexedGroupKind){optionalIndexed=&b;optionalGroup=true;const bool elements=kind==indexedGroupKind+1;
     buffer=elements?&b.indexedGroupIndexBuffer:&b.indexedGroupVertexBuffer;data=elements?(const void*)b.indexedGroupIndices.data():!b.compactGroup.empty()?(const void*)b.compactGroup.data():(const void*)b.indexedGroupVertices.data();bytes=elements?b.indexedGroupIndices.size()*sizeof(uint32_t):b.indexedGroupVertices.size()*(b.compactGroup.empty()?sizeof(V):sizeof(nadoc_vr::view_compact::Vertex));}
    else if(kind>=indexKind){optionalIndexed=&b;const bool elements=kind==indexKind+1;
     buffer=elements?&b.indexBuffer:&b.indexedVertexBuffer;data=elements?(const void*)b.indices.data():(const void*)b.indexedVertices.data();bytes=elements?b.indices.size()*sizeof(uint32_t):b.indexedVertices.size()*sizeof(V);}
    else {buffer=kind==2?&b.groupedVertexBuffer:kind==1?&b.instanceBuffer:&b.vertexBuffer;
     data=kind==2?(!b.compactGroup.empty()?(const void*)b.compactGroup.data():(const void*)b.groupedVertices.data()):kind==1?(const void*)b.instances.data():(const void*)b.vertices.data();
     bytes=kind==2?b.groupedVertices.size()*(b.compactGroup.empty()?sizeof(V):sizeof(nadoc_vr::view_compact::Vertex)):kind==1?b.instances.size()*sizeof(Instance):b.vertices.size()*sizeof(V);}}
   const auto discardOptional=[&](const char* reason){if(optionalGroup)discardIndexedGroups(*optionalIndexed,reason);else discardIndexed(*optionalIndexed,reason);};
   const auto noteOptionalError=[&](GLenum error){if(optionalGroup)optionalIndexed->indexedGroupUploadGlError=error;else optionalIndexed->indexUploadGlError=error;};
   if(!bytes){++s.buffer;s.offset=0;continue;}
   if(!*buffer){glGenBuffers(1,buffer);
    if(optionalIndexed && !*buffer){noteOptionalError(glGetError());discardOptional("indexed_buffer_name_failed");++s.buffer;s.offset=0;continue;}
    glBindBuffer(GL_ARRAY_BUFFER,*buffer);glBufferData(GL_ARRAY_BUFFER,bytes,nullptr,GL_STREAM_DRAW);
    if(optionalIndexed){GLint allocated=0;glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&allocated);if(allocated!=int(bytes)){noteOptionalError(glGetError());discardOptional("indexed_buffer_allocation_failed");++s.buffer;s.offset=0;continue;}}
   }else glBindBuffer(GL_ARRAY_BUFFER,*buffer);
   const size_t n=std::min(size_t(256*1024),bytes-s.offset);if(n)glBufferSubData(GL_ARRAY_BUFFER,s.offset,n,(const char*)data+s.offset);
   // Only optional staged uploads inspect errors. A pre-existing error also
   // conservatively falls back, and its code remains visible in diagnostics.
   if(optionalIndexed){const auto error=glGetError();if(error!=GL_NO_ERROR){noteOptionalError(error);discardOptional("indexed_upload_gl_error");++s.buffer;s.offset=0;continue;}}
   s.offset+=n;
   if(s.offset==bytes){++s.buffer;s.offset=0;}
  }
  if(s.buffer==count&&!s.view.pixels.empty()&&glfwGetTime()-start<.001){
   if(!s.texture){glGenTextures(1,&s.texture);glBindTexture(GL_TEXTURE_2D,s.texture);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,s.view.header[6],s.view.header[7],0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);}
   glBindTexture(GL_TEXTURE_2D,s.texture);glPixelStorei(GL_UNPACK_ALIGNMENT,1);
   while(s.textureRow<s.view.header[7]&&glfwGetTime()-start<.001){const size_t rows=std::min(size_t(16),s.view.header[7]-s.textureRow);glTexSubImage2D(GL_TEXTURE_2D,0,0,s.textureRow,s.view.header[6],rows,GL_RGBA,GL_UNSIGNED_BYTE,s.view.pixels.data()+s.textureRow*s.view.header[6]*4);s.textureRow+=rows;}
  }
  s.uploadMs+=(glfwGetTime()-start)*1000;
  if(s.buffer==count&&(s.view.pixels.empty()||s.textureRow==s.view.header[7])){
   if(s.view.panelOnly){
    glDeleteTextures(1,&panelTexture);panelTexture=s.texture;
    version=s.view.header[1];acknowledged=s.view.header[9];if(acknowledged>=sequence)waiting=false;
    parseMs=s.view.parseMs;uploadMs=s.uploadMs;staging.reset();if(!continuous)return true;applied=true;
   }else{
   if(!s.view.transformsOnly){clearBatches();}
   glDeleteBuffers(1,&triangleVbo);glDeleteBuffers(1,&lineVbo);triangleVbo=s.triangles;lineVbo=s.lines;
   if(s.texture){if(s.view.panelPatch){glDeleteTextures(1,&panelTexture);panelTexture=s.texture;}else{glDeleteTextures(1,&texture);texture=s.texture;glDeleteTextures(1,&panelTexture);panelTexture=0;}}
   if(s.view.groupedAny || s.view.indexedGroupedAny){GLint active=0;glGetIntegerv(GL_ACTIVE_TEXTURE,&active);glActiveTexture(GL_TEXTURE0+nadoc_vr::view_groups::textureUnit);
    for(auto& b:s.view.batches)if((b.groupPlan.eligible && b.groupedVertexBuffer) || (b.indexedGroupPlan.eligible && b.indexedGroupVertexBuffer && b.indexedGroupIndexBuffer)){glGenTextures(1,&b.instanceTexture);GLint width=0,format=0,vertexBytes=0;
     if(b.groupPlan.eligible){glBindBuffer(GL_ARRAY_BUFFER,b.groupedVertexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&vertexBytes);}
     if(b.instanceTexture){glBindTexture(GL_TEXTURE_BUFFER,b.instanceTexture);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,b.instanceBuffer);glGetTexLevelParameteriv(GL_TEXTURE_BUFFER,0,GL_TEXTURE_WIDTH,&width);glGetTexLevelParameteriv(GL_TEXTURE_BUFFER,0,GL_TEXTURE_INTERNAL_FORMAT,&format);}
     const auto error=b.indexedGroupPlan.eligible?glGetError():GL_NO_ERROR;
     if((b.groupPlan.eligible && vertexBytes!=int(b.groupedVertices.size()*(b.compactGroup.empty()?sizeof(V):sizeof(nadoc_vr::view_compact::Vertex)))) || width!=int(b.instances.size()*5) || format!=GL_RGBA32F || error!=GL_NO_ERROR){if(b.instanceTexture)glDeleteTextures(1,&b.instanceTexture);b.instanceTexture=0;
      if(b.indexedGroupPlan.eligible){b.indexedGroupUploadGlError=error;discardIndexedGroups(b,"indexed_group_texture_incomplete");}
      if(b.groupPlan.eligible){glDeleteBuffers(1,&b.groupedVertexBuffer);b.groupedVertexBuffer=0;std::vector<V>().swap(b.groupedVertices);std::vector<nadoc_vr::view_compact::Vertex>().swap(b.compactGroup);b.groupPlan={false,"grouped_resource_incomplete"};}}}
    glActiveTexture(active);}
   if(s.view.indexedAny)for(auto& b:s.view.batches)if(b.indexPlan.eligible){GLint vertices=0,elements=0;
    if(b.indexedVertexBuffer){glBindBuffer(GL_ARRAY_BUFFER,b.indexedVertexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&vertices);}
    if(b.indexBuffer){glBindBuffer(GL_ARRAY_BUFFER,b.indexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&elements);}
    if(!nadoc_vr::view_indexed::resourcesComplete(b.indexPlan,sizeof(V),vertices,elements))discardIndexed(b,"indexed_resource_incomplete");}
   if(s.view.indexedGroupedAny)for(auto& b:s.view.batches)if(b.indexedGroupPlan.eligible){GLint vertices=0,elements=0;
    if(b.indexedGroupVertexBuffer){glBindBuffer(GL_ARRAY_BUFFER,b.indexedGroupVertexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&vertices);}
    if(b.indexedGroupIndexBuffer){glBindBuffer(GL_ARRAY_BUFFER,b.indexedGroupIndexBuffer);glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&elements);}
    if(!b.instanceTexture || !nadoc_vr::view_indexed::groupResourcesComplete(b.indexedGroupPlan,b.compactGroup.empty()?sizeof(V):sizeof(nadoc_vr::view_compact::Vertex),vertices,elements))discardIndexedGroups(b,"indexed_group_resource_incomplete");}
   opaqueEligibility=s.view.opaqueEligibility;
   if(s.view.transformsOnly){
    for(size_t i=0;i<batches.size();++i){auto& active=batches[i];auto& next=s.view.batches[i];
     active.spareInstanceBuffer=active.instanceBuffer;active.spareInstanceFence=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
     active.instanceBuffer=next.instanceBuffer;next.instanceBuffer=0;active.instances=std::move(next.instances);
     if(active.instanceTexture){glBindTexture(GL_TEXTURE_BUFFER,active.instanceTexture);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,active.instanceBuffer);}
    }++transformUpdateCount;
   }else{batches=std::move(s.view.batches);transformBase=s.view.transformBase;++fullSnapshotCount;}
   triangles=std::move(s.view.triangles);lines=std::move(s.view.lines);sprites=std::move(s.view.sprites);
   static const bool pipelineTrace=[] {const char* v=std::getenv("NADOC_VR_VIEW_PIPELINE");return v&&std::string_view(v)=="1";}();
   if(pipelineTrace)nadoc_vr::TraceRecord()<<std::fixed<<std::setprecision(6)<<"VR_VIEW_PIPELINE_NATIVE epoch_ms="<<std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count()<<" version="<<s.view.header[1]<<" transforms="<<s.view.transformsOnly<<" full_snapshots="<<fullSnapshotCount<<" transform_updates="<<transformUpdateCount<<" read_epoch_ms="<<s.view.readEpochMs<<" read_parse_ms="<<s.view.parseMs<<" upload_ms="<<s.uploadMs<<'\n';
   cachedSceneBounds=s.view.bounds;version=s.view.header[1];flags=s.view.header[2];acknowledged=s.view.header[9];if(acknowledged>=sequence)waiting=false;parseMs=s.view.parseMs;uploadMs=s.uploadMs;staging.reset();if(!continuous)return true;applied=true;
   }
  }
 }
 if(!reading.valid()&&!staging&&(continuous||++frames%3==0)){
  auto packet=inbox->take();
  // Once IPC is established, never reapply a stale legacy file between packets.
  if(packet || !inbox->received())reading=std::async(std::launch::async,[=,packet=std::move(packet),current=version,classifyOpaque=opaqueRequested,groupInstances=groupsAvailable(),limits=groupLimits,indexMeshes=indexedRequested,groupIndexedMeshes=indexedGroupsRequested&&groupsAvailable(),base=transformBase,compactMeshes=compactRequested]() mutable {return readView(path+".viewtools",current,center,scale,origin,classifyOpaque,groupInstances,limits,indexMeshes,groupIndexedMeshes,std::move(packet),base,compactMeshes);});
 }
 return applied;
}
void cancelStaging(){if(!staging)return;auto& s=*staging;for(auto& b:s.view.batches){if(b.indexedGroupVertexBuffer)glDeleteBuffers(1,&b.indexedGroupVertexBuffer);if(b.indexedGroupIndexBuffer)glDeleteBuffers(1,&b.indexedGroupIndexBuffer);if(b.indexedVertexBuffer)glDeleteBuffers(1,&b.indexedVertexBuffer);if(b.indexBuffer)glDeleteBuffers(1,&b.indexBuffer);if(b.vertexBuffer)glDeleteBuffers(1,&b.vertexBuffer);if(b.instanceTexture)glDeleteTextures(1,&b.instanceTexture);if(b.groupedVertexBuffer)glDeleteBuffers(1,&b.groupedVertexBuffer);if(b.instanceBuffer)glDeleteBuffers(1,&b.instanceBuffer);}if(s.triangles)glDeleteBuffers(1,&s.triangles);if(s.lines)glDeleteBuffers(1,&s.lines);if(s.texture)glDeleteTextures(1,&s.texture);staging.reset();}
