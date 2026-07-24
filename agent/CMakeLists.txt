cmake_minimum_required(VERSION 3.15)
project(agent VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include_directories(${CMAKE_SOURCE_DIR}/include)

add_executable(agent
    src/main.cpp
)

target_include_directories(agent PRIVATE ${CMAKE_SOURCE_DIR}/include)
