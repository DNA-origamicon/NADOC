#include "latest_atomic_file.hpp"
#include <cassert>
#include <future>
#include <vector>
int main(){
    std::promise<void> entered,release;
    auto gate=release.get_future().share();std::vector<std::string> writes;
    {
        nadoc_vr::LatestAtomicFile writer([&](const auto&,const std::string& bytes){
            writes.push_back(bytes);
            if(bytes=="first"){entered.set_value();gate.wait();}
        });
        writer.publish("pose","first");entered.get_future().wait();
        // These must complete while the first filesystem operation is blocked.
        writer.publish("pose","obsolete");writer.publish("pose","latest");
        release.set_value();
    }
    assert((writes==std::vector<std::string>{"first","latest"}));
    std::promise<void> failed;
    {
        nadoc_vr::LatestAtomicFile writer([&](const auto&,const auto&){failed.set_value();throw std::runtime_error("disk");});
        writer.publish("pose","value");failed.get_future().wait();
    }
}
