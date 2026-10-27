"""Route subsequent launcher invocations to the running process."""

import os
import tempfile
import time

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    """Use a local lock and socket to forward repeated launches.

    Attributes:
        activated (Signal): Emitted when another process requests activation.
    """
    activated = Signal()

    def __init__(self):
        """Prepare a user-specific socket path and its associated lock."""
        super().__init__()
        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        self.path = os.path.join(runtime, f"screenmask-{os.getuid()}.sock")
        self.lock = QLockFile(self.path + ".lock")
        self.server = None

    def start(self):
        """Start the server or forward activation to the existing process.

        Returns:
            bool: True for the primary instance; False after forwarding.

        Raises:
            RuntimeError: If the server cannot start or the primary instance
                fails to respond.
        """
        if not self.lock.tryLock(0):
            # The first instance may still be starting its server.
            for _ in range(30):
                socket = QLocalSocket()
                socket.connectToServer(self.path)
                if socket.waitForConnected(100):
                    socket.write(b"activate\n")
                    socket.flush()
                    socket.waitForBytesWritten(500)
                    socket.disconnectFromServer()
                    return False
                time.sleep(0.1)
            raise RuntimeError("ScreenMask is already running but did not respond.")

        QLocalServer.removeServer(self.path)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.path):
            self.lock.unlock()
            raise RuntimeError(f"Could not start ScreenMask control socket: {self.server.errorString()}")
        self.server.newConnection.connect(self.receive)
        return True

    def receive(self):
        """Emit an activation request for each pending local connection."""
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            # A connection is itself the activation request; no data is trusted.
            self.activated.emit()
            socket.disconnectFromServer()
            socket.deleteLater()

    def close(self):
        """Close the server, remove its socket, and release the lock."""
        if self.server is not None:
            self.server.close()
            QLocalServer.removeServer(self.path)
            self.server = None
            self.lock.unlock()
