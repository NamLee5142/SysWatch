cmake_minimum_required(VERSION 3.15)
project(agent VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(agent_core STATIC
    src/collector/CPUCollector.cpp
    src/collector/MemoryCollector.cpp
    src/collector/DiskCollector.cpp
    src/collector/OsCollector.cpp
)

target_include_directories(agent_core PUBLIC ${CMAKE_SOURCE_DIR}/include)

target_compile_features(agent_core PUBLIC cxx_std_17)

if (CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_link_options(agent_core PRIVATE "-static-libgcc" "-static-libstdc++")
endif()

add_executable(agent
    src/main.cpp
)

target_link_libraries(agent PRIVATE agent_core)

target_include_directories(agent PRIVATE ${CMAKE_SOURCE_DIR}/include)
