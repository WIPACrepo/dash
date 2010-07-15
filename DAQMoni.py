#!/usr/bin/env python

#
# DAQ Monitoring object for high level DAQRun scrupt
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started December, 2006

import datetime, os, sys, threading
from DAQRPC import RPCClient
from DAQLogClient import LiveMonitor

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

def unFixValue(obj):
    """
    Look for numbers masquerading as strings.  If an obj is a
    string and successfully converts to a number, return that
    convertion.  If obj is a dict or list, recuse into it
    converting all such masquerading strings.  All other types are
    unaltered.  This pairs with the similarly named fix* methods in
    icecube.daq.juggler.mbean.XMLRPCServer
    """

    if type(obj) is dict:
        for k in obj.keys():
            obj[k] = unFixValue(obj[k])
    elif type(obj) is list:
        for i in xrange(0, len(obj)):
            obj[i] = unFixValue(obj[i])
    elif type(obj) is str:
        try:
            return int(obj)
        except ValueError:
            pass
    return obj

class BeanFieldNotFoundException(Exception): pass

class MoniData(object):
    # XXX - disable I3Live monitoring for now
    SEND_LIVE_MONI = False

    def __init__(self, name, daqID, addr, port):
        self.__name = name
        self.__daqID = daqID

        self.__client = self.getRPCClient(addr, port)

        self.__beanFields = {}
        self.__beanList = self.__client.mbean.listMBeans()
        for bean in self.__beanList:
            self.__beanFields[bean] = self.__client.mbean.listGetters(bean)

    def __str__(self):
        return '%s-%d' % (self.__name, self.__daqID)

    def _report(self, now, beanName, attrs):
        raise Exception('Unimplemented')

    def getBeanField(self, ID, bean, fld):
        if bean not in self.__beanList:
            msg = "Bean %s not in list of beans for ID %d (%s-%d)" % \
                (bean, ID, self.__name, self.__daqID)
            raise BeanFieldNotFoundException(msg)

        if fld not in self.__beanFields[bean]:
            msg = "Bean %s field %s not in list of bean fields (%s)" % \
                (bean, fld, str(self.__beanFields[bean]))
            raise BeanFieldNotFoundException(msg)

        return unFixValue(self.__client.mbean.get(bean, fld))

    def getRPCClient(self, addr, port):
        return RPCClient(addr, port)

    def listBeans(self):
        return self.__beanList[:]

    def monitor(self, now):
        bSrt = self.__beanFields.keys()
        bSrt.sort()
        for b in bSrt:
            attrs = self.__client.mbean.getAttributes(b, self.__beanFields[b])

            # report monitoring data
            if len(attrs) > 0:
                for k in attrs.keys():
                    attrs[k] = unFixValue(attrs[k])
                self._report(now, b, attrs)

    def monitorBean(self, now, bean):
        if bean not in self.__beanList:
            msg = "Bean %s not in list of %s-%d beans" % \
                (bean, self.__name, self.__daqID)
            raise BeanFieldNotFoundException(msg)

        attrs = self.__client.mbean.getAttributes(bean, self.__beanFields[bean])

        # report monitoring data
        if len(attrs) > 0:
            for k in attrs.keys():
                attrs[k] = unFixValue(attrs[k])
            self._report(now, bean, attrs)

    def monitorField(self, now, bean, fld):
        if bean not in self.__beanList:
            msg = "Bean %s not in list of %s-%d beans" % \
                (bean, self.__name, self.__daqID)
            raise BeanFieldNotFoundException(msg)

        val = unFixValue(self.__client.mbean.get(bean, fld))

        self._report(now, bean, { fld:val, })

class FileMoniData(MoniData):
    def __init__(self, name, daqID, addr, port, fname):
        self.__fd = self.openFile(fname)

        super(FileMoniData, self).__init__(name, daqID, addr, port)

    def _report(self, now, beanName, attrs):
        print >>self.__fd, '%s: %s:' % (beanName, now)
        for key in attrs:
            print >>self.__fd, '\t%s: %s' % \
                (key, str(attrs[key]))
        print >>self.__fd
        self.__fd.flush()

    def openFile(self, fname):
        "Open file -- might return an exception"
        if fname is None:
            return sys.stdout
        return open(fname, "w+")

class LiveMoniData(MoniData):
    def __init__(self, name, daqID, addr, port):
        super(LiveMoniData, self).__init__(name, daqID, addr, port)

        self.__moni = LiveMonitor()

    def _report(self, now, beanName, attrs):
        if not MoniData.SEND_LIVE_MONI: return

        for key in attrs:
            self.__moni.send('%s*%s+%s' %
                             (str(self), beanName, key), now, attrs[key])

