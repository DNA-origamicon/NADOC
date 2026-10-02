// GlScene adapter: changed hover with an unchanged selection only changes glow
// geometry. Keep primary buffers and the weighted preview baseline intact.
#ifdef NADOC_SCRYWRITE_TESTING
    bool staticSnapHighlightsForTest = true;
#endif
    bool updateStaticSnapHighlights(bool selectionUnchanged,
        const std::unordered_set<std::string>& priorSnapTokens,
        const std::unordered_set<std::string>& priorSnapIdentities) {
#ifdef NADOC_SCRYWRITE_TESTING
        if (!staticSnapHighlightsForTest) return false;
#endif
        if (!selectionUnchanged || renderingVolumes_ ||
            !toolPreviewToken_.empty() || !toolCommittedToken_.empty() ||
            !visualizationPositions_.empty() || !visualizationColors_.empty() ||
            !visualizationSlabFrames_.empty() || stylePending()) return false;
        const auto& prepared=scene_.prepared[static_cast<size_t>(representation_)];
        if (!prepared || prepared->index.get()!=sourceIndex_ || !sourceIndexValid_) return false;
        nadoc_vr::CalculationScope auditScope("updateStaticSnapHighlights");
        std::array<std::vector<unsigned char>,4> masks;
        for(size_t i=0;i<4;++i)masks[i].resize(prepared->records[i].size());
        auto collect=[](auto& output,const auto& keys,const auto& index,unsigned char level){for(const auto& key:keys){
            if(const auto found=index.find(key);found!=index.end())
                for(const auto& [channel,row]:found->second)output[channel][row]=std::max(output[channel][row],level);
        }};
        collect(masks,selectedHighlightOwnerTokens_,prepared->highlightOwners,2);
        collect(masks,selectedHighlightIdentities_,prepared->highlightIdentities,2);
        auto previousMasks=masks;
        collect(previousMasks,priorSnapTokens,prepared->highlightOwners,1);
        collect(previousMasks,priorSnapIdentities,prepared->highlightIdentities,1);
        collect(masks,snapHighlightOwnerTokens_,prepared->highlightOwners,1);
        collect(masks,snapHighlightIdentities_,prepared->highlightIdentities,1);
        // A selected primitive stays green even when the hover changes. In that
        // common case the visible result and weighted glow cache are unchanged.
        if(masks==previousMasks)return true;
        auto build=[&](size_t channel,const auto& source,const auto& primary,auto& glow,GLuint buffer,GLsizei& count){
            using T=typename std::decay_t<decltype(source)>::value_type;
            std::vector<T> values;size_t edit=0;
            values.reserve(std::count_if(masks[channel].begin(),masks[channel].end(),[](auto value){return value!=0;}));
            glow={};if(previewGeometry_.active())glow.original.reserve(values.capacity());
            for(size_t row=0;row<source.size();++row){
                if(!masks[channel][row])continue;
                const auto color=masks[channel][row]==2?glm::vec3(.22F,1.F,.42F):glm::vec3(1.F,.68F,.12F);
                const auto& v=source[row];
                if constexpr(std::is_same_v<T,Vertex>)values.push_back({v.position,color,v.size*1.55F});
                else if constexpr(std::is_same_v<T,Cylinder>)values.push_back({v.start,v.end,v.radius*1.55F,color,0,v.endRadius<0?-1.F:v.endRadius*1.55F});
                else values.push_back({v.center,v.axisX*1.18F,v.axisY*1.18F,v.axisZ*1.18F,color});
                if(previewGeometry_.active()){
                    while(edit<primary.edits.size() && primary.edits[edit].index<row)++edit;
                    const auto weights=edit<primary.edits.size() && primary.edits[edit].index==row
                        ? primary.edits[edit].weights : RigidPreviewGeometry::Weights{0,0};
                    glow.add(values.back(),weights);
                }
            }
            if(previewGeometry_.active())glow.finish();
            glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferData(GL_ARRAY_BUFFER,values.size()*sizeof(T),values.data(),GL_DYNAMIC_DRAW);
            count=static_cast<GLsizei>(values.size());
        };
        build(0,prepared->points,previewGeometry_.points,previewGeometry_.glowPoints,sphereGlowInstanceVbo_,sphereGlowCount_);
        build(1,prepared->cylinders,previewGeometry_.cylinders,previewGeometry_.glowCylinders,cylinderGlowInstanceVbo_,cylinderGlowCount_);
        build(2,prepared->halves,previewGeometry_.halves,previewGeometry_.glowHalves,halfCylinderGlowInstanceVbo_,halfCylinderGlowCount_);
        build(3,prepared->boxes,previewGeometry_.boxes,previewGeometry_.glowBoxes,boxGlowInstanceVbo_,boxGlowCount_);
        return true;
    }
