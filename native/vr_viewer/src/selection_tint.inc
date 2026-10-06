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
    bool dynamicSelectionRows_ = false;
    std::array<std::vector<const std::string*>,4> selectionRows_;
    mutable std::array<GLuint,4> selectionBuffers_{}, selectionTextures_{};
    mutable std::array<std::vector<unsigned char>,4> selectionMasks_;
    void updateSelectionTint() const {
        if (!selectionTintEnabled() || !selectionTintDirty_) return;
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
    }
    void bindSelectionTint(GLuint program,size_t channel) const {
        glActiveTexture(GL_TEXTURE6);glBindTexture(GL_TEXTURE_BUFFER,selectionTextures_[channel]);
        glUniform1i(glGetUniformLocation(program,"uSelectionState"),6);
        glUniform1i(glGetUniformLocation(program,"uSelectionCount"),selectionTintEnabled()?int(selectionMasks_[channel].size()):0);
        glActiveTexture(GL_TEXTURE0);
    }
