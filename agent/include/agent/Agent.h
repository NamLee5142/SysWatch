#pragma once

namespace agent {

class Agent {
public:
    Agent() noexcept;
    virtual ~Agent() noexcept;

    virtual void start() = 0;
    virtual void stop() = 0;
};

} // namespace agent
