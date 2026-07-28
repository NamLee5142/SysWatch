#pragma once

// Placeholder for the public agent runtime interface.
// Implement this when the agent runner needs a pluggable execution entrypoint.
class Agent {
public:
    virtual ~Agent() = default;
    virtual void run() = 0;
};
