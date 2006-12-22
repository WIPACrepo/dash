#!/usr/bin/env python

#
# DAQ Monitoring object for high level DAQRun scrupt
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started December, 2006

from DAQLog import *
from DAQRPC import RPCClient
import datetime
from exc_string import *

class DAQMoni(object):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof, rpcAddrOf, rpcPortOf):
        self.log         = daqLog
        self.path        = daqLog.logPath
        self.interval    = interval
        self.tstart      = datetime.datetime.now()
        self.tlast       = None
        self.IDs         = IDs
        self.fdOf        = {}
        self.rpcPortOf   = rpcPortOf
        self.rpcAddrOf   = rpcAddrOf
        self.rpcClientOf = {}
        for c in self.IDs:
            fname = DAQMoni.fileName(self.path, shortNameOf[c], daqIDof[c])
            self.logmsg("Creating moni output file %s (remote is %s:%d)" % (fname,
                                                                            self.rpcAddrOf[c],
                                                                            self.rpcPortOf[c]))
            self.rpcClientOf[c] = RPCClient(self.rpcAddrOf[c], self.rpcPortOf[c])
            
    def fileName(path, name, daqID):
        return "%s/%s-%d.moni" % (path, name, daqID)
    fileName = staticmethod(fileName)
    
    def timeToMoni(self):
        if not self.tlast: return True
        now = datetime.datetime.now()
        dt  = now - self.tlast
        if dt.seconds+dt.microseconds*1.E-6 > self.interval: return True
        return False
    
    def doMoni(self):
        now = datetime.datetime.now()
        self.logmsg("Doing monitoring at %s" % now)
        for c in self.IDs:
            self.logmsg("Tickle %d: %s:%d..." % (c, self.rpcAddrOf[c], self.rpcPortOf[c]))
            try:
                self.rpcClientOf[c].xmlrpc.monitorHack(c)
            except Exception, e:
                self.logmsg("Got exception %s: %s" % (e, exc_string()))
        self.tlast = now
    
    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log: self.log.dashLog(m)
                        
