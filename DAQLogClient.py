#!/usr/bin/env python

# DAQLogClient
# jacobsen@npxdesigns.com
# December, 2006
#
# Logger to write timestamped or raw data to a remote UDP logger (see DAQLog.py)

import datetime, socket, sys
from DAQConst import DAQPort

try:
    from live.transport.Queue import Prio
except ImportError:
    # create a bogus Prio class
    class Prio:
        ITS   = 123
        EMAIL = 444
        SCP   = 555
        DEBUG = 666

class BaseAppender(object):
    def __init__(self, name):
        self.__name = name

    def __str__(self):
        return self.__name

    def _getTime(self):
        "Get the current local time"
        return datetime.datetime.now()

    def close(self):
        pass

    def getName(self):
        return self.__name

    def write(self, msg, time=None):
        pass

class BaseFileAppender(BaseAppender):
    def __init__(self, name, fd):
        "Create a file-based appender"
        super(BaseFileAppender, self).__init__(name)

        self.__fd = fd

    def _write(self, fd, time, msg):
        print >>fd, "%s [%s] %s" % (self.getName(), time, msg)
        fd.flush()

    def close(self):
        if self.__fd is not None:
            self.close_fd(self.__fd)
            self.__fd = None

    def close_fd(self, fd):
        "Close the file descriptor (ConsoleAppender overrides this)"
        fd.close()

    def write(self, msg, time=None):
        "Write log information to local file"
        if self.__fd is None:
            raise Exception('Appender %s has been closed' % self.getName())

        if time is None:
            time = self._getTime()

        self._write(self.__fd, time, msg)

class ConsoleAppender(BaseFileAppender):
    def __init__(self, name):
        "Create a console logger"
        super(ConsoleAppender, self).__init__(name, sys.stdout)

    def close_fd(self, fd):
        "Don't close system file handle"
        pass

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

    def __str__(self):
        return '%s@%s' % (str(self.__appender), self.__getLevelName())

    def __getLevelName(self):
        if self.__level == DAQLog.TRACE:
            return "TRACE"
        if self.__level == DAQLog.DEBUG:
            return "DEBUG"
        if self.__level == DAQLog.INFO:
            return "INFO"
        if self.__level == DAQLog.WARN:
            return "WARN"
        if self.__level == DAQLog.ERROR:
            return "ERROR"
        if self.__level == DAQLog.FATAL:
            return "FATAL"
        return "?level=%d?" % self.__level

    def _logmsg(self, level, msg):
        "This is semi-private so CnCLogger can extend it"
        if level >= self.__level:
            self.__appender.write(msg)

    def close(self):
        if self.__appender != self.__defaultAppender:
            self.__appender.close()
        self.__defaultAppender.close()

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

class FileAppender(BaseFileAppender):
    def __init__(self, name, path):
        "Create a file-based appender"
        super(FileAppender, self).__init__(name, open(path, "w"))

class LogSocketAppender(BaseFileAppender):
    "Log to DAQ logging socket"
    def __init__(self, node, port):
        self.__loc = '%s:%d' % (node, port)
        super(LogSocketAppender, self).__init__(self.__loc,
                                                self.__openSocket(node, port))

    def __openSocket(self, node, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((node, port))
        return sock

    def _write(self, fd, time, msg):
        try:
            fd.send("%s [%s] %s" % ('-', time, msg))
        except socket.error, se:
            raise socket.error('LogSocket %s: %s' % (self.__loc, str(se)))

class LiveFormatter(object):
    def __init__(self, service='pdaq'):
        self.__svc = service

    def format(self, varName, time, msg, priority=Prio.DEBUG):
        return '%s(%s:%s) %d [%s] %s\n' % \
            (self.__svc, varName, type(msg).__name__, priority, time, msg)

class LiveSocketAppender(LogSocketAppender):
    "Log to I3Live logging socket"
    def __init__(self, node, port, priority=Prio.DEBUG, service='pdaq'):
        super(LiveSocketAppender, self).__init__(node, port)

        self.__prio = priority
        self.__fmt = LiveFormatter()

    def _getTime(self):
        return datetime.datetime.utcnow()

    def _write(self, fd, time, msg):
        if type(msg) == unicode:
            msg = str(msg)
        if not msg.startswith('Start of log at '):
            fd.send(self.__fmt.format('log', time, msg, self.__prio))

class BothSocketAppender(object):
    def __init__(self, logHost, logPort, liveHost, livePort,
                 priority=Prio.DEBUG):
        if logHost is not None and logPort is not None:
            self.__log = LogSocketAppender(logHost, logPort)
        else:
            self.__log = ConsoleAppender('both-cons')
        if liveHost is not None and livePort is not None:
            self.__live = LiveSocketAppender(liveHost, livePort, priority)
        else:
            self.__live = None

    def __str__(self):
        return self.getName()

    def close(self):
        if self.__log is not None:
            self.__log.close()
        if self.__live is not None:
            self.__live.close()

    def getName(self):
        if self.__log is None:
            if self.__live is None:
                return 'noLogging'
            return 'live(%s)-log' % str(self.__live)
        elif self.__live is None:
            return 'log(%s)-live' % str(self.__log)
        return 'log(%s)+live(%s)' % (str(self.__log), str(self.__live))

    def setLiveAppender(self, appender):
        self.__live = appender

    def setLogAppender(self, appender):
        self.__log = appender

    def write(self, msg, time=None):
        if self.__log is not None:
            self.__log.write(msg, time)
        if self.__live is not None:
            self.__live.write(msg, time)

class LiveMonitor(object):
    "Send I3Live monitoring data"
    def __init__(self, node='localhost', port=DAQPort.I3LIVE, service='pdaq'):
        self.__svc = service

        self.__loc = '%s:%d' % (node, port)

        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.connect((node, port))

        self.__fmt = LiveFormatter()

    def _getTime(self):
        return datetime.datetime.utcnow()

    def close(self):
        if self.__sock is not None:
            self.__sock.close()
            self.__sock = None

    def send(self, varName, time, data):
        # XXX - disable I3Live monitoring for now
        return

        if self.__sock is None:
            raise Exception('LiveMonitor has been closed')

        if type(data) == unicode:
            data = str(data)

        try:
            msg = self.__fmt.format(varName, time, data)
            self.__sock.send(msg)
        except socket.error, se:
            raise socket.error('LogSocket %s: %s' % (self.__loc, str(se)))
