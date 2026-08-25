cmake_minimum_required(VERSION 3.20)
project(nadoc_vr_viewer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenGL REQUIRED)
find_package(ZLIB REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GLFW REQUIRED IMPORTED_TARGET glfw3)
pkg_check_modules(OPENXR REQUIRED IMPORTED_TARGET openxr)
pkg_check_modules(X11 REQUIRED IMPORTED_TARGET x11)

add_executable(nadoc-vr-viewer src/main.cpp)
target_link_libraries(nadoc-vr-viewer PRIVATE
  PkgConfig::OPENXR
  PkgConfig::GLFW
  PkgConfig::X11
  OpenGL::GL
  ZLIB::ZLIB
  ${CMAKE_DL_LIBS}
)
target_compile_options(nadoc-vr-viewer PRIVATE
  -Wall -Wextra -Wpedantic -Wno-missing-field-initializers
)

add_executable(nadoc-vr-scrywrite src/scrywrite_main.cpp)
target_include_directories(nadoc-vr-scrywrite PRIVATE src)
target_compile_options(nadoc-vr-scrywrite PRIVATE -Wall -Wextra -Wpedantic)

add_executable(nadoc-vr-scrywrite-export src/scrywrite_export_main.cpp)
target_include_directories(nadoc-vr-scrywrite-export PRIVATE src)
target_compile_options(nadoc-vr-scrywrite-export PRIVATE -Wall -Wextra -Wpedantic)

install(TARGETS nadoc-vr-viewer nadoc-vr-scrywrite nadoc-vr-scrywrite-export
        RUNTIME DESTINATION bin)

