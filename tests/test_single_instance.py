# Author: Patricio Labin Correa <plabin@outlook.cl>
"""Exercise launcher activation between separate processes."""

import os
import socket
import subprocess
import sys
import tempfile
import unittest


class SingleInstanceTests(unittest.TestCase):
    """Check communication between primary and secondary instances."""

    def test_second_process_activates_first(self):
        """Forward a second process's activation request to the first."""
        # Some restricted environments prohibit Unix sockets entirely.
        with tempfile.TemporaryDirectory() as probe_dir:
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.bind(os.path.join(probe_dir, "probe.sock"))
            except PermissionError:
                self.skipTest("Unix-domain sockets are blocked in this environment")
            finally:
                probe.close()
        server_code = """
from PySide6.QtCore import QCoreApplication, QTimer
from screenmask.single_instance import SingleInstance
app = QCoreApplication([])
instance = SingleInstance()
assert instance.start()
def activated():
    print('activated', flush=True)
    app.quit()
instance.activated.connect(activated)
QTimer.singleShot(10000, app.quit)
print('ready', flush=True)
app.exec()
instance.close()
"""
        client_code = """
from PySide6.QtCore import QCoreApplication
from screenmask.single_instance import SingleInstance
app = QCoreApplication([])
instance = SingleInstance()
assert not instance.start()
"""
        with tempfile.TemporaryDirectory() as runtime:
            env = os.environ.copy()
            env["XDG_RUNTIME_DIR"] = runtime
            server = subprocess.Popen([sys.executable, "-c", server_code], env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(server.stdout.readline().strip(), "ready")
                client = subprocess.run([sys.executable, "-c", client_code], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(client.returncode, 0, client.stderr)
                output, errors = server.communicate(timeout=10)
                self.assertEqual(server.returncode, 0, errors)
                self.assertIn("activated", output)
            finally:
                if server.poll() is None:
                    server.kill()
                server.communicate()


if __name__ == "__main__":
    unittest.main()
