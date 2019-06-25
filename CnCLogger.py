#!/usr/bin/env python

from __future__ import print_function

import sys

from DAQLog import DAQLog, LiveSocketAppender, LogException, LogSocketAppender


class LogInfo(object):
    def __init__(self, logHost, logPort, liveHost, livePort):
        self.__logHost = logHost
        self.__logPort = logPort
        self.__liveHost = liveHost
        self.__livePort = livePort

    def __cmp__(self, other):
        val = cmp(self.logHost, other.logHost)
        if val == 0:
            val = cmp(self.logPort, other.logPort)
            if val == 0:
                val = cmp(self.liveHost, other.liveHost)
                if val == 0:
                    val = cmp(self.livePort, other.livePort)
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

    @property
    def liveHost(self):
        return self.__liveHost

    @property
    def livePort(self):
        return self.__livePort

    @property
    def logHost(self):
        return self.__logHost

    @property
    def logPort(self):
        return self.__logPort


class CnCLogger(DAQLog):
    "CnC logging client"

    def __init__(self, name, appender=None, quiet=False, extraLoud=False):
        "create a logging client"
        self.__quiet = quiet
        self.__extraLoud = extraLoud

        self.__prevInfo = None
        self.__logInfo = None

        super(CnCLogger, self).__init__(name, appender=appender)

    def __str__(self):
        if self.__logInfo is not None:
            return 'LOG=%s' % str(self.__logInfo)
        if self.__prevInfo is not None:
            return 'PREV=%s' % str(self.__prevInfo)
        return '?LOG?'

    def __addAppenders(self):
        if self.__logInfo.logHost is not None:
            self.addAppender(LogSocketAppender(self.__logInfo.logHost,
                                               self.__logInfo.logPort))

        if self.__logInfo.liveHost is not None:
            self.addAppender(LiveSocketAppender(self.__logInfo.liveHost,
                                                self.__logInfo.livePort))
        if not self.hasAppender():
            raise LogException("Not logging to socket or I3Live")

    def __reset_and_retry(self, level, msg, retry=False):
        "Reset logging config and retry log message if 'retry' is True"
        self.resetLog()
        if retry and self.hasAppender():
            self._logmsg(level, msg, False)

    def _logmsg(self, level, msg, retry=True):
        """
        Log a string to stdout and, if available, to the socket logger
        stdout of course will not appear if daemonized.
        """
        if not self.__quiet:
            print(msg)

        try:
            super(CnCLogger, self)._logmsg(level, msg)
        except LogException:
            self.__reset_and_retry(level, msg, retry=retry)
        except Exception as ex:
            if str(ex).find('Connection refused') < 0:
                raise
            print('Lost logging connection to %s' %
                  str(self.__logInfo), file=sys.stderr)
            self.__reset_and_retry(level, msg, retry=retry)

    def closeLog(self):
        "Close the log socket"
        if self.hasAppender() and self.__extraLoud:
            self.info("End of log")
        self.resetLog()

    def closeFinal(self):
        self.close()
        self.__logInfo = None
        self.__prevInfo = None

    @property
    def liveHost(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.liveHost

    @property
    def livePort(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.livePort

    @property
    def logHost(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.logHost

    @property
    def logPort(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.logPort

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
            self.__prevInfo = None
            self.__addAppenders()

        if self.hasAppender() and self.__extraLoud:
            self.info('Reset log to %s' % str(self))
