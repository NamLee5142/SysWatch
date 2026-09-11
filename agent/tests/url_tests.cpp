// Parsing the address an operator writes in a configuration file.
//
// Deliberately strict. Everything this refuses is something the agent could
// only handle by guessing, and a guess about where to send a credential is the
// wrong kind of guess.

#include "http/Url.h"
#include <cassert>
#include <iostream>
#include <string>

namespace {

http::Url parsed(const std::string &text) {
    http::Url url;
    const bool ok = http::Url::parse(text, url);
    assert(ok);
    return url;
}

bool rejects(const std::string &text) {
    http::Url url;
    return !http::Url::parse(text, url);
}

void readsTheObviousParts() {
    const auto url = parsed("http://backend.example.com:8000/api/ingest/snapshot");

    assert(url.scheme == "http");
    assert(url.host == "backend.example.com");
    assert(url.port == 8000);
    assert(url.path == "/api/ingest/snapshot");
}

void portDefaultsToTheScheme() {
    assert(parsed("http://example.com/x").port == 80);
    assert(parsed("https://example.com/x").port == 443);
}

void pathDefaultsToRoot() {
    assert(parsed("http://example.com").path == "/");
    assert(parsed("http://example.com:8000").path == "/");
}

void schemeAndHostAreCaseInsensitive() {
    // "HTTP://EXAMPLE.COM" is the same address as the lowercase form, and a
    // comparison against "127.0.0.1" later must not depend on how it was typed.
    const auto url = parsed("HTTP://Backend.Example.COM/Path");

    assert(url.scheme == "http");
    assert(url.host == "backend.example.com");
    // The path is not lowercased: paths are case sensitive.
    assert(url.path == "/Path");
}

void refusesWhatItCannotHandle() {
    assert(rejects(""));
    assert(rejects("example.com"));            // no scheme
    assert(rejects("ftp://example.com"));      // not a scheme this speaks
    assert(rejects("http://"));                // no host
    assert(rejects("http:///path"));           // no host, only a path
    assert(rejects("http://example.com:0"));   // not a port
    assert(rejects("http://example.com:70000"));
    assert(rejects("http://example.com:http"));

    // Credentials in the URL are refused rather than ignored. The agent's
    // token belongs in a header; one written here would be printed by anything
    // that ever logs the destination.
    assert(rejects("http://user:pass@example.com/x"));
}

void failureLeavesTheOutputAlone() {
    http::Url url;
    assert(http::Url::parse("http://good.example.com:9000/x", url));

    assert(!http::Url::parse("nonsense", url));

    // Still the last good value, not a half-filled one.
    assert(url.host == "good.example.com");
    assert(url.port == 9000);
}

void recognisesLoopback() {
    assert(parsed("http://127.0.0.1:8000/x").isLoopback());
    assert(parsed("http://localhost:8000/x").isLoopback());
    assert(parsed("http://LOCALHOST:8000/x").isLoopback());

    // The whole 127.0.0.0/8 block, not just .1. Treating 127.0.0.2 as remote
    // would refuse a working local configuration.
    assert(parsed("http://127.0.0.2:8000/x").isLoopback());
    assert(parsed("http://127.255.255.254:8000/x").isLoopback());
}

void recognisesEverythingElseAsRemote() {
    assert(!parsed("http://backend.example.com/x").isLoopback());
    assert(!parsed("http://10.0.0.1/x").isLoopback());
    assert(!parsed("http://192.168.1.50:8000/x").isLoopback());

    // The trap this check exists to avoid: a name that merely starts with the
    // loopback digits, or contains "localhost", is not loopback.
    assert(!parsed("http://127.example.com/x").isLoopback());
    assert(!parsed("http://1270.0.0.1/x").isLoopback());
    assert(!parsed("http://notlocalhost/x").isLoopback());
    assert(!parsed("http://localhost.example.com/x").isLoopback());
}

} // namespace

int main() {
    readsTheObviousParts();
    portDefaultsToTheScheme();
    pathDefaultsToRoot();
    schemeAndHostAreCaseInsensitive();
    refusesWhatItCannotHandle();
    failureLeavesTheOutputAlone();
    recognisesLoopback();
    recognisesEverythingElseAsRemote();

    std::cout << "Url tests passed." << std::endl;
    return 0;
}
