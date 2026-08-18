cmake_minimum_required(VERSION 3.20)
project(nadoc_vr_viewer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenGL REQUIRED)
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
)
target_compile_options(nadoc-vr-viewer PRIVATE
  -Wall -Wextra -Wpedantic -Wno-missing-field-initializers
)

install(TARGETS nadoc-vr-viewer RUNTIME DESTINATION bin)

include(CTest)
if(BUILD_TESTING)
  add_executable(nadoc-vr-interaction-test tests/interaction_test.cpp)
  target_include_directories(nadoc-vr-interaction-test PRIVATE src)
  target_compile_options(nadoc-vr-interaction-test PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME nadoc-vr-interaction COMMAND nadoc-vr-interaction-test)
  add_test(
    NAME nadoc-vr-scene-v6
    COMMAND nadoc-vr-viewer --validate ${CMAKE_CURRENT_SOURCE_DIR}/examples/triangle.nadocvr
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
endif()
