#!/usr/bin/env python

import sys

from DAQLog import DAQLog, FileAppender, LiveSocketAppender, LogException, \
    LogSocketAppender

class LogInfo(object):
    def __init__(self, logHost, logPort, liveHost, livePort):
        self.__logHost = logHost
        self.__logPort = logPort
        self.__liveHost = liveHost
        self.__livePort = livePort

    def __cmp__(self, other):
        val = cmp(self.__logHost, other.__logHost)
        if val == 0:
            val = cmp(self.__logPort, other.__logPort)
            if val == 0:
                val = cmp(self.__liveHost, other.__liveHost)
                if val == 0:
                    val = cmp(self.__livePort, other.__livePort)
        return val

    def __str__(self):
        outStr = ''
        if self.__logHost is not None and self.__logPort is not None:
            outStr += ' log(%s:%d)' % (self.__logHost, self.__logPort)
        if self.__liveHost is not None and self.__livePort is not None:
            outStr += ' live(%s:%d)' % (self.__liveHost, self.__livePort)
        if len(outStr) == 0:
            return 'NoInfo'
        return outStr[1:]

    def logHost(self): return self.__logHost
    def logPort(self): return self.__logPort
    def liveHost(self): return self.__liveHost
    def livePort(self): return self.__livePort

class CnCLogger(DAQLog):
    "CnC logging client"

    def __init__(self, appender=None, quiet=False, extraLoud=False):
        "create a logging client"
        self.__quiet = quiet
        self.__extraLoud = extraLoud

        self.__prevInfo = None
        self.__logInfo = None

        super(CnCLogger, self).__init__(appender)

    def __str__(self):
        return self.__getName()

    def __addAppenders(self):
        if self.__logInfo.logHost() is not None and \
                self.__logInfo.logPort() is not None:
            self.addAppender(LogSocketAppender(self.__logInfo.logHost(),
                                               self.__logInfo.logPort()))

        if self.__logInfo.liveHost() is not None and \
                self.__logInfo.livePort() is not None:
            self.addAppender(LiveSocketAppender(self.__logInfo.liveHost(),
                                                self.__logInfo.livePort()))
        if not self.hasAppender():
            raise LogException("Not logging to socket or I3Live")

    def __getName(self):
        if self.__logInfo is not None:
            return 'LOG=%s' % str(self.__logInfo)
        if self.__prevInfo is not None:
            return 'PREV=%s' % str(self.__prevInfo)
        return '?LOG?'

    def _logmsg(self, level, s, retry=True):
        """
        Log a string to stdout and, if available, to the socket logger
        stdout of course will not appear if daemonized.
        """
        if not self.__quiet: print s
        try:
            super(CnCLogger, self)._logmsg(level, s)
        except Exception, ex:
            if str(ex).find('Connection refused') < 0:
                raise
            print >>sys.stderr, 'Lost logging connection to %s' % \
                str(self.__logInfo)
            self.resetLog()
            if retry:
                self._logmsg(level, s, False)

    def closeLog(self):
        "Close the log socket"
        if self.hasAppender() and self.__extraLoud:
            self.info("End of log")
        self.resetLog()

    def closeFinal(self):
        self.close()
        self.__logInfo = None
        self.__prevInfo = None

    def liveHost(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.liveHost()

    def livePort(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.livePort()

    def logHost(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.logHost()

    def logPort(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.logPort()

    def openLog(self, logHost, logPort, liveHost, livePort):
        "initialize socket logger"
        if self.__prevInfo is None:
            self.__prevInfo = self.__logInfo

        self.close()

        self.__logInfo = LogInfo(logHost, logPort, liveHost, livePort)
        self.__addAppenders()

        self.debug('Start of log at %s' % str(self))

    def resetLog(self):
        "close current log and reset to initial state"

        if self.__prevInfo is not None and self.__logInfo != self.__prevInfo:
            self.close()
            self.__logInfo = self.__prevInfo
            self.__addAppenders()

        if self.hasAppender() and self.__extraLoud:
            self.info('Reset log to %s' % str(self))
