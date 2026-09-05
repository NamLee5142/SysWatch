// The agent's log file.
//
// As a Windows Service there is no console: every std::cout goes nowhere,
// including the reason the agent failed to start. These check that the file
// gets written, that it stays bounded, and — most importantly — that losing it
// never stops the agent from collecting.

#include "logging/Logger.h"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

namespace fs = std::filesystem;

fs::path scratch() {
    const auto dir = fs::temp_directory_path() / "syswatch-logger-tests";
    fs::remove_all(dir);
    fs::create_directories(dir);
    return dir;
}

std::string read(const fs::path &path) {
    std::ifstream file(path);
    std::ostringstream out;
    out << file.rdbuf();
    return out.str();
}

void writesWhatItIsGiven() {
    const auto path = scratch() / "agent.log";
    {
        logging::Logger log(path.string());
        assert(log.writingToFile());
        log.info("listening on 127.0.0.1:8080");
        log.warning("something worth noticing");
        log.error("something worth fixing");
    }

    const std::string text = read(path);
    assert(text.find("INFO agent: listening on 127.0.0.1:8080") != std::string::npos);
    assert(text.find("WARNING agent: something worth noticing") != std::string::npos);
    assert(text.find("ERROR agent: something worth fixing") != std::string::npos);
}

void createsTheDirectory() {
    const auto path = scratch() / "nested" / "deeper" / "agent.log";
    {
        logging::Logger log(path.string());
        assert(log.writingToFile());
        log.info("hello");
    }
    assert(fs::exists(path));
}

void appendsRatherThanTruncating() {
    const auto path = scratch() / "agent.log";
    { logging::Logger log(path.string()); log.info("first run"); }
    { logging::Logger log(path.string()); log.info("second run"); }

    // A restart must not throw away the reason for the restart.
    const std::string text = read(path);
    assert(text.find("first run") != std::string::npos);
    assert(text.find("second run") != std::string::npos);
}

void rotatesRatherThanGrowingForever() {
    const auto dir = scratch();
    const auto path = dir / "agent.log";
    {
        // Small enough to roll after a few lines.
        logging::Logger log(path.string(), 200, 2);
        for (int i = 0; i < 60; ++i) {
            log.info("a line that takes up a reasonable amount of room " + std::to_string(i));
        }
    }

    // An unattended service must not be able to fill a disk.
    assert(fs::exists(path));
    assert(fs::exists(dir / "agent.log.1"));
    assert(fs::file_size(path) <= 400);

    // Only the configured number of backups survives.
    assert(!fs::exists(dir / "agent.log.3"));
}

void survivesAnUnusablePath() {
    const auto dir = scratch();
    const auto blocker = dir / "logs";
    { std::ofstream file(blocker); file << "this is a file, not a directory"; }

    // A path whose parent is a file: the open must fail and nothing may throw.
    logging::Logger log((blocker / "agent.log").string());

    assert(!log.writingToFile());
    log.info("still has to be safe to call");
    log.error("and this");
}

void anEmptyPathDisablesTheFile() {
    logging::Logger log("");

    assert(!log.writingToFile());
    log.info("console only");
}

void interleavedWritesStayOnTheirOwnLines() {
    const auto path = scratch() / "agent.log";
    {
        logging::Logger log(path.string());

        // The collector thread and the HTTP accept thread both log.
        std::vector<std::thread> writers;
        for (int t = 0; t < 4; ++t) {
            writers.emplace_back([&log, t] {
                for (int i = 0; i < 50; ++i) {
                    log.info("thread " + std::to_string(t) + " line " + std::to_string(i));
                }
            });
        }
        for (auto &writer : writers) {
            writer.join();
        }
    }

    std::ifstream file(path);
    std::string line;
    int lines = 0;
    while (std::getline(file, line)) {
        // Every line is one complete record, not two spliced together.
        assert(line.find("agent: thread ") != std::string::npos);
        assert(line.find(" line ") != std::string::npos);
        ++lines;
    }
    assert(lines == 200);
}

} // namespace

int main() {
    writesWhatItIsGiven();
    createsTheDirectory();
    appendsRatherThanTruncating();
    rotatesRatherThanGrowingForever();
    survivesAnUnusablePath();
    anEmptyPathDisablesTheFile();
    interleavedWritesStayOnTheirOwnLines();

    std::filesystem::remove_all(std::filesystem::temp_directory_path() / "syswatch-logger-tests");
    std::cout << "Logger tests passed." << std::endl;
    return 0;
}
