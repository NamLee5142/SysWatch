#pragma once

namespace runtime {

enum class Mode {
    // No arguments: run in the foreground, print snapshots, stop on Ctrl+C.
    // The default, because that is what a developer wants and a service
    // manager passes --service explicitly.
    Console,
    // Started by the Service Control Manager. Never run this by hand — without
    // the SCM on the other end the dispatcher just fails.
    Service,
    Help,
    Unknown,
};

// Returns the mode named by the arguments. argv[0] is ignored.
Mode parseMode(int argc, const char *const *argv);

// What --help prints, and what an unrecognised argument prints before exiting
// non-zero.
const char *usage();

} // namespace runtime
