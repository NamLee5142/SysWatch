cmake_minimum_required(VERSION 3.15)
project(agent VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(agent_core STATIC
    src/Agent.cpp
    src/repository/SnapshotRepository.cpp
    src/scheduler/Scheduler.cpp
    src/http/HTTPServer.cpp
    src/runtime/AgentRuntime.cpp
    src/logging/Logger.cpp
    src/runtime/CommandLine.cpp
    src/service/WindowsService.cpp
    src/service/ServiceInstall.cpp
    src/http/HttpParser.cpp
    src/collector/CPUCollector.cpp
    src/collector/MemoryCollector.cpp
    src/collector/DiskCollector.cpp
    src/collector/OsCollector.cpp
    src/collector/ProcessCollector.cpp
    src/collector/NetworkCollector.cpp
)

target_include_directories(agent_core PUBLIC ${CMAKE_SOURCE_DIR}/include)

target_compile_features(agent_core PUBLIC cxx_std_17)

# Static, and on the executable rather than the library.
#
# agent_core is a static library and has no link step, so link options set on
# it never reach agent.exe — which was therefore importing libstdc++-6.dll,
# libgcc_s_seh-1.dll and libwinpthread-1.dll from whatever happened to be on
# PATH. That is fine in a shell with the toolchain on PATH and fatal
# everywhere else: the process exits 127 with no message, so a service
# installed this way would be registered, start, and die silently.
if (CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    set(AGENT_STATIC_LINK_OPTIONS -static-libgcc -static-libstdc++ -static)
endif()

if (WIN32)
    # ws2_32 for the HTTP server socket, psapi for GetProcessMemoryInfo in the
    # process collector, iphlpapi for GetIfTable2 in the network collector.
    # advapi32 for the Service Control Manager calls in WindowsService.cpp.
    target_link_libraries(agent_core PRIVATE ws2_32 psapi iphlpapi advapi32)
endif()

add_executable(agent
    src/main.cpp
)

target_link_libraries(agent PRIVATE agent_core)

target_include_directories(agent PRIVATE ${CMAKE_SOURCE_DIR}/include)

if (AGENT_STATIC_LINK_OPTIONS)
    target_link_options(agent PRIVATE ${AGENT_STATIC_LINK_OPTIONS})
endif()

add_executable(agent_tests
    tests/scheduler_lifecycle_tests.cpp
)

target_link_libraries(agent_tests PRIVATE agent_core)

target_include_directories(agent_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(cpu_collector_tests
    tests/cpu_collector_tests.cpp
)

target_link_libraries(cpu_collector_tests PRIVATE agent_core)

target_include_directories(cpu_collector_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(process_collector_tests
    tests/process_collector_tests.cpp
)

target_link_libraries(process_collector_tests PRIVATE agent_core)

target_include_directories(process_collector_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(network_collector_tests
    tests/network_collector_tests.cpp
)

target_link_libraries(network_collector_tests PRIVATE agent_core)

target_include_directories(network_collector_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_tests
    tests/http_server_lifecycle_tests.cpp
)

target_link_libraries(http_server_tests PRIVATE agent_core)

target_include_directories(http_server_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_accept_tests
    tests/http_server_accept_tests.cpp
)

target_link_libraries(http_server_accept_tests PRIVATE agent_core)

target_include_directories(http_server_accept_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(command_line_tests
    tests/command_line_tests.cpp
)

target_link_libraries(command_line_tests PRIVATE agent_core)

target_include_directories(command_line_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(logger_tests
    tests/logger_tests.cpp
)

target_link_libraries(logger_tests PRIVATE agent_core)

target_include_directories(logger_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(agent_runtime_tests
    tests/agent_runtime_tests.cpp
)

target_link_libraries(agent_runtime_tests PRIVATE agent_core)

target_include_directories(agent_runtime_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_bind_tests
    tests/http_server_bind_tests.cpp
)

target_link_libraries(http_server_bind_tests PRIVATE agent_core)

target_include_directories(http_server_bind_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_routing_tests
    tests/http_server_routing_tests.cpp
)

target_link_libraries(http_server_routing_tests PRIVATE agent_core)

target_include_directories(http_server_routing_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_snapshot_tests
    tests/http_server_snapshot_tests.cpp
)

target_link_libraries(http_server_snapshot_tests PRIVATE agent_core)

target_include_directories(http_server_snapshot_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_concurrency_tests
    tests/http_server_concurrency_tests.cpp
)

target_link_libraries(http_server_concurrency_tests PRIVATE agent_core)

target_include_directories(http_server_concurrency_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_server_integration_tests
    tests/http_server_integration_tests.cpp
)

target_link_libraries(http_server_integration_tests PRIVATE agent_core)

target_include_directories(http_server_integration_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

add_executable(http_request_parse_tests
    tests/http_request_parse_tests.cpp
)

target_link_libraries(http_request_parse_tests PRIVATE agent_core)

target_include_directories(http_request_parse_tests PRIVATE ${CMAKE_SOURCE_DIR}/include)

# hello_test removed
