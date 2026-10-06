// GlScene adapter for CPU-prepared, budgeted static representation activation.
private:
    bool deferStyles_=false;
    std::array<bool,kRepresentationCount> pinnedSources_{};
    Representation stagedTarget_=Representation::full;
    Coloring stagedColor_=Coloring::strand;
    StagedRepresentation stagedStyle_;
    std::shared_ptr<ResidentRepresentation> activeResident_;
    std::array<std::shared_ptr<ResidentRepresentation>,kRepresentationCount> residentStyles_{};
    void bindResidentAttributes() {
        using nadoc_vr::bindInstanceAttribute;
        auto attribute=[](GLuint vao,GLuint buffer,GLuint at,int count,int stride,size_t offset){
            nadoc_vr::bindInstanceAttribute(vao,buffer,at,count,stride,offset);
        };
        attribute(sphereVao_,sphereInstanceVbo_,1,3,sizeof(Vertex),offsetof(Vertex,position));
        attribute(sphereVao_,sphereInstanceVbo_,2,1,sizeof(Vertex),offsetof(Vertex,size));
        attribute(sphereVao_,sphereInstanceVbo_,3,3,sizeof(Vertex),offsetof(Vertex,color));
        for(auto [vao,buffer]:{std::pair{cylinderVao_,cylinderInstanceVbo_},std::pair{atomisticBondVao_,cylinderInstanceVbo_},std::pair{halfCylinderVao_,halfCylinderInstanceVbo_}}){
            attribute(vao,buffer,1,3,sizeof(Cylinder),offsetof(Cylinder,start));
            attribute(vao,buffer,2,3,sizeof(Cylinder),offsetof(Cylinder,end));
            attribute(vao,buffer,3,1,sizeof(Cylinder),offsetof(Cylinder,radius));
            attribute(vao,buffer,4,3,sizeof(Cylinder),offsetof(Cylinder,color));
            attribute(vao,buffer,6,1,sizeof(Cylinder),offsetof(Cylinder,endRadius));
        }
        for(auto [at,offset]:{std::pair{1,offsetof(Box,center)},std::pair{2,offsetof(Box,axisX)},std::pair{3,offsetof(Box,axisY)},std::pair{4,offsetof(Box,axisZ)},std::pair{6,offsetof(Box,color)}})
            attribute(boxVao_,boxInstanceVbo_,at,3,sizeof(Box),offset);
        for(int i=0;i<3;++i)attribute(boxVao_,boxInstanceVbo_,8+i,3,sizeof(Box),offsetof(Box,normals)+i*sizeof(glm::vec3));
        auto ids=[](GLuint vao,GLuint buffer,int stride,size_t offset){
            glBindVertexArray(vao);glBindBuffer(GL_ARRAY_BUFFER,buffer);glEnableVertexAttribArray(7);
            glVertexAttribIPointer(7,1,GL_UNSIGNED_INT,stride,reinterpret_cast<void*>(offset));glVertexAttribDivisor(7,1);
        };
        ids(sphereVao_,sphereInstanceVbo_,sizeof(Vertex),offsetof(Vertex,objectId));
        ids(cylinderVao_,cylinderInstanceVbo_,sizeof(Cylinder),offsetof(Cylinder,objectId));
        ids(atomisticBondVao_,cylinderInstanceVbo_,sizeof(Cylinder),offsetof(Cylinder,objectId));
        ids(halfCylinderVao_,halfCylinderInstanceVbo_,sizeof(Cylinder),offsetof(Cylinder,objectId));
        ids(boxVao_,boxInstanceVbo_,sizeof(Box),offsetof(Box,objectId));glBindVertexArray(0);
    }
    void activateResident(std::shared_ptr<ResidentRepresentation> resident,Representation rep,Coloring color) {
        if(!activeResident_){const std::array<GLuint,4> old{sphereInstanceVbo_,cylinderInstanceVbo_,halfCylinderInstanceVbo_,boxInstanceVbo_};glDeleteBuffers(4,old.data());}
        selectionTintDirty_=true; dynamicSelectionRows_=false;
        activeResident_=std::move(resident);
        const auto& b=activeResident_->buffers;const auto& n=activeResident_->counts;
        sphereInstanceVbo_=b[0];cylinderInstanceVbo_=b[1];halfCylinderInstanceVbo_=b[2];boxInstanceVbo_=b[3];
        sphereCount_=n[0];cylinderCount_=n[1];halfCylinderCount_=n[2];boxCount_=n[3];
        sphereGlowCount_=cylinderGlowCount_=halfCylinderGlowCount_=boxGlowCount_=0;
        representation_=rep;coloring_=color;localCenter_=activeResident_->prepared->center;localRadius_=activeResident_->prepared->radius;
        prepareDisplayedSource();ensureSourceIndex(currentSource());bindResidentAttributes();
        atomisticBuffersResident_=false;uploadedVisualizationRevision_=visualizationRevision_;
    }
    void detachResidentStyle() {
        if(!activeResident_)return;
        std::array<GLuint,4> b{};glGenBuffers(4,b.data());
        sphereInstanceVbo_=b[0];cylinderInstanceVbo_=b[1];halfCylinderInstanceVbo_=b[2];boxInstanceVbo_=b[3];
        activeResident_.reset();bindResidentAttributes();
    }
    void requestPreparedStyle(Representation rep,Coloring color) {
        if(stagedStyle_.pending() && stagedTarget_==rep && stagedColor_==color)return;
        stagedStyle_.cancel();stagedTarget_=rep;stagedColor_=color;
        auto& resident=residentStyles_[static_cast<size_t>(rep)];
        if(resident && resident->color==color){activateResident(resident,rep,color);return;}
        // Keep at most 256 MiB of inactive GPU geometry, plus the active scene and
        // one pending representation. Eviction never copies GPU storage.
        size_t bytes=0;for(const auto& entry:residentStyles_)if(entry && entry!=activeResident_)bytes+=entry->prepared->bytes();
        if(bytes+scene_.prepared[static_cast<size_t>(rep)]->bytes()>256*1024*1024)
            for(auto& entry:residentStyles_)if(entry!=activeResident_)entry.reset();
        stagedStyle_.start(scene_.prepared[static_cast<size_t>(rep)],color);
    }
