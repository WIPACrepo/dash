#!/usr/bin/env python

import datetime
import socket
import threading
try:
    import xmlrpclib as xclient
except ImportError:
    import xmlrpc.client as xclient

from CnCLogger import CnCLogger
from DAQRPC import RPCClient
from UniqueID import UniqueID
from scmversion import get_scmversion_str

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


def unFixValue(obj):
    """
    Look for numbers masquerading as strings.  If an obj is a string and
    successfully converts to a number, return that number.  If obj is a dict
    or list, recurse into it converting all numeric back into numbers.  All
    other types are unaltered.  This pairs with the similarly named fix*
    methods in icecube.daq.juggler.mbean.XMLRPCServer
    """
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            obj[k] = unFixValue(obj[k])
    elif isinstance(obj, list):
        for i in range(0, len(obj)):
            obj[i] = unFixValue(obj[i])
    elif isinstance(obj, tuple):
        newObj = []
        for v in obj:
            newObj.append(unFixValue(v))
        obj = tuple(newObj)
    elif isinstance(obj, str):
        try:
            if obj.endswith("L"):
                return int(obj[:-1])
            else:
                return int(obj)
        except ValueError:
            pass
    return obj


class BeanException(Exception):
    pass


class BeanFieldNotFoundException(BeanException):
    pass


class BeanLoadException(BeanException):
    pass


class BeanTimeoutException(BeanException):
    pass


class MBeanClient(object):
    def __init__(self, compName, host, port):
        "Python interface to Java MBeanAgent"
        self.__compName = compName
        self.__client = self.createClient(host, port)
        self.__beanList = []
        self.__beanFields = {}

        self.__beanLock = threading.Lock()
        self.__loadedInfo = False

    def __str__(self):
        return "MBeanClient(%s)" % (self.__compName, )

    def __loadBeanInfo(self):
        """
        Get the bean names and fields from the remote client
        Note that self.__beanLock is acquired before calling this method
        """

        self.__loadedInfo = False
        try:
            self.__beanList = self.__client.mbean.listMBeans()
        except socket.error as serr:
            raise BeanTimeoutException("Cannot get list of %s MBeans"
                                       " <socket error %s>" %
                                       (self.__compName, serr))
        except (xclient.Fault, xclient.ProtocolError) as xerr:
            raise BeanTimeoutException("Cannot get list of %s MBeans: %s" %
                                       (self.__compName, xerr))
        except:
            raise BeanLoadException("Cannot load list of %s MBeans: %s " %
                                    (self.__compName, exc_string()))

        failed = []
        for bean in self.__beanList:
            try:
                self.__beanFields[bean] = self.__client.mbean.listGetters(bean)
            except:
                # don't let a single failure abort remaining fetches,
                failed.append(bean)

                # make sure bean has an entry
                if bean not in self.__beanFields:
                    self.__beanFields[bean] = []

        if len(failed) > 0:
            raise BeanLoadException("Cannot load %s MBeans %s: %s" %
                                    (self.__compName, failed, exc_string()))

        self.__loadedInfo = True

    def __lockAndLoad(self):
        "load bean info from the remote client if it hasn't yet been loaded"

        if not self.__loadedInfo:
            with self.__beanLock:
                if not self.__loadedInfo:
                    self.__loadBeanInfo()

    def createClient(self, host, port):
        "create an MBean RPC client"
        return RPCClient(host, port)

    def get(self, bean, fld):
        "get the value for a single MBean field"
        try:
            with self.__beanLock:
                val = self.__client.mbean.get(bean, fld)
        except socket.error as serr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s:%s\":"
                                       " <socket error %s>" %
                                       (self.__compName, bean, fld, serr))
        except (xclient.Fault, xclient.ProtocolError) as xerr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s:%s\": %s" %
                                       (self.__compName, bean, fld, xerr))
        except:
            raise BeanLoadException("Cannot load %s MBean \"%s:%s\": %s" %
                                    (self.__compName, bean, fld,
                                     exc_string()))

        return unFixValue(val)

    def getAttributes(self, bean, fldList):
        "get the values for a list of MBean fields"
        try:
            with self.__beanLock:
                attrs = self.__client.mbean.getAttributes(bean, fldList)
        except socket.error as serr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s\""
                                       " attributes <socket error %s>" %
                                       (self.__compName, bean, serr))
        except (xclient.Fault, xclient.ProtocolError) as xerr:
            raise BeanTimeoutException("Cannot get %s MBean \"%s\":"
                                       " attributes %s" %
                                       (self.__compName, bean, xerr))
        except:
            raise BeanLoadException("Cannot load %s MBean \"%s\""
                                    " attributes %s: %s" %
                                    (self.__compName, bean, fldList,
                                     exc_string()))

        if not isinstance(attrs, dict):
            raise BeanException("%s getAttributes(%s, %s) should return dict,"
                                " not %s (%s)" % (self.__compName, bean,
                                                  fldList, type(attrs), attrs))

        if len(attrs) > 0:
            for k in list(attrs.keys()):
                attrs[k] = unFixValue(attrs[k])
        return attrs

    def getBeanNames(self):
        "return a list of MBean names associated with this component"
        self.__lockAndLoad()

        return self.__beanList

    def getBeanFields(self, bean):
        "return a list of fields associated with this component's MBean"
        self.__lockAndLoad()

        if bean not in self.__beanFields:
            msg = "Bean %s not in list of beans for %s" % \
                (bean, self.__compName)
            raise BeanFieldNotFoundException(msg)

        return self.__beanFields[bean]

    def getDictionary(self):
        "get the value for all MBean fields"
        with self.__beanLock:
            try:
                attrs = self.__client.mbean.getDictionary()
            except socket.error as serr:
                raise BeanTimeoutException("Cannot get %s MBean attributes:"
                                           " <socket error %s>" %
                                           (self.__compName, serr))
            except (xclient.Fault, xclient.ProtocolError) as xerr:
                raise BeanTimeoutException("Cannot get %s MBean attributes:"
                                           " %s" % (self.__compName, xerr))
            except:
                raise BeanLoadException("Cannot load %s MBean attributes:"
                                        " %s" %
                                        (self.__compName, exc_string()))

        if not isinstance(attrs, dict):
            raise BeanException("%s getDictionary() should return dict,"
                                " not %s (%s)" % \
                                (self.__compName, type(attrs).__name__, attrs))

        if len(attrs) > 0:
            for k in list(attrs.keys()):
                attrs[k] = unFixValue(attrs[k])
        return attrs

    def reload(self):
        "reload MBean names and fields during the next request"
        self.__loadedInfo = False


