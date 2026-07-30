#include "http/HttpParser.h"
#include <cassert>
#include <iostream>

int main() {
    const std::string rawRequest =
        "GET /hello?name=test HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "User-Agent: SysWatchTest\r\n"
        "X-Test: value\r\n"
        "\r\n";

    http::HttpRequest request;
    bool parsed = http::parseHttpRequest(rawRequest, request);
    assert(parsed);
    assert(request.method == "GET");
    assert(request.path == "/hello?name=test");
    assert(request.headers["Host"] == "localhost");
    assert(request.headers["User-Agent"] == "SysWatchTest");
    assert(request.headers["X-Test"] == "value");

    std::cout << "HTTP request parse test passed." << std::endl;
    return 0;
}
