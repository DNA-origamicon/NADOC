    struct WarmPreview {
        // Declaration order ensures the worker finishes before GL ownership is
        // released, on the render thread. The worker never owns or calls GL.
        std::shared_ptr<ResidentRepresentation> resident;
        std::string token;
        std::future<RigidPreviewGeometry> result;
    };
    mutable std::unique_ptr<WarmPreview> warmPreview_;
#ifdef NADOC_SCRYWRITE_TESTING
    bool usedWarmPreviewForTest=false;
    bool warmPreviewReadyForTest() const {
        return warmPreview_ && warmPreview_->result.wait_for(std::chrono::seconds(0))==std::future_status::ready;
    }
#endif

    static RigidPreviewGeometry previewEdits(const PreparedRepresentation& prepared,
            const std::string& token) {
        RigidPreviewGeometry next;
        next.token=token;
        const auto owner=prepared.highlightOwners.find(token);
        if(owner==prepared.highlightOwners.end()) return {};
        for (auto [kind,row] : owner->second) {
            RigidPreviewGeometry::Weights weights{1,1};
            if (const auto* record=prepared.records[kind][row].ownership) {
                for (const auto& candidate : record->owners) {
                    if (candidate.token == next.token) {
                        weights={candidate.startWeight,candidate.endWeight};
                        break; // Explicit weights take precedence over an alias.
                    }
                }
            }
            if (weights.first == 0 && weights.second == 0) continue;
            auto add=[&](auto& channel){channel.edits.push_back({row,weights});};
            switch(kind) {case 0:add(next.points);break;case 1:add(next.cylinders);break;
                case 2:add(next.halves);break;case 3:add(next.boxes);break;}
        }
        return next;
    }
    static RigidPreviewGeometry fillPreview(const ResidentRepresentation& resident,
            RigidPreviewGeometry next) {
        const auto& prepared=*resident.prepared;
        // Only immutable, owning values are read on the worker. Prepared records
        // contain SceneData pointers and must never be dereferenced here.
        auto copy=[&](auto& channel,const auto& values,size_t kind) {
            channel.original=values;
            for(size_t row=0;row<values.size();++row) {
                channel.original[row].color=resident.colors[kind][row];
                channel.original[row].objectId=resident.objectIds[kind][row];
            }
        };
        copy(next.points,prepared.points,0); copy(next.cylinders,prepared.cylinders,1);
        copy(next.halves,prepared.halves,2); copy(next.boxes,prepared.boxes,3);
        next.finish();
        return next;
    }
    void warmResidentPreview(const std::string& token) const {
        if(warmPreview_) {
            if(warmPreview_->resident==activeResident_ && warmPreview_->token==token) return;
            // Never destroy a running future (which waits) on an interaction frame.
            if(warmPreview_->result.wait_for(std::chrono::seconds(0))!=std::future_status::ready) return;
            warmPreview_.reset();
        }
        if(!packedPreviewEnabled_ || previewGeometry_.active() || !selectionTintEnabled() ||
            !activeResident_ || stylePending() || !toolCommittedToken_.empty() ||
            !toolPreviewToken_.empty() || !visualizationPositions_.empty() ||
            !visualizationColors_.empty() || !visualizationSlabFrames_.empty() ||
            activeResident_->prepared!=scene_.prepared[static_cast<size_t>(representation_)]) return;
        auto next=previewEdits(*activeResident_->prepared,token);
        if(!next.active()) return;
        auto warm=std::make_unique<WarmPreview>();
        warm->resident=activeResident_; warm->token=token;
        const auto* resident=warm->resident.get();
        warm->result=std::async(std::launch::async,[resident,next=std::move(next)]() mutable {
            return fillPreview(*resident,std::move(next));
        });
        warmPreview_=std::move(warm);
    }
// First-grab cache construction from the displayed immutable representation.
// General visualization/committed-pose paths still use setStyle. Never modify
// a resident cache's GL buffers: detach before the first preview upload.
    bool prepareResidentPreview() {
#ifdef NADOC_SCRYWRITE_TESTING
        if (!residentPreviewForTest) return false;
#endif
        const bool supported = representation_ == Representation::full ||
            representation_ == Representation::stick || representation_ == Representation::ballstick ||
            representation_ == Representation::vdw;
        if (!packedPreviewEnabled_ || !supported || !selectionTintEnabled() ||
            !activeResident_ || stylePending() || toolPreviewToken_.empty() ||
            !toolCommittedToken_.empty() || !visualizationPositions_.empty() ||
            !visualizationColors_.empty() || !visualizationSlabFrames_.empty()) return false;
        const auto& prepared = *activeResident_->prepared;
        if (activeResident_->prepared != scene_.prepared[static_cast<size_t>(representation_)]) return false;
        const auto owner = prepared.highlightOwners.find(toolPreviewToken_);
        if (owner == prepared.highlightOwners.end()) return false;
        nadoc_vr::CalculationScope scope("prepareResidentPreview");
        RigidPreviewGeometry next;
        if(warmPreview_ && warmPreview_->resident==activeResident_ &&
            warmPreview_->token==toolPreviewToken_ &&
            warmPreview_->result.wait_for(std::chrono::seconds(0))==std::future_status::ready) {
#ifdef NADOC_SCRYWRITE_TESTING
            usedWarmPreviewForTest=true;
#endif
            next=warmPreview_->result.get();
            warmPreview_.reset();
        } else {
            next=fillPreview(*activeResident_,previewEdits(prepared,toolPreviewToken_));
        }
        detachResidentStyle();
        previewGeometry_ = std::move(next);
        // applyPackedPreview uploads edited channels. Seed only untouched ones
        // here, including zero-sized channels, into the detached buffer set.
        auto seed=[](const auto& channel,GLuint buffer){
            if (!channel.edits.empty()) return;
            glBindBuffer(GL_ARRAY_BUFFER,buffer);
            glBufferData(GL_ARRAY_BUFFER,channel.current.size()*sizeof(channel.current[0]),
                channel.current.data(),GL_STREAM_DRAW);
        };
        seed(previewGeometry_.points,sphereInstanceVbo_);
        seed(previewGeometry_.cylinders,cylinderInstanceVbo_);
        seed(previewGeometry_.halves,halfCylinderInstanceVbo_);
        seed(previewGeometry_.boxes,boxInstanceVbo_);
        atomisticBuffersResident_=false;
        return true;
    }
