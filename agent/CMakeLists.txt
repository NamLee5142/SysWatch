cmake_minimum_required(VERSION 3.15)

# One version for the whole product, read from the file the backend and the
# dashboard also take it from. Read before project(), which is the only place
# CMake will accept it.
#
# CONFIGURE_DEPENDS has no equivalent here: CMake caches this at configure time,
# so editing VERSION means re-running cmake. That is what the sync script and
# its --check mode are for.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" SYSWATCH_VERSION)
string(STRIP "${SYSWATCH_VERSION}" SYSWATCH_VERSION)

project(agent VERSION ${SYSWATCH_VERSION} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

enable_testing()

add_library(agent_core STATIC
    src/Agent.cpp
    src/repository/SnapshotRepository.cpp
    src/scheduler/Scheduler.cpp
    src/http/HTTPServer.cpp
    src/http/HttpParser.cpp
    src/http/HttpClient.cpp
    src/http/SnapshotJson.cpp
    src/push/SnapshotPusher.cpp
    src/http/Url.cpp
    src/runtime/AgentRuntime.cpp
    src/runtime/CommandLine.cpp
    src/service/WindowsService.cpp
    src/service/ServiceInstall.cpp
    src/logging/Logger.cpp
    src/collector/CPUCollector.cpp
    src/collector/MemoryCollector.cpp
    src/collector/DiskCollector.cpp
    src/collector/OsCollector.cpp
    src/collector/ProcessCollector.cpp
    src/collector/NetworkCollector.cpp
)

target_include_directories(agent_core PUBLIC ${CMAKE_SOURCE_DIR}/include)

# PUBLIC so the tests see the same string the agent logs, rather than a second
# copy that can disagree with it.
target_compile_definitions(agent_core PUBLIC SYSWATCH_VERSION="${SYSWATCH_VERSION}")

target_compile_features(agent_core PUBLIC cxx_std_17)

# Static, and on the executables rather than the library.
#
# agent_core is a static library and has no link step, so link options set on
# it never reach agent.exe — which was therefore importing libstdc++-6.dll,
# libgcc_s_seh-1.dll and libwinpthread-1.dll from whatever happened to be on
# PATH. Fine in a shell with the toolchain on PATH and fatal everywhere else:
# the process exits 127 with no message, so a service installed that way would
# be registered, start, and die silently.
if (CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    set(AGENT_STATIC_LINK_OPTIONS -static-libgcc -static-libstdc++ -static)
endif()

if (WIN32)
    # ws2_32 for the HTTP server socket, psapi for GetProcessMemoryInfo in the
    # process collector, iphlpapi for GetIfTable2 in the network collector,
    # advapi32 for the Service Control Manager calls.
    target_link_libraries(agent_core PRIVATE ws2_32 psapi iphlpapi advapi32)
endif()

add_executable(agent src/main.cpp)
target_link_libraries(agent PRIVATE agent_core)
target_include_directories(agent PRIVATE ${CMAKE_SOURCE_DIR}/include)

if (AGENT_STATIC_LINK_OPTIONS)
    target_link_options(agent PRIVATE ${AGENT_STATIC_LINK_OPTIONS})
endif()

# One assert-based executable per test, registered with CTest so a failing run
# names the test rather than reporting a shell loop's exit code — which is all
# CI could have said about the for-loop this replaces.
#
# Several of these bind a socket. They use distinct ports, and none uses 8080,
# so an agent running on the machine does not break the suite.
function(add_agent_test name source)
    add_executable(${name} ${source})
    target_link_libraries(${name} PRIVATE agent_core)
    target_include_directories(${name} PRIVATE ${CMAKE_SOURCE_DIR}/include)

    # Every test here checks with assert(), and a Release build defines NDEBUG,
    # which compiles assert() to nothing. CI builds Release. So each of these
    # executables ran to the end of main(), printed "passed" and checked
    # nothing - a suite that could not fail, in the configuration that ships.
    #
    # Demonstrated by making Logger.cpp stamp local time instead of UTC, the
    # thing logger_tests was written to catch: it printed "Logger tests passed"
    # while logging 09:16 local as 09:16Z.
    #
    # Undefined per test target rather than by changing the build type: the
    # agent should keep shipping -O3, and the tests are not what ships.
    if (MSVC)
        target_compile_options(${name} PRIVATE /UNDEBUG)
    else()
        target_compile_options(${name} PRIVATE -UNDEBUG)
    endif()

    if (AGENT_STATIC_LINK_OPTIONS)
        target_link_options(${name} PRIVATE ${AGENT_STATIC_LINK_OPTIONS})
    endif()

    add_test(NAME ${name} COMMAND ${name})
    # A socket test that hangs would otherwise hold a CI job until the job
    # itself times out, with nothing said about which test it was.
    set_tests_properties(${name} PROPERTIES TIMEOUT 60)
endfunction()

add_agent_test(version_tests tests/version_tests.cpp)
add_agent_test(agent_tests tests/scheduler_lifecycle_tests.cpp)
add_agent_test(agent_runtime_tests tests/agent_runtime_tests.cpp)
add_agent_test(command_line_tests tests/command_line_tests.cpp)
add_agent_test(logger_tests tests/logger_tests.cpp)
add_agent_test(cpu_collector_tests tests/cpu_collector_tests.cpp)
add_agent_test(process_collector_tests tests/process_collector_tests.cpp)
add_agent_test(network_collector_tests tests/network_collector_tests.cpp)
add_agent_test(http_server_tests tests/http_server_lifecycle_tests.cpp)
add_agent_test(http_server_accept_tests tests/http_server_accept_tests.cpp)
add_agent_test(http_server_bind_tests tests/http_server_bind_tests.cpp)
add_agent_test(http_server_routing_tests tests/http_server_routing_tests.cpp)
add_agent_test(http_server_snapshot_tests tests/http_server_snapshot_tests.cpp)
add_agent_test(http_server_concurrency_tests tests/http_server_concurrency_tests.cpp)
add_agent_test(http_server_integration_tests tests/http_server_integration_tests.cpp)
add_agent_test(http_request_parse_tests tests/http_request_parse_tests.cpp)
add_agent_test(url_tests tests/url_tests.cpp)
add_agent_test(http_client_tests tests/http_client_tests.cpp)
add_agent_test(http_client_parsing_tests tests/http_client_parsing_tests.cpp)
add_agent_test(snapshot_pusher_tests tests/snapshot_pusher_tests.cpp)
add_agent_test(push_security_tests tests/push_security_tests.cpp)
