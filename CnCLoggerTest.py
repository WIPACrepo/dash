#!/usr/bin/env python

import unittest
from CnCServer import CnCLogger

from DAQMocks import MockAppender, SocketReaderFactory

class CnCLoggerTest(unittest.TestCase):
    def createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__appender = MockAppender('mock')

    def tearDown(self):
        self.__logFactory.tearDown()

        self.__appender.checkStatus(10)

    def testOpenReset(self):
        dc = CnCLogger(self.__appender, True)

        logPort = 12345

        logObj = self.createLog('file', logPort)

        dc.openLog('localhost', logPort, None, None)
        self.assertEqual(dc.logHost(), 'localhost')
        self.assertEqual(dc.logPort(), logPort)
        self.assertEqual(dc.liveHost(), None)
        self.assertEqual(dc.livePort(), None)

        logObj.checkStatus(1000)

        dc.resetLog()
        self.failIf(dc.logHost() is not None, 'logIP was not cleared')
        self.failIf(dc.logPort() is not None, 'logPort was not cleared')

        logObj.checkStatus(1000)

    def testOpenResetLive(self):
        dc = CnCLogger(self.__appender, True)

        livePort = 6789

        liveObj = self.createLog('live', livePort, False)

        dc.openLog(None, None, 'localhost', livePort)
        self.assertEqual(dc.logHost(), None)
        self.assertEqual(dc.logPort(), None)
        self.assertEqual(dc.liveHost(), 'localhost')
        self.assertEqual(dc.livePort(), livePort)

        liveObj.checkStatus(1000)

        dc.resetLog()
        self.failIf(dc.liveHost() is not None, 'liveIP was not cleared')
        self.failIf(dc.livePort() is not None, 'livePort was not cleared')

        liveObj.checkStatus(1000)

    def testOpenResetBoth(self):
        dc = CnCLogger(self.__appender, True)

        logPort = 12345
        livePort = 6789

        logObj = self.createLog('file', logPort)
        liveObj = self.createLog('live', livePort, False)

        dc.openLog('localhost', logPort, 'localhost', livePort)
        self.assertEqual(dc.logHost(), 'localhost')
        self.assertEqual(dc.logPort(), logPort)
        self.assertEqual(dc.liveHost(), 'localhost')
        self.assertEqual(dc.livePort(), livePort)

        logObj.checkStatus(1000)
        liveObj.checkStatus(1000)

        dc.resetLog()
        self.failIf(dc.logHost() is not None, 'logIP was not cleared')
        self.failIf(dc.logPort() is not None, 'logPort was not cleared')
        self.failIf(dc.liveHost() is not None, 'liveIP was not cleared')
        self.failIf(dc.livePort() is not None, 'livePort was not cleared')

        logObj.checkStatus(1000)
        liveObj.checkStatus(1000)

    def testOpenClose(self):
        dc = CnCLogger(self.__appender, True)

        logHost = 'localhost'
        logPort = 12345

        logObj = self.createLog('file', logPort)

        dc.openLog(logHost, logPort, None, None)
        self.assertEqual(dc.logHost(), logHost)
        self.assertEqual(dc.logPort(), logPort)
        self.assertEqual(dc.liveHost(), None)
        self.assertEqual(dc.livePort(), None)

        logObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.failIf(dc.logHost() is not None, 'logIP was not cleared')
        self.failIf(dc.logPort() is not None, 'logPort was not cleared')
        self.failIf(dc.liveHost() is not None, 'liveIP was not cleared')
        self.failIf(dc.livePort() is not None, 'livePort was not cleared')

    def testOpenCloseLive(self):
        dc = CnCLogger(self.__appender, True)

        liveHost = 'localhost'
        livePort = 6789

        liveObj = self.createLog('live', livePort, False)

        dc.openLog(None, None, liveHost, livePort)
        self.assertEqual(dc.logHost(), None)
        self.assertEqual(dc.logPort(), None)
        self.assertEqual(dc.liveHost(), liveHost)
        self.assertEqual(dc.livePort(), livePort)

        liveObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.failIf(dc.logHost() is not None, 'logIP was not cleared')
        self.failIf(dc.logPort() is not None, 'logPort was not cleared')
        self.failIf(dc.liveHost() is not None, 'liveIP was not cleared')
        self.failIf(dc.livePort() is not None, 'livePort was not cleared')

    def testOpenCloseBoth(self):
        dc = CnCLogger(self.__appender, True)

        logHost = 'localhost'
        logPort = 12345
        liveHost = 'localhost'
        livePort = 6789

        logObj = self.createLog('file', logPort)
        liveObj = self.createLog('live', livePort, False)

        dc.openLog(logHost, logPort, liveHost, livePort)
        self.assertEqual(dc.logHost(), logHost)
        self.assertEqual(dc.logPort(), logPort)
        self.assertEqual(dc.liveHost(), liveHost)
        self.assertEqual(dc.livePort(), livePort)

        logObj.addExpectedTextRegexp('End of log')
        liveObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.failIf(dc.logHost() is not None, 'logIP was not cleared')
        self.failIf(dc.logPort() is not None, 'logPort was not cleared')
        self.failIf(dc.liveHost() is not None, 'liveIP was not cleared')
        self.failIf(dc.livePort() is not None, 'livePort was not cleared')

    def testLogFallback(self):
        dc = CnCLogger(self.__appender, True)

        dfltHost = 'localhost'
        dfltPort = 11111

        dfltObj = self.createLog('dflt', dfltPort)

        logHost = 'localhost'
        logPort = 12345

        logObj = self.createLog('file', logPort)

        dc.openLog(dfltHost, dfltPort, None, None)
        self.assertEqual(dc.logHost(), dfltHost)
        self.assertEqual(dc.logPort(), dfltPort)

        dfltObj.checkStatus(1000)

        dc.openLog(logHost, logPort, None, None)
        self.assertEqual(dc.logHost(), logHost)
        self.assertEqual(dc.logPort(), logPort)

        logObj.checkStatus(1000)

        logObj.addExpectedTextRegexp('End of log')
        dfltObj.addExpectedText('Reset log to %s:%d' % (dfltHost, dfltPort))

        dc.closeLog()
        self.assertEqual(dc.logHost(), dfltHost)
        self.assertEqual(dc.logPort(), dfltPort)

        logObj.checkStatus(1000)

        dfltObj.checkStatus(1000)

        newHost = 'localhost'
        newPort = 45678

        newObj = self.createLog('new', newPort)

        dc.openLog(newHost, newPort, None, None)
        self.assertEqual(dc.logHost(), newHost)
        self.assertEqual(dc.logPort(), newPort)

        dfltObj.checkStatus(1000)

        newObj.checkStatus(1000)

        newObj.addExpectedTextRegexp('End of log')
        dfltObj.addExpectedText('Reset log to %s:%d' % (dfltHost, dfltPort))

        dc.closeLog()
        self.assertEqual(dc.logHost(), dfltHost)
        self.assertEqual(dc.logPort(), dfltPort)

        newObj.checkStatus(1000)

        dfltObj.checkStatus(1000)

        dfltObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.assertEqual(dc.logHost(), None)
        self.assertEqual(dc.logPort(), None)

        dfltObj.checkStatus(1000)

    def testLogFallbackSwitch(self):
        dc = CnCLogger(self.__appender, True)

        dfltHost = 'localhost'
        dfltPort = 11111

        dfltObj = self.createLog('dflt', dfltPort)

        liveHost = 'localhost'
        livePort = 6789

        liveObj = self.createLog('live', livePort, False)

        dc.openLog(dfltHost, dfltPort, None, None)
        self.assertEqual(dc.logHost(), dfltHost)
        self.assertEqual(dc.logPort(), dfltPort)
        self.assertEqual(dc.liveHost(), None)
        self.assertEqual(dc.livePort(), None)

        dfltObj.checkStatus(1000)

        dc.openLog(None, None, liveHost, livePort)
        self.assertEqual(dc.logHost(), None)
        self.assertEqual(dc.logPort(), None)
        self.assertEqual(dc.liveHost(), liveHost)
        self.assertEqual(dc.livePort(), livePort)

        liveObj.checkStatus(1000)

        liveObj.addExpectedTextRegexp('End of log')
        dfltObj.addExpectedText('Reset log to %s:%d' % (dfltHost, dfltPort))

        dc.closeLog()
        self.assertEqual(dc.logHost(), dfltHost)
        self.assertEqual(dc.logPort(), dfltPort)
        self.assertEqual(dc.liveHost(), None)
        self.assertEqual(dc.livePort(), None)

        liveObj.checkStatus(1000)

        dfltObj.checkStatus(1000)

        newHost = 'localhost'
        newPort = 45678

        newObj = self.createLog('new', newPort)

        dc.openLog(newHost, newPort, None, None)
        self.assertEqual(dc.logHost(), newHost)
        self.assertEqual(dc.logPort(), newPort)

        dfltObj.checkStatus(1000)

        newObj.checkStatus(1000)

        newObj.addExpectedTextRegexp('End of log')
        dfltObj.addExpectedText('Reset log to %s:%d' % (dfltHost, dfltPort))

        dc.closeLog()
        self.assertEqual(dc.logHost(), dfltHost)
        self.assertEqual(dc.logPort(), dfltPort)

        newObj.checkStatus(1000)

        dfltObj.checkStatus(1000)

        dfltObj.addExpectedTextRegexp('End of log')

        dc.closeLog()
        self.assertEqual(dc.logHost(), None)
        self.assertEqual(dc.logPort(), None)

        dfltObj.checkStatus(1000)

if __name__ == '__main__':
    unittest.main()
