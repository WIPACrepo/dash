#!/usr/bin/env python

# DAQLog.py
# jaacobsen@npxdesigns.com
# Nov. - Dec. 2006
#
# Objects for persisting DAQ data, grouped in separate directories labeled by run number
#

from datetime import datetime
from DAQRPC import RPCClient
from select import select
from time import sleep
import threading
import os.path
import socket
import os
import sys

class SocketLogger(object):
    LOGLEVEL_TRACE = "trace"
    LOGLEVEL_DEBUG = "debug"
    LOGLEVEL_INFO  = "info"
    LOGLEVEL_WARN  = "warn"
    LOGLEVEL_ERROR = "error"
    LOGLEVEL_FATAL = "fatal"
    "Create class which logs requests from a remote object to a file"
    "Works nonblocking in a separate thread to guarantee concurrency"
    def __init__(self, port, cname, logpath): # Logpath should be fully qualified in case I'm a Daemon
        self.port    = port
        self.cname   = cname
        self.logpath = logpath
        self.go      = False
        self.thread  = None

    def startServing(self):
        "Creates listener thread, prepares file for output, and returns"
        self.go      = True
        if self.logpath:
            self.outfile = open(self.logpath, "a+")
        else:
            self.outfile = sys.stdout
        self.thread  = threading.Thread(target=self.listener)
        self.thread.start()

    def listener(self):
        """
        Create listening, non-blocking UDP socket, read from it, and write to file;
        close socket and end thread if signaled via self.go variable.
        """
                 
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(0)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", self.port))
        pr = [self.sock]
        pw = []
        pe = [self.sock]
        while self.go:
            rd, rw, re = select(pr, pw, pe, 0.5)
            if len(re) != 0: print >>self.outfile, "Error on select was detected."
            if len(rd) == 0: continue
            while 1: # Slurp up waiting packets, return to select if EAGAIN
                try:
                    data = self.sock.recv(8192, socket.MSG_DONTWAIT)
                    print >>self.outfile, "%s %s" % (self.cname, data)
                    self.outfile.flush()
                except Exception, e:
                    break # Go back to select so we don't busy-wait
        self.sock.close()
        if self.logpath:
            self.outfile.close()

    def stopServing(self):
        "Signal listening thread to exit; wait for thread to finish"
        self.go = False
        if self.thread != None: self.thread.join()
        self.thread = None


class logCollector(object):
    "Methods for creating log directory for a run and for primary DAQ output (dash.log)"
    def __init__(self, runNum, loggingDir):
        self.runNum      = runNum
        self.enabled     = True
        self.dashLogFile = None
        self.name        = "DAQRun"
        if not os.path.exists(loggingDir):
            self.enabled = False
            raise Exception("Directory %s not found!" % loggingDir)
        self.logPath = loggingDir+"/"+self.logDirName(runNum)
        if os.path.exists(self.logPath):
            self.renameToOld(self.logPath)
        os.mkdir(self.logPath)
        self.dashLogFile = self.logPath + "/" + "dash.log"
        self.log         = open(self.dashLogFile, "w")

    def close(self):
        self.enabled = False
        self.log.close()
        
    def renameToOld(self, dir):
        "Rename existing directory to old one without clobbering output file"
        basenum = 0
        path    = os.path.dirname(dir)
        name    = os.path.basename(dir)
        while 1:
            dest = "%s/old_%s_%02d" % (path, name, basenum)
            if not os.path.exists(dest):
                os.rename(dir, dest)
                return
            basenum += 1

    def logDirName(self, runNum):
        "Get log directory name, not including loggingDir portion of path"
        return "daqrun%05d" % runNum

    def dashLog(self, msg):
        "Persist DAQRun log information to local disk, without using remote UDP logger"
        if not self.enabled: return
        if self.dashLogFile == None: return
        print >>self.log, "%s [%s] %s" % (self.name, datetime.now(), msg)
        self.log.flush()
        
if __name__ == "__main__":

    try:
        print "Creating logger..."
        logger = SocketLogger(6666, "javaComponent", "./test.log")
        print "Start serving..."
        logger.startServing()
        sleep(10000)
    except KeyboardInterrupt, k:
        raise SystemExit        
    
    raise SystemExit

    # Old test:
    remote = RPCClient("localhost", 6667)
    for i in xrange(0,50):
        logger = SocketLogger(6666, "myComponent", "/tmp/better%05d.log" % i)
        logger.startServing()
        try:
            remote.log_to("localhost", 6666)
            # sleep(0.01)
            remote.close_log()
            logger.stopServing()
            logger = None
            # sleep(0.01)
        except KeyboardInterrupt, k:
            raise SystemExit
        except Exception, e:
            print "Failed to set up remote logging: ", e

