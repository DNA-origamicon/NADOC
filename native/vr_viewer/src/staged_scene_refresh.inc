// Reuse the renderer and its stable object-ID registry across topology revisions.
// The old scene remains authoritative for drawing and picking until the fence
// completes. CPU-only obsolete data is released by the retirement worker.
private:
    std::optional<SceneData> refreshingScene_;
    StagedRepresentation refreshingStyle_;
    std::shared_ptr<ResidentRepresentation> refreshingResident_;
    Representation refreshingTarget_=Representation::full;
    Coloring refreshingColor_=Coloring::strand;
public:
    void beginSceneRefresh(SceneData scene) {
        if(refreshingScene_)throw std::runtime_error("Scene refresh already pending");
        refreshingScene_.emplace(std::move(scene));
    }
    SceneData takeSceneRefresh() {
        refreshingStyle_.cancel();refreshingResident_.reset();
        SceneData result=std::move(refreshingScene_.value());refreshingScene_.reset();
        return result;
    }
    bool canStageSceneRefresh(const nadoc_vr::VisualizationSnapshot& snapshot) const {
        const auto rep=snapshot.representation.empty() || snapshot.coloring.empty()
            ? representation_:representationFromName(snapshot.representation);
        return refreshingScene_ && snapshot.points.empty() &&
            bool(refreshingScene_->prepared[static_cast<size_t>(rep)]);
    }
    bool advanceSceneRefresh(const nadoc_vr::VisualizationSnapshot& snapshot,
                             SceneRetirement& retired,double budgetMs=1.0) {
        nadoc_vr::CalculationScope scope("stageSceneRefresh");
        if(!canStageSceneRefresh(snapshot))throw std::runtime_error("Refresh requires visualization fallback");
        const bool explicitStyle=!snapshot.representation.empty() && !snapshot.coloring.empty();
        const auto rep=explicitStyle?representationFromName(snapshot.representation):representation_;
        const auto color=explicitStyle?coloringFromName(snapshot.coloring):coloring_;
        if((!refreshingStyle_.pending() && !refreshingResident_) ||
                rep!=refreshingTarget_ || color!=refreshingColor_) {
            refreshingResident_.reset();refreshingTarget_=rep;refreshingColor_=color;
            refreshingStyle_.start(refreshingScene_->prepared[static_cast<size_t>(rep)],color);
        }
        if(!refreshingResident_)refreshingResident_=refreshingStyle_.poll(
            [this](const std::string& id){return objectId(id);},budgetMs);
        if(!refreshingResident_ || retired.full())return false;

        nadoc_vr::CalculationScope activation("activateSceneRefresh");
        // All potentially large CPU containers move in constant time. Keep the
        // old source alive until its borrowing indexes/resident refs are dropped.
        auto obsolete=std::make_tuple(std::move(scene_),std::move(staticSourceIndices_),
            std::move(previewGeometry_),std::move(committedHandleOffsets_),
            std::move(atomisticSphereInstances_),std::move(atomisticCylinderInstances_),
            std::move(atomisticSphereCoordinateIndices_),std::move(atomisticCylinderCoordinateIndices_),
            std::move(visualizationPositions_),std::move(visualizationColors_),
            std::move(visualizationSlabFrames_),std::move(visualizationAtomTokens_),
            std::move(visualizationCoordinateIndex_),std::move(visualizationCoordinateTokens_),
            std::move(visualizationCoordinatePositions_),std::move(normalizedCoordinateScratch_),
            std::move(visualizationDeltas_),std::move(selectionRows_));
        scene_=std::move(*refreshingScene_);refreshingScene_.reset();
        cancelPreparedStyle();representationBuffers_.clear();
        for(auto& resident:residentStyles_)resident.reset();
        // Swapping the active resident releases GL buffers on this thread only.
        // activateResident preserves the previous resident until rebinding.
        toolPreviewToken_.clear();toolCommittedToken_.clear();
        toolPreviewTransform_=toolCommittedTransform_=glm::mat4(1);
        previewGeometry_=RigidPreviewGeometry{};
        displayedSource_=nullptr;displayedSourceValid_=sourceIndexValid_=false;
        sourceIndex_=nullptr;visualizationDeltasValid_=false;
        visualizationMode_=snapshot.mode;++visualizationRevision_;
        cachedAtomisticVisualizationRevision_=std::numeric_limits<uint64_t>::max();
        atomisticBuffersResident_=false;ballstickSphereCount_=0;
        // Static resident representations share their own prepared geometry;
        // no full-scene equivalence scan is needed for the streaming fast path.
        atomisticSharedGeometry_=scene_.preparedAtomisticSharedGeometry.value_or(false);pinnedSources_.fill(false);
        residentStyles_[static_cast<size_t>(rep)]=refreshingResident_;
        activateResident(std::move(refreshingResident_),rep,color);
        retired.retire(std::move(obsolete));
        return true;
    }
