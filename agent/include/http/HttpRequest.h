#pragma once

#include <string>
#include <map>
#include <sstream>
#include <algorithm>

namespace http {

struct HttpRequest {
    std::string method;
    std::string path;
    std::map<std::string, std::string> headers;
    std::string body;
};

inline std::string trim(const std::string &value) {
    size_t start = value.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return {};
    }
    size_t end = value.find_last_not_of(" \t\r\n");
    return value.substr(start, end - start + 1);
}

inline bool parseHttpRequest(const std::string &raw, HttpRequest &request) {
    size_t headerEnd = raw.find("\r\n\r\n");
    if (headerEnd == std::string::npos) {
        return false;
    }

    std::istringstream stream(raw.substr(0, headerEnd));
    std::string requestLine;
    if (!std::getline(stream, requestLine) || requestLine.empty()) {
        return false;
    }

    if (!requestLine.empty() && requestLine.back() == '\r') {
        requestLine.pop_back();
    }

    std::istringstream lineStream(requestLine);
    std::string version;
    if (!(lineStream >> request.method >> request.path >> version)) {
        return false;
    }

    if (version.rfind("HTTP/", 0) != 0) {
        return false;
    }

    std::string headerLine;
    while (std::getline(stream, headerLine)) {
        if (!headerLine.empty() && headerLine.back() == '\r') {
            headerLine.pop_back();
        }
        if (headerLine.empty()) {
            break;
        }

        size_t colon = headerLine.find(':');
        if (colon == std::string::npos) {
            continue;
        }

        std::string name = trim(headerLine.substr(0, colon));
        std::string value = trim(headerLine.substr(colon + 1));
        request.headers[std::move(name)] = std::move(value);
    }

    return true;
}

} // namespace http
