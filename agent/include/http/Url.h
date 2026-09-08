#pragma once

#include <string>

namespace http {

// Enough of a URL to open a connection to it. Not a general parser: the agent
// speaks to one address that an operator wrote in a configuration file, so
// query strings, fragments, userinfo and IPv6 literals in brackets are all
// absent because nothing that reaches here can contain them - and accepting
// what cannot be handled correctly is worse than refusing it.
struct Url {
    std::string scheme;  // "http" or "https", lowercased
    std::string host;    // a name or an IPv4 literal, lowercased
    unsigned short port{0};
    std::string path{"/"};

    // True when the host names this machine and nothing else can reach it.
    // Not a string comparison against "localhost": the whole 127.0.0.0/8 block
    // is loopback, so 127.0.0.2 is as local as 127.0.0.1, and ::1 is too.
    bool isLoopback() const;

    // Parses, or returns false and leaves the output untouched. A URL the
    // agent cannot parse is a configuration error to report at startup, not a
    // connection to attempt against a guess.
    static bool parse(const std::string &text, Url &out);
};

} // namespace http
