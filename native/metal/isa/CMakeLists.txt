# SPDX-License-Identifier: MIT
# Copyright (c) 2026 hackios contributors.
cmake_minimum_required(VERSION 3.24)
project(hackios_portable_metal C)

# A single portable source import, not another frontend/provider assembly.
# Required external files are verified below, never copied or regenerated.
set(HACKIOS_ROOT "" CACHE PATH "Repository containing the frozen external dependencies")
if(NOT IS_ABSOLUTE "${HACKIOS_ROOT}")
  message(FATAL_ERROR "Set HACKIOS_ROOT to an absolute repository path; see README.md")
endif()
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/EXTERNAL-DEPENDENCIES.json" dependency_json)
string(JSON dependency_count LENGTH "${dependency_json}" files)
math(EXPR last_dependency "${dependency_count} - 1")
foreach(index RANGE 0 ${last_dependency})
  string(JSON relative GET "${dependency_json}" files ${index} path)
  string(JSON expected GET "${dependency_json}" files ${index} sha256)
  set(dependency "${HACKIOS_ROOT}/${relative}")
  if(NOT EXISTS "${dependency}")
    message(FATAL_ERROR "Missing frozen dependency: ${relative}")
  endif()
  file(SHA256 "${dependency}" actual)
  if(NOT actual STREQUAL expected)
    message(FATAL_ERROR "Frozen dependency drift: ${relative}; review an explicit delta")
  endif()
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${dependency}")
endforeach()

# Preserve the original C gates and defaults. Enabled tests require all four.
option(BLAZER "Compile the existing Blazer shared-init path" OFF)
option(HMGPU_NATIVE_STREAMS "Enable the existing streams integration gate" OFF)
option(HMGPU_NATIVE_SHARED_INIT "Compile shared-init and frozen-resource validation" OFF)
option(BLAZER_HMG_QUEUE "Compile the existing queue callback bridge" OFF)
option(HM_PORTABLE_TESTS "Build the existing focused source tests" OFF)
option(HM_PORTABLE_SANITIZERS "Instrument portable C and tests with ASan/UBSan" OFF)

set(fleet "${HACKIOS_ROOT}/research/ios26-metal-native-20261102")
set(air_root "${fleet}/air-r4")
set(streams "${CMAKE_CURRENT_SOURCE_DIR}/../streams")
# Expose only these exact external headers, so AIR-r4's other sparse portable
# copies cannot silently satisfy a missing imported header. Build-only symlinks
# name the same pinned originals; no competing ABI header is authored/copied.
set(air_include "${CMAKE_CURRENT_BINARY_DIR}/external-include")
file(MAKE_DIRECTORY "${air_include}")
foreach(header hm_air.h hmn.h hmn_streams.h)
  file(CREATE_LINK "${air_root}/composition/include/${header}"
    "${air_include}/${header}" SYMBOLIC)
endforeach()
if(CMAKE_SYSTEM_NAME STREQUAL "iOS")
  set(air_platform ios)
else()
  set(air_platform host)
endif()
add_library(hm_air_frontend SHARED IMPORTED)
set_target_properties(hm_air_frontend PROPERTIES
  IMPORTED_LOCATION "${air_root}/build/${air_platform}/HMAIRFrontend.dylib"
  INTERFACE_INCLUDE_DIRECTORIES "${air_include}")

add_library(hm_native_isa SHARED
  src/hm_isa_memory.c src/hm_isa_alu.c src/hm_isa_alloc.c src/hm_isa_air.c
  src/hm_isa_raw.c src/hm_isa_program.c src/hm_isa_link.c)
add_library(hm_native_streams SHARED
  "${streams}/src/hm_streams.c" "${streams}/src/hm_shared.c"
  "${streams}/src/hm_shared_decode.c" "${streams}/src/hm_shared_bridge.c"
  "${streams}/src/hm_shared_queue.c")
