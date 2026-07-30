#pragma once

#include "http/HttpRequest.h"
#include <string>

namespace http {

bool parseHttpRequest(const std::string &raw, HttpRequest &request);

} // namespace http
