#!/usr/bin/env python

# DAQLog.py
# jaacobsen@npxdesigns.com
# Nov. - Dec. 2006
#
# Logging classes

from __future__ import print_function

import datetime
import os
import select
import socket
import sys
import threading

from DAQConst import DAQPort
from LiveImports import LIVE_IMPORT, MoniClient, Prio, SERVICE_NAME
from decorators import classproperty
from reraise import reraise_excinfo


class LogException(Exception):
    "Exception used by log-related classes"
    pass


class LogSocketServer(object):
    """
    Log requests from a remote object to a file.
    Works nonblocking in a separate thread to guarantee concurrency
    """

    NEXT_PORT = DAQPort.EPHEMERAL_BASE
    NEXT_LOCK = threading.Lock()

    def __init__(self, port, cname, logpath, quiet=False):
        "Logpath should be fully qualified in case I'm a Daemon"
        if not os.path.isabs(logpath):
            raise LogException("Cannot log to non-absolute path \"%s\"" %
                               (logpath, ))

        self.__port = port
        self.__cname = cname
        self.__logpath = logpath
        self.__quiet = quiet
        self.__thread = None
        self.__outfile = None
        self.__serving = False

    def __main(self):
        """
        Create listening, non-blocking UDP socket, read from it,
        and write to file; close socket and end thread if signaled via
        self.__thread variable.
        """

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if os.name != "nt":
            # initialize POSIX socket
            sock.setblocking(0)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if self.__port is not None:
            try:
                sock.bind(("", self.__port))
            except socket.error:
                raise LogException('Cannot bind %s log server to port %d' %
                                   (self.__cname, self.__port))
        else:
            while True:
                self.__port = self.next_log_port

                try:
                    sock.bind(("", self.__port))
                    break
                except socket.error:
                    pass

        self.__outfile = self.__open_path(self.__logpath)
        self.__serving = True
        try:
            if os.name == "nt":
                self.__win_loop(sock)
            else:
                self.__posix_loop(sock)
        finally:
            self.__serving = False
            try:
                sock.close()
            except:
                pass # ignore errors on close

            if self.__outfile is not None:
                try:
                    XXX = False
                    if XXX:
                        print("StopLog %s #%s" % (self.__cname, self.__port),
                              file=self.__outfile)
                        self.__outfile.flush()
                    self.__outfile.close()
                except:
                    pass # ignore errors on close
                self.__outfile = None

    @classmethod
    def __open_path(cls, path):
        if path is None:
            return sys.stdout
        return open(path, "a")

    def __posix_loop(self, sock):
        prd = [sock]
        pwr = []
        per = [sock]
        while self.__thread is not None:
            srd, _, sre = select.select(prd, pwr, per, 0.5)
            if len(sre) != 0:
                if self.__outfile is not None:
                    print("Error on select was detected.", file=self.__outfile)
            if len(srd) == 0:
                continue
            while True:  # Slurp up waiting packets, return to select if EAGAIN
                try:
                    data = sock.recv(8192, socket.MSG_DONTWAIT)
                    self.__write_data(data)
                except:
                    break  # Go back to select so we don't busy-wait

    def __win_loop(self, sock):
        """
        Windows version of listener - no select().
        """
        while self.__thread is not None:
            data = sock.recv(8192)
            self.__write_data(data)

    def __write_data(self, data):
        if self.__outfile is None:
            return

        if not self.__quiet:
            print("%s %s" % (self.__cname, data))
        print("%s %s" % (self.__cname, data), file=self.__outfile)
        self.__outfile.flush()

    @property
    def is_serving(self):
        "Is this object actively processing data?"
        return self.__serving

    @classproperty
    def next_log_port(cls):
        with cls.NEXT_LOCK:
            port = cls.NEXT_PORT
            cls.NEXT_PORT += 1
            if cls.NEXT_PORT > DAQPort.EPHEMERAL_MAX:
                cls.NEXT_PORT = DAQPort.EPHEMERAL_BASE
            return port


    @property
    def port(self):
        "Return the socket port number used by this object"
        return self.__port

    def start_serving(self):
        "Creates listener thread, prepares file for output, and returns"
        if self.__thread is not None:
            raise LogException("Thread for %s:%s has started" %
                               (self.__cname, self.__logpath))

        self.__serving = False
        self.__thread = threading.Thread(target=self.__main,
                                         name=self.__logpath)
        self.__thread.setDaemon(True)
        self.__thread.start()

    def set_output(self, new_path):
        "Change logging output file.  Send to sys.stdout if path is None"
        old_fd = self.__outfile
        self.__outfile = self.__open_path(new_path)
        try:
            if old_fd is not None:
                old_fd.close()
        except:
            pass

        # rename the thread
        #
        self.__thread.name = new_path

    def stop_serving(self):
        "Signal listening thread to exit; wait for thread to finish"
        if self.__thread is not None:
            thread = self.__thread
            self.__thread = None
            thread.join()


