#!/usr/bin/env python

# DAQLog.py
# jaacobsen@npxdesigns.com
# Nov. - Dec. 2006
#
# Logging classes

import datetime, os, select, socket, sys, threading, time
from DAQConst import DAQPort
from LiveImports import MoniClient, Prio, SERVICE_NAME

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class LogException(Exception): pass

class LogSocketServer(object):
    "Create class which logs requests from a remote object to a file"
    "Works nonblocking in a separate thread to guarantee concurrency"
    def __init__(self, port, cname, logpath, quiet=False):
        "Logpath should be fully qualified in case I'm a Daemon"
        self.__port    = port
        self.__cname   = cname
        self.__logpath = logpath
        self.__quiet   = quiet
        self.__thread  = None
        self.__outfile = None
        self.__serving = False

    def __listener(self):
        """
        Create listening, non-blocking UDP socket, read from it, and write to file;
        close socket and end thread if signaled via self.__thread variable.
        """

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.__port))
        except socket.error:
            raise LogException('Cannot bind %s log server to port %d' %
                               (self.__cname, self.__port))

        self.__serving = True
        pr = [sock]
        pw = []
        pe = [sock]
        while self.__thread is not None:
            rd, rw, re = select.select(pr, pw, pe, 0.5)
            if len(re) != 0: print >>self.__outfile, "Error on select was detected."
            if len(rd) == 0: continue
            while 1: # Slurp up waiting packets, return to select if EAGAIN
                try:
                    data = sock.recv(8192, socket.MSG_DONTWAIT)
                    if not self.__quiet: print "%s %s" % (self.__cname, data)
                    print >>self.__outfile, "%s %s" % (self.__cname, data)
                    self.__outfile.flush()
                except:
                    break # Go back to select so we don't busy-wait
        sock.close()
        if self.__logpath:
            self.__outfile.close()
        self.__serving = False

    def __win_listener(self):
        """
        Windows version of listener - no select().
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #sock.setblocking(1)
        #sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.__port))
        self.__serving = True
        while self.__thread is not None:
            data = sock.recv(8192)
            if not self.__quiet: print "%s %s" % (self.__cname, data)
            print >>self.__outfile, "%s %s" % (self.__cname, data)
            self.__outfile.flush()
        sock.close()
        if self.__logpath: self.__outfile.close()
        self.__serving = False

    def isServing(self):
        return self.__serving

    def port(self):
        return self.__port

    def startServing(self):
        "Creates listener thread, prepares file for output, and returns"
        if self.__logpath:
            self.__outfile = open(self.__logpath, "a")
        else:
            self.__outfile = sys.stdout
        if os.name == "nt":
            self.__thread = threading.Thread(target=self.__win_listener,
                                             name=self.__logpath)
        else:
            self.__thread = threading.Thread(target=self.__listener,
                                             name=self.__logpath)
        self.__serving = False
        self.__thread.setDaemon(True)
        self.__thread.start()

    def stopServing(self):
        "Signal listening thread to exit; wait for thread to finish"
        if self.__thread != None:
            thread = self.__thread
            self.__thread = None
            thread.join()
        self.__outfile.close()

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
            raise LogException('Appender %s has been closed' % self.getName())

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
        self.__level = level
        self.__appenderList = []
        if appender is not None:
            self.__appenderList.append(appender)

    def __str__(self):
        return '%s:%s' % (self.__getLevelName(), str(self.__appenderList))

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
            if len(self.__appenderList) == 0:
                raise LogException("No appenders have been added: " + msg)
            for a in self.__appenderList:
                a.write(msg)

    def addAppender(self, appender):
        if appender is None:
            raise LogException("Cannot add null appender")
        self.__appenderList.append(appender)

    def clearAppenders(self):
        self.close()

    def close(self):
        for a in self.__appenderList:
            a.close()
        del self.__appenderList[:]

    def debug(self, msg): self._logmsg(DAQLog.DEBUG, msg)

    def error(self, msg): self._logmsg(DAQLog.ERROR, msg)

    def fatal(self, msg): self._logmsg(DAQLog.FATAL, msg)

    def hasAppender(self): return len(self.__appenderList) > 0

    def info(self, msg): self._logmsg(DAQLog.INFO, msg)

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
            fd.send("%s %s [%s] %s" % ('-', '-', time, msg))
        except socket.error, se:
            raise LogException('LogSocket %s: %s' % (self.__loc, str(se)))

class LiveFormatter(object):
    def __init__(self, service=SERVICE_NAME):
        self.__svc = service

    def format(self, varName, time, msg, priority=Prio.DEBUG):
        return '%s(%s:%s) %d [%s] %s\n' % \
            (self.__svc, varName, type(msg).__name__, priority, time, msg)

class LiveSocketAppender(LogSocketAppender):
    "Log to I3Live logging socket"
    def __init__(self, node, port, priority=Prio.DEBUG, service=SERVICE_NAME):
        super(LiveSocketAppender, self).__init__(node, port)

        self.__prio = priority
        self.__fmt = LiveFormatter()

    def _getTime(self):
        return datetime.datetime.utcnow()

    def _write(self, fd, time, msg):
        if type(msg) == unicode:
            msg = str(msg)
        if not msg.startswith('Start of log at '):
            try:
                fd.send(self.__fmt.format('log', time, msg, self.__prio))
            except socket.error, err:
                raise LogException("%s (Cannot send: %s)" % (msg, exc_string()))

class LiveMonitor(object):
    "Send I3Live monitoring data"
    def __init__(self, node='localhost', port=DAQPort.I3LIVE,
                 service=SERVICE_NAME):
        self.__client = MoniClient(service, node, port)
        self.__clientLock = threading.Lock()

    def close(self):
        if self.__client is not None:
            self.__clientLock.acquire()
            try:
                self.__client.close()
                self.__client = None
            finally:
                self.__clientLock.release()

    def send(self, varName, time, data):
        if self.__client is None:
            raise LogException('LiveMonitor has been closed')

        self.__clientLock.acquire()
        try:
            if not self.__client.sendMoni(varName, data, Prio.ITS, time):
                raise LogException('LiveMonitor %s: cannot send %s data' %
                                   (str(self.__client), varName))
        finally:
            self.__clientLock.release()

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print "Usage: DAQLogServer.py <file> <port>"
        raise SystemExit

    logfile = sys.argv[1]
    port    = int(sys.argv[2])

    if logfile == '-':
        logfile = None
        filename = 'stderr'
    else:
        filename = logfile

    print "Write log messages arriving on port %d to %s." % (port, filename)

    try:
        logger = LogSocketServer(port, "all-components", logfile)
        logger.startServing()
        try:
            while 1:
                time.sleep(1)
        except:
            pass
    finally:
         # This tells thread to stop if KeyboardInterrupt
        # If you skip this step you will be unable to control-C
        logger.stopServing()