class ComponentName(object):
    "DAQ component name"
    def __init__(self, name, num):
        self.__name = name
        self.__num = num

    def __repr__(self):
        return self.fullname

    @property
    def filename(self):
        return '%s-%d' % (self.__name, self.__num)

    @property
    def fullname(self):
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    @property
    def isBuilder(self):
        "Is this an eventBuilder (or debugging fooBuilder)?"
        return self.__name.lower().find("builder") >= 0

    def isComponent(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def isHub(self):
        return self.__name.endswith("Hub")

    @property
    def isReplayHub(self):
        return self.isHub and self.__name.lower().find("replay") >= 0

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num


class DAQClientException(Exception):
    pass


class DAQClientState(object):
    # internal state indicating that the client hasn't answered
    # some number of pings but has not been declared dead
    #
    MISSING = 'missing'

    # internal state indicating that the client is
    # no longer responding to pings
    #
    DEAD = "DEAD"

    # internal state indicating that the client has not answered
    # an XML-RPC call
    #
    HANGING = "hanging"

    # internal state indicating that the most recent XML-RPC call failed
    #
    ERROR = "ERROR"


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

    # maximum number of failed pings before a component is declared dead
    #
    MAX_DEAD_COUNT = 3

    # next component ID
    #
    ID = UniqueID()

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

        self.__id = next(DAQClient.ID)

        self.__host = host
        self.__port = port
        self.__mbeanPort = mbeanPort
        self.__connectors = connectors

        self.__deadCount = 0
        self.__cmdOrder = None

        self.__log = self.createLogger(quiet=quiet)

        self.__client = self.createClient(host, port)

        try:
            self.__mbean = self.createMBeanClient()
        except:
            self.__mbean = None

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

        if self.__deadCount == 0:
            deadStr = ''
        else:
            deadStr = " DEAD#%d" % self.__deadCount

        return "ID#%d %s%s%s%s%s" % \
            (self.__id, self.fullname, hpStr, mbeanStr, extraStr, deadStr)

    def addDeadCount(self):
        self.__deadCount += 1

    def close(self):
        self.__log.close()

    def commitSubrun(self, subrunNum, latestTime):
        "Start marking events with the subrun number"
        try:
            return self.__client.xmlrpc.commitSubrun(subrunNum, latestTime)
        except:
            self.__log.error(exc_string())
            return None

    def configure(self, configName=None):
        "Configure this component"
        try:
            if not configName:
                return self.__client.xmlrpc.configure()
            else:
                return self.__client.xmlrpc.configure(configName)
        except:
            self.__log.error(exc_string())
            return None

    def connect(self, connList=None):
        "Connect this component with other components in a runset"

        if not connList:
            return self.__client.xmlrpc.connect()

        cl = []
        for conn in connList:
            cl.append(conn.map())

        return self.__client.xmlrpc.connect(cl)

    def connectors(self):
        return self.__connectors[:]

    def createClient(self, host, port):
        return RPCClient(host, port)

    def createLogger(self, quiet):
        return CnCLogger(self.fullname, quiet=quiet)

    def createMBeanClient(self):
        return MBeanClient(self.fullname, self.__host, self.__mbeanPort)

    def forcedStop(self):
        "Force component to stop running"
        try:
            return self.__client.xmlrpc.forcedStop()
        except:
            self.__log.error(exc_string())
            return None

    def getReplayStartTime(self):
        "Get the earliest time for a replay hub"
        try:
            return unFixValue(self.__client.xmlrpc.getReplayStartTime())
        except:
            self.__log.error(exc_string())
            return None

    def getRunData(self, runNum):
        "Get the run data for the specified run"
        try:
            return unFixValue(self.__client.xmlrpc.getRunData(runNum))
        except:
            self.__log.error(exc_string())
            return None

    def getRunNumber(self):
        "Get the current run number"
        try:
            return self.__client.xmlrpc.getRunNumber()
        except:
            self.__log.error(exc_string())
            return None

    @property
    def host(self):
        return self.__host

    @property
    def id(self):
        return self.__id

    @property
    def is_dead(self):
        return self.__deadCount >= self.MAX_DEAD_COUNT

    @property
    def is_dying(self):
        return self.__deadCount > 0

    @property
    def isSource(self):
        "Is this component a source of data?"

        # XXX Hack for stringHubs which are sources but which confuse
        #     things by also reading requests from the eventBuilder
        if self.isHub:
            return True

        for conn in self.__connectors:
            if conn.isInput:
                return False

        return True

    def listConnectorStates(self):
        return self.__client.xmlrpc.listConnectorStates()

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

        self.__client.xmlrpc.logTo(logIP, logPort, liveIP, livePort)

        self.__log.debug("Version info: " + get_scmversion_str())

    def map(self):
        return {"id": self.__id,
                "compName": self.name,
                "compNum": self.num,
                "host": self.__host,
                "rpcPort": self.__port,
                "mbeanPort": self.__mbeanPort}

    def matches(self, other):
        return self.name == other.name and self.num == other.num and \
            self.__host == other.__host and self.__port == other.__port and \
            self.__mbeanPort == other.__mbeanPort

    @property
    def mbean(self):
        return self.__mbean

    @property
    def mbeanPort(self):
        return self.__mbeanPort

    def order(self):
        return self.__cmdOrder

    @property
    def port(self):
        return self.__port

    def prepareSubrun(self, subrunNum):
        "Start marking events as bogus in preparation for subrun"
        try:
            return self.__client.xmlrpc.prepareSubrun(subrunNum)
        except:
            self.__log.error(exc_string())
            return None

    def reset(self):
        "Reset component back to the idle state"
        self.__log.closeLog()
        return self.__client.xmlrpc.reset()

    def resetLogging(self):
        "Reset component back to the idle state"
        self.__log.resetLog()
        return self.__client.xmlrpc.resetLogging()

    def setFirstGoodTime(self, payTime):
        "Set the first time where all hubs have reported a hit"
        try:
            self.__client.xmlrpc.setFirstGoodTime(str(payTime) + "L")
        except:
            self.__log.error(exc_string())

    def setLastGoodTime(self, payTime):
        "Set the last time where all hubs have reported a hit"
        try:
            self.__client.xmlrpc.setLastGoodTime(str(payTime) + "L")
        except:
            self.__log.error(exc_string())

    def setOrder(self, orderNum):
        self.__cmdOrder = orderNum

    def setReplayOffset(self, offset):
        "Get the time offset for a replay hub"
        try:
            self.__client.xmlrpc.setReplayOffset(str(offset) + "L")
        except:
            self.__log.error(exc_string())

    def startRun(self, runNum):
        "Start component processing DAQ data"
        try:
            return self.__client.xmlrpc.startRun(runNum)
        except:
            self.__log.error(exc_string())
            return None

    def startSubrun(self, data):
        "Send subrun data to stringHubs"
        try:
            return self.__client.xmlrpc.startSubrun(data)
        except:
            self.__log.error(exc_string())
            return None

    @property
    def state(self):
        "Get current state"
        try:
            state = self.__client.xmlrpc.getState()
        except (socket.error, xclient.Fault, xclient.ProtocolError):
            state = None
        except:
            self.__log.error(exc_string())
            state = None

        if state is not None:
            self.__deadCount = 0
        elif not self.is_dead:
            state = DAQClientState.MISSING
        else:
            state = DAQClientState.DEAD

        return state

    def stopRun(self):
        "Stop component processing DAQ data"
        try:
            return self.__client.xmlrpc.stopRun()
        except:
            self.__log.error(exc_string())
            return None

    def subrunEvents(self, subrunNumber):
        "Get the number of events in the specified subrun"
        try:
            evts = self.__client.xmlrpc.getEvents(subrunNumber)
            if isinstance(evts, str):
                evts = int(evts[:-1])
            return evts
        except:
            self.__log.error(exc_string())
            return None

    def switchToNewRun(self, newRun):
        "Switch to new run"
        try:
            return self.__client.xmlrpc.switchToNewRun(newRun)
        except:
            self.__log.error(exc_string())
            return None

    def terminate(self):
        "Terminate component"
        state = self.state
        if state != "idle" and state != "ready" and \
                state != DAQClientState.MISSING and \
                state != DAQClientState.DEAD:
            raise DAQClientException("%s state is %s" % (self, state))

        self.__log.closeFinal()
        try:
            self.__client.xmlrpc.terminate()
        except:
            # ignore termination exceptions
            pass
