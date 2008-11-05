#!/usr/bin/env python

import unittest
from CnCServer import CnCLogger

from DAQMocks import MockAppender, SocketReaderFactory

class CnCLoggerTest(unittest.TestCase):
    def createLog(self, name, port):
        return self.__logFactory.createLog(name, port)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__appender = MockAppender('mock')

    def tearDown(self):
        self.__logFactory.tearDown()

        self.__appender.checkEmpty()

    def testOpenReset(self):
        dc = CnCLogger(self.__appender, True)

        logPort = 12345

        logObj = self.createLog('main', logPort)

        dc.openLog('localhost', logPort)
        self.assertEqual(dc.getLogHost(), 'localhost')
        self.assertEqual(dc.getLogPort(), logPort)
        self.failIf(dc.getPreviousHost() is not None, 'prevHost is not empty')
        self.failIf(dc.getPreviousPort() is not None, 'prevPort is not empty')

        logObj.waitForEmpty(1000)
        logObj.checkEmpty()

        dc.resetLog()
        self.failIf(dc.getLogHost() is not None, 'logIP was not cleared')
        self.failIf(dc.getLogPort() is not None, 'logPort was not cleared')
        self.failIf(dc.getPreviousHost() is not None,
                    'prevHost was not cleared')
        self.failIf(dc.getPreviousPort() is not None,
                    'prevPort was not cleared')

        logObj.checkEmpty()

    def testOpenClose(self):
        dc = CnCLogger(self.__appender, True)

        logHost = 'localhost'
        logPort = 12345

        logObj = self.createLog('main', logPort)

        dc.openLog(logHost, logPort)
        self.assertEqual(dc.getLogHost(), logHost)
        self.assertEqual(dc.getLogPort(), logPort)
        self.failIf(dc.getPreviousHost() is not None, 'prevHost is not empty')
        self.failIf(dc.getPreviousPort() is not None, 'prevPort is not empty')

        logObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.failIf(dc.getLogHost() is not None, 'logIP was not cleared')
        self.failIf(dc.getLogPort() is not None, 'logPort was not cleared')
        self.failIf(dc.getPreviousHost() is not None,
                    'prevHost was not cleared')
        self.failIf(dc.getPreviousPort() is not None,
                    'prevPort was not cleared')

    def testLogFallback(self):
        dc = CnCLogger(self.__appender, True)

        dfltHost = 'localhost'
        dfltPort = 11111

        dfltObj = self.createLog('dflt', dfltPort)

        logHost = 'localhost'
        logPort = 12345

        logObj = self.createLog('main', logPort)

        dc.openLog(dfltHost, dfltPort)
        self.assertEqual(dc.getLogHost(), dfltHost)
        self.assertEqual(dc.getLogPort(), dfltPort)
        self.failIf(dc.getPreviousHost() is not None, 'prevHost is not empty')
        self.failIf(dc.getPreviousPort() is not None, 'prevPort is not empty')

        dfltObj.waitForEmpty(1000)
        dfltObj.checkEmpty()

        dc.openLog(logHost, logPort)
        self.assertEqual(dc.getLogHost(), logHost)
        self.assertEqual(dc.getLogPort(), logPort)
        self.assertEqual(dc.getPreviousHost(), dfltHost)
        self.assertEqual(dc.getPreviousPort(), dfltPort)

        logObj.waitForEmpty(1000)
        logObj.checkEmpty()

        logObj.addExpectedTextRegexp('End of log')
        dfltObj.addExpectedText('Reset log to %s:%d' % (dfltHost, dfltPort))

        dc.closeLog()
        self.assertEqual(dc.getLogHost(), dfltHost)
        self.assertEqual(dc.getLogPort(), dfltPort)
        self.failIf(dc.getPreviousHost() is not None,
                    'prevHost was not cleared')
        self.failIf(dc.getPreviousPort() is not None,
                    'prevPort was not cleared')

        logObj.waitForEmpty(1000)
        logObj.checkEmpty()

        dfltObj.waitForEmpty(1000)
        dfltObj.checkEmpty()

        newHost = 'localhost'
        newPort = 45678

        newObj = self.createLog('new', newPort)

        dc.openLog(newHost, newPort)
        self.assertEqual(dc.getLogHost(), newHost)
        self.assertEqual(dc.getLogPort(), newPort)
        self.assertEqual(dc.getPreviousHost(), dfltHost)
        self.assertEqual(dc.getPreviousPort(), dfltPort)

        dfltObj.waitForEmpty(1000)
        dfltObj.checkEmpty()

        newObj.waitForEmpty(1000)
        newObj.checkEmpty()

        newObj.addExpectedTextRegexp('End of log')
        dfltObj.addExpectedText('Reset log to %s:%d' % (dfltHost, dfltPort))

        dc.closeLog()
        self.assertEqual(dc.getLogHost(), dfltHost)
        self.assertEqual(dc.getLogPort(), dfltPort)
        self.failIf(dc.getPreviousHost() is not None,
                    'prevHost was not cleared')
        self.failIf(dc.getPreviousPort() is not None,
                    'prevPort was not cleared')

        newObj.waitForEmpty(1000)
        newObj.checkEmpty()

        dfltObj.waitForEmpty(1000)
        dfltObj.checkEmpty()

        dfltObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.assertEqual(dc.getLogHost(), None)
        self.assertEqual(dc.getLogPort(), None)

        dfltObj.waitForEmpty(1000)
        dfltObj.checkEmpty()

if __name__ == '__main__':
    unittest.main()