public:
    void trimPreparedCache(SceneRetirement& retired,size_t budget=512*1024*1024){
        if(retired.full() || stagedStyle_.pending() || !visualizationPositions_.empty() ||
            !toolPreviewToken_.empty() || !toolCommittedToken_.empty())return;
        const auto current=representationSourceIndex(representation_);
        size_t bytes=0,victim=kRepresentationCount,largest=0;
        for(size_t i=0;i<kRepresentationCount;++i){
            if(i==current || i==size_t(Representation::full) || pinnedSources_[i])continue;
            bytes+=scene_.cpuBytes[i];
            if(scene_.cpuBytes[i]>largest && !staticSourceIndices_.contains(&scene_.representations[i])){
                largest=scene_.cpuBytes[i];victim=i;
            }
        }
        if(bytes<=budget || victim==kRepresentationCount)return;
        SceneData obsolete;
        obsolete.representations[victim]=std::move(scene_.representations[victim]);
        scene_.cpuBytes[victim]=0;
        for(size_t i=0;i<kRepresentationCount;++i)if(representationSourceIndex(static_cast<Representation>(i))==victim){
            residentStyles_[i].reset();representationBuffers_.invalidate(i);
            obsolete.prepared[i]=std::move(scene_.prepared[i]);scene_.available[i]=false;
        }
        retired.retire(std::move(obsolete));
        nadoc_vr::TraceRecord{}<<"VR_CACHE_RETIRE source="<<victim<<" estimated_bytes="<<largest<<'\n';
    }
    void installInitialScene(SceneData incoming){
        // The empty startup shell exposes authoring controls for all styles; its
        // availability and zero-sized caches are not loaded model geometry.
        scene_.available.fill(false);representationBuffers_.clear();
        scene_.normalizationCenter=incoming.normalizationCenter;scene_.normalizationScale=incoming.normalizationScale;
        scene_.extrudePlane=incoming.extrudePlane;scene_.emptyAuthoring=incoming.emptyAuthoring;
        installRepresentation(std::move(incoming));
    }
    void enablePreparedStyles(){deferStyles_=true;}
    bool stylePending()const{return stagedStyle_.pending();}
    double styleProgress()const{return stagedStyle_.progress();}
    void cancelPreparedStyle(){stagedStyle_.cancel();}
    void pollPreparedStyle(){
        if(auto ready=stagedStyle_.poll([this](const std::string& id){return objectId(id);})){
            residentStyles_[static_cast<size_t>(stagedTarget_)]=ready;
            activateResident(std::move(ready),stagedTarget_,stagedColor_);
        }
    }
