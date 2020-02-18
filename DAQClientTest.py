#!/usr/bin/env python

import unittest
from DAQClient import DAQClient

from DAQMocks import MockCnCLogger, MockLogger


class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbean_port, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbean_port, connectors,
                                              quiet=True)

    def create_client(self, host, port):
        return None

    def create_logger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet)


class TestDAQClient(unittest.TestCase):
    def test_init(self):
        appender = MockLogger('test')
        MostlyDAQClient('foo', 0, 'localhost', 543, 0, [], appender)


if __name__ == '__main__':
    unittest.main()
