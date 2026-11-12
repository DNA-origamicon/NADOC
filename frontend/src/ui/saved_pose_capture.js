/** Shared camera snapshot for V, the pose list, and keyframe capture. */
export function captureNamedPose(document, captureCurrentCamera, captureThumbnail = () => null) {
  return {
    name: `Pose ${(document.camera_poses?.length ?? 0) + 1}`,
    state: { ...captureCurrentCamera(), thumbnail: captureThumbnail() },
  }
}
