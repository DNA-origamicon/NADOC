// Exact shadow reuse for immutable resident or versioned packed-preview buffers.
// Layout callbacks and visualization mutations always take the ordinary path.
    uint64_t shadowGeometryRevision_=0,shadowCachedRevision_=0;
    bool shadowCacheValid_=false,shadowCachedPacked_=false;
    std::weak_ptr<ResidentRepresentation> shadowCachedResident_;
    glm::mat4 shadowCachedModel_{1},shadowCachedProjection_{1};
    GLsizei shadowCachedCylinderCount_=0,shadowCachedBoxCount_=0;
    const void* shadowCachedCylinderOffset_=nullptr;
    const void* shadowCachedBoxOffset_=nullptr;
#ifdef NADOC_SCRYWRITE_TESTING
    bool shadowCacheEnabledForTest=true;
    size_t shadowDrawsForTest=0,shadowReusesForTest=0;
#endif
    bool reusePreparedShadow(const glm::mat4& model,bool ordinary) {
#ifdef NADOC_SCRYWRITE_TESTING
        ordinary=ordinary && shadowCacheEnabledForTest;
#endif
        const bool resident=bool(activeResident_);
        const bool packed=!resident && previewGeometry_.active();
        const bool eligible=ordinary && (resident || packed) &&
            visualizationPositions_.empty() && visualizationColors_.empty() && visualizationSlabFrames_.empty();
        const bool sameGeometry=resident
            ? !shadowCachedPacked_ && shadowCachedResident_.lock()==activeResident_
            : packed && shadowCachedPacked_;
        const bool hit=eligible && shadowCacheValid_ && sameGeometry &&
            shadowCachedRevision_==shadowGeometryRevision_ &&
            shadowCachedModel_==model && shadowCachedProjection_==lightViewProjection_ &&
            shadowCachedCylinderCount_==motionCylinderCount() && shadowCachedCylinderOffset_==motionCylinderOffset() &&
            shadowCachedBoxCount_==boxDrawCount() && shadowCachedBoxOffset_==boxDrawOffset();
        if(hit) {
#ifdef NADOC_SCRYWRITE_TESTING
            ++shadowReusesForTest;
#endif
            return true;
        }
        shadowCacheValid_=eligible;
        shadowCachedPacked_=packed;shadowCachedResident_=activeResident_;
        shadowCachedRevision_=shadowGeometryRevision_;
        shadowCachedModel_=model;shadowCachedProjection_=lightViewProjection_;
        shadowCachedCylinderCount_=motionCylinderCount();shadowCachedCylinderOffset_=motionCylinderOffset();
        shadowCachedBoxCount_=boxDrawCount();shadowCachedBoxOffset_=boxDrawOffset();
        return false;
    }
