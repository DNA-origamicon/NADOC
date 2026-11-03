#pragma once
// Included after SourceIndex and scene types. Borrowed point/token addresses
// remain valid for the owning immutable SceneData, just like SourceIndex.
struct HandleOffsetIndex {
    struct Point { const StyledPoint* source; const TransformOwnership* ownership; std::vector<size_t> aliases; };
    std::vector<Point> points;
    std::unordered_map<std::string_view,size_t> tokens;
    std::vector<size_t> counts;
    void rebuild(const RepresentationData& source,const SourceIndex& index) {
        points.clear();tokens.clear();counts.clear();
        for(const auto& point:source.points) {
            if(!point.identity.ends_with(":backbone"))continue;
            const auto found=index.aliases.find(point.identity);
            if(found==index.aliases.end())continue;
            const auto owner=index.ownership.find(point.identity);
            Point row{&point,owner==index.ownership.end()?nullptr:owner->second,{}};
            for(const auto& token:found->second->tokens) {
                auto [entry,inserted]=tokens.try_emplace(token,counts.size());
                if(inserted)counts.push_back(0);
                row.aliases.push_back(entry->second);++counts[entry->second];
            }
            points.push_back(std::move(row));
        }
    }
    std::vector<glm::vec3> offsets(const glm::mat4& transform,const std::string& token) const {
        std::vector<glm::vec3> result(counts.size(),glm::vec3(0));
        const auto alias=tokens.find(token);
        // Preserve the previous point order and floating-point operations.
        // Only alias lookup/counting moves off the commit frame.
        for(const auto& row:points) {
            const auto& p=*row.source;
            float weight=0;bool explicitOwner=false;
            if(!token.empty() && row.ownership)for(const auto& owner:row.ownership->owners) {
                if(owner.token==token){weight=owner.startWeight;explicitOwner=true;break;}
            }
            if(!token.empty() && !explicitOwner && alias!=tokens.end() &&
                std::find(row.aliases.begin(),row.aliases.end(),alias->second)!=row.aliases.end())weight=1;
            const auto delta=nadoc_vr::weightedTransformPoint(p.position,transform,weight)-p.position;
            for(const auto index:row.aliases)result[index]+=delta;
        }
        for(size_t i=0;i<result.size();++i)result[i]/=float(counts[i]);
        return result;
    }
    size_t bytes() const {
        size_t result=points.capacity()*sizeof(Point)+counts.capacity()*sizeof(size_t)+tokens.bucket_count()*sizeof(void*)+tokens.size()*64;
        for(const auto& row:points)result+=row.aliases.capacity()*sizeof(size_t);
        return result;
    }
};
