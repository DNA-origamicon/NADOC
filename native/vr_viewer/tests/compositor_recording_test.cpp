#include "compositor_recording.hpp"
#include <cassert>

int main() {
    using namespace nadoc_vr;
    unsetenv("NADOC_VR_COMPOSITOR_CAPTURE_DIR");
    {CompositorRecording recording;assert(!recording.enabled());assert(!recording.busy());assert(!recording.setSeconds(5));recording.poll();}
    setenv("NADOC_VR_COMPOSITOR_CAPTURE_DIR","/private/capture path",1);
    {CompositorRecording recording;assert(recording.enabled());assert(!recording.busy());
        assert(recording.seconds()==2 && recording.label()=="Record final output 2s");
        assert(recording.durationLabel()=="Duration: 2 seconds");
        assert(!recording.setSeconds(0) && !recording.setSeconds(3));
        recording.toggleDuration();
        assert(recording.seconds()==5 && recording.label()=="Record final output 5s");
        recording.poll();assert(recording.label()=="Record final output 5s");
        recording.toggleDuration();assert(recording.seconds()==2);
        assert(recording.json().find("\"duration_seconds\":2")!=std::string::npos);
        assert(recording.json().find("\"application_eye_recording\":false")!=std::string::npos);
        assert(recording.json().find("\"optical_output_verified\":false")!=std::string::npos);
        // The private nonexistent directory cannot arm a compositor. A worker
        // future remains busy until polled even if the helper exits promptly.
        recording.start();assert(recording.busy());
        assert(!recording.setSeconds(5));recording.toggleDuration();
        assert(recording.seconds()==2);recording.shutdown();}
    const auto state=parseCompositorRecordingStatus(
        "NADOC_CAPTURE_UI 1 \"saved\" \"Record final output 5s\" \"Saved frames; timing unverified\" \"/private/capture path\" 9007199254740993 447 0\n");
    assert(state.request==9007199254740993ULL && state.saved==447 && state.drops==0);
    assert(state.directory=="/private/capture path");
    for(const auto* invalid:{"", "NADOC_CAPTURE_UI 2", "NADOC_CAPTURE_UI 1 saved label status folder 1 2",
        "NADOC_CAPTURE_UI 1 invented label status folder 1 2 0", "NADOC_CAPTURE_UI 1 saved label status folder 1 2 0 extra"}) {
        bool rejected=false;try{parseCompositorRecordingStatus(invalid);}catch(const std::runtime_error&){rejected=true;}assert(rejected);
    }
    unsetenv("NADOC_VR_COMPOSITOR_CAPTURE_DIR");
}
