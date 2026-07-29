#include "http/HTTPServer.h"

namespace http {

HTTPServer::HTTPServer(agent::Agent &agent)
    : agent_(agent) {}

HTTPServer::~HTTPServer() = default;

void HTTPServer::start() {}
void HTTPServer::stop() {}

} // namespace http
