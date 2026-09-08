// Where the agent's settings come from.
//
// The file is shared with the backend, so most of what is in it is not the
// agent's. Half of these are about ignoring things correctly.

#include "config/ConfigFile.h"

#include <cassert>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

namespace {

namespace fs = std::filesystem;

fs::path scratch() {
    const auto dir = fs::temp_directory_path() / "syswatch-config-tests";
    fs::create_directories(dir);
    return dir;
}

// Writes a config file and loads it into a default AgentConfig.
struct Loaded {
    agent::AgentConfig config;
    config::LoadResult result;
};

Loaded load(const std::string &contents) {
    const auto path = scratch() / "syswatch.env";
    {
        std::ofstream file(path);
        file << contents;
    }

    Loaded loaded;
    loaded.result = config::loadInto(path.string(), loaded.config);
    return loaded;
}

void readsTheBackendUrlAndToken() {
    const auto loaded = load(
        "SYSWATCH_AGENT_BACKEND_URL=http://backend:8000/api/ingest/snapshot\n"
        "SYSWATCH_AGENT_TOKEN=a-real-token\n");

    assert(loaded.result.fileFound);
    assert(loaded.config.backendUrl == "http://backend:8000/api/ingest/snapshot");
    assert(loaded.config.backendToken == "a-real-token");
    assert(loaded.config.pushesToABackend());
    assert(loaded.result.problems.empty());
}

void anAbsentFileMeansTheDefaults() {
    // The single-machine install: no file, no configuration, no push.
    agent::AgentConfig config;
    const agent::AgentConfig defaults;

    const auto result = config::loadInto(
        (scratch() / "there-is-no-such-file.env").string(), config);

    assert(!result.fileFound);
    assert(result.problems.empty());
    assert(config.backendUrl == defaults.backendUrl);
    assert(config.serverPort == defaults.serverPort);
    assert(!config.pushesToABackend());
}

void anEmptyFileChangesNothing() {
    const auto loaded = load("");

    assert(loaded.result.fileFound);
    assert(!loaded.config.pushesToABackend());
}

void unknownKeysAreIgnoredInSilence() {
    // Most of this file is the backend's. An agent that complained about
    // SYSWATCH_SESSION_SECRET would be complaining about a correct machine.
    const auto loaded = load(
        "SYSWATCH_SESSION_SECRET=not-the-agents-business\n"
        "SYSWATCH_PORT=8000\n"
        "SYSWATCH_DATABASE_URL=sqlite:///x.db\n"
        "SYSWATCH_AGENT_TOKEN=mine\n");

    assert(loaded.result.problems.empty());
    assert(loaded.config.backendToken == "mine");
    // The backend's port did not become the agent's.
    assert(loaded.config.serverPort == agent::AgentConfig{}.serverPort);
}

void commentsAndBlankLinesAreSkipped() {
    const auto loaded = load(
        "# The backend to push to\n"
        "\n"
        "   \n"
        "SYSWATCH_AGENT_TOKEN=kept\n"
        "#SYSWATCH_AGENT_BACKEND_URL=http://commented-out/\n");

    assert(loaded.config.backendToken == "kept");
    assert(loaded.config.backendUrl.empty());
}

void whitespaceAroundThePairIsIgnored() {
    const auto loaded = load("   SYSWATCH_AGENT_TOKEN   =   spaced-out   \n");

    assert(loaded.config.backendToken == "spaced-out");
}

void quotesAreStrippedInPairs() {
    // A token pasted with quotation marks round it, and a path with a trailing
    // space that only survives because it was quoted.
    assert(load("SYSWATCH_AGENT_TOKEN=\"quoted\"\n").config.backendToken == "quoted");
    assert(load("SYSWATCH_AGENT_TOKEN='quoted'\n").config.backendToken == "quoted");

    // A lone quote is part of the value: guessing which end was meant is worse
    // than keeping it, and a token is exactly the wrong thing to trim by guess.
    assert(load("SYSWATCH_AGENT_TOKEN=\"unbalanced\n").config.backendToken ==
           "\"unbalanced");
}

void anEqualsInTheValueSurvives() {
    // Base64url has no '=' but a future credential might, and a URL query
    // certainly does.
    const auto loaded = load("SYSWATCH_AGENT_BACKEND_URL=http://b/x?a=1&b=2\n");

    assert(loaded.config.backendUrl == "http://b/x?a=1&b=2");
}

void booleansTakeTheUsualSpellings() {
    for (const std::string yes : {"true", "TRUE", "True", "1", "yes", "on"}) {
        assert(load("SYSWATCH_AGENT_ALLOW_INSECURE_PUSH=" + yes + "\n")
                   .config.allowInsecurePush);
    }
    for (const std::string no : {"false", "FALSE", "0", "no", "off"}) {
        assert(!load("SYSWATCH_AGENT_ALLOW_INSECURE_PUSH=" + no + "\n")
                    .config.allowInsecurePush);
    }
}

void anUnreadableValueIsReportedNotGuessed() {
    // A port of "eighty-eighty" silently becoming 8080 is a machine that does
    // not do what its configuration says, and nobody finds out.
    const auto loaded = load(
        "SYSWATCH_AGENT_PORT=eighty-eighty\n"
        "SYSWATCH_AGENT_ALLOW_INSECURE_PUSH=maybe\n"
        "SYSWATCH_AGENT_INTERVAL_SECONDS=0\n");

    assert(loaded.result.problems.size() == 3);
    for (const auto &problem : loaded.result.problems) {
        // Each one names the setting it is about.
        assert(problem.find("SYSWATCH_AGENT_") != std::string::npos);
    }
    // And the defaults are untouched rather than half-applied.
    assert(loaded.config.serverPort == agent::AgentConfig{}.serverPort);
    assert(!loaded.config.allowInsecurePush);
}

void numbersOutsideTheirRangeAreRefused() {
    assert(!load("SYSWATCH_AGENT_PORT=0\n").result.problems.empty());
    assert(!load("SYSWATCH_AGENT_PORT=70000\n").result.problems.empty());
    assert(!load("SYSWATCH_AGENT_INTERVAL_SECONDS=100000\n").result.problems.empty());
    assert(!load("SYSWATCH_AGENT_PUSH_BUFFER=0\n").result.problems.empty());
    assert(!load("SYSWATCH_AGENT_PUSH_TIMEOUT_SECONDS=-5\n").result.problems.empty());
}

void everySettingCanBeSet() {
    const auto loaded = load(
        "SYSWATCH_AGENT_BACKEND_URL=http://b:8000/x\n"
        "SYSWATCH_AGENT_TOKEN=t\n"
        "SYSWATCH_AGENT_ALLOW_INSECURE_PUSH=true\n"
        "SYSWATCH_AGENT_PORT=9090\n"
        "SYSWATCH_AGENT_INTERVAL_SECONDS=30\n"
        "SYSWATCH_AGENT_PUSH_TIMEOUT_SECONDS=5\n"
        "SYSWATCH_AGENT_PUSH_BUFFER=100\n"
        "SYSWATCH_AGENT_LOG_FILE=C:\\logs\\agent.log\n");

    assert(loaded.result.problems.empty());
    assert(loaded.config.serverPort == 9090);
    assert(loaded.config.allowInsecurePush);
    assert(loaded.config.collectionInterval == std::chrono::seconds(30));
    assert(loaded.config.pushTimeoutMs == 5000);
    assert(loaded.config.pushBufferSize == 100);
    assert(loaded.config.logPath == "C:\\logs\\agent.log");
}

void thereIsNoKeyForTheBindAddress() {
    // The rule two sprints have argued for. The agent serves every metric it
    // collects with no authentication of its own, and 127.0.0.1 is the whole
    // of what makes that safe - so there must be no way to widen it, including
    // by a setting somebody adds without reading HTTPServer::start().
    const auto loaded = load(
        "SYSWATCH_AGENT_HOST=0.0.0.0\n"
        "SYSWATCH_AGENT_BIND=0.0.0.0\n"
        "SYSWATCH_AGENT_BIND_ADDRESS=0.0.0.0\n"
        "SYSWATCH_AGENT_LISTEN=0.0.0.0\n");

    // Not recognised, so not a problem either - just nothing.
    assert(loaded.result.problems.empty());
}

void theSourceFileMentionsNoBindKey() {
    // Belt and braces, and cheap: the check above only proves those four
    // spellings do nothing. This proves no spelling was added.
    const auto source =
        fs::path(__FILE__).parent_path().parent_path() / "src" / "config" / "ConfigFile.cpp";
    std::ifstream file(source);
    const std::string text((std::istreambuf_iterator<char>(file)),
                           std::istreambuf_iterator<char>());
    assert(!text.empty());

    assert(text.find("0.0.0.0") == std::string::npos);
    assert(text.find("bindAddress") == std::string::npos);
    assert(text.find("_BIND") == std::string::npos);
    assert(text.find("_HOST") == std::string::npos);
}

void thePathHonoursTheEnvironmentVariable() {
    // The path may come from the environment; no value may. A machine-wide
    // variable is readable by every account on the box, and the token is the
    // one thing here worth stealing.
#if defined(_WIN32)
    _putenv_s("SYSWATCH_AGENT_CONFIG_FILE", "C:\\somewhere\\else.env");
#else
    setenv("SYSWATCH_AGENT_CONFIG_FILE", "/somewhere/else.env", 1);
#endif
    assert(config::defaultConfigPath().find("else.env") != std::string::npos);

#if defined(_WIN32)
    _putenv_s("SYSWATCH_AGENT_CONFIG_FILE", "");
#else
    unsetenv("SYSWATCH_AGENT_CONFIG_FILE");
#endif
    // Falls back to the shared location beside the backend's own settings.
    assert(config::defaultConfigPath().find("syswatch.env") != std::string::npos);
}

void noValueCanComeFromTheEnvironment() {
    // The token especially. If this ever starts passing for the wrong reason,
    // somebody has added a getenv for a setting.
#if defined(_WIN32)
    _putenv_s("SYSWATCH_AGENT_TOKEN", "from-the-environment");
    _putenv_s("SYSWATCH_AGENT_BACKEND_URL", "http://from-the-environment/");
#else
    setenv("SYSWATCH_AGENT_TOKEN", "from-the-environment", 1);
    setenv("SYSWATCH_AGENT_BACKEND_URL", "http://from-the-environment/", 1);
#endif

    agent::AgentConfig config;
    config::loadInto((scratch() / "there-is-no-such-file.env").string(), config);

    assert(config.backendToken.empty());
    assert(config.backendUrl.empty());

#if defined(_WIN32)
    _putenv_s("SYSWATCH_AGENT_TOKEN", "");
    _putenv_s("SYSWATCH_AGENT_BACKEND_URL", "");
#else
    unsetenv("SYSWATCH_AGENT_TOKEN");
    unsetenv("SYSWATCH_AGENT_BACKEND_URL");
#endif
}

} // namespace

int main() {
    readsTheBackendUrlAndToken();
    anAbsentFileMeansTheDefaults();
    anEmptyFileChangesNothing();
    unknownKeysAreIgnoredInSilence();
    commentsAndBlankLinesAreSkipped();
    whitespaceAroundThePairIsIgnored();
    quotesAreStrippedInPairs();
    anEqualsInTheValueSurvives();
    booleansTakeTheUsualSpellings();
    anUnreadableValueIsReportedNotGuessed();
    numbersOutsideTheirRangeAreRefused();
    everySettingCanBeSet();
    thereIsNoKeyForTheBindAddress();
    theSourceFileMentionsNoBindKey();
    thePathHonoursTheEnvironmentVariable();
    noValueCanComeFromTheEnvironment();

    fs::remove_all(fs::temp_directory_path() / "syswatch-config-tests");
    std::cout << "Config file tests passed." << std::endl;
    return 0;
}
