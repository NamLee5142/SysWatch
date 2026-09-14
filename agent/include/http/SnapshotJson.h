#pragma once

#include "domain/Snapshot.h"

#include <string>

namespace http {

// The wire format the agent speaks, in one place.
//
// This lived in HTTPServer.cpp's anonymous namespace, which was right while the
// server was the only thing that produced it. The pusher sends the same
// document to the backend, and two renderings of one format drift: the day
// somebody adds a field to the served snapshot and not to the pushed one, a
// polled host and a pushed host stop being comparable and nothing fails.
std::string snapshotToJson(const Snapshot &snapshot);

} // namespace http
