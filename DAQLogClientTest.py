#!/usr/bin/env python
"""
Test the DAQ log client
"""

import os
import tempfile
import time
import unittest
from DAQLog import FileAppender


class TestDAQLogClient(unittest.TestCase):
    "Test the DAQ log client"

    DIR_PATH = None

    @classmethod
    def read_log(cls, log_path):
        "Return a list of text lines from 'log_path'"
        lines = []
        with open(log_path, 'r') as fin:
            for line in fin:
                lines.append(line.rstrip())
            return lines

    def setUp(self):
        self.collector = None

        TestDAQLogClient.DIR_PATH = tempfile.mkdtemp()

    def tearDown(self):
        if self.collector is not None:
            self.collector.close()

        time.sleep(0.1)

        for root, dirs, files in os.walk(TestDAQLogClient.DIR_PATH,
                                         topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(TestDAQLogClient.DIR_PATH)
        TestDAQLogClient.DIR_PATH = None

    def test_daq_log_client(self):
        "Test FileAppender"
        log_name = 'foo'
        log_path = os.path.join(TestDAQLogClient.DIR_PATH, "dash.log")

        self.collector = FileAppender(log_name, log_path)

        self.assertTrue(os.path.exists(log_path), 'Log file was not created')

        msg = 'Test msg'

        self.collector.write(msg)

        self.collector.close()

        lines = self.read_log(log_path)
        self.assertEqual(1, len(lines), 'Expected 1 line, not %d' % len(lines))

        prefix = log_name + ' ['

        line = lines[0].rstrip()
        self.assertTrue(line.startswith(prefix),
                        'Log entry "%s" should start with "%s"' %
                        (line, prefix))
        self.assertTrue(line.endswith('] ' + msg),
                        'Log entry "%s" should start with "%s"' %
                        (line, '] ' + msg))

    def test_daq_log_client_bad_path(self):
        "Test FileAppender bad path handling"
        log_name = 'foo'
        bad_path = os.path.join('a', 'bad', 'path')
        while os.path.exists(bad_path):
            bad_path = os.path.join(bad_path, 'x')

        self.assertRaises(Exception, FileAppender, log_name, bad_path)


if __name__ == '__main__':
    unittest.main()
