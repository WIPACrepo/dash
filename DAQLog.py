#!/usr/bin/env python

# DAQLog.py
# jaacobsen@npxdesigns.com
# Nov. - Dec. 2006
#
# Objects for persisting DAQ data, grouped in separate directories labeled by run number

from select import select
from time import sleep
import threading
import socket
import os
import sys

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
            raise Exception('Cannot bind %s log server to port %d' %
                            (self.__cname, self.__port))

        self.__serving = True
        pr = [sock]
        pw = []
        pe = [sock]
        while self.__thread is not None:
            rd, rw, re = select(pr, pw, pe, 0.5)
            if len(re) != 0: print >>self.__outfile, "Error on select was detected."
            if len(rd) == 0: continue
            while 1: # Slurp up waiting packets, return to select if EAGAIN
                try:
                    data = sock.recv(8192, socket.MSG_DONTWAIT)
                    if not self.__quiet: print "%s %s" % (self.__cname, data)
                    print >>self.__outfile, "%s %s" % (self.__cname, data)
                    self.__outfile.flush()
                except Exception:
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

    def startServing(self):
        "Creates listener thread, prepares file for output, and returns"
        if self.__logpath:
            self.__outfile = open(self.__logpath, "w")
        else:
            self.__outfile = sys.stdout
        if os.name == "nt":
            self.__thread = threading.Thread(target=self.__win_listener)
        else:
            self.__thread = threading.Thread(target=self.__listener)
        self.__serving = False
        self.__thread.start()

    def stopServing(self):
        "Signal listening thread to exit; wait for thread to finish"
        if self.__thread != None:
            thread = self.__thread
            self.__thread = None
            thread.join()

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
                sleep(1)
        except:
            pass
    finally:
         # This tells thread to stop if KeyboardInterrupt
        # If you skip this step you will be unable to control-C
        logger.stopServing()
