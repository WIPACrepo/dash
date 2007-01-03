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

class MoniData(object):
    def __init__(self, id, fname, addr, port):
        self.id = id
        self.addr = addr
        self.port = port
        self.fd = open(fname, "w+") # Might throw exception
        self.client = RPCClient(addr, port)
        self.beanData = None

    def __str__(self):
        return '%d: %s:%d' % (self.id, self.addr, self.port)

    def monitor(self, now):
        if not self.beanData:
            beanList = self.client.mbean.listMBeans()

            self.beanData = {}
            for bean in beanList:
                self.beanData[bean] = self.client.mbean.listGetters(bean)

        for b in self.beanData.keys():
            vals = self.client.mbean.getList(b, self.beanData[b])

            # report monitoring data
            print >>self.fd, '%s: %s:\n' % (b, now)
            for i in range(0,len(vals)):
                print >>self.fd, '\t%s: %s' % (self.beanData[b][i], str(vals[i]))
            print >>self.fd
            self.fd.flush()
            
class DAQMoni(object):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof, rpcAddrOf, mbeanPortOf):
        self.log         = daqLog
        self.path        = daqLog.logPath
        self.interval    = interval
        self.tstart      = datetime.datetime.now()
        self.tlast       = None
        self.IDs         = IDs
        self.fdOf        = {}
        self.mbeanPortOf = mbeanPortOf
        self.rpcAddrOf   = rpcAddrOf
        self.moniList    = []
        for c in self.IDs:
            if self.mbeanPortOf[c] > 0:
                fname = DAQMoni.fileName(self.path, shortNameOf[c], daqIDof[c])
                self.logmsg("Creating moni output file %s (remote is %s:%d)" % (fname,
                                                                                self.rpcAddrOf[c],
                                                                                self.mbeanPortOf[c]))
                try:
                    md = MoniData(c, fname, self.rpcAddrOf[c], self.mbeanPortOf[c])
                    self.moniList.append(md)
                except Exception, e:
                    self.logmsg("Couldn't create monitoring output (%s) for component %d!" % (fname, md))
                    self.logmsg("%s: %s", e, exc_string())

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
        for c in self.moniList:
            try:
                c.monitor(now)
            except Exception, e:
                self.logmsg("Got exception %s: %s" % (e, exc_string()))
        self.tlast = now
    
    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log: self.log.dashLog(m)
     
