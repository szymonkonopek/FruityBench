# FruitBench -- a benchmark for the UNA Watch activity pipeline.
#
# Ordering follows the SDK's example apps (and PEEK): una-app.cmake sets the
# toolchain, so it must be included before project(). The build functions read
# SERVICE_SOURCES / GUI_SOURCES / *_INCLUDE_DIRS out of this scope, and
# una_app_build_app() looks for the two ELF targets by the exact names
# ${APP_NAME}Service.elf and ${APP_NAME}GUI.elf.
#
# Like PEEK and UOOM, GUI_SOURCES does NOT include UNA_SDK_SOURCES_GUI: that
# group owns `main` and the touchgfx_* entry points and does not compile
# without a TouchGFX Designer project. FbMain.cpp supplies main() instead. An
# Activity app still has to ship a GUI ELF -- app_merging.py only makes it
# optional for glances -- so this is not a way to skip the GUI, only a way to
# write one without Designer.

cmake_minimum_required(VERSION 3.21)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/build")

# ----------------------------------------------------------------- identity

set(APP_NAME      "FRUITBENCH")
set(APP_USER_NAME "FruitBench")
set(APP_TYPE      "Activity")
set(APP_AUTOSTART Off)
set(DEV_ID        "UNA")

# The App ID lives in tools/app_id.txt because three things must agree on it:
# this build (it is stamped into the .uapp), app-manifest.json (the store
# matches uploads by it) and the FIT developer_data_id the recorder writes.
# tools/gen_measures.py reads the same file, and tools/make_release.sh fails
# the release if the three ever drift apart.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/tools/app_id.txt" APP_ID_RAW)
string(REGEX MATCH "[0-9A-Fa-f]+" APP_ID "${APP_ID_RAW}")
string(TOUPPER "${APP_ID}" APP_ID)
string(LENGTH "${APP_ID}" APP_ID_LEN)
if(NOT APP_ID_LEN EQUAL 16)
    message(FATAL_ERROR
        "tools/app_id.txt must hold exactly 16 hex characters (got '${APP_ID}')")
endif()

# --------------------------------------------------------------------- paths

set(RESOURCES_PATH "${CMAKE_CURRENT_SOURCE_DIR}/Resources")
set(OUTPUT_PATH    "${CMAKE_CURRENT_SOURCE_DIR}/Output")
set(SRC_PATH       "${CMAKE_CURRENT_SOURCE_DIR}/src")

# A flag, not a project: una_app_build_app() merges the GUI ELF into the .uapp
# only when TOUCHGFX_PATH is defined -- it checks the variable, not a project.
set(TOUCHGFX_PATH  "${CMAKE_CURRENT_SOURCE_DIR}")

# --------------------------------------------------------------------- memory
#
# Link-time ceilings for the single MEMORY region in the SDK's Sections.ld, not
# reservations. The recorder holds the generator (about 4 KB of per-measure
# state) plus the FIT writer's payload buffer; the screen holds the 57.6 KB
# panel buffer and its sparkline history.

set(UNA_APP_SERVICE_RAM_LENGTH  "64K")
set(UNA_APP_SERVICE_STACK_SIZE  "8*1024")
set(UNA_APP_GUI_RAM_LENGTH      "192K")
set(UNA_APP_GUI_STACK_SIZE      "16*1024")

# ------------------------------------------------------------------- SDK glue

include($ENV{UNA_SDK}/cmake/una-app.cmake)   # sets the toolchain; before project()
include($ENV{UNA_SDK}/cmake/una-sdk.cmake)   # UNA_SDK_SOURCES_*, *_INCLUDE_DIRS_*

project(${APP_NAME} C CXX ASM)

if(NOT DEFINED BUILD_VERSION)
    set(BUILD_VERSION "0.1.0")
endif()
una_app_setup_version(BUILD_VERSION ${CMAKE_CURRENT_SOURCE_DIR})

# The one TouchGFX-group file worth having: no TouchGFX headers, carries the
# whole kernel-side GUI protocol (frame tick, key samples, framebuffer push).
set(FB_SDK_CMDPROC
    $ENV{UNA_SDK}/Libs/Source/Port/TouchGFX/TouchGFXCommandProcessor.cpp
)

# ------------------------------------------------------------------ targets

# The recorder: the generator, the FIT writer, and the SDK's FIT group
# (FitWriter, FitCrc, FitRecordCadence, RecordingMarker).
set(SERVICE_SOURCES
    ${SRC_PATH}/Service.cpp
    ${SRC_PATH}/fb_fit.cpp
    ${SRC_PATH}/fb_gen.c
    ${SRC_PATH}/fb_fmt.c
    ${SRC_PATH}/fb_measures.c
    ${UNA_SDK_SOURCES_COMMON}
    ${UNA_SDK_SOURCES_APPSYSTEM}      # the SDK's service main(), #includes Service.hpp
    ${UNA_SDK_SOURCES_FIT}
)
set(SERVICE_INCLUDE_DIRS
    ${SRC_PATH}
    ${UNA_SDK_INCLUDE_DIRS_COMMON}
)
una_app_build_service(${APP_NAME}Service.elf)

# The screen: no generator here -- it only draws what the recorder sends, plus
# the catalogue it needs for titles, units and value formatting.
set(GUI_SOURCES
    ${SRC_PATH}/FbMain.cpp
    ${SRC_PATH}/fb_una_platform.cpp
    ${SRC_PATH}/fb_ui.c
    ${SRC_PATH}/fb_video.c
    ${SRC_PATH}/fb_text.c
    ${SRC_PATH}/fb_fmt.c
    ${SRC_PATH}/fb_measures.c
    ${UNA_SDK_SOURCES_COMMON}         # startup, system.cpp, KernelBuilder, Logger
    ${FB_SDK_CMDPROC}
    # NOT ${UNA_SDK_SOURCES_GUI}: see the note at the top and FbMain.cpp
)
set(GUI_INCLUDE_DIRS
    ${SRC_PATH}
    ${UNA_SDK_INCLUDE_DIRS_COMMON}
    ${UNA_SDK_INCLUDE_DIRS_GUI}
)
una_app_build_gui(${APP_NAME}GUI.elf)

una_app_build_app()
