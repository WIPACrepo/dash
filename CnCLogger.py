#!/usr/bin/env python

from __future__ import print_function

import sys

from DAQLog import DAQLog, LiveSocketAppender, LogException, LogSocketAppender


class LogInfo(object):
    def __init__(self, log_host, log_port, live_host, live_port):
        self.__log_host = log_host
        self.__log_port = log_port
        self.__live_host = live_host
        self.__live_port = live_port

    def __cmp__(self, other):
        val = cmp(self.log_host, other.log_host)
        if val == 0:
            val = cmp(self.log_port, other.log_port)
            if val == 0:
                val = cmp(self.live_host, other.live_host)
                if val == 0:
                    val = cmp(self.live_port, other.live_port)
        return val

    def __str__(self):
        outStr = ''
        if self.__log_host is not None and self.__log_port is not None:
            outStr += ' log(%s:%d)' % (self.__log_host, self.__log_port)
        if self.__live_host is not None and self.__live_port is not None:
            outStr += ' live(%s:%d)' % (self.__live_host, self.__live_port)
        if len(outStr) == 0:
            return 'NoInfo'
        return outStr[1:]

    @property
    def live_host(self):
        return self.__live_host

    @property
    def live_port(self):
        return self.__live_port

    @property
    def log_host(self):
        return self.__log_host

    @property
    def log_port(self):
        return self.__log_port


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
        return self.__getName()

    def __addAppenders(self):
        if self.__logInfo.log_host is not None and \
                self.__logInfo.log_port is not None:
            self.addAppender(LogSocketAppender(self.__logInfo.log_host,
                                               self.__logInfo.log_port))

        if self.__logInfo.live_host is not None and \
                self.__logInfo.live_port is not None:
            self.addAppender(LiveSocketAppender(self.__logInfo.live_host,
                                                self.__logInfo.live_port))
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
        if not self.__quiet:
            print(s)

        try:
            super(CnCLogger, self)._logmsg(level, s)
        except Exception as ex:
            if not isinstance(ex, LogException):
                if str(ex).find('Connection refused') < 0:
                    raise
                print('Lost logging connection to %s' % \
                      str(self.__logInfo), file=sys.stderr)
            self.resetLog()
            if retry and self.hasAppender():
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

    @property
    def live_host(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.live_host

    @property
    def live_port(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.live_port

    @property
    def log_host(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.log_host

    @property
    def log_port(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.log_port

    def openLog(self, log_host, log_port, live_host, live_port):
        "initialize socket logger"
        if self.__prevInfo is None:
            self.__prevInfo = self.__logInfo

        self.close()

        self.__logInfo = LogInfo(log_host, log_port, live_host, live_port)
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
