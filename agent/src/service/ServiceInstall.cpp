#include "service/WindowsService.h"

#include <iostream>

#if defined(_WIN32)

#include <windows.h>
#include <string>

namespace service {

namespace {

// Restart after 5s, then 10s, then every minute. Reset the count after a day,
// so a service that fails once a week is treated as a first failure each time
// rather than eventually giving up.
constexpr DWORD RestartDelaysMs[] = {5000, 10000, 60000};
constexpr DWORD FailureResetSeconds = 86400;

constexpr int ExitOk = 0;
constexpr int ExitFailed = 1;

std::string executablePath() {
    char buffer[MAX_PATH]{};
    const DWORD length = GetModuleFileNameA(nullptr, buffer, MAX_PATH);
    return length ? std::string(buffer, length) : std::string{};
}

// Quoted, because a path with a space in it — "C:\Program Files\..." — is
// otherwise read by the SCM as a program name plus arguments.
std::string serviceCommand() {
    return "\"" + executablePath() + "\" --service";
}

std::string describe(DWORD error) {
    char *text = nullptr;
    const DWORD length = FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr, error, 0, reinterpret_cast<char *>(&text), 0, nullptr);

    std::string message = length && text ? std::string(text, length) : "error " + std::to_string(error);
    if (text) {
        LocalFree(text);
    }

    while (!message.empty() && (message.back() == '\n' || message.back() == '\r')) {
        message.pop_back();
    }
    return message;
}

// Every one of these fails with ACCESS_DENIED from an ordinary prompt, which
// on its own is a five-digit number and no advice.
bool reportAccessDenied(DWORD error, const char *action) {
    if (error != ERROR_ACCESS_DENIED) {
        return false;
    }

    std::cerr << "Cannot " << action << " the service without administrator rights.\n"
              << "Open a command prompt as administrator and run this again." << std::endl;
    return true;
}

SC_HANDLE openManager(DWORD access, const char *action) {
    SC_HANDLE manager = OpenSCManagerA(nullptr, nullptr, access);
    if (manager != nullptr) {
        return manager;
    }

    const DWORD error = GetLastError();
    if (!reportAccessDenied(error, action)) {
        std::cerr << "Could not reach the Service Control Manager: " << describe(error) << std::endl;
    }
    return nullptr;
}

void applyRecoveryActions(SC_HANDLE handle) {
    SC_ACTION actions[3];
    for (int index = 0; index < 3; ++index) {
        actions[index].Type = SC_ACTION_RESTART;
        actions[index].Delay = RestartDelaysMs[index];
    }

    SERVICE_FAILURE_ACTIONSA failure{};
    failure.dwResetPeriod = FailureResetSeconds;
    failure.cActions = 3;
    failure.lpsaActions = actions;

    if (!ChangeServiceConfig2A(handle, SERVICE_CONFIG_FAILURE_ACTIONS, &failure)) {
        // Installed but without automatic restart: worth saying, not worth
        // undoing the install over.
        std::cerr << "Warning: could not set restart-on-failure (" << describe(GetLastError())
                  << "). The service is installed but will not restart itself." << std::endl;
    }
}

void applyDescription(SC_HANDLE handle) {
    SERVICE_DESCRIPTIONA description{};
    description.lpDescription = const_cast<LPSTR>(Description);
    ChangeServiceConfig2A(handle, SERVICE_CONFIG_DESCRIPTION, &description);
}

bool stopIfRunning(SC_HANDLE handle) {
    SERVICE_STATUS status{};
    if (!QueryServiceStatus(handle, &status) || status.dwCurrentState == SERVICE_STOPPED) {
        return true;
    }

    std::cout << "Stopping " << DisplayName << "..." << std::endl;
    if (!ControlService(handle, SERVICE_CONTROL_STOP, &status)) {
        std::cerr << "Could not stop the service: " << describe(GetLastError()) << std::endl;
        return false;
    }

    // Deleting a running service leaves it marked for deletion until the next
    // reboot, and a reinstall in the meantime fails with a message that does
    // not mention any of this.
    for (int waited = 0; waited < 30; ++waited) {
        Sleep(500);
        if (!QueryServiceStatus(handle, &status) || status.dwCurrentState == SERVICE_STOPPED) {
            return true;
        }
    }

    std::cerr << "The service did not stop within 15 seconds." << std::endl;
    return false;
}

} // namespace

