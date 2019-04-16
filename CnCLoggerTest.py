#!/usr/bin/env python

import traceback
import unittest
from CnCLogger import CnCLogger

from DAQMocks import MockLogger, SocketReaderFactory


class CnCLoggerTest(unittest.TestCase):
    def createLog(self, name, port):
        return self.__logFactory.createLog(name, port, False)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__appender = MockLogger("mock")

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

        log_host = "localhost"
        log_port = 12345

        logObj = self.createLog("file", log_port)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extra_loud=xl)

            # set up default logger
            dfltObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                    (dfltHost, dfltPort))
            dc.openLog(dfltHost, dfltPort, None, None)

            # set up file logger
            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (log_host, log_port))
            dc.openLog(log_host, log_port, None, None)

            self.assertEqual(dc.log_host, log_host)
            self.assertEqual(dc.log_port, log_port)
            self.assertEqual(dc.live_host, None)
            self.assertEqual(dc.live_port, None)

            logObj.checkStatus(1000)
            dfltObj.checkStatus(1000)

            if xl:
                dfltObj.addExpectedText("Reset log to LOG=log(%s:%d)" %
                                        (dfltHost, dfltPort))

            dc.resetLog()
            self.assertFalse(dc.live_host is not None,
                             "logIP was not cleared")
            self.assertFalse(dc.live_port is not None,
                             "log_port was not cleared")
            self.assertEqual(dc.log_host, dfltHost,
                             "log_host should be %s, not %s" %
                             (dfltHost, dc.log_host))
            self.assertEqual(dc.log_port, dfltPort,
                             "log_port should be %s, not %s" %
                             (dfltPort, dc.log_port))

            logObj.checkStatus(1000)
            dfltObj.checkStatus(1000)

    def testOpenResetLive(self):
        dfltHost = "localhost"
        dfltPort = 54321

        dfltObj = self.createLog("dflt", dfltPort)

        log_host = "localhost"
        log_port = 6789

        logObj = self.createLog("log", log_port)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extra_loud=xl)

            dfltObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                    (dfltHost, dfltPort))

            # set up default logger
            dc.openLog(dfltHost, dfltPort, None, None)

            dfltObj.checkStatus(1000)
            logObj.checkStatus(1000)

            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (log_host, log_port))

            dc.openLog(log_host, log_port, None, None)
            self.assertEqual(dc.live_host, None)
            self.assertEqual(dc.live_port, None)
            self.assertEqual(dc.log_host, log_host)
            self.assertEqual(dc.log_port, log_port)

            dfltObj.checkStatus(1000)
            logObj.checkStatus(1000)

            if xl:
                dfltObj.addExpectedText("Reset log to LOG=log(%s:%d)" %
                                        (dfltHost, dfltPort))

            dc.resetLog()
            self.assertEqual(dc.log_host, dfltHost,
                             "log_host should be %s, not %s" %
                             (dfltHost, dc.log_host))
            self.assertEqual(dc.log_port, dfltPort,
                             "log_port should be %s, not %s" %
                             (dfltPort, dc.log_port))
            self.assertFalse(dc.live_host is not None,
                             "liveIP was not cleared")
            self.assertFalse(dc.live_port is not None,
                             "live_port was not cleared")

            logObj.checkStatus(1000)
            dfltObj.checkStatus(1000)

    def testOpenResetBoth(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        host = "localhost"
        log_port = 12345
        live_port = 6789

        logObj = self.createLog("file", log_port)
        liveObj = self.createLog("live", live_port)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extra_loud=xl)

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
                                   (host, log_port, host, live_port))

            dc.openLog(host, log_port, host, live_port)
            self.assertEqual(dc.log_host, host)
            self.assertEqual(dc.log_port, log_port)
            self.assertEqual(dc.live_host, host)
            self.assertEqual(dc.live_port, live_port)

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
            self.assertEqual(dc.log_host, dfltHost,
                             "log_host should be %s, not %s" %
                             (dfltHost, dc.log_host))
            self.assertEqual(dc.log_port, dfltLog,
                             "log_port should be %s, not %s" %
                             (dfltLog, dc.log_port))
            self.assertEqual(dc.live_host, dfltHost,
                             "live_host should be %s, not %s" %
                             (dfltHost, dc.live_host))
            self.assertEqual(dc.live_port, dfltLive,
                             "live_port should be %s, not %s" %
                             (dfltLive, dc.live_port))

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

        log_host = "localhost"
        log_port = 12345

        logObj = self.createLog("file", log_port)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extra_loud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (log_host, log_port))

            dc.openLog(log_host, log_port, None, None)
            self.assertEqual(dc.log_host, log_host)
            self.assertEqual(dc.log_port, log_port)
            self.assertEqual(dc.live_host, None)
            self.assertEqual(dc.live_port, None)

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
            self.assertEqual(dc.log_host, dfltHost,
                             "log_host should be %s, not %s" %
                             (dfltHost, dc.log_host))
            self.assertEqual(dc.log_port, dfltLog,
                             "log_port should be %s, not %s" %
                             (dfltLog, dc.log_port))
            self.assertEqual(dc.live_host, dfltHost,
                             "live_host should be %s, not %s" %
                             (dfltHost, dc.live_host))
            self.assertEqual(dc.live_port, dfltLive,
                             "live_port should be %s, not %s" %
                             (dfltLive, dc.live_port))

            logObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

    def testOpenCloseLive(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        live_host = "localhost"
        live_port = 6789

        liveObj = self.createLog("live", live_port)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extra_loud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            dc.openLog(None, None, live_host, live_port)
            self.assertEqual(dc.log_host, None)
            self.assertEqual(dc.log_port, None)
            self.assertEqual(dc.live_host, live_host)
            self.assertEqual(dc.live_port, live_port)

            liveObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            if xl:
                dLogObj.addExpectedText(("Reset log to LOG=log(%s:%d)" +
                                         " live(%s:%d)") %
                                        (dfltHost, dfltLog,
                                         dfltHost, dfltLive))

            dc.closeLog()
            self.assertEqual(dc.log_host, dfltHost,
                             "log_host should be %s, not %s" %
                             (dfltHost, dc.log_host))
            self.assertEqual(dc.log_port, dfltLog,
                             "log_port should be %s, not %s" %
                             (dfltLog, dc.log_port))
            self.assertEqual(dc.live_host, dfltHost,
                             "live_host should be %s, not %s" %
                             (dfltHost, dc.live_host))
            self.assertEqual(dc.live_port, dfltLive,
                             "live_port should be %s, not %s" %
                             (dfltLive, dc.live_port))

            liveObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

    def testOpenCloseBoth(self):
        dfltHost = "localhost"
        dfltLog = 54321
        dfltLive = 9876

        dLogObj = self.createLog("dLog", dfltLog)
        dLiveObj = self.createLog("dLive", dfltLive)

        log_host = "localhost"
        log_port = 12345
        live_host = ""
        live_port = 0

        logObj = self.createLog("file", log_port)

        for xl in (False, True):
            dc = CnCLogger("xl=%s" % str(xl), appender=self.__appender,
                           quiet=True, extra_loud=xl)

            dLogObj.addExpectedText(("Start of log at LOG=log(%s:%d)" +
                                     " live(%s:%d)") %
                                    (dfltHost, dfltLog, dfltHost, dfltLive))

            # set up default logger
            dc.openLog(dfltHost, dfltLog, dfltHost, dfltLive)

            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)

            logObj.addExpectedText("Start of log at LOG=log(%s:%d)" %
                                   (log_host, log_port))

            dc.openLog(log_host, log_port, live_host, live_port)
            self.assertEqual(dc.log_host, log_host)
            self.assertEqual(dc.log_port, log_port)
            self.assertEqual(dc.live_host, live_host)
            self.assertEqual(dc.live_port, live_port)

            if xl:
                logObj.addExpectedTextRegexp("End of log")
                dLogObj.addExpectedText(("Reset log to LOG=log(%s:%d)" +
                                         " live(%s:%d)") %
                                        (dfltHost, dfltLog,
                                         dfltHost, dfltLive))

            dc.closeLog()
            self.assertEqual(dc.log_host, dfltHost,
                             "log_host should be %s, not %s" %
                             (dfltHost, dc.log_host))
            self.assertEqual(dc.log_port, dfltLog,
                             "log_port should be %s, not %s" %
                             (dfltLog, dc.log_port))
            self.assertEqual(dc.live_host, dfltHost,
                             "live_host should be %s, not %s" %
                             (dfltHost, dc.live_host))
            self.assertEqual(dc.live_port, dfltLive,
                             "live_port should be %s, not %s" %
                             (dfltLive, dc.live_port))

            logObj.checkStatus(1000)
            dLogObj.checkStatus(1000)
            dLiveObj.checkStatus(1000)


if __name__ == "__main__":
    unittest.main()
