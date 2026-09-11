// Whether the agent will put its credential on the network.
//
// A push carries the token in an Authorization header. Over http:// to another
// machine that header is readable by anything on the path, and a stolen agent
// token writes whatever history it likes for the host it names. The agent
// speaks no TLS, so the only two honest positions are "refuse" and "refuse
// unless somebody said otherwise, loudly, every time".
//
// These call the real runtime rather than a helper, because the decision has to
// be made before anything starts: a refusal that happens after the first push
// has already sent the token.

#include "runtime/AgentRuntime.h"

#include <atomic>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

namespace {

namespace fs = std::filesystem;

fs::path scratch() {
    const auto dir = fs::temp_directory_path() / "syswatch-push-security-tests";
    fs::remove_all(dir);
    fs::create_directories(dir);
    return dir;
}

struct Run {
    int code;
    std::string log;
};

// Starts the agent with this configuration and stops it immediately. A
// configuration that is refused never reaches the stop check.
Run runWith(const std::string &url, bool allowInsecure, unsigned short port) {
    const auto path = scratch() / "agent.log";

    agent::AgentConfig config;
    config.serverPort = port;
    config.logPath = path.string();
    config.backendUrl = url;
    config.backendToken = "a-token-that-must-never-be-logged";
    config.allowInsecurePush = allowInsecure;

    const int code = runtime::runUntilStopped(config, [] { return true; }, {});

    std::ifstream file(path);
    std::ostringstream contents;
    contents << file.rdbuf();
    return {code, contents.str()};
}

bool mentions(const std::string &text, const std::string &phrase) {
    return text.find(phrase) != std::string::npos;
}

void refusesPlainHttpToAnotherMachine() {
    const auto run = runWith("http://backend.example.com:8000/api/ingest/snapshot",
                             false, 54350);

    assert(run.code == runtime::ExitBadConfiguration);
    assert(mentions(run.log, "Refusing to push"));
    // The message has to name the setting, or the operator has nothing to act
    // on but a refusal.
    assert(mentions(run.log, "allowInsecurePush"));
    assert(mentions(run.log, "in clear"));
    // And it must not have started collecting on the way to deciding.
    assert(!mentions(run.log, "Pushing snapshots to"));
}

void refusesAnIpAddressJustTheSame() {
    const auto run = runWith("http://192.168.1.50:8000/api/ingest/snapshot", false, 54351);

    assert(run.code == runtime::ExitBadConfiguration);
    assert(mentions(run.log, "allowInsecurePush"));
}

void allowsLoopbackWithoutAsking() {
    // The single-machine case, which must keep working with no configuration.
    const auto run = runWith("http://127.0.0.1:8000/api/ingest/snapshot", false, 54352);

    assert(run.code == 0);
    assert(mentions(run.log, "Pushing snapshots to"));
    assert(!mentions(run.log, "crosses the network in clear"));
}

void allowsTheRestOfTheLoopbackBlock() {
    // 127.0.0.0/8 is all loopback. Refusing 127.0.0.2 would reject a working
    // local configuration for no gain.
    const auto run = runWith("http://127.0.0.2:8000/api/ingest/snapshot", false, 54353);

    assert(run.code == 0);
}

void allowsLocalhostByName() {
    const auto run = runWith("http://localhost:8000/api/ingest/snapshot", false, 54354);

    assert(run.code == 0);
}

void aNameThatMerelyLooksLoopbackIsRefused() {
    // The bug that the assertion fix uncovered: an earlier isLoopback checked
    // only the first dotted label, so this - a name anybody can register -
    // counted as this machine, and the token would have gone to it in clear.
    const auto run = runWith("http://127.example.com:8000/api/ingest/snapshot",
                             false, 54355);

    assert(run.code == runtime::ExitBadConfiguration);
    assert(mentions(run.log, "Refusing to push"));
}

void aSimilarNameIsRefusedToo() {
    for (const std::string host : {"notlocalhost", "localhost.example.com", "1270.0.0.1"}) {
        const auto run = runWith("http://" + host + ":8000/x", false, 54356);
        assert(run.code == runtime::ExitBadConfiguration);
    }
}

void allowsPlainHttpWhenSomebodySaidSo() {
    const auto run = runWith("http://backend.example.com:8000/api/ingest/snapshot",
                             true, 54357);

    assert(run.code == 0);
    assert(mentions(run.log, "Pushing snapshots to"));
    // Warned on every start, not once at install: the network this decision was
    // taken about may not be the network it is running on now.
    assert(mentions(run.log, "crosses the network in clear"));
}

void refusesHttpsBecauseItCannotSpeakIt() {
    // Refused at startup rather than once per push. An agent that starts,
    // reports itself healthy and fails every push identically is harder to read
    // than one that will not start.
    const auto run = runWith("https://backend.example.com/api/ingest/snapshot",
                             false, 54358);

    assert(run.code == runtime::ExitBadConfiguration);
    assert(mentions(run.log, "https"));
    assert(!mentions(run.log, "Pushing snapshots to"));
}

void theOptOutDoesNotRescueHttps() {
    // allowInsecurePush is about sending a token in clear, not about making the
    // client understand TLS. Confusing the two would produce an agent that
    // silently fails every push.
    const auto run = runWith("https://backend.example.com/api/ingest/snapshot",
                             true, 54359);

    assert(run.code == runtime::ExitBadConfiguration);
    assert(mentions(run.log, "https"));
}

void theTokenIsNeverWrittenToTheLog() {
    // Every path above, including the ones that refuse: a refusal message that
    // quoted the configuration would put the credential in a file that outlives
    // the decision.
    const std::string token = "a-token-that-must-never-be-logged";

    for (const auto run : {runWith("http://backend.example.com/x", false, 54360),
                           runWith("http://backend.example.com/x", true, 54361),
                           runWith("https://backend.example.com/x", false, 54362),
                           runWith("http://127.0.0.1:8000/x", false, 54363)}) {
        assert(!mentions(run.log, token));
    }
}

} // namespace

int main() {
    refusesPlainHttpToAnotherMachine();
    refusesAnIpAddressJustTheSame();
    allowsLoopbackWithoutAsking();
    allowsTheRestOfTheLoopbackBlock();
    allowsLocalhostByName();
    aNameThatMerelyLooksLoopbackIsRefused();
    aSimilarNameIsRefusedToo();
    allowsPlainHttpWhenSomebodySaidSo();
    refusesHttpsBecauseItCannotSpeakIt();
    theOptOutDoesNotRescueHttps();
    theTokenIsNeverWrittenToTheLog();

    fs::remove_all(fs::temp_directory_path() / "syswatch-push-security-tests");
    std::cout << "Push security tests passed." << std::endl;
    return 0;
}
