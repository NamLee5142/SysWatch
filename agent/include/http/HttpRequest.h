#pragma once

#include <string>
#include <map>

namespace http {

struct HttpRequest {
    std::string method;
    std::string path;
    std::map<std::string, std::string> headers;
    std::string body;
};

} // namespace http
