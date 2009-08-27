#!/usr/bin/env python

import unittest
from CnCServer import DAQClient

from DAQMocks import MockAppender, MockCnCLogger

class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet)

class TestDAQClient(unittest.TestCase):
    def testInit(self):
        appender = MockAppender('test')
        MostlyDAQClient('foo', 0, 'localhost', 543, 0, [], appender)

if __name__ == '__main__':
    unittest.main()
