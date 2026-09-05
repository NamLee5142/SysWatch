#pragma once

#include <cstddef>
#include <fstream>
#include <mutex>
#include <string>

namespace logging {

enum class Level { Info, Warning, Error };

// 2 MB before rolling, three kept. The agent says far less than the backend
// does, so a smaller budget still covers a long outage — and an unattended
// service must not be able to fill a disk.
constexpr std::size_t DefaultMaxBytes = 2 * 1024 * 1024;
constexpr int DefaultBackups = 3;

// A file the agent can leave evidence in.
//
// Running as a Windows Service there is no console: every std::cout goes
// nowhere, including the reason the agent failed to start. Without this the
// only way to find out why a service is not answering is to reinstall it as a
// console application and try again.
class Logger {
public:
    explicit Logger(std::string path = {},
                    std::size_t maxBytes = DefaultMaxBytes,
                    int backups = DefaultBackups);

    void info(const std::string &message);
    void warning(const std::string &message);
    void error(const std::string &message);

    // False when the path could not be opened — a read-only directory, a name
    // that is already a file, a drive that is not there. The agent carries on
    // collecting either way; losing the log is not worth losing monitoring
    // over.
    bool writingToFile() const;

private:
    void write(Level level, const std::string &message);
    void rotateIfNeeded(std::size_t incoming);

    mutable std::mutex mutex_;
    std::string path_;
    std::ofstream file_;
    std::size_t maxBytes_;
    int backups_;
};

} // namespace logging
