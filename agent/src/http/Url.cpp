#include "http/Url.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>

namespace http {

namespace {

std::string lowercased(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

bool allDigits(const std::string &value) {
    return !value.empty() && std::all_of(value.begin(), value.end(), [](unsigned char c) {
        return std::isdigit(c) != 0;
    });
}

// The first octet of an IPv4 literal, or -1 when the text is not one.
//
// The whole address is validated, not just the part before the first dot. An
// earlier version checked only that the leading label was numeric, which made
// "127.example.com" loopback - a name an attacker can register, and one that
// commit 9 would then let a token cross the network in clear to reach.
int firstOctet(const std::string &host) {
    int octets[4] = {0, 0, 0, 0};
    std::size_t start = 0;

    for (int i = 0; i < 4; ++i) {
        const std::size_t dot = host.find('.', start);
        const bool last = (i == 3);

        if (last != (dot == std::string::npos)) {
            return -1;  // too few dots, or too many
        }

        const std::string part =
            last ? host.substr(start) : host.substr(start, dot - start);

        if (!allDigits(part) || part.size() > 3) {
            return -1;
        }

        const int value = std::atoi(part.c_str());
        if (value > 255) {
            return -1;
        }

        octets[i] = value;
        start = last ? start : dot + 1;
    }

    return octets[0];
}

} // namespace

bool Url::isLoopback() const {
    if (host == "localhost" || host == "::1") {
        return true;
    }

    // 127.0.0.0/8, all sixteen million of it. Checking only 127.0.0.1 would
    // call 127.0.0.2 remote, which is wrong in the direction that matters: it
    // would refuse a working local configuration.
    return firstOctet(host) == 127;
}

bool Url::parse(const std::string &text, Url &out) {
    const std::size_t schemeEnd = text.find("://");
    if (schemeEnd == std::string::npos) {
        return false;
    }

    Url parsed;
    parsed.scheme = lowercased(text.substr(0, schemeEnd));
    if (parsed.scheme != "http" && parsed.scheme != "https") {
        return false;
    }

    const std::string rest = text.substr(schemeEnd + 3);
    if (rest.empty()) {
        return false;
    }

    // Everything from the first slash is the path. A URL with no slash at all
    // addresses the root.
    const std::size_t pathStart = rest.find('/');
    const std::string authority =
        pathStart == std::string::npos ? rest : rest.substr(0, pathStart);
    parsed.path = pathStart == std::string::npos ? "/" : rest.substr(pathStart);

    if (authority.empty()) {
        return false;
    }

    // Credentials in a URL are refused rather than ignored. The agent's
    // credential belongs in a header, and one written here would be logged by
    // anything that ever prints the destination.
    if (authority.find('@') != std::string::npos) {
        return false;
    }

    const std::size_t colon = authority.find(':');
    if (colon == std::string::npos) {
        parsed.host = lowercased(authority);
        parsed.port = parsed.scheme == "https" ? 443 : 80;
    } else {
        parsed.host = lowercased(authority.substr(0, colon));
        const std::string port = authority.substr(colon + 1);

        if (!allDigits(port)) {
            return false;
        }

        const long number = std::atol(port.c_str());
        if (number <= 0 || number > 65535) {
            return false;
        }

        parsed.port = static_cast<unsigned short>(number);
    }

    if (parsed.host.empty()) {
        return false;
    }

    out = parsed;
    return true;
}

} // namespace http
