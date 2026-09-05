// How the one executable decides what it is.
//
// The same binary runs in a console and under the Service Control Manager, so
// getting this wrong means either a service that prints snapshots into a void
// or a developer whose agent exits immediately.

#include "runtime/CommandLine.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

namespace {

runtime::Mode modeOf(std::vector<const char *> arguments) {
    arguments.insert(arguments.begin(), "agent.exe");
    return runtime::parseMode(static_cast<int>(arguments.size()), arguments.data());
}

void bareInvocationIsAConsole() {
    // The default, because that is what a developer types and the SCM passes
    // --service explicitly.
    assert(modeOf({}) == runtime::Mode::Console);
}

void serviceFlagIsRecognised() {
    assert(modeOf({"--service"}) == runtime::Mode::Service);
}

void helpIsRecognised() {
    assert(modeOf({"--help"}) == runtime::Mode::Help);
    assert(modeOf({"-h"}) == runtime::Mode::Help);
}

void installAndUninstallAreRecognised() {
    assert(modeOf({"--install"}) == runtime::Mode::Install);
    assert(modeOf({"--uninstall"}) == runtime::Mode::Uninstall);
}

void anythingElseIsRefused() {
    // Silently falling back to console would mean a mistyped --service starts
    // an agent the SCM is not talking to.
    assert(modeOf({"--serivce"}) == runtime::Mode::Unknown);
    assert(modeOf({"-service"}) == runtime::Mode::Unknown);
    // Without the dashes it is not the flag, and running a console agent
    // instead of installing one is a confusing way to find that out.
    assert(modeOf({"install"}) == runtime::Mode::Unknown);
    assert(modeOf({"--uninstal"}) == runtime::Mode::Unknown);
    assert(modeOf({""}) == runtime::Mode::Unknown);
}

void extraArgumentsAreRefused() {
    assert(modeOf({"--service", "--help"}) == runtime::Mode::Unknown);
}

void usageNamesEveryMode() {
    const std::string text = runtime::usage();

    assert(text.find("--service") != std::string::npos);
    assert(text.find("--help") != std::string::npos);
    assert(text.find("--install") != std::string::npos);
    assert(text.find("--uninstall") != std::string::npos);
    assert(text.find("administrator") != std::string::npos);
    assert(text.find("console") != std::string::npos);
}

} // namespace

int main() {
    bareInvocationIsAConsole();
    serviceFlagIsRecognised();
    installAndUninstallAreRecognised();
    helpIsRecognised();
    anythingElseIsRefused();
    extraArgumentsAreRefused();
    usageNamesEveryMode();

    std::cout << "Command line tests passed." << std::endl;
    return 0;
}
