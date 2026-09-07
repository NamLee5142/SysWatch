"""Real servers on real sockets, for the tests that need one.

Not doubles. `alert_doubles.py` holds the fakes, and most delivery tests
correctly use them - a test about what the engine does when delivery fails has
no business waiting on a TCP handshake.

These exist for the small number of claims a double cannot support, because a
double is written by the same person as the code it stands in for. "Credentials
are never sent to a server that will not encrypt" is a statement about what
leaves the machine, and the only way to know is to have something else receive
it. So is "the message a real MTA sees is well formed", and so is "the webhook
token never reaches the log", which passes trivially against a transport that
was intercepted before it opened a connection.

The argument gets stronger, not weaker, when agents start pushing to the
backend: that is C++ serialisation consumed by Pydantic across a socket, and a
Python fake of the agent will always produce exactly what its Python author
expected the C++ to produce. WebhookServer is already the shape of a backend
receiving a push - see docs/decisions/0001-agents-push-to-the-backend.md.

Everything here listens on an ephemeral port on loopback and is torn down with
the test. Nothing is left running and no fixed port is claimed.
"""
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def free_port():
    """A port the OS has just confirmed is free.

    Racy in principle, and the alternative - a hard-coded port - is worse: it
    collides with whatever a developer happens to be running, and on CI it
    collides with the other test that hard-coded the same number.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --- SMTP -------------------------------------------------------------------


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Enough of RFC 5321 for smtplib to complete a delivery."""

    def handle(self):
        self.wfile.write(b"220 localhost ESMTP\r\n")
        sender, recipients = None, []

        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode("utf-8", "replace").strip()
            verb = command.upper()

            if verb.startswith("EHLO"):
                extensions = [b"250-localhost", b"250-SIZE 10240000"]
                if self.server.offer_starttls:
                    extensions.append(b"250-STARTTLS")
                # AUTH is advertised deliberately, and it is what makes the
                # refusal test mean anything: against a server offering no
                # AUTH, smtplib declines to authenticate on its own, and the
                # test would pass even with the refusal deleted from smtp.py.
                extensions.append(b"250-AUTH PLAIN LOGIN")
                extensions.append(b"250 HELP")
                self.wfile.write(b"\r\n".join(extensions) + b"\r\n")
            elif verb.startswith("HELO"):
                self.wfile.write(b"250 localhost\r\n")
            elif verb.startswith("MAIL FROM"):
                sender = command.split(":", 1)[1].split()[0].strip()
                self.wfile.write(b"250 OK\r\n")
            elif verb.startswith("RCPT TO"):
                recipients.append(command.split(":", 1)[1].split()[0].strip())
                self.wfile.write(b"250 OK\r\n")
            elif verb == "DATA":
                self.wfile.write(b"354 End with <CRLF>.<CRLF>\r\n")
                body = b""
                while True:
                    chunk = self.rfile.readline()
                    if not chunk or chunk in (b".\r\n", b".\n"):
                        break
                    body += chunk
                self.server.delivered.append(
                    {"sender": sender, "recipients": list(recipients), "data": body}
                )
                self.wfile.write(b"250 OK queued\r\n")
            elif verb.startswith("AUTH"):
                # Recorded rather than accepted. A test asserts this never
                # happens, and it can only assert that from the receiving end.
                self.server.auth_attempted = True
                self.wfile.write(b"535 Authentication failed\r\n")
            elif verb == "QUIT":
                self.wfile.write(b"221 Bye\r\n")
                return
            else:
                self.wfile.write(b"250 OK\r\n")


class SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port, offer_starttls=False):
        super().__init__(("127.0.0.1", port), _SmtpHandler)
        self.port = port
        self.offer_starttls = offer_starttls
        self.delivered = []
        self.auth_attempted = False


# --- HTTP -------------------------------------------------------------------


class _WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.received.append(
            {
                "path": self.path,
                "content_type": self.headers.get("Content-Type"),
                "body": self.rfile.read(length).decode("utf-8"),
            }
        )
        self.send_response(self.server.status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        # BaseHTTPRequestHandler writes every request to stderr otherwise, and
        # the request line contains the webhook path - which is the credential
        # these tests are checking never gets written anywhere.
        pass


class WebhookServer(HTTPServer):
    def __init__(self, port, status=200):
        super().__init__(("127.0.0.1", port), _WebhookHandler)
        self.port = port
        self.status = status
        self.received = []
