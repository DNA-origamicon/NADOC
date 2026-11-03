#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <limits>
#include <vector>
#include <glm/glm.hpp>

namespace nadoc_vr {
// Immutable broad phase built with static representation data on the reader
// thread. Exact primitive intersection and source-order tie breaking stay with
// the caller. No picking tolerance or molecular geometry is changed.
class PickIndex {
public:
    struct Entry { glm::vec3 lo,hi; uint32_t channel,row; };
private:
    struct Node { glm::vec3 lo,hi; uint32_t begin=0,count=0,left=0,right=0; };
    std::vector<Entry> entries_;
    std::vector<Node> nodes_;
    uint32_t build(uint32_t begin,uint32_t end) {
        Node node;node.lo=glm::vec3(std::numeric_limits<float>::max());node.hi=-node.lo;
        for(auto i=begin;i<end;++i){node.lo=glm::min(node.lo,entries_[i].lo);node.hi=glm::max(node.hi,entries_[i].hi);}
        const auto at=uint32_t(nodes_.size());nodes_.push_back(node);
        if(end-begin<=8){nodes_[at].begin=begin;nodes_[at].count=end-begin;return at;}
        const auto extent=node.hi-node.lo;int axis=extent.y>extent.x?1:0;if(extent.z>extent[axis])axis=2;
        const auto mid=begin+(end-begin)/2;
        std::nth_element(entries_.begin()+begin,entries_.begin()+mid,entries_.begin()+end,
            [axis](const Entry& a,const Entry& b){return a.lo[axis]+a.hi[axis]<b.lo[axis]+b.hi[axis];});
        const auto left=build(begin,mid),right=build(mid,end);nodes_[at].left=left;nodes_[at].right=right;return at;
    }
    static bool intersects(glm::vec3 lo,glm::vec3 hi,glm::vec3 origin,glm::vec3 direction) {
        float near=0,far=std::numeric_limits<float>::infinity();
        // The existing float sphere/capsule quadratics subtract squared
        // distances. At atom scales their uncertainty is proportional to
        // sqrt(epsilon)*ray distance, not epsilon*primitive size. Preserve
        // their accepted boundary hits; exact tests below still decide them.
        const float epsilon=8.F*std::sqrt(std::numeric_limits<float>::epsilon())*
            std::max({1.F,glm::length(origin-lo),glm::length(origin-hi)});
        for(int axis=0;axis<3;++axis){
            lo[axis]-=epsilon;hi[axis]+=epsilon;
            if(direction[axis]==0){if(origin[axis]<lo[axis] || origin[axis]>hi[axis])return false;continue;}
            float a=(lo[axis]-origin[axis])/direction[axis],b=(hi[axis]-origin[axis])/direction[axis];
            if(a>b)std::swap(a,b);
            near=std::max(near,a);far=std::min(far,b);if(near>far)return false;
        }
        return true;
    }
    void query(uint32_t at,glm::vec3 origin,glm::vec3 direction,std::vector<Entry>& result) const {
        const auto& n=nodes_[at];if(!intersects(n.lo,n.hi,origin,direction))return;
        if(n.count){for(auto i=n.begin;i<n.begin+n.count;++i)if(intersects(entries_[i].lo,entries_[i].hi,origin,direction))result.push_back(entries_[i]);}
        else {query(n.left,origin,direction,result);query(n.right,origin,direction,result);}
    }
public:
    void reset(std::vector<Entry> entries) {entries_=std::move(entries);nodes_.clear();if(!entries_.empty())build(0,uint32_t(entries_.size()));}
    size_t bytes() const {return entries_.capacity()*sizeof(Entry)+nodes_.capacity()*sizeof(Node);}
    std::vector<Entry> candidates(glm::vec3 origin,glm::vec3 direction) const {
        std::vector<Entry> result;if(!nodes_.empty())query(0,origin,direction,result);
        std::sort(result.begin(),result.end(),[](const auto& a,const auto& b){return a.channel==b.channel?a.row<b.row:a.channel<b.channel;});
        return result;
    }
};
}
