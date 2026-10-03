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
        next.token = toolPreviewToken_;
        // The prepared rows already encode representation filtering, radii,
        // normals and ordering. Only style color and stable IDs were late-bound.
        auto copy = [&](auto& channel, const auto& values, size_t kind) {
            channel.original = values;
            const auto& records = prepared.records[kind];
            for (size_t row=0; row<values.size(); ++row) {
                channel.original[row].color = records[row].colors->get(coloring_);
                channel.original[row].objectId = objectId(*records[row].identity);
            }
        };
        copy(next.points, prepared.points, 0);
        copy(next.cylinders, prepared.cylinders, 1);
        copy(next.halves, prepared.halves, 2);
        copy(next.boxes, prepared.boxes, 3);
        for (auto [kind,row] : owner->second) {
            const auto& id = *prepared.records[kind][row].identity;
            RigidPreviewGeometry::Weights weights{1,1};
            if (auto record=prepared.index->ownership.find(id); record!=prepared.index->ownership.end()) {
                for (const auto& candidate : record->second->owners) {
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
        // An identity may appear in both the ownership and alias indexes.
        auto unique=[](auto& channel){
            auto& edits=channel.edits;
            std::sort(edits.begin(),edits.end(),[](const auto& a,const auto& b){return a.index<b.index;});
            edits.erase(std::unique(edits.begin(),edits.end(),[](const auto& a,const auto& b){return a.index==b.index;}),edits.end());
        };
        unique(next.points);unique(next.cylinders);unique(next.halves);unique(next.boxes);
        next.finish();
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
