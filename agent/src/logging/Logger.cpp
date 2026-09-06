#include "logging/Logger.h"

#include <chrono>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>

namespace logging {

namespace {

const char *levelName(Level level) {
    switch (level) {
        case Level::Warning: return "WARNING";
        case Level::Error: return "ERROR";
        default: return "INFO";
    }
}

// ISO 8601, in UTC, with the offset spelled out. Same shape as the backend's
// format, so the two logs read alike when someone has both open - and so a log
// line can be compared directly with the collectedAt of the snapshot it
// describes, which has always been UTC.
//
// UTC rather than local because a support bundle is read somewhere other than
// where it was written, and because the two halves of this system must agree:
// an agent logging local time and a backend logging UTC put the same instant
// seven hours apart on the machine this was found on.
std::string timestamp() {
    const auto now = std::chrono::system_clock::now();
    const auto seconds = std::chrono::system_clock::to_time_t(now);
    const auto millis = std::chrono::duration_cast<std::chrono::milliseconds>(
                            now.time_since_epoch()) % 1000;

    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &seconds);
#else
    gmtime_r(&seconds, &utc);
#endif

    std::ostringstream out;
    out << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.'
        << std::setw(3) << std::setfill('0') << millis.count() << 'Z';
    return out.str();
}

std::string backupPath(const std::string &path, int index) {
    return path + "." + std::to_string(index);
}

} // namespace

Logger::Logger(std::string path, std::size_t maxBytes, int backups)
    : path_(std::move(path)), maxBytes_(maxBytes), backups_(backups) {
    if (path_.empty()) {
        return;
    }

    std::error_code error;
    const std::filesystem::path file(path_);
    if (file.has_parent_path()) {
        // Ignored deliberately: if the directory cannot be created the open
        // below fails too, and that is the one place this reports it.
        std::filesystem::create_directories(file.parent_path(), error);
    }

    file_.open(path_, std::ios::app);

    if (!file_.is_open()) {
        // To stderr rather than silence: a console user should be told the log
        // is going nowhere, and under a service this goes nowhere anyway,
        // which is the situation being reported.
        std::cerr << "Could not open the log file " << path_
                  << "; continuing without one." << std::endl;
    }
}

bool Logger::writingToFile() const {
    std::lock_guard<std::mutex> guard(mutex_);
    return file_.is_open();
}

void Logger::info(const std::string &message) { write(Level::Info, message); }
void Logger::warning(const std::string &message) { write(Level::Warning, message); }
void Logger::error(const std::string &message) { write(Level::Error, message); }

void Logger::write(Level level, const std::string &message) {
    std::ostringstream line;
    line << timestamp() << ' ' << levelName(level) << " agent: " << message;
    const std::string text = line.str();

    std::lock_guard<std::mutex> guard(mutex_);

    // The collector thread and the HTTP accept thread both log, so without the
    // lock two lines interleave into one unreadable one.
    if (file_.is_open()) {
        rotateIfNeeded(text.size() + 1);
        file_ << text << '\n';
        file_.flush();
    }

    // Also to the console when there is one. Under a service this write goes
    // nowhere, which costs nothing.
    (level == Level::Info ? std::cout : std::cerr) << text << std::endl;
}

void Logger::rotateIfNeeded(std::size_t incoming) {
    std::error_code error;
    const auto size = std::filesystem::file_size(path_, error);
    if (error || size + incoming <= maxBytes_) {
        return;
    }

    file_.close();

    // Drop the oldest, then shuffle each one along: .2 becomes .3, .1 becomes
    // .2, and the live file becomes .1.
    std::filesystem::remove(backupPath(path_, backups_), error);
    for (int index = backups_ - 1; index >= 1; --index) {
        std::filesystem::rename(backupPath(path_, index), backupPath(path_, index + 1), error);
    }
    std::filesystem::rename(path_, backupPath(path_, 1), error);

    file_.open(path_, std::ios::app);
}

} // namespace logging
