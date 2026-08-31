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
    src/http/HttpParser.cpp
    src/collector/CPUCollector.cpp
    src/collector/MemoryCollector.cpp
    src/collector/DiskCollector.cpp
    src/collector/OsCollector.cpp
    src/collector/ProcessCollector.cpp
)

target_include_directories(agent_core PUBLIC ${CMAKE_SOURCE_DIR}/include)

target_compile_features(agent_core PUBLIC cxx_std_17)

if (CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_link_options(agent_core PRIVATE "-static-libgcc" "-static-libstdc++")
endif()

if (WIN32)
    # ws2_32 for the HTTP server socket, psapi for GetProcessMemoryInfo in the
    # process collector.
    target_link_libraries(agent_core PRIVATE ws2_32 psapi)
endif()

add_executable(agent
    src/main.cpp
)

target_link_libraries(agent PRIVATE agent_core)

target_include_directories(agent PRIVATE ${CMAKE_SOURCE_DIR}/include)

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