class BaseAppender(object):
    "Base log appender"
    def __init__(self, name):
        "Stash away this appender's name"
        self.__name = name

    def __str__(self):
        "Return the appender name"
        return self.__name

    def close(self):
        "Close the appender"
        pass

    @property
    def name(self):
        "Return this appender's name"
        return self.__name

    def write(self, msg, mtime=None, level=None):
        "Write the log message"
        raise NotImplementedError()


class BaseFileAppender(BaseAppender):
    "Write log messages to a file handle"
    def __init__(self, name, fdesc):
        "Create a file-based appender"
        super(BaseFileAppender, self).__init__(name)

        self.__fdesc = fdesc

    def _write(self, fdesc, mtime, msg):
        "Format the log message and write it to the file"
        print("%s [%s] %s" % (self.name, mtime, msg), file=fdesc)
        fdesc.flush()

    def close(self):
        "Close the file handle"
        if self.__fdesc is not None:
            self.close_fd(self.__fdesc)
            self.__fdesc = None

    def close_fd(self, fdesc):
        "Close the file descriptor (ConsoleAppender overrides this)"
        fdesc.close()

    def write(self, msg, mtime=None, level=None):
        "Write log message to local file"
        if self.__fdesc is None:
            raise LogException('Appender %s has been closed' % (self.name, ))

        if mtime is None:
            mtime = datetime.datetime.now()

        self._write(self.__fdesc, mtime, msg)


class ConsoleAppender(BaseFileAppender):
    "Write log messages to sys.stdout"
    def __init__(self, name):
        "Create a console logger"
        super(ConsoleAppender, self).__init__(name, sys.stdout)

    def close_fd(self, fdesc):
        "Don't close system file handle"
        pass


class DAQLog(object):
    "Log message handler"
    TRACE = 1
    DEBUG = 2
    INFO = 3
    WARN = 4
    ERROR = 5
    FATAL = 6

    __LEVEL_NAME = {
        TRACE: "TRACE",
        DEBUG: "DEBUG",
        INFO: "INFO",
        WARN: "WARN",
        ERROR: "ERROR",
        FATAL: "FATAL",
    }

    def __init__(self, name, appender=None, level=TRACE):
        if not isinstance(name, str):
            raise Exception("Name cannot be %s<%s>" % (name, type(name)))
        self.__name = name
        self.__level = level
        self.__appender_list = []
        if appender is not None:
            self.__appender_list.append(appender)

    def __str__(self):
        return '%s@%s:%s' % (self.__name, self.__get_level_name(),
                             str(self.__appender_list))

    def __get_level_name(self):
        if self.__level in self.__LEVEL_NAME:
            return self.__LEVEL_NAME[self.__level]
        return "?level=%d?" % self.__level

    def _logmsg(self, level, msg):
        "This is semi-private so CnCLogger can extend it"
        if level >= self.__level:
            if len(self.__appender_list) == 0:
                raise LogException("No appenders have been added to %s: %s" %
                                   (self.__name, msg))
            for apnd in self.__appender_list:
                apnd.write(msg, level=level)

    def add_appender(self, appender):
        "Add an appender"
        if appender is None:
            raise LogException("Cannot add null appender")
        self.__appender_list.append(appender)

    def close(self):
        "Close all appenders used by this logger"
        saved_exc = None
        for apnd in self.__appender_list:
            try:
                apnd.close()
            except:
                saved_exc = sys.exc_info()
        del self.__appender_list[:]
        if saved_exc:
            reraise_excinfo(saved_exc)

    def debug(self, msg):
        "Log a debugging message"
        self._logmsg(DAQLog.DEBUG, msg)

    def error(self, msg):
        "Log an error message"
        self._logmsg(DAQLog.ERROR, msg)

    def fatal(self, msg):
        "Log a fatal message"
        self._logmsg(DAQLog.FATAL, msg)

    def has_appender(self):
        "Does this logger have at least one appender?"
        return len(self.__appender_list) > 0

    def info(self, msg):
        "Log an informational message"
        self._logmsg(DAQLog.INFO, msg)

    @property
    def is_debug_enabled(self):
        "Are DEBUG level messages enabled?"
        return self.__level == DAQLog.DEBUG

    @property
    def is_error_enabled(self):
        "Are ERROR level messages enabled?"
        return self.__level == DAQLog.ERROR

    @property
    def is_fatal_enabled(self):
        "Are FATAL level messages enabled?"
        return self.__level == DAQLog.FATAL

    @property
    def is_info_enabled(self):
        "Are INFO level messages enabled?"
        return self.__level == DAQLog.INFO

    @property
    def is_trace_enabled(self):
        "Are TRACE level messages enabled?"
        return self.__level == DAQLog.TRACE

    @property
    def is_warn_enabled(self):
        "Are WARN level messages enabled?"
        return self.__level == DAQLog.WARN

    def set_level(self, level):
        "Set logger level"
        self.__level = level

    def trace(self, msg):
        "Log a trace message"
        self._logmsg(DAQLog.TRACE, msg)

    def warn(self, msg):
        "Log a warning"
        self._logmsg(DAQLog.WARN, msg)


