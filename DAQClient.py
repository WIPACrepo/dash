#!/usr/bin/env python

import os, socket, sys, threading

from CnCLogger import CnCLogger
from DAQRPC import RPCClient
from RunSet import RunSet
from UniqueID import UniqueID

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID  = "$Id: CnCServer.py 4782 2009-12-04 15:50:49Z dglo $"

class BeanFieldNotFoundException(Exception): pass

class MBeanClient(object):
    def __init__(self, compName, host, port):
        self.__compName = compName
        self.__client = RPCClient(host, port)

        self.__beanFields = {}
        self.__beanList = self.__client.mbean.listMBeans()
        for bean in self.__beanList:
            self.__beanFields[bean] = self.__client.mbean.listGetters(bean)

    def __unFixValue(cls, obj):

        """ Look for numbers masquerading as strings.  If an obj is a
        string and successfully converts to a number, return that
        convertion.  If obj is a dict or list, recuse into it
        converting all such masquerading strings.  All other types are
        unaltered.  This pairs with the similarly named fix* methods in
        icecube.daq.juggler.mbean.XMLRPCServer """

        if type(obj) is dict:
            for k in obj.keys():
                obj[k] = cls.__unFixValue(obj[k])
        elif type(obj) is list:
            for i in xrange(0, len(obj)):
                obj[i] = cls.__unFixValue(obj[i])
        elif type(obj) is str:
            try:
                return int(obj)
            except ValueError:
                pass
        return obj
    __unFixValue = classmethod(__unFixValue)

    def checkBeanField(self, bean, fld):
        if bean not in self.__beanList:
            msg = "Bean %s not in list of beans for %s" % \
                (bean, self.__compName)
            raise BeanFieldNotFoundException(msg)

        if fld not in self.__beanFields[bean]:
            msg = "Bean %s field %s not in list of bean fields for %s (%s)" % \
                (bean, fld, self.__compName, str(self.__beanFields[bean]))
            raise BeanFieldNotFoundException(msg)

    def get(self, bean, fld):
        self.checkBeanField(bean, fld)

        return self.__unFixValue(self.__client.mbean.get(bean, fld))

    def getAttributes(self, bean, fldList):
        attrs = self.__client.mbean.getAttributes(bean, fldList)
        if type(attrs) == dict and len(attrs) > 0:
            for k in attrs.keys():
                attrs[k] = self.__unFixValue(attrs[k])
        return attrs

    def getBeanNames(self):
        return self.__beanList

    def getBeanFields(self, bean):
        if bean not in self.__beanList:
            msg = "Bean %s not in list of beans for %s" % \
                (bean, self.__compName)
            raise BeanFieldNotFoundException(msg)

        return self.__beanFields[bean]

