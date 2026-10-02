#pragma once
// CPU-only preparation. Included after scene primitive types. All referenced
// records live in SceneData; moving its vectors preserves their element addresses.
struct SourceIndex {
        nadoc_vr::SelectionOwnerIndex selectionOwners;
        std::unordered_map<std::string_view, const TransformOwnership*> ownership;
        std::unordered_map<std::string_view, const nadoc_vr::OwnerAliasEntry*> aliases;
        std::unordered_map<std::string_view, const ToolHandle*> toolHandles;

        void rebuild(const RepresentationData& source) {
            selectionOwners.reset(source.ownerAliases);
            for (const auto& handle : source.toolHandles) selectionOwners.addKind(handle.token, handle.kind);
            for (const auto& handle : source.ownerHandles) selectionOwners.addKind(handle.token, "cluster");
            ownership.clear();
            aliases.clear();
            toolHandles.clear();
            const auto& records = source.toolScopeOwnership.empty()
                ? source.transformOwnership : source.toolScopeOwnership;
            ownership.reserve(records.size());
            aliases.reserve(source.ownerAliases.size());
            toolHandles.reserve(source.toolHandles.size());
            for (const TransformOwnership& record : records) {
                ownership.emplace(record.identity, &record);
            }
            for (const nadoc_vr::OwnerAliasEntry& entry : source.ownerAliases) {
                aliases.emplace(entry.identity, &entry);
            }
            for (const ToolHandle& handle : source.toolHandles) {
                toolHandles.try_emplace(handle.token, &handle);
            }
        }
    };


struct PreparedRepresentation {
    struct Record { const std::string* identity; const ColorSet* colors; };
    std::vector<Vertex> points;
    std::vector<Cylinder> cylinders, halves;
    std::vector<Box> boxes;
    std::array<std::vector<Record>,4> records;
    using PrimitiveRef = std::pair<size_t,size_t>;
    std::unordered_map<std::string_view,std::vector<PrimitiveRef>> highlightOwners, highlightIdentities;
    size_t highlightIndexBytes() const {
        size_t bytes=0;
        for(const auto* map:{&highlightOwners,&highlightIdentities}) {
            bytes+=map->bucket_count()*sizeof(void*)+map->size()*80;
            for(const auto& [key,refs]:*map)bytes+=refs.capacity()*sizeof(PrimitiveRef);
        }
        return bytes;
    }
    void indexHighlights() {
        for(size_t channel=0;channel<records.size();++channel)for(size_t row=0;row<records[channel].size();++row) {
            const auto& identity=*records[channel][row].identity;
            const PrimitiveRef ref{channel,row};highlightIdentities[identity].push_back(ref);
            if(const auto alias=index->aliases.find(identity);alias!=index->aliases.end())
                for(const auto& token:alias->second->tokens)highlightOwners[token].push_back(ref);
            if(const auto owners=index->ownership.find(identity);owners!=index->ownership.end())
                for(const auto& owner:owners->second->owners)
                    if(owner.startWeight>0 || owner.endWeight>0)highlightOwners[owner.token].push_back(ref);
        }
    }
    std::shared_ptr<SourceIndex> index;
    glm::vec3 center{};
    float radius=.5F;
    size_t bytes() const {return points.size()*sizeof(Vertex)+(cylinders.size()+halves.size())*sizeof(Cylinder)+boxes.size()*sizeof(Box);}
};
inline std::shared_ptr<PreparedRepresentation> prepareStaticRepresentation(
        const RepresentationData& source, Representation rep,
        std::shared_ptr<SourceIndex> index) {
    auto p=std::make_shared<PreparedRepresentation>();p->index=std::move(index);
    glm::vec3 lo(std::numeric_limits<float>::max()),hi(std::numeric_limits<float>::lowest());
    auto include=[&](glm::vec3 v,float r=0){lo=glm::min(lo,v-glm::vec3(r));hi=glm::max(hi,v+glm::vec3(r));};
    p->points.reserve(source.points.size());p->cylinders.reserve(source.cylinders.size());
    p->halves.reserve(source.halfCylinders.size());p->boxes.reserve(source.boxes.size());
    for(const auto& v:source.points) {
        const float radius=representationPointRadius(rep,v);
        p->points.push_back({v.position,{},radius,0});p->records[0].push_back({&v.identity,&v.colors});include(v.position,radius);
    }
    auto cylinders=[&](const auto& source,auto& dest,size_t channel){for(const auto& v:source){
        if(channel==1 && !representationCylinderVisible(rep,v.identity))continue;
        dest.push_back({v.start,v.end,v.radius,{},0,v.endRadius});p->records[channel].push_back({&v.identity,&v.colors});
        include(v.start,v.radius);include(v.end,v.radius);
    }};
    cylinders(source.cylinders,p->cylinders,1);cylinders(source.halfCylinders,p->halves,2);
    for(const auto& v:source.boxes){if(!representationBoxVisible(rep,v.identity))continue;
        p->boxes.push_back({v.center,v.axisX,v.axisY,v.axisZ,{},0,v.normals});p->records[3].push_back({&v.identity,&v.colors});
        nadoc_vr::includeMeshBounds(p->boxes.back(),include);
    }
    if(p->bytes()){p->center=(lo+hi)*.5F;p->radius=std::max(glm::length(hi-lo)*.5F,.01F);}
    else p->center={0,0,-kViewDistanceMeters};
    p->indexHighlights();
    return p;
}

// Conservative retained CPU estimate, evaluated only by the parsing worker.
// Includes semantic strings/owners and hash-node overhead, not only GL vertices.
inline size_t representationCpuBytes(const RepresentationData& source){
    size_t bytes=0;
    auto primitives=[&](const auto& values){bytes+=values.capacity()*sizeof(typename std::decay_t<decltype(values)>::value_type);
        for(const auto& value:values)bytes+=value.identity.capacity()+1;};
    primitives(source.points);primitives(source.cylinders);primitives(source.halfCylinders);primitives(source.boxes);
    bytes+=source.ownerHandles.capacity()*sizeof(OwnerHandle);
    for(const auto& v:source.ownerHandles)bytes+=v.token.capacity()+1;
    bytes+=source.toolHandles.capacity()*sizeof(ToolHandle);
    for(const auto& v:source.toolHandles)bytes+=v.id.capacity()+v.token.capacity()+v.kind.capacity()+3;
    bytes+=source.ownerAliases.capacity()*sizeof(nadoc_vr::OwnerAliasEntry);
    for(const auto& v:source.ownerAliases){bytes+=v.identity.capacity()+1+v.tokens.capacity()*sizeof(std::string);for(const auto& token:v.tokens)bytes+=token.capacity()+1;}
    for(const auto* records:{&source.transformOwnership,&source.toolScopeOwnership}){
        bytes+=records->capacity()*sizeof(TransformOwnership);
        for(const auto& v:*records){bytes+=v.identity.capacity()+1+v.owners.capacity()*sizeof(TransformOwner);for(const auto& owner:v.owners)bytes+=owner.token.capacity()+1;}
    }
    bytes+=64*(source.toolHandles.size()+source.ownerAliases.size()+source.transformOwnership.size()+source.toolScopeOwnership.size());
    // Additional immutable selection alias/type indexes (including set nodes).
    bytes+=64*source.ownerAliases.size()+128*(source.toolHandles.size()+source.ownerHandles.size());
    return bytes;
}