int install() {
    const std::string command = serviceCommand();
    if (command.empty()) {
        std::cerr << "Could not determine this executable's path." << std::endl;
        return ExitFailed;
    }

    SC_HANDLE manager = openManager(SC_MANAGER_CREATE_SERVICE, "install");
    if (manager == nullptr) {
        return ExitFailed;
    }

    SC_HANDLE handle = CreateServiceA(
        manager, ServiceName, DisplayName,
        SERVICE_CHANGE_CONFIG | SERVICE_START,
        SERVICE_WIN32_OWN_PROCESS,
        // Auto-start: the point of a service is that a reboot does not need
        // anybody to log in.
        SERVICE_AUTO_START,
        SERVICE_ERROR_NORMAL,
        command.c_str(),
        nullptr, nullptr, nullptr,
        // LocalSystem. The collectors read process and adapter information for
        // the whole machine, which a per-user account cannot see in full.
        nullptr, nullptr);

    if (handle == nullptr) {
        const DWORD error = GetLastError();
        CloseServiceHandle(manager);

        if (error == ERROR_SERVICE_EXISTS) {
            std::cerr << DisplayName << " is already installed. Run --uninstall first."
                      << std::endl;
        } else if (!reportAccessDenied(error, "install")) {
            std::cerr << "Could not install the service: " << describe(error) << std::endl;
        }
        return ExitFailed;
    }

    applyDescription(handle);
    applyRecoveryActions(handle);

    std::cout << "Installed " << DisplayName << " (" << ServiceName << ")\n"
              << "  " << command << "\n"
              << "It starts automatically at boot. Start it now with:\n"
              << "  sc start " << ServiceName << std::endl;

    CloseServiceHandle(handle);
    CloseServiceHandle(manager);
    return ExitOk;
}

int uninstall() {
    SC_HANDLE manager = openManager(SC_MANAGER_CONNECT, "uninstall");
    if (manager == nullptr) {
        return ExitFailed;
    }

    SC_HANDLE handle = OpenServiceA(manager, ServiceName, SERVICE_STOP | SERVICE_QUERY_STATUS | DELETE);
    if (handle == nullptr) {
        const DWORD error = GetLastError();
        CloseServiceHandle(manager);

        if (error == ERROR_SERVICE_DOES_NOT_EXIST) {
            // Not an error: uninstalling something that is not there is the
            // state the caller wanted.
            std::cout << DisplayName << " is not installed." << std::endl;
            return ExitOk;
        }
        if (!reportAccessDenied(error, "uninstall")) {
            std::cerr << "Could not open the service: " << describe(error) << std::endl;
        }
        return ExitFailed;
    }

    if (!stopIfRunning(handle)) {
        CloseServiceHandle(handle);
        CloseServiceHandle(manager);
        return ExitFailed;
    }

    const bool deleted = DeleteService(handle) != 0;
    const DWORD error = GetLastError();

    CloseServiceHandle(handle);
    CloseServiceHandle(manager);

    if (!deleted) {
        std::cerr << "Could not remove the service: " << describe(error) << std::endl;
        return ExitFailed;
    }

    std::cout << "Removed " << DisplayName << ". The log directory is left alone." << std::endl;
    return ExitOk;
}

} // namespace service

#else

namespace service {

int install() {
    std::cerr << "Windows Service installation is only available on Windows." << std::endl;
    return 1;
}

int uninstall() { return install(); }

} // namespace service

#endif
