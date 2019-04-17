#!/usr/bin/env python

import datetime
import os
import tempfile
import time
import unittest
from DAQLog import LogSocketServer

from DAQMocks import SocketWriter


class TestDAQLog(unittest.TestCase):
    "Test DAQLog class"
    DIR_PATH = None

    def __check_log(self, log_path, msg_list):
        "Compare log file lines against original log messages"
        lines = self.__read_log(log_path)
        self.assertEqual(len(msg_list), len(lines), 'Expected %d line, not %d' %
                         (len(msg_list), len(lines)))

        for idx, msg in enumerate(msg_list):
            msg = msg.rstrip()
            line = lines[idx].rstrip()
            self.assertEqual(line, msg,
                             'Expected "%s", not "%s"' % (msg, line))

    @classmethod
    def __read_log(cls, log_path):
        "Return log file contents as a list of strings"
        lines = []
        with open(log_path, 'r') as fin:
            for line in fin:
                lines.append(line.rstrip())
        return lines

    def setUp(self):
        self.__sock_log = None

        TestDAQLog.DIR_PATH = tempfile.mkdtemp()

    def tearDown(self):
        if self.__sock_log is not None:
            self.__sock_log.stop_serving()

        time.sleep(0.1)

        for root, dirs, files in os.walk(TestDAQLog.DIR_PATH, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(TestDAQLog.DIR_PATH)
        TestDAQLog.DIR_PATH = None

    def test_log_socket_server(self):
        "Test LogSocketServer"
        port = 5432
        cname = 'foo'
        log_path = os.path.join(TestDAQLog.DIR_PATH, cname + '.log')

        self.__sock_log = LogSocketServer(port, cname, log_path, True)
        self.__sock_log.start_serving()
        for _ in range(5):
            if self.__sock_log.is_serving:
                break
            time.sleep(0.1)
        self.assertTrue(os.path.exists(log_path), 'Log file was not created')
        self.assertTrue(self.__sock_log.is_serving,
                        'Log server was not started')

        now = datetime.datetime.now()
        msg = 'Test 1 2 3'

        client = SocketWriter('localhost', port)
        client.write_ts(msg, now)

        client.close()

        self.__sock_log.stop_serving()

        self.__check_log(log_path, ('%s - - [%s] %s' % (cname, now, msg), ))


if __name__ == '__main__':
    unittest.main()