target_include_directories(hm_native_isa PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(hm_native_isa PUBLIC hm_air_frontend)
target_include_directories(hm_native_streams PUBLIC
  "${streams}/include" "${fleet}/queue/include"
  "${HACKIOS_ROOT}/research/ios26-metaldrv-r1/abi"
  "${HACKIOS_ROOT}/research/ios26-gpucc-r1/include")
target_compile_definitions(hm_native_streams PUBLIC
  BLAZER=$<BOOL:${BLAZER}> HMGPU_NATIVE_STREAMS=$<BOOL:${HMGPU_NATIVE_STREAMS}>
  HMGPU_NATIVE_SHARED_INIT=$<BOOL:${HMGPU_NATIVE_SHARED_INIT}>
  BLAZER_HMG_QUEUE=$<BOOL:${BLAZER_HMG_QUEUE}>)

function(portable_flags target)
  target_compile_features(${target} PRIVATE c_std_11)
  target_compile_options(${target} PRIVATE -Wall -Wextra -Werror)
  if(APPLE)
    target_link_options(${target} PRIVATE -Wl,-undefined,error)
  else()
    target_link_options(${target} PRIVATE -Wl,--no-undefined)
  endif()
  if(HM_PORTABLE_SANITIZERS)
    if(CMAKE_CROSSCOMPILING)
      message(FATAL_ERROR "Sanitizers are for runnable host tests only")
    endif()
    target_compile_options(${target} PRIVATE -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(${target} PRIVATE -fsanitize=address,undefined)
  endif()
endfunction()
portable_flags(hm_native_isa)
portable_flags(hm_native_streams)
target_compile_options(hm_native_isa PRIVATE -Wconversion)
set_target_properties(hm_native_isa PROPERTIES
  BUILD_RPATH "${air_root}/build/${air_platform}")

if(HM_PORTABLE_TESTS)
  if(NOT (BLAZER AND HMGPU_NATIVE_STREAMS AND HMGPU_NATIVE_SHARED_INIT AND BLAZER_HMG_QUEUE))
    message(FATAL_ERROR "Focused tests require the four existing gates explicitly ON")
  endif()
  enable_testing()
  # Only the original MIT textual LLVM fixtures are assembled, in the build
  # directory. There is no Apple compiler invocation or binary fixture import.
  find_program(LLVM_AS llvm-as HINTS /opt/homebrew/opt/llvm/bin REQUIRED)
  set(fixture_dir "${CMAKE_CURRENT_BINARY_DIR}/fixtures")
  set(bitcode)
  foreach(name add sub mul constant alias_order single_add chain multi)
    if(name STREQUAL "chain" OR name STREQUAL "multi")
      set(source "${CMAKE_CURRENT_SOURCE_DIR}/tests/${name}.ll")
    else()
      set(source "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/${name}.ll")
    endif()
    add_custom_command(OUTPUT "${fixture_dir}/${name}.bc"
      COMMAND ${CMAKE_COMMAND} -E make_directory "${fixture_dir}"
      COMMAND "${LLVM_AS}" "${source}" -o "${fixture_dir}/${name}.bc"
      DEPENDS "${source}" VERBATIM)
    list(APPEND bitcode "${fixture_dir}/${name}.bc")
  endforeach()
  add_custom_target(hm_source_fixtures ALL DEPENDS ${bitcode})

  function(source_test name source)
    add_executable(${name} "${source}")
    target_link_libraries(${name} PRIVATE hm_native_isa hm_native_streams)
    portable_flags(${name})
    target_compile_options(${name} PRIVATE -UNDEBUG)
    add_dependencies(${name} hm_source_fixtures)
    # Absolute executable path allows PATH to be unavailable to the parser.
    add_test(NAME ${name} COMMAND $<TARGET_FILE:${name}> ${ARGN})
    set_tests_properties(${name} PROPERTIES ENVIRONMENT
      "ASAN_OPTIONS=detect_leaks=0:symbolize=0;PATH=/nonexistent")
  endfunction()
  source_test(isa_memory tests/test_memory.c)
  source_test(isa_native tests/test_native.c)
  source_test(isa_program tests/test_program.c)
  source_test(isa_air_memory tests/test_air_memory.c "${fixture_dir}/single_add.bc")
  source_test(isa_air tests/test_air.c "${fixture_dir}/single_add.bc"
    "${fixture_dir}/add.bc" "${fixture_dir}/sub.bc" "${fixture_dir}/mul.bc")
  source_test(isa_plan tests/test_plan.c "${fixture_dir}/chain.bc"
    "${fixture_dir}/constant.bc" "${fixture_dir}/alias_order.bc")
  source_test(isa_shared_air tests/test_shared_air.c "${fixture_dir}/single_add.bc")
  source_test(isa_air_link tests/test_air_link.c "${fixture_dir}/single_add.bc"
    "${fixture_dir}/add.bc" "${fixture_dir}/sub.bc" "${fixture_dir}/mul.bc"
    "${fixture_dir}/chain.bc" "${fixture_dir}/multi.bc")
  source_test(streams_base "${streams}/tests/test_streams.c")
  source_test(streams_shared "${streams}/tests/test_shared.c")

  # Reuse only the frozen AIR-r4 reference adapter/core for existing integration
  # tests. No copied Metal implementation or second userspace assembly.
  add_library(hm_reference_metal STATIC
    "${air_root}/composition/src/hmn.c" "${air_root}/composition/src/hmn_streams.c")
  target_link_libraries(hm_reference_metal PUBLIC hm_native_streams)
  target_include_directories(hm_reference_metal PRIVATE "${air_include}")
  target_compile_definitions(hm_reference_metal PRIVATE HM_NATIVE_METAL=1)
  portable_flags(hm_reference_metal)
  source_test(streams_bridge "${streams}/tests/test_bridge.c")
  source_test(streams_lifetime "${streams}/tests/test_lifetime.c")
  target_sources(streams_lifetime PRIVATE "${streams}/tests/model.c")
  foreach(target streams_bridge streams_lifetime)
    target_link_libraries(${target} PRIVATE hm_reference_metal)
    target_include_directories(${target} PRIVATE "${air_include}")
    target_compile_definitions(${target} PRIVATE HM_NATIVE_METAL=1)
  endforeach()
endif()
