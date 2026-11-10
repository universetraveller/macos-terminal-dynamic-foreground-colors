import os
import sys
import threading
import unittest
from unittest import mock

try:
    import termios
    import terminal_color_probe as probe
except ImportError:
    termios = None
    probe = None


@unittest.skipIf(probe is None, 'TTY probe requires POSIX termios')
class ReplyParsing(unittest.TestCase):
    def test_bel_st_and_channel_widths(self):
        reply = (b'\x1b]4;12;rgb:0000/0000/ffff\x07'
                 b'\x1b]11;rgb:1e/1e/1e\x1b\\'
                 b'\x1b]10;rgb:f/f/f\x07')
        values = probe.parse_replies(reply)
        self.assertEqual(values[12], (0, 0, 1))
        self.assertEqual(values['bg'], (30/255,)*3)
        self.assertEqual(values['fg'], (1, 1, 1))

    def test_fragment_requires_complete_terminator(self):
        reply = b'\x1b]4;4;rgb:0000/0000/B333\x1b\\'
        self.assertEqual(probe.parse_replies(reply[:-1]), {})
        self.assertEqual(probe.parse_replies(reply)[4], (0, 0, 0xB333/65535))


@unittest.skipUnless(probe is not None and hasattr(os, 'openpty'), 'PTY test requires POSIX')
class TerminalCleanup(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()
        self.original = termios.tcgetattr(self.slave)
        self.patcher = mock.patch.object(probe, 'open', self.open_terminal, create=True)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        os.close(self.master)
        os.close(self.slave)

    def open_terminal(self, path, *args, **kwargs):
        self.assertEqual(path, '/dev/tty')
        return os.fdopen(os.dup(self.slave), 'r+b', buffering=0)

    def assert_terminal_restored(self):
        restored = termios.tcgetattr(self.slave)
        original = self.original.copy()
        if sys.platform == 'darwin':
            # macOS sets PENDIN when restoring canonical input mode.
            restored[3] &= ~termios.PENDIN
            original[3] &= ~termios.PENDIN
        self.assertEqual(restored, original)

    def test_fragmented_query_and_tty_restore(self):
        reply = b''.join(f'\x1b]4;{i};rgb:0000/0000/ffff\x07'.encode()
                         for i in range(16))
        reply += b'\x1b]10;rgb:0000/0000/0000\x07\x1b]11;rgb:ffff/ffff/ffff\x07'
        errors = []

        def respond():
            try:
                query = b''
                while query.count(b'\x07') < 18:
                    query += os.read(self.master, 8192)
                if query.count(b'\x1b]4;') != 16:
                    raise AssertionError('Expected sixteen palette queries')
                os.write(self.master, reply[:37])
                os.write(self.master, reply[37:])
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=respond, daemon=True)
        worker.start()
        values = probe.query_palette(timeout=1)
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(values), 18)
        self.assertEqual(values['bg'], (1, 1, 1))
        self.assert_terminal_restored()

    def test_tty_restore_after_timeout(self):
        self.assertEqual(probe.query_palette(timeout=.02), {})
        self.assert_terminal_restored()

    def test_tty_restore_after_read_error(self):
        with mock.patch.object(probe.select, 'select', side_effect=OSError('simulated')):
            with self.assertRaises(OSError):
                probe.query_palette(timeout=.02)
        self.assert_terminal_restored()


if __name__ == '__main__':
    unittest.main()
