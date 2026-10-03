#include "ordered_atomic_file.hpp"
#include <cassert>
#include <future>
#include <vector>
#include <unistd.h>
int main() {
    std::promise<void> entered, release;
    auto released=release.get_future().share();
    std::vector<std::string> written;
    {
        nadoc_vr::OrderedAtomicFile writer([&](const auto&,const auto& bytes) {
            if(bytes=="first"){entered.set_value();released.wait();}
            written.push_back(bytes);
        });
        writer.publish("test","first");entered.get_future().wait();
        // A stalled filesystem writer must not block subsequent event enqueue.
        auto publishing=std::async(std::launch::async,[&] {
            writer.publish("test","commit");writer.publish("test","undo");
        });
        const auto status=publishing.wait_for(std::chrono::seconds(1));
        release.set_value();assert(status==std::future_status::ready);publishing.get();
    }
    assert((written==std::vector<std::string>{"first","commit","undo"}));
    const auto path=std::filesystem::temp_directory_path()/("nadoc-events-"+std::to_string(getpid()));
    {nadoc_vr::OrderedAtomicFile writer;writer.publish(path.string(),"complete JSON snapshot");}
    std::ifstream input(path);std::string bytes((std::istreambuf_iterator<char>(input)),{});
    assert(bytes=="complete JSON snapshot");assert(!std::filesystem::exists(path.string()+".events-next"));
    std::filesystem::remove(path);
}