include(CTest)
if(BUILD_TESTING)
  add_executable(nadoc-vr-interaction-test tests/interaction_test.cpp)
  target_include_directories(nadoc-vr-interaction-test PRIVATE src)
  target_compile_options(nadoc-vr-interaction-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-interaction COMMAND nadoc-vr-interaction-test)
  add_executable(nadoc-vr-menu-layout-test tests/menu_layout_test.cpp)
  target_include_directories(nadoc-vr-menu-layout-test PRIVATE src)
  target_compile_options(nadoc-vr-menu-layout-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-menu-layout-unit COMMAND nadoc-vr-menu-layout-test)
  add_executable(nadoc-vr-scrywrite-test tests/scrywrite_test.cpp)
  target_include_directories(nadoc-vr-scrywrite-test PRIVATE src)
  target_compile_options(nadoc-vr-scrywrite-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-scrywrite-unit COMMAND nadoc-vr-scrywrite-test)
  add_executable(nadoc-vr-scrywrite-witness-test tests/scrywrite_witness_test.cpp)
  target_include_directories(nadoc-vr-scrywrite-witness-test PRIVATE src)
  target_compile_options(nadoc-vr-scrywrite-witness-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-scrywrite-witness-unit COMMAND nadoc-vr-scrywrite-witness-test)
  add_executable(nadoc-vr-scrywrite-visual-test tests/scrywrite_visual_test.cpp)
  target_include_directories(nadoc-vr-scrywrite-visual-test PRIVATE src)
  target_link_libraries(nadoc-vr-scrywrite-visual-test PRIVATE ZLIB::ZLIB)
  target_compile_options(nadoc-vr-scrywrite-visual-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-scrywrite-visual-unit COMMAND nadoc-vr-scrywrite-visual-test)
  add_executable(nadoc-vr-scrywrite-evidence-test tests/scrywrite_evidence_test.cpp)
  target_include_directories(nadoc-vr-scrywrite-evidence-test PRIVATE src)
  target_compile_options(nadoc-vr-scrywrite-evidence-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-scrywrite-evidence-unit COMMAND nadoc-vr-scrywrite-evidence-test)
  add_executable(nadoc-vr-spectator-mirror-test tests/spectator_mirror_test.cpp)
  target_include_directories(nadoc-vr-spectator-mirror-test PRIVATE src)
  target_compile_options(nadoc-vr-spectator-mirror-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-spectator-mirror-unit COMMAND nadoc-vr-spectator-mirror-test)
  add_executable(nadoc-vr-spectator-diagnostics-test tests/spectator_diagnostics_test.cpp)
  target_include_directories(nadoc-vr-spectator-diagnostics-test PRIVATE src)
  target_compile_options(nadoc-vr-spectator-diagnostics-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-spectator-diagnostics-unit COMMAND nadoc-vr-spectator-diagnostics-test)
  add_executable(nadoc-vr-reference-grid-test tests/reference_grid_test.cpp)
  target_include_directories(nadoc-vr-reference-grid-test PRIVATE src)
  target_compile_options(nadoc-vr-reference-grid-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-reference-grid-unit COMMAND nadoc-vr-reference-grid-test)
  add_test(
    NAME nadoc-vr-scrywrite-evidence-export
    COMMAND nadoc-vr-scrywrite-export
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_chiral_perspective.nadocvr
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_witness_chiral.scry
      ${CMAKE_CURRENT_BINARY_DIR}/scrywrite_chiral_perspective
      --expect
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_chiral_perspective.scry-evidence
  )
  add_test(
    NAME nadoc-vr-scrywrite-witness-script
    COMMAND nadoc-vr-viewer --validate-witness
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_witness_menu.scry
  )
  add_test(
    NAME nadoc-vr-scrywrite-witness-capture-script
    COMMAND nadoc-vr-viewer --validate-witness
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_witness_menu_capture.scry
  )
  add_test(
    NAME nadoc-vr-scrywrite-witness-headset-menu-script
    COMMAND nadoc-vr-viewer --validate-witness
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_witness_headset_menu.scry
  )
  add_test(
    NAME nadoc-vr-scrywrite-witness-atomistic-24hb-script
    COMMAND nadoc-vr-viewer --validate-witness
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_witness_atomistic_24hb.scry
  )
  add_test(
    NAME nadoc-vr-scrywrite-witness-atomistic-24hb-hold-script
    COMMAND nadoc-vr-viewer --validate-witness
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_witness_atomistic_24hb_hold.scry
  )
  add_test(
    NAME nadoc-vr-scrywrite-poc
    COMMAND nadoc-vr-scrywrite
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_move_rotate.scry
  )
  add_test(
    NAME nadoc-vr-scene-v6
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/triangle.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-scrywrite-origami
    COMMAND nadoc-vr-viewer --validate
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_simple_origami.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-scrywrite-chiral
    COMMAND nadoc-vr-viewer --validate
      ${CMAKE_CURRENT_SOURCE_DIR}/examples/scrywrite_chiral_perspective.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-v8
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/owner_alias_v8.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-v8-invalid-alias
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/owner_alias_v8_invalid.nadocvr
  )
  set_tests_properties(nadoc-vr-scene-v8-invalid-alias PROPERTIES WILL_FAIL TRUE)
  add_test(
    NAME nadoc-vr-scene-v9
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/owner_handle_v9.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-v9-invalid-handle
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/owner_handle_v9_invalid.nadocvr
  )
  set_tests_properties(nadoc-vr-scene-v9-invalid-handle PROPERTIES WILL_FAIL TRUE)
  add_test(
    NAME nadoc-vr-scene-v10
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/transform_owner_v10.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-v10-invalid-transform-owner
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/transform_owner_v10_invalid.nadocvr
  )
  set_tests_properties(nadoc-vr-scene-v10-invalid-transform-owner PROPERTIES WILL_FAIL TRUE)
  add_test(
    NAME nadoc-vr-scene-v11-semantic-atom
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/semantic_atom_v11.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-v12-tool-scope
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/tool_scope_v12.nadocvr
  )
  add_test(
    NAME nadoc-vr-scene-v12-gzip
    COMMAND /bin/sh -c "/usr/bin/gzip -c '${CMAKE_CURRENT_SOURCE_DIR}/examples/tool_scope_v12.nadocvr' > '${CMAKE_CURRENT_BINARY_DIR}/tool_scope_v12.nadocvr.gz' && '$<TARGET_FILE:nadoc-vr-viewer>' --validate '${CMAKE_CURRENT_BINARY_DIR}/tool_scope_v12.nadocvr.gz'"
  )
  add_test(
    NAME nadoc-vr-scene-v12-corrupt-gzip
    COMMAND /bin/sh -c "/usr/bin/gzip -c '${CMAKE_CURRENT_SOURCE_DIR}/examples/tool_scope_v12.nadocvr' > '${CMAKE_CURRENT_BINARY_DIR}/tool_scope_v12_corrupt.nadocvr.gz' && /usr/bin/truncate -s -8 '${CMAKE_CURRENT_BINARY_DIR}/tool_scope_v12_corrupt.nadocvr.gz' && '$<TARGET_FILE:nadoc-vr-viewer>' --validate '${CMAKE_CURRENT_BINARY_DIR}/tool_scope_v12_corrupt.nadocvr.gz'"
  )
  set_tests_properties(nadoc-vr-scene-v12-corrupt-gzip PROPERTIES WILL_FAIL TRUE)
endif()
