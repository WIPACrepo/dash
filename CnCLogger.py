#!/usr/bin/env python
"""
logging class which should probably be replaced by something like
Python's `logging` package; it was originally useful for sending log
messages to Live and also writing them to a local file
"""

from __future__ import print_function

import sys

from DAQLog import DAQLog, LiveSocketAppender, LogException, LogSocketAppender
from i3helper import Comparable


class LogInfo(Comparable):
    "Paired pDAQ+Live logging information"
    def __init__(self, log_host, log_port, live_host, live_port):
        """
        log_host - pDAQ logging socket hostname
        log_port - pDAQ logging socket port
        log_host - I3Live logging socket hostname
        log_port - I3Live logging socket port
        """
        self.__log_host = log_host
        self.__log_port = log_port
        self.__live_host = live_host
        self.__live_port = live_port

    def __str__(self):
        outstr = ''
        if self.__log_host is not None and self.__log_port is not None:
            outstr += ' log(%s:%d)' % (self.__log_host, self.__log_port)
        if self.__live_host is not None and self.__live_port is not None:
            outstr += ' live(%s:%d)' % (self.__live_host, self.__live_port)
        if outstr == "":
            return 'NoInfo'
        return outstr[1:]

    @property
    def compare_key(self):
        "Return the keys to be used by the Comparable methods"
        return (self.__log_host, self.__log_port, self.__live_host,
                self.__live_port)

    @property
    def live_host(self):
        "I3Live logging host"
        return self.__live_host

    @property
    def live_port(self):
        "I3Live logging port"
        return self.__live_port

    @property
    def log_host(self):
        "pDAQ logging host"
        return self.__log_host

    @property
    def log_port(self):
        "pDAQ logging port"
        return self.__log_port


class CnCLogger(DAQLog):
    "CnC logging client"

    def __init__(self, name, appender=None, quiet=False, extra_loud=False):
        "create a logging client"
        self.__quiet = quiet
        self.__extra_loud = extra_loud

        self.__prev_info = None
        self.__log_info = None

        super(CnCLogger, self).__init__(name, appender=appender)

    def __str__(self):
        if self.__log_info is not None:
            return 'LOG=%s' % str(self.__log_info)
        if self.__prev_info is not None:
            return 'PREV=%s' % str(self.__prev_info)
        return '?LOG?'

    def __add_appenders(self):
        if self.__log_info.log_host is not None:
            self.add_appender(LogSocketAppender(self.__log_info.log_host,
                                                self.__log_info.log_port))

        if self.__log_info.live_host is not None:
            self.add_appender(LiveSocketAppender(self.__log_info.live_host,
                                                 self.__log_info.live_port))
        if not self.has_appender():
            raise LogException("Not logging to socket or I3Live")

    def __reset_and_retry(self, level, msg, retry=False):
        "Reset logging config and retry log message if 'retry' is True"
        self.reset_log()
        if retry and self.has_appender():
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
        except Exception as ex:  # pylint: disable=broad-except
            if str(ex).find('Connection refused') < 0:
                raise
            print('Lost logging connection to %s' %
                  str(self.__log_info), file=sys.stderr)
            self.__reset_and_retry(level, msg, retry=retry)

    def close_log(self):
        "Close the active log socket and reset to the previous logging config"
        if self.has_appender() and self.__extra_loud:
            self.info("End of log")
        self.reset_log()

    def close_final(self):
        "Close everything and clear all cached logging information"
        self.close()
        self.__log_info = None
        self.__prev_info = None

    @property
    def live_host(self):
        "I3Live logging host"
        if self.__log_info is None:
            return None
        return self.__log_info.live_host

    @property
    def live_port(self):
        "I3Live logging port"
        if self.__log_info is None:
            return None
        return self.__log_info.live_port

    @property
    def log_host(self):
        "pDAQ logging host"
        if self.__log_info is None:
            return None
        return self.__log_info.log_host

    @property
    def log_port(self):
        "pDAQ logging port"
        if self.__log_info is None:
            return None
        return self.__log_info.log_port

    def open_log(self, log_host, log_port, live_host, live_port):
        "initialize socket logger"
        if self.__prev_info is None:
            self.__prev_info = self.__log_info

        self.close()

        self.__log_info = LogInfo(log_host, log_port, live_host, live_port)
        self.__add_appenders()

        self.debug('Start of log at %s' % str(self))

    def reset_log(self):
        "close current log and reset to initial state"

        if self.__prev_info is not None and \
          self.__log_info != self.__prev_info:
            self.close()
            self.__log_info = self.__prev_info
            self.__prev_info = None
            self.__add_appenders()

        if self.has_appender() and self.__extra_loud:
            self.info('Reset log to %s' % str(self))
