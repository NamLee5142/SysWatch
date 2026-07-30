#pragma once

#include <string>
#include <map>

namespace http {

struct HttpResponse {
    int status = 200;
    std::map<std::string, std::string> headers;
    std::string body;
};

} // namespace http
