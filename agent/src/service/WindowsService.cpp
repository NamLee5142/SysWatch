#include "service/WindowsService.h"

#include "logging/Logger.h"
#include "runtime/AgentRuntime.h"

#if defined(_WIN32)

#include <windows.h>
#include <atomic>
#include <string>

namespace service {

namespace {

// The SCM talks to a service through globals: the control handler it calls has
// no user parameter of its own worth threading a context through, and there is
// exactly one service per process.
SERVICE_STATUS_HANDLE statusHandle = nullptr;
SERVICE_STATUS serviceStatus{};
std::atomic<bool> stopRequested{false};
agent::AgentConfig serviceConfig;

// How long the SCM should wait before deciding a pending transition has hung.
// Starting means binding a socket and spawning one thread, so this is generous
// rather than tight.
constexpr DWORD StartWaitHintMs = 10000;
constexpr DWORD StopWaitHintMs = 5000;

void report(DWORD state, DWORD waitHint = 0, DWORD exitCode = NO_ERROR) {
    static DWORD checkPoint = 1;

    serviceStatus.dwServiceType = SERVICE_WIN32_OWN_PROCESS;
    serviceStatus.dwCurrentState = state;
    serviceStatus.dwWin32ExitCode = exitCode;
    serviceStatus.dwWaitHint = waitHint;

    // Only accept a stop once actually running. Accepting it while still
    // starting invites the SCM to send one before there is anything to stop.
    serviceStatus.dwControlsAccepted =
        (state == SERVICE_RUNNING) ? (SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN) : 0;

    // The check point has to advance on every pending report, or the SCM reads
    // a repeated value as a hung transition and kills the process.
    serviceStatus.dwCheckPoint =
        (state == SERVICE_RUNNING || state == SERVICE_STOPPED) ? 0 : checkPoint++;

    if (statusHandle != nullptr) {
        SetServiceStatus(statusHandle, &serviceStatus);
    }
}

DWORD WINAPI controlHandler(DWORD control, DWORD, LPVOID, LPVOID) {
    switch (control) {
        case SERVICE_CONTROL_STOP:
        case SERVICE_CONTROL_SHUTDOWN:
            // SHUTDOWN as well as STOP: without it a reboot kills the process
            // mid-collection instead of letting it close its socket and log.
            report(SERVICE_STOP_PENDING, StopWaitHintMs);
            stopRequested = true;
            return NO_ERROR;

        case SERVICE_CONTROL_INTERROGATE:
            report(serviceStatus.dwCurrentState);
            return NO_ERROR;

        default:
            return ERROR_CALL_NOT_IMPLEMENTED;
    }
}

VOID WINAPI serviceMain(DWORD, LPSTR *) {
    statusHandle = RegisterServiceCtrlHandlerExA(ServiceName, controlHandler, nullptr);
    if (statusHandle == nullptr) {
        return;
    }

    // Reported before anything slow happens. The SCM gives a service a limited
    // window to say it is starting, and missing it is a kill.
    report(SERVICE_START_PENDING, StartWaitHintMs);

    runtime::Callbacks callbacks;
    // RUNNING only once the socket is bound and collection has begun — the
    // point at which the service is genuinely doing its job.
    callbacks.onReady = [] { report(SERVICE_RUNNING); };

    const int result = runtime::runUntilStopped(
        serviceConfig, [] { return stopRequested.load(); }, callbacks);

    // A non-zero result means the agent never came up — almost always a port
    // already in use. Reporting it as an error is what puts a reason in the
    // Windows event log instead of a service that silently will not start.
    report(SERVICE_STOPPED, 0, result == 0 ? NO_ERROR : ERROR_SERVICE_SPECIFIC_ERROR);
    if (result != 0) {
        serviceStatus.dwServiceSpecificExitCode = static_cast<DWORD>(result);
        SetServiceStatus(statusHandle, &serviceStatus);
    }
}

} // namespace

int runAsService(const agent::AgentConfig &config) {
    serviceConfig = config;

    SERVICE_TABLE_ENTRYA table[] = {
        {const_cast<LPSTR>(ServiceName), serviceMain},
        {nullptr, nullptr},
    };

    if (!StartServiceCtrlDispatcherA(table)) {
        const DWORD error = GetLastError();

        // 1063 is "this process was not started by the SCM", which is what
        // happens when someone runs --service by hand. Say so, in the log and
        // on the console, rather than exiting silently.
        logging::Logger log(config.logPath);
        log.error(error == ERROR_FAILED_SERVICE_CONTROLLER_CONNECT
                      ? "--service is for the Service Control Manager to start. "
                        "Run agent.exe with no arguments for a console."
                      : "Could not connect to the Service Control Manager (error " +
                            std::to_string(error) + ")");
        return 1;
    }

    return 0;
}

} // namespace service

#else

namespace service {

int runAsService(const agent::AgentConfig &config) {
    logging::Logger log(config.logPath);
    log.error("Windows Service mode is only available on Windows.");
    return 1;
}

} // namespace service

#endif
