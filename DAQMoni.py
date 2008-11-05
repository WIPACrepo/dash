#!/usr/bin/env python

#
# DAQ Monitoring object for high level DAQRun scrupt
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started December, 2006

from DAQRPC import RPCClient
import datetime, sys, threading

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class BeanFieldNotFoundException(Exception): pass

class MoniData(object):
    def __init__(self, id, fname, name, daqID, addr, port):
        self.__name = name
        self.__daqID = daqID

        if fname is None:
            self.__fd = sys.stdout
        else:
            self.__fd = open(fname, "w+") # Might throw exception

        self.__client = RPCClient(addr, port)

        self.__beanFields = {}
        self.__beanList = self.__client.mbean.listMBeans()
        for bean in self.__beanList:
            self.__beanFields[bean] = self.__client.mbean.listGetters(bean)

    def __str__(self):
        return '%s-%d' % (self.__name, self.__daqID)

    def unFixValue(self, obj):

        """ Look for numbers masquerading as strings.  If an obj is a
        string and successfully converts to a number, return that
        convertion.  If obj is a dict or list, recuse into it
        converting all such masquerading strings.  All other types are
        unaltered.  This pairs with the similarly named fix* methods in
        icecube.daq.juggler.mbean.XMLRPCServer """

        if type(obj) is dict:
            for k in obj.keys():
                obj[k] = self.unFixValue(obj[k])
        elif type(obj) is list:
            for i in xrange(0, len(obj)):
                obj[i] = self.unFixValue(obj[i])
        elif type(obj) is str:
            try:
                return int(obj)
            except ValueError:
                pass
        return obj

    def monitor(self, now):
        for b in self.__beanFields.keys():
            attrs = self.__client.mbean.getAttributes(b, self.__beanFields[b])

            # report monitoring data
            if len(attrs) > 0:
                print >>self.__fd, '%s: %s:' % (b, now)
                for key in attrs:
                    print >>self.__fd, '\t%s: %s' % \
                            (key, str(self.unFixValue(attrs[key])))
            print >>self.__fd
            self.__fd.flush()

class MoniThread(threading.Thread):
    def __init__(self, moniData, log):
        self.__moniData = moniData
        self.__log = log

        self.now = None
        self.done = True

        threading.Thread.__init__(self)

        self.setName(str(self.__moniData))

    def getNewThread(self, now):
        mt = MoniThread(self.__moniData, self.__log)
        mt.now = now
        return mt

    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.__log: self.__log.dashLog(m)

    def run(self):
        self.done = False
        try:
            self.__moniData.monitor(self.now)
        except Exception:
            self.__logmsg("Ignoring %s: %s" %
                          (str(self.__moniData), exc_string()))

        self.done = True

class DAQMoni(object):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof, rpcAddrOf, mbeanPortOf):
        self.__log         = daqLog
        self.__interval    = interval
        self.__tlast       = None
        self.__moniList    = {}
        self.__threadList  = {}
        for c in IDs:
            if mbeanPortOf[c] > 0:
                fname = DAQMoni.fileName(daqLog.logPath, shortNameOf[c], daqIDof[c])
                self.logmsg("Creating moni output file %s (remote is %s:%d)" % (fname,
                                                                                rpcAddrOf[c],
                                                                                mbeanPortOf[c]))
                try:
                    md = MoniData(c, fname, shortNameOf[c], daqIDof[c], rpcAddrOf[c], mbeanPortOf[c])
                    self.__moniList[c] = md
                    self.__threadList[c] = MoniThread(md, self.__log)
                except Exception, e:
                    self.logmsg("Couldn't create monitoring output (%s) for component %d!" % (fname, c))
                    self.logmsg("%s: %s" % (e, exc_string()))

    def fileName(path, name, daqID):
        return "%s/%s-%d.moni" % (path, name, daqID)
    fileName = staticmethod(fileName)

    def getSingleBeanField(self, ID, beanName, beanField):
        if not self.__moniList:
            raise BeanFieldNotFoundException("Empty list of monitoring objects")
        if ID not in self.__moniList:
            raise BeanFieldNotFoundException("Component %d not found" % ID)
        md = self.__moniList[ID]
        if beanName not in md.beanList:
            raise BeanFieldNotFoundException("Bean %s not in list of beans for ID %d" % (beanName, ID))

        if beanField not in md.beanFields[beanName]:
            raise BeanFieldNotFoundException("Bean field %s not in list of bean fields (%s) for bean %s"
                                             % (beanField, `md.beanFields`, beanName))
        return md.client.mbean.get(beanName, beanField)

    def timeToMoni(self):
        if not self.__tlast: return True
        now = datetime.datetime.now()
        dt  = now - self.__tlast
        if dt.seconds+dt.microseconds*1.E-6 > self.__interval: return True
        return False

    def doMoni(self):
        now = datetime.datetime.now()
        self.__tlast = now
        for c in self.__threadList.keys():
            if self.__threadList[c].done:
                self.__threadList[c] = self.__threadList[c].getNewThread(now)
                self.__threadList[c].start()

    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.__log: self.__log.dashLog(m)

if __name__ == "__main__":
    usage = False
    if len(sys.argv) < 2:
        usage = True
    else:
        for i in range(1, len(sys.argv)):
            colon = sys.argv[i].find(':')
            if colon < 0:
                print "No colon"
                usage = True
            else:
                host = sys.argv[i][:colon]
                port = sys.argv[i][colon+1:]

                moni = MoniData(i, None, 'unknown', 0, host, port)
                moni.monitor('snapshot')
    if usage:
        print "Usage: DAQMoni.py host:beanPort [host:beanPort ...]"
        raise SystemExit

