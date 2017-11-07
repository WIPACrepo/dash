#!/usr/bin/env python

import traceback
import unittest
from CnCLogger import CnCLogger

from DAQMocks import MockAppender, SocketReaderFactory


class CnCLoggerTest(unittest.TestCase):
    def createLog(self, name, port):
        return self.__logFactory.createLog(name, port, False)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__appender = MockAppender("mock")

    def tearDown(self):
        try:
            self.__logFactory.tearDown()
        except:
            traceback.print_exc()

        self.__appender.checkStatus(10)

    def testOpenReset(self):
        dfltHost = "localhost"
        dfltPort = 54321

        dfltObj = self.createLog("dflt", dfltPort)

        logHost = "localhost"
        logPort = 12345

        logObj = self.createLog("file", logPort)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extraLoud=xl)

            # set up default logger
            dfltObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                    (dfltHost, dfltPort))
            dc.openLog(dfltHost, dfltPort, None, None)

            # set up file logger
            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (logHost, logPort))
            dc.openLog(logHost, logPort, None, None)

            self.assertEqual(dc.logHost, logHost)
            self.assertEqual(dc.logPort, logPort)
            self.assertEqual(dc.liveHost, None)
            self.assertEqual(dc.livePort, None)

            logObj.checkStatus(1000)
            dfltObj.checkStatus(1000)

            if xl:
                dfltObj.addExpectedText("Reset log to LOG=log(%s:%d)" %
                                        (dfltHost, dfltPort))

            dc.resetLog()
            self.assertFalse(dc.liveHost is not None,
                             "logIP was not cleared")
            self.assertFalse(dc.livePort is not None,
                             "logPort was not cleared")
            self.assertEqual(dc.logHost, dfltHost,
                             "logHost should be %s, not %s" %
                             (dfltHost, dc.logHost))
            self.assertEqual(dc.logPort, dfltPort,
                             "logPort should be %s, not %s" %
                             (dfltPort, dc.logPort))

            logObj.checkStatus(1000)
            dfltObj.checkStatus(1000)

    def testOpenResetLive(self):
        dfltHost = "localhost"
        dfltPort = 54321

        dfltObj = self.createLog("dflt", dfltPort)

        logHost = "localhost"
        logPort = 6789

        logObj = self.createLog("log", logPort)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extraLoud=xl)

            dfltObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                    (dfltHost, dfltPort))

            # set up default logger
            dc.openLog(dfltHost, dfltPort, None, None)

            dfltObj.checkStatus(1000)
            logObj.checkStatus(1000)

            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (logHost, logPort))

            dc.openLog(logHost, logPort, None, None)
            self.assertEqual(dc.liveHost, None)
            self.assertEqual(dc.livePort, None)
            self.assertEqual(dc.logHost, logHost)
            self.assertEqual(dc.logPort, logPort)

            dfltObj.checkStatus(1000)
            logObj.checkStatus(1000)

            if xl:
                dfltObj.addExpectedText("Reset log to LOG=log(%s:%d)" %
                                        (dfltHost, dfltPort))

            dc.resetLog()
            self.assertEqual(dc.logHost, dfltHost,
                             "logHost should be %s, not %s" %
                             (dfltHost, dc.logHost))
            self.assertEqual(dc.logPort, dfltPort,
                             "logPort should be %s, not %s" %
                             (dfltPort, dc.logPort))
            self.assertFalse(dc.liveHost is not None,
                             "liveIP was not cleared")
            self.assertFalse(dc.livePort is not None,
                             "livePort was not cleared")

            logObj.checkStatus(1000)
            dfltObj.checkStatus(1000)

    def testOpenResetBoth(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        host = "localhost"
        logPort = 12345
        livePort = 6789

        logObj = self.createLog("file", logPort)
        liveObj = self.createLog("live", livePort)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extraLoud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)
            logObj.checkStatus(1000)
            liveObj.checkStatus(1000)

            logObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                    " live(%s:%d)") %
                                   (host, logPort, host, livePort))

            dc.openLog(host, logPort, host, livePort)
            self.assertEqual(dc.logHost, host)
            self.assertEqual(dc.logPort, logPort)
            self.assertEqual(dc.liveHost, host)
            self.assertEqual(dc.livePort, livePort)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)
            logObj.checkStatus(1000)
            liveObj.checkStatus(1000)

            if xl:
                dLogObj.addExpectedText(("Reset log to LOG=log(%s:%d)" +
                                         " live(%s:%d)") %
                                        (dfltHost, dfltLog,
                                         dfltHost, dfltLive))

            dc.resetLog()
            self.assertEqual(dc.logHost, dfltHost,
                             "logHost should be %s, not %s" %
                             (dfltHost, dc.logHost))
            self.assertEqual(dc.logPort, dfltLog,
                             "logPort should be %s, not %s" %
                             (dfltLog, dc.logPort))
            self.assertEqual(dc.liveHost, dfltHost,
                             "liveHost should be %s, not %s" %
                             (dfltHost, dc.liveHost))
            self.assertEqual(dc.livePort, dfltLive,
                             "livePort should be %s, not %s" %
                             (dfltLive, dc.livePort))

            logObj.checkStatus(1000)
            liveObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

    def testOpenClose(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        logHost = "localhost"
        logPort = 12345

        logObj = self.createLog("file", logPort)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extraLoud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (logHost, logPort))

            dc.openLog(logHost, logPort, None, None)
            self.assertEqual(dc.logHost, logHost)
            self.assertEqual(dc.logPort, logPort)
            self.assertEqual(dc.liveHost, None)
            self.assertEqual(dc.livePort, None)

            logObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            if xl:
                logObj.addExpectedText("End of log")
                dLogObj.addExpectedText(("Reset log to LOG=log(%s:%d)" +
                                         " live(%s:%d)") %
                                        (dfltHost, dfltLog,
                                         dfltHost, dfltLive))

            dc.closeLog()
            self.assertEqual(dc.logHost, dfltHost,
                             "logHost should be %s, not %s" %
                             (dfltHost, dc.logHost))
            self.assertEqual(dc.logPort, dfltLog,
                             "logPort should be %s, not %s" %
                             (dfltLog, dc.logPort))
            self.assertEqual(dc.liveHost, dfltHost,
                             "liveHost should be %s, not %s" %
                             (dfltHost, dc.liveHost))
            self.assertEqual(dc.livePort, dfltLive,
                             "livePort should be %s, not %s" %
                             (dfltLive, dc.livePort))

            logObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

    def testOpenCloseLive(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        liveHost = "localhost"
        livePort = 6789

        liveObj = self.createLog("live", livePort)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extraLoud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            dc.openLog(None, None, liveHost, livePort)
            self.assertEqual(dc.logHost, None)
            self.assertEqual(dc.logPort, None)
            self.assertEqual(dc.liveHost, liveHost)
            self.assertEqual(dc.livePort, livePort)

            liveObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            if xl:
                dLogObj.addExpectedText(("Reset log to LOG=log(%s:%d)" +
                                         " live(%s:%d)") %
                                        (dfltHost, dfltLog,
                                         dfltHost, dfltLive))

            dc.closeLog()
            self.assertEqual(dc.logHost, dfltHost,
                             "logHost should be %s, not %s" %
                             (dfltHost, dc.logHost))
            self.assertEqual(dc.logPort, dfltLog,
                             "logPort should be %s, not %s" %
                             (dfltLog, dc.logPort))
            self.assertEqual(dc.liveHost, dfltHost,
                             "liveHost should be %s, not %s" %
                             (dfltHost, dc.liveHost))
            self.assertEqual(dc.livePort, dfltLive,
                             "livePort should be %s, not %s" %
                             (dfltLive, dc.livePort))

            liveObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

    def testOpenCloseBoth(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        logHost = "localhost"
        logPort = 12345
        liveHost = ""
        livePort = 0

        logObj = self.createLog("file", logPort)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extraLoud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (logHost, logPort))

            dc.openLog(logHost, logPort, liveHost, livePort)
            self.assertEqual(dc.logHost, logHost)
            self.assertEqual(dc.logPort, logPort)
            self.assertEqual(dc.liveHost, liveHost)
            self.assertEqual(dc.livePort, livePort)

            if xl:
                logObj.addExpectedTextRegexp("End of log")
                dLogObj.addExpectedText(("Reset log to LOG=log(%s:%d)" +
                                         " live(%s:%d)") %
                                        (dfltHost, dfltLog,
                                         dfltHost, dfltLive))

            dc.closeLog()
            self.assertEqual(dc.logHost, dfltHost,
                             "logHost should be %s, not %s" %
                             (dfltHost, dc.logHost))
            self.assertEqual(dc.logPort, dfltLog,
                             "logPort should be %s, not %s" %
                             (dfltLog, dc.logPort))
            self.assertEqual(dc.liveHost, dfltHost,
                             "liveHost should be %s, not %s" %
                             (dfltHost, dc.liveHost))
            self.assertEqual(dc.livePort, dfltLive,
                             "livePort should be %s, not %s" %
                             (dfltLive, dc.livePort))

            logObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)


if __name__ == "__main__":
    unittest.main()