class BothMoniData(FileMoniData):
    def __init__(self, name, daqID, addr, port, fname):
        super(BothMoniData, self).__init__(name, daqID, addr, port, fname)

        self.__moni = LiveMonitor()

    def _report(self, now, beanName, attrs):
        super(BothMoniData, self)._report(now, beanName, attrs)

        if not MoniData.SEND_LIVE_MONI: return

        for key in attrs:
            self.__moni.send('%s*%s+%s' %
                             (str(self), beanName, key), now, attrs[key])

class MoniThread(threading.Thread):
    def __init__(self, moniData, log, quiet):
        self.__moniData = moniData
        self.__log = log
        self.__quiet = quiet

        self.now = None
        self.done = True

        threading.Thread.__init__(self)

        self.setName(str(self.__moniData))

    def getNewThread(self, now):
        mt = MoniThread(self.__moniData, self.__log, self.__quiet)
        mt.now = now
        return mt

    def run(self):
        self.done = False
        try:
            self.__moniData.monitor(self.now)
        except Exception:
            self.__log.error("Ignoring %s: %s" %
                             (str(self.__moniData), exc_string()))

        self.done = True

class DAQMoni(object):
    TYPE_FILE = 1
    TYPE_LIVE = 2
    TYPE_BOTH = 3

    def __init__(self, daqLog, moniPath, components, moniType, quiet=False):
        self.__log         = daqLog
        self.__quiet       = quiet
        self.__moniList    = {}
        self.__threadList  = {}
        for c, comp in components.iteritems():
            if comp.mbeanPort() > 0:
                if moniType == DAQMoni.TYPE_LIVE:
                    md = self.createLiveData(comp.name(), comp.id(),
                                             comp.inetAddress(),
                                             comp.mbeanPort())
                else:
                    fname = DAQMoni.fileName(moniPath, comp.name(),
                                             comp.id())
                    self.__log.info(("Creating moni output file %s (remote" +
                                     " is %s:%d)") %
                                    (fname, comp.inetAddress(),
                                     comp.mbeanPort()))
                    try:
                        if moniType == DAQMoni.TYPE_FILE:
                            md = self.createFileData(comp.name(), comp.id(),
                                                     comp.inetAddress(),
                                                     comp.mbeanPort(), fname)
                        else:
                            md = self.createBothData(comp.name(), comp.id(),
                                                     comp.inetAddress(),
                                                     comp.mbeanPort(), fname)
                    except Exception:
                        self.__log.error(("Couldn't create monitoring output" +
                                          ' (%s) for component %d!: %s') %
                                         (fname, c, exc_string()))
                        continue

                self.__moniList[c] = md
                self.__threadList[c] = MoniThread(md, self.__log, self.__quiet)

    def createBothData(self, name, daqID, addr, port, fname):
        return BothMoniData(name, daqID, addr, port, fname)

    def createFileData(self, name, daqID, addr, port, fname):
        return FileMoniData(name, daqID, addr, port, fname)

    def createLiveData(self, name, daqID, addr, port):
        return LiveMoniData(name, daqID, addr, port)

    def fileName(path, name, daqID):
        return os.path.join(path, "%s-%d.moni" % (name, daqID))
    fileName = staticmethod(fileName)

    def getSingleBeanField(self, ID, beanName, beanField):
        if not self.__moniList:
            raise BeanFieldNotFoundException("Empty list of monitoring" +
                                             " objects")
        if ID not in self.__moniList:
            raise BeanFieldNotFoundException("Component %d not found" % ID)
        return self.__moniList[ID].getBeanField(ID, beanName, beanField)

    def doMoni(self):
        now = None
        for c in self.__threadList.keys():
            if self.__threadList[c].done:
                if now is None:
                    now = datetime.datetime.now()
                self.__threadList[c] = self.__threadList[c].getNewThread(now)
                self.__threadList[c].done = False
                self.__threadList[c].start()

    def isActive(self):
        for c in self.__threadList.keys():
            if not self.__threadList[c].done:
                return True
        return False

    def listBeans(self, ID):
        if not self.__moniList:
            raise BeanFieldNotFoundException("Empty list of monitoring objects")
        if ID not in self.__moniList:
            raise BeanFieldNotFoundException("Component %d not found" % ID)
        return self.__moniList[ID].listBeans()


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
                port = sys.argv[i][colon+1:]
                host = sys.argv[i][:colon]

                beanName = None
                fldName = None

                colon = port.find(':')
                if colon > 0:
                    beanName = port[colon+1:]
                    port = port[:colon]
                    
                    colon = beanName.find(':')
                    if colon > 0:
                        fldName = beanName[colon+1:]
                        beanName = beanName[:colon]

                moni = FileMoniData('unknown', 0, host, port, None)
                if beanName is None:
                    moni.monitor('snapshot')
                elif fldName is None:
                    moni.monitorBean('snapshot', beanName)
                else:
                    moni.monitorField('snapshot', beanName, fldName)
    if usage:
        print "Usage: DAQMoni.py host:beanPort[:beanName[:fldName]]" + \
            " [host:beanPort[:beanName[:fldName]] ...]"
        raise SystemExit