class FileAppender(BaseFileAppender):
    "Write log messages to a file"
    def __init__(self, name, path):
        "Create a file-based appender"
        super(FileAppender, self).__init__(name, open(path, "w"))


class LogSocketAppender(BaseFileAppender):
    "Write log messages to a DAQ logging socket"
    def __init__(self, node, port):
        if port is None:
            raise Exception("Port cannot be None")

        self.__loc = '%s:%d' % (node, port)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((node, port))

        super(LogSocketAppender, self).__init__(self.__loc, sock)

    def _write(self, fdesc, mtime, msg):
        "Format the log message and write it to the file"
        try:
            fdesc.send("%s %s [%s] %s" % ('-', '-', mtime, msg))
        except socket.error as sex:
            raise LogException('LogSocket %s: %s' % (self.__loc, sex))


class LiveSocketAppender(BaseAppender):
    "Write log messages to an I3Live logging socket"
    def __init__(self, node, port, priority=Prio.DEBUG, service=SERVICE_NAME):
        super(LiveSocketAppender, self).__init__("LiveSocketAppender")

        self.__client = None
        if LIVE_IMPORT:
            self.__client = MoniClient(service, node, port)
        self.__client_lock = threading.Lock()
        self.__prio = priority

    def close(self):
        "Close the monitoring client"
        if self.__client:
            self.__client_lock.acquire()
            try:
                self.__client.close()
                self.__client = None
            finally:
                self.__client_lock.release()

    def write(self, msg, mtime=None, level=DAQLog.DEBUG):
        "Send the log message to I3Live"
        if isinstance(msg, unicode):
            msg = str(msg)

        self.__client_lock.acquire()
        try:
            if not msg.startswith('Start of log at '):
                if self.__client:
                    self.__client.sendMoni("log", str(msg), prio=self.__prio,
                                           time=mtime)
        finally:
            self.__client_lock.release()


if __name__ == "__main__":
    import argparse
    import time as pytime

    from CnCLogger import CnCLogger

    def add_arguments(parser):
        "Add all command-line arguments"
        parser.add_argument("-L", "--liveLog", dest="livelog",
                            help="Hostname:port for IceCube Live")
        parser.add_argument("-M", "--mesg", dest="logmsg", default="",
                            help="Message to log")
        parser.add_argument("logfile")
        parser.add_argument("port", type=int)

    def main():
        "Main method"
        parser = argparse.ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args()

        logfile = args.logfile
        port = args.port

        if logfile == '-':
            logfile = None
            filename = 'stderr'
        else:
            filename = logfile

        print("Write log messages arriving on port %d to %s." %
              (port, filename))

        # if someone specifies a live ip and port connect to it and
        # send a few test messages

        if args.livelog:
            import random

            try:
                live_addr, port_str = args.livelog.split(':')
                live_port = int(port_str)
                print("User specified a live logging destination,"
                      " try to use it")
                print("Dest: (%s:%d)" % (live_addr, live_port))
            except ValueError:
                sys.exit("ERROR: Bad livelog argument '%s'" % args.livelog)

            log = CnCLogger("live", quiet=False)
            log_server = LogSocketServer(port, "all-components", logfile)
            try:
                log_server.start_serving()

                log.open_log("localhost", port, live_addr, live_port)
                for idx in range(100):
                    msg = "Logging test message (%s) %d" % (args.logmsg, idx)
                    log.debug(msg)
                    sleep_time = random.uniform(0, 0.5)
                    pytime.sleep(sleep_time)

            finally:
                log_server.stop_serving()
        else:
            try:
                logger = LogSocketServer(port, "all-components", logfile)
                logger.start_serving()
                try:
                    while True:
                        pytime.sleep(1)
                except:
                    pass
            finally:
                # This tells thread to stop if KeyboardInterrupt
                # If you skip this step you will be unable to control-C
                logger.stop_serving()

    main()
