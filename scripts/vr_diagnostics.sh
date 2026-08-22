#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_directory/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/vr_diagnostics.sh <check|validation|api-dump|nsys|renderdoc> [--] <command> [args...]

Environment overrides:
  NADOC_OPENXR_LAYER_PATH       Directory containing explicit OpenXR layer JSON files
  NADOC_XR_DIAGNOSTIC_OUTPUT    Log/capture output path or prefix
  XR_RUNTIME_JSON               Active OpenXR runtime manifest (SteamVR is auto-detected)
EOF
}

find_layer_directory() {
  local required_json="$1"
  local candidate
  for candidate in \
    "${NADOC_OPENXR_LAYER_PATH:-}" \
    "$repository_root/native/vr_viewer/build/openxr_layers" \
    /usr/share/openxr/1/api_layers/explicit.d \
    /etc/openxr/1/api_layers/explicit.d \
    /usr/lib/ucsf-chimerax/lib/python3.11/site-packages/xr/api_layer/linux; do
    if [[ -n "$candidate" && -f "$candidate/$required_json" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

runtime_manifest() {
  if [[ -n "${XR_RUNTIME_JSON:-}" && -f "$XR_RUNTIME_JSON" ]]; then
    printf '%s\n' "$XR_RUNTIME_JSON"
    return 0
  fi
  local steamvr_manifest="$HOME/.local/share/Steam/steamapps/common/SteamVR/steamxr_linux64.json"
  if [[ -f "$steamvr_manifest" ]]; then
    printf '%s\n' "$steamvr_manifest"
    return 0
  fi
  return 1
}

availability() {
  local validation="missing"
  local api_dump="missing"
  local runtime="missing"
  local profiler="missing"
  local debugger="missing"
  find_layer_directory XrApiLayer_core_validation.json >/dev/null && validation="available"
  find_layer_directory XrApiLayer_api_dump.json >/dev/null && api_dump="available"
  runtime_manifest >/dev/null && runtime="available"
  command -v nsys >/dev/null 2>&1 && profiler="available"
  command -v renderdoccmd >/dev/null 2>&1 && debugger="available"
  printf 'OpenXR runtime: %s\n' "$runtime"
  printf 'OpenXR core validation layer: %s\n' "$validation"
  printf 'OpenXR API dump layer: %s\n' "$api_dump"
  printf 'Nsight Systems OpenGL profiler: %s\n' "$profiler"
  printf 'RenderDoc frame debugger: %s\n' "$debugger"
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

mode="$1"
shift
if [[ "$mode" == "check" ]]; then
  availability
  exit 0
fi
if [[ "${1:-}" == "--" ]]; then shift; fi
if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

runtime="$(runtime_manifest)" || {
  echo "VR diagnostics: no OpenXR runtime manifest found; set XR_RUNTIME_JSON" >&2
  exit 1
}
base_environment=(env -u LD_LIBRARY_PATH "XR_RUNTIME_JSON=$runtime")

case "$mode" in
  validation)
    layer_directory="$(find_layer_directory XrApiLayer_core_validation.json)" || {
      echo "VR diagnostics: OpenXR core validation layer is not installed" >&2
      exit 1
    }
    output="${NADOC_XR_DIAGNOSTIC_OUTPUT:-/tmp/nadoc-openxr-validation.log}"
    "${base_environment[@]}" \
      "LD_LIBRARY_PATH=$layer_directory" \
      "XR_API_LAYER_PATH=$layer_directory" \
      "XR_ENABLE_API_LAYERS=XR_APILAYER_LUNARG_core_validation" \
      XR_LOADER_DEBUG=warn \
      "$@" 2>&1 | tee "$output"
    ;;
  api-dump)
    layer_directory="$(find_layer_directory XrApiLayer_api_dump.json)" || {
      echo "VR diagnostics: OpenXR API dump layer is not installed" >&2
      exit 1
    }
    output="${NADOC_XR_DIAGNOSTIC_OUTPUT:-/tmp/nadoc-openxr-api-dump.log}"
    echo "VR diagnostics: writing OpenXR API dump to $output"
    "${base_environment[@]}" \
      "LD_LIBRARY_PATH=$layer_directory" \
      "XR_API_LAYER_PATH=$layer_directory" \
      "XR_ENABLE_API_LAYERS=XR_APILAYER_LUNARG_api_dump" \
      XR_LOADER_DEBUG=warn \
      "$@" >"$output" 2>&1
    ;;
  nsys)
    command -v nsys >/dev/null 2>&1 || {
      echo "VR diagnostics: nsys is not installed" >&2
      exit 1
    }
    output="${NADOC_XR_DIAGNOSTIC_OUTPUT:-/tmp/nadoc-vr-nsys}"
    "${base_environment[@]}" nsys profile \
      --trace=opengl,osrt \
      --opengl-gpu-workload=true \
      --force-overwrite=true \
      --output="$output" \
      "$@"
    ;;
  renderdoc)
    command -v renderdoccmd >/dev/null 2>&1 || {
      echo "VR diagnostics: renderdoccmd is not installed; install RenderDoc before frame capture" >&2
      exit 1
    }
    output="${NADOC_XR_DIAGNOSTIC_OUTPUT:-/tmp/nadoc-vr-frame}"
    "${base_environment[@]}" renderdoccmd capture --wait-for-exit \
      --capture-file "$output" "$@"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
