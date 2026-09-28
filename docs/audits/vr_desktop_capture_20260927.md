# VR tour desktop capture timing

The reported run at `.development-artifacts/vr-sidebar/tour-20260927-145258`
passed every focus interaction check under all four controller profiles. Its final
X11 comparison failed at 7.08% agreement. No failed desktop pixels were retained,
so that artifact alone cannot distinguish head motion from desktop occlusion.

The checker had a timing race: it waited for native stereo PNG encoding and
capture copying before grabbing the desktop, which continues displaying new
tracked frames. The checker now samples the actual desktop concurrently with
capture, with a bounded 32-image buffer. Native rendering and head tracking
continue normally. The best matching observation must satisfy the original 95%
feature-pixel agreement, 32-value color tolerance and one-pixel registration
allowance. Per-sample scores and times are retained; window movement/resizing
fails verification. Only a passing desktop crop is saved, to avoid recording
other applications when the viewer is covered.

A failed final desktop comparison now prints an explicit diagnostic and leaves
the menus open for default interactive review. It still returns failure afterward;
`--exit` returns failure immediately. Controller test failures remain strict.

Focused regression tests cover overlapping capture sampling, desktop errors,
a later mismatching frame, occlusion and changing window geometry. All eight tests
in `tests/test_vr_visual_checks.py` passed. Initial physical-runtime `steady_fast`
focus tour passed with 100% desktop pixel agreement, with evidence retained at
`.development-artifacts/vr-desktop-capture/steady-fast`. The saved desktop image
was visually inspected and contains both sidebars, text and controls.

This fixes the identified comparison race; it does not prove the cause of the
original mismatch or establish physical headset scanout and comfort.

Final `--focus-checks --validate --exit` passed all four profiles with 100.00% desktop agreement. Evidence: `.development-artifacts/vr-desktop-capture/validated`. Both owned test viewers and sockets were cleaned up.
