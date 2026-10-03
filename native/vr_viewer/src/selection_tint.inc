// Selection is a byte per rendered instance, independent of resident geometry,
// scientific colors, picking IDs and the packed tool-preview buffers.
#ifdef NADOC_SCRYWRITE_TESTING
    bool selectionTintForTest = true;
#endif
    bool selectionTintEnabled() const {
#ifdef NADOC_SCRYWRITE_TESTING
        return selectionTintForTest;
#else
        return true;
#endif
    }
    mutable bool selectionTintDirty_ = true;
    mutable bool selectionCornersDirty_ = true;
    bool dynamicSelectionRows_ = false;
    std::array<std::vector<const std::string*>,4> selectionRows_;
    mutable std::array<GLuint,4> selectionBuffers_{}, selectionTextures_{};
    mutable std::array<std::vector<unsigned char>,4> selectionMasks_;
    struct SelectionCorners {
        std::string token;
        glm::vec3 low, high;
    };
    mutable std::vector<SelectionCorners> selectionCorners_;

    void updateSelectionTint() const {
        if (!selectionTintEnabled() || (!selectionTintDirty_ && !selectionCornersDirty_)) return;
        const auto& prepared = scene_.prepared[static_cast<size_t>(representation_)];
        if (selectionTintDirty_) {
            selectionTintDirty_ = false;
            const std::array<size_t,4> counts{size_t(sphereCount_),size_t(cylinderCount_),
                size_t(halfCylinderCount_),size_t(boxCount_)};
            for(size_t c=0;c<4;++c) selectionMasks_[c].assign(counts[c],0);
            if (prepared && !dynamicSelectionRows_ && visualizationPositions_.empty()) {
                auto collect=[&](const auto& keys,const auto& index,unsigned char level) {
                    for(const auto& key:keys) if(auto it=index.find(key);it!=index.end())
                        for(auto [channel,row]:it->second) if(row<selectionMasks_[channel].size())
                            selectionMasks_[channel][row]=std::max(selectionMasks_[channel][row],level);
                };
                collect(snapHighlightOwnerTokens_,prepared->highlightOwners,1);
                collect(snapHighlightIdentities_,prepared->highlightIdentities,1);
                collect(selectedHighlightOwnerTokens_,prepared->highlightOwners,2);
                collect(selectedHighlightIdentities_,prepared->highlightIdentities,2);
            } else if(sourceIndex_) {
                // Shared atomistic-buffer restores can omit unavailable endpoints.
                // Reconstruct their row order only when no fresh style-build rows exist.
                std::array<std::vector<const std::string*>,4> restoredRows;
                const auto* rows=&selectionRows_;
                if(!dynamicSelectionRows_) {
                    const auto& source=currentSource();
                    for(const auto& v:source.points)
                        if(!v.identity.starts_with("atom-ref:") || hasCompleteVisualizationAtomEndpoints(source,v.identity))
                            restoredRows[0].push_back(&v.identity);
                    for(const auto& v:source.cylinders)
                        if(representationCylinderVisible(representation_,v.identity) &&
                           (!v.identity.starts_with("atom-bond-ref:") || hasCompleteVisualizationAtomEndpoints(source,v.identity)))
                            restoredRows[1].push_back(&v.identity);
                    for(const auto& v:source.halfCylinders)restoredRows[2].push_back(&v.identity);
                    for(const auto& v:source.boxes)if(representationBoxVisible(representation_,v.identity))restoredRows[3].push_back(&v.identity);
                    rows=&restoredRows;
                }
                auto matches=[&](const std::string& id,const auto& tokens,const auto& ids) {
                    if(ids.contains(id))return true;
                    if(tokens.empty())return false;
                    if(auto it=sourceIndex_->aliases.find(id);it!=sourceIndex_->aliases.end())
                        for(const auto& token:it->second->tokens)if(tokens.contains(token))return true;
                    if(auto it=sourceIndex_->ownership.find(id);it!=sourceIndex_->ownership.end())
                        for(const auto& owner:it->second->owners)
                            if((owner.startWeight>0 || owner.endWeight>0) && tokens.contains(owner.token))return true;
                    return false;
                };
                for(size_t c=0;c<4;++c)for(size_t i=0;i<(*rows)[c].size() && i<counts[c];++i) {
                    const auto& id=*(*rows)[c][i];
                    selectionMasks_[c][i]=matches(id,selectedHighlightOwnerTokens_,selectedHighlightIdentities_)?2:
                        matches(id,snapHighlightOwnerTokens_,snapHighlightIdentities_)?1:0;
                }
            }
            if(!selectionBuffers_[0]) {
                glGenBuffers(4,selectionBuffers_.data());glGenTextures(4,selectionTextures_.data());
            }
            for(size_t c=0;c<4;++c) {
                const unsigned char empty=0;
                glBindBuffer(GL_TEXTURE_BUFFER,selectionBuffers_[c]);
                glBufferData(GL_TEXTURE_BUFFER,std::max(size_t(1),counts[c]),
                    counts[c]?selectionMasks_[c].data():&empty,GL_DYNAMIC_DRAW);
                glActiveTexture(GL_TEXTURE6);glBindTexture(GL_TEXTURE_BUFFER,selectionTextures_[c]);
                glTexBuffer(GL_TEXTURE_BUFFER,GL_R8UI,selectionBuffers_[c]);
            }
            glActiveTexture(GL_TEXTURE0);
        }
        if(!selectionCornersDirty_)return;
        selectionCornersDirty_=false;
        selectionCorners_.clear();
        if(!prepared)return;
        const auto& source=currentSource();
        const bool staticPose=visualizationPositions_.empty() && visualizationSlabFrames_.empty();
        for(const auto& handle:source.ownerHandles) {
            if(!selectedHighlightOwnerTokens_.contains(handle.token))continue;
            auto found=prepared->highlightOwners.find(handle.token);
            if(found==prepared->highlightOwners.end())continue;
            glm::vec3 low(std::numeric_limits<float>::max()),high(std::numeric_limits<float>::lowest());
            auto include=[&](glm::vec3 point,float radius){low=glm::min(low,point-glm::vec3(radius));high=glm::max(high,point+glm::vec3(radius));};
            for(auto [channel,row]:found->second) {
                const auto& id=*prepared->records[channel][row].identity;
                auto point=[&](glm::vec3 v,bool end=false){if(staticPose)return v; const auto offsets=visualizationOffsets(source,id); return v+(end?offsets.second:offsets.first);};
                if(channel==0){const auto& v=prepared->points[row];include(point(v.position),v.size);}
                else if(channel==1 || channel==2){const auto& v=channel==1?prepared->cylinders[row]:prepared->halves[row];include(point(v.start),v.radius);include(point(v.end,true),std::max(v.radius,v.endRadius));}
                else {const auto& v=prepared->boxes[row];for(int k=0;k<8;++k)
                    include(point(v.center+float(k&1?1:-1)*v.axisX+float(k&2?1:-1)*v.axisY+float(k&4?1:-1)*v.axisZ),0);}
            }
            if(low.x<=high.x) {
                const float pad=std::max(glm::length(high-low)*.015F,.002F);
                selectionCorners_.push_back({handle.token,low-glm::vec3(pad),high+glm::vec3(pad)});
            }
        }
    }
    void bindSelectionTint(GLuint program,size_t channel) const {
        glActiveTexture(GL_TEXTURE6);glBindTexture(GL_TEXTURE_BUFFER,selectionTextures_[channel]);
        glUniform1i(glGetUniformLocation(program,"uSelectionState"),6);
        glUniform1i(glGetUniformLocation(program,"uSelectionCount"),selectionTintEnabled()?int(selectionMasks_[channel].size()):0);
        glActiveTexture(GL_TEXTURE0);
    }
    void renderSelectionCorners(const glm::mat4& vp,const glm::mat4& model) const {
        if(!selectionTintEnabled())return;
        std::vector<Vertex> lines;
        lines.reserve(selectionCorners_.size()*48);
        for(const auto& bounds:selectionCorners_) {
            auto transform=model;
            if(bounds.token==toolPreviewToken_) transform*=toolPreviewTransform_;
            if(bounds.token==toolCommittedToken_) transform*=toolCommittedTransform_;
            const auto extent=(bounds.high-bounds.low)*.16F;
            for(int k=0;k<8;++k) {
                glm::vec3 corner(k&1?bounds.high.x:bounds.low.x,k&2?bounds.high.y:bounds.low.y,k&4?bounds.high.z:bounds.low.z);
                for(int axis=0;axis<3;++axis) {
                    auto end=corner;end[axis]+=(k&(1<<axis)?-1:1)*extent[axis];
                    for(auto p:{corner,end})lines.push_back({glm::vec3(transform*glm::vec4(p,1)),{.22F,1.F,.42F},1});
                }
            }
        }
        // One small batch per eye, independent of the selected atom count.
        renderGuides(vp,lines,nullptr,2.F,false);
    }