class ComponentName(object):
    "DAQ component name"
    def __init__(self, name, num):
        self.__name = name
        self.__num = num

    def __repr__(self):
        return self.fullName()

    def fileName(self):
        return '%s-%d' % (self.__name, self.__num)

    def fullName(self):
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    def isBuilder(self):
        "Is this an eventBuilder (or debugging fooBuilder)?"
        return self.__name.endswith("Builder")

    def isComponent(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__name == name and (num < 0 or self.__num == num)

    def isHub(self):
        return self.__name.endswith("Hub")

    def name(self):
        return self.__name

    def num(self):
        return self.__num

class DAQClientException(Exception): pass

class DAQClient(ComponentName):
    """DAQ component
    id - internal client ID
    name - component name
    num - component instance number
    host - component host name
    port - component port number
    mbeanPort - component's MBean server port number
    connectors - list of Connectors
    client - XML-RPC client
    deadCount - number of sequential failed pings
    cmdOrder - order in which start/stop commands are issued
    """

    # next component ID
    #
    ID = UniqueID()

    # internal state indicating that the client hasn't answered
    # some number of pings but has not been declared dead
    #
    STATE_MISSING = 'MIA'

    # internal state indicating that the client is
    # no longer responding to pings
    #
    STATE_DEAD = RunSet.STATE_DEAD

    def __init__(self, name, num, host, port, mbeanPort, connectors,
                 quiet=False):
        """
        DAQClient constructor
        name - component name
        num - component instance number
        host - component host name
        port - component port number
        mbeanPort - component MBean port number
        connectors - list of Connectors
        """

        super(DAQClient, self).__init__(name, num)

        self.__id = DAQClient.ID.next()

        self.__host = host
        self.__port = port
        self.__mbeanPort = mbeanPort
        self.__connectors = connectors

        self.__deadCount = 0
        self.__cmdOrder = None

        self.__log = self.createLogger(quiet=quiet)

        self.__client = self.createClient(host, port)
        self.__clientLock = threading.Lock()

        self.__mbean = self.createMBeanClient(host, mbeanPort)
        self.__mbeanLock = threading.Lock()

    def __str__(self):
        "String description"
        if self.__port <= 0:
            hpStr = ''
        else:
            hpStr = ' at %s:%d' % (self.__host, self.__port)

        if self.__mbeanPort <= 0:
            mbeanStr = ''
        else:
            mbeanStr = ' M#%d' % self.__mbeanPort

        extraStr = ''
        if self.__connectors and len(self.__connectors) > 0:
            first = True
            for c in self.__connectors:
                if first:
                    extraStr += ' [' + str(c)
                    first = False
                else:
                    extraStr += ' ' + str(c)
            extraStr += ']'

        return "ID#%d %s#%s%s%s%s" % \
            (self.__id, self.name(), self.num(), hpStr, mbeanStr, extraStr)

    def checkBeanField(self, bean, field):
        self.__mbean.checkBeanField(bean, field)

    def close(self):
        self.__log.close()

    def commitSubrun(self, subrunNum, latestTime):
        "Start marking events with the subrun number"
        try:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.commitSubrun(subrunNum, latestTime)
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def configure(self, configName=None):
        "Configure this component"
        try:
            if not configName:
                self.__clientLock.acquire()
                try:
                    return self.__client.xmlrpc.configure()
                finally:
                    self.__clientLock.release()
            else:
                self.__clientLock.acquire()
                try:
                    return self.__client.xmlrpc.configure(configName)
                finally:
                    self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def connect(self, connList=None):
        "Connect this component with other components in a runset"

        if not connList:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.connect()
            finally:
                self.__clientLock.release()

        cl = []
        for conn in connList:
            cl.append(conn.map())

        self.__clientLock.acquire()
        try:
            return self.__client.xmlrpc.connect(cl)
        finally:
            self.__clientLock.release()

    def connectors(self):
        return self.__connectors[:]

    def createClient(self, host, port):
        return RPCClient(host, port)

    def createLogger(self, quiet):
        return CnCLogger(quiet=quiet)

    def createMBeanClient(self, host, mbeanPort):
        return MBeanClient(self.fullName(), host, mbeanPort)

    def events(self, subrunNumber):
        "Get the number of events in the specified subrun"
        try:
            self.__clientLock.acquire()
            try:
                evts = self.__client.xmlrpc.getEvents(subrunNumber)
            finally:
                self.__clientLock.release()
            if type(evts) == str:
                evts = long(evts[:-1])
            return evts
        except:
            self.__log.error(exc_string())
            return None

    def forcedStop(self):
        "Force component to stop running"
        try:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.forcedStop()
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def getBeanFields(self, bean):
        return self.__mbean.getBeanFields(bean)

    def getBeanNames(self):
        return self.__mbean.getBeanNames()

    def getMultiBeanFields(self, name, fieldList):
        self.__mbeanLock.acquire()
        try:
            return self.__mbean.getAttributes(name, fieldList)
        finally:
            self.__mbeanLock.release()

    def getNonstoppedConnectorsString(self):
        """
        Return string describing states of all connectors
        which have not yet stopped
        """
        try:
            self.__clientLock.acquire()
            try:
                connStates = self.__client.xmlrpc.listConnectorStates()
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

        csStr = None
        for cs in connStates:
            if cs["state"] == 'idle':
                continue
            if not csStr:
                csStr = '['
            else:
                csStr += ', '
            csStr += '%s:%s' % (cs["type"], cs["state"])

        if not csStr:
            csStr = ''
        else:
            csStr += ']'

        return csStr

    def getSingleBeanField(self, name, field):
        self.__mbeanLock.acquire()
        try:
            return self.__mbean.get(name, field)
        finally:
            self.__mbeanLock.release()

    def host(self):
        return self.__host

    def id(self):
        return self.__id

    def isSource(self):
        "Is this component a source of data?"

        # XXX Hack for stringHubs which are sources but which confuse
        #     things by also reading requests from the eventBuilder
        if self.isHub():
            return True

        for conn in self.__connectors:
            if conn.isInput():
                return False

        return True

    def listConnectorStates(self):
        self.__clientLock.acquire()
        try:
            return self.__client.xmlrpc.listConnectorStates()
        finally:
            self.__clientLock.release()

    def logTo(self, logIP, logPort, liveIP, livePort):
        "Send log messages to the specified host and port"
        self.__log.openLog(logIP, logPort, liveIP, livePort)

        if logIP is None:
            logIP = ''
        if logPort is None:
            logPort = 0
        if liveIP is None:
            liveIP = ''
        if livePort is None:
            livePort = 0

        self.__clientLock.acquire()
        try:
            self.__client.xmlrpc.logTo(logIP, logPort, liveIP, livePort)
            infoStr = self.__client.xmlrpc.getVersionInfo()
        finally:
            self.__clientLock.release()

        self.__log.debug(("Version info: %(filename)s %(revision)s" +
                          " %(date)s %(time)s %(author)s %(release)s" +
                          " %(repo_rev)s") % get_version_info(infoStr))

    def map(self):
        return { "id" : self.__id,
                 "compName" : self.name(),
                 "compNum" : self.num(),
                 "host" : self.__host,
                 "rpcPort" : self.__port,
                 "mbeanPort" : self.__mbeanPort }

    def mbeanPort(self):
        return self.__mbeanPort

    def monitor(self):
        "Return the monitoring value"
        return self.state()

    def order(self):
        return self.__cmdOrder

    def port(self):
        return self.__port

    def prepareSubrun(self, subrunNum):
        "Start marking events as bogus in preparation for subrun"
        try:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.prepareSubrun(subrunNum)
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def reset(self):
        "Reset component back to the idle state"
        self.__log.closeLog()
        self.__clientLock.acquire()
        try:
            return self.__client.xmlrpc.reset()
        finally:
            self.__clientLock.release()

    def resetLogging(self):
        "Reset component back to the idle state"
        self.__log.resetLog()
        self.__clientLock.acquire()
        try:
            return self.__client.xmlrpc.resetLogging()
        finally:
            self.__clientLock.release()

    def setOrder(self, orderNum):
        self.__cmdOrder = orderNum

    def startRun(self, runNum):
        "Start component processing DAQ data"
        try:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.startRun(runNum)
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def startSubrun(self, data):
        "Send subrun data to stringHubs"
        try:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.startSubrun(data)
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def state(self):
        "Get current state"
        try:
            self.__clientLock.acquire()
            try:
                state = self.__client.xmlrpc.getState()
            finally:
                self.__clientLock.release()
        except socket.error:
            state = None
        except:
            self.__log.error(exc_string())
            state = None

        if not state:
            self.__deadCount += 1
            if self.__deadCount < 3:
                state = DAQClient.STATE_MISSING
            else:
                state = DAQClient.STATE_DEAD

        return state

    def stopRun(self):
        "Stop component processing DAQ data"
        try:
            self.__clientLock.acquire()
            try:
                return self.__client.xmlrpc.stopRun()
            finally:
                self.__clientLock.release()
        except:
            self.__log.error(exc_string())
            return None

    def terminate(self):
        "Terminate component"
        state = self.state()
        if state != "idle" and state != "ready" and \
                state != self.STATE_MISSING and state != self.STATE_DEAD:
            raise DAQClientException("%s state is %s" % (self, state))

        self.__log.closeLog()
        try:
            self.__client.xmlrpc.terminate()
        except:
            # ignore termination exceptions
            pass
