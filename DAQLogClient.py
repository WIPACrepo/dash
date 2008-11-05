#!/usr/bin/env python

# DAQLogClient
# jacobsen@npxdesigns.com
# December, 2006
#
# Logger to write timestamped or raw data to a remote UDP logger (see DAQLog.py)

import datetime, socket

class BaseAppender(object):
    def __init__(self, name):
        self.__name = name

    def __str__(self):
        return self.__name

    def close(self):
        pass

    def getName(self):
        return self.__name

class ConsoleAppender(BaseAppender):
    "Create a file-based logger"
    def __init__(self, name):
        super(ConsoleAppender, self).__init__(name)

        self.__isOpen = True

    def close(self):
        self.__isOpen = False

    def write(self, msg):
        if not self.__isOpen:
            raise Exception('Appender %s has been closed' % self.getName())

        print "%s [%s] %s" % \
            (self.getName(), datetime.datetime.now(), msg)

class DAQLog(object):
    TRACE = 1
    DEBUG = 2
    INFO = 3
    WARN = 4
    ERROR = 5
    FATAL = 6

    def __init__(self, appender=None, level=TRACE):
        if appender is None:
            appender = ConsoleAppender('console')
        self.__defaultAppender = appender

        self.__level = level
        self.__appender = appender

    def _logmsg(self, level, msg):
        "This is semi-private so CnCLogger can extend it"
        if level >= self.__level:
            self.__appender.write(msg)

    def debug(self, msg): self._logmsg(DAQLog.DEBUG, msg)

    def error(self, msg): self._logmsg(DAQLog.ERROR, msg)

    def fatal(self, msg): self._logmsg(DAQLog.FATAL, msg)

    def info(self, msg): self._logmsg(DAQLog.INFO, msg)

    def setAppender(self, appender):
        if self.__appender != self.__defaultAppender:
            self.__appender.close()

        if appender is not None:
            self.__appender = appender
        else:
            self.__appender = self.__defaultAppender

    def setLevel(self, level):
        self.__level = level

    def trace(self, msg): self._logmsg(DAQLog.TRACE, msg)

    def warn(self, msg): self._logmsg(DAQLog.WARN, msg)

class FileAppender(BaseAppender):
    "Create a file-based logger"
    def __init__(self, name, path):
        super(FileAppender, self).__init__(name)

        self.__log = open(path, "w")

    def close(self):
        if self.__log is not None:
            self.__log.close()
            self.__log = None

    def write(self, msg):
        "Write log information to local file"
        if self.__log is None:
            raise Exception('No file to append')

        print >>self.__log, "%s [%s] %s" % \
            (self.getName(), datetime.datetime.now(), msg)
        self.__log.flush()

class LogSocketAppender(BaseAppender):
    "Log to UDP socket, somewhere"
    def __init__(self, node, port):
        super(LogSocketAppender, self).__init__('%s:%d' % (node, port))

        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__socket.connect((node, port))

    def close(self):
        "Shutdown socket to remote server to avoid stale sockets"
        self.__socket.close()

    def write(self, s, time=None):
        "Write time-stamped log msg to remote logger"
        if time is None:
            time = datetime.datetime.now()
        self.__socket.send("- [%s] %s" % (time, s))
