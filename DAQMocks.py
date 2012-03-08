#!/usr/bin/env python
#
# Classes used for pDAQ unit testing

import datetime
import os
import re
import select
import socket
import sys
import tempfile
import threading
import time

from unittest import TestCase

from CnCLogger import CnCLogger
from Component import Component
from DAQClient import DAQClient
import DeployPDAQ
from DAQConst import DAQPort
from DAQLaunch import RELEASE, getCompJar
from LiveImports import SERVICE_NAME
from utils import ip
from utils.DashXMLLog import DashXMLLog

import traceback

if "PDAQ_HOME" in os.environ:
    METADIR = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    METADIR = find_pdaq_trunk()


class BaseChecker(object):
    PAT_DAQLOG = re.compile(r'^([^\]]+)\s+\[([^\]]+)\]\s+(.*)$', re.MULTILINE)
    PAT_LIVELOG = re.compile(r'^(\S+)\((\S+):(\S+)\)\s+(\d+)\s+\[([^\]]+)\]' +
                             r'\s+(.*)$', re.MULTILINE)

    def __init__(self):
        pass

    def check(self, checker, msg, debug, setError=True):
        raise NotImplementedError()


class BaseLiveChecker(BaseChecker):
    def __init__(self, varName):
        self.__varName = varName
        super(BaseLiveChecker, self).__init__()

    def __str__(self):
        return '%s:%s=%s' % \
            (self._getShortName(), self.__varName, self._getValue())

    def _checkText(self, checker, msg, debug, setError):
        raise NotImplementedError()

    def _getShortName(self):
        raise NotImplementedError()

    def _getValue(self):
        raise NotImplementedError()

    def _getValueType(self):
        raise NotImplementedError()

    def check(self, checker, msg, debug, setError=True):
        m = BaseChecker.PAT_LIVELOG.match(msg)
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:LFMT: %s' % (name, msg)
                checker.setError('Bad format for %s I3Live message "%s"' %
                                 (name, msg))
            return False

        svcName = m.group(1)
        varName = m.group(2)
        varType = m.group(3)
        msgPrio = m.group(4)
        msgTime = m.group(5)
        msgText = m.group(6)

        global SERVICE_NAME
        if svcName != SERVICE_NAME:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:SVC: %s (%s)' % \
                        (name, SERVICE_NAME, self._getValue())
                checker.setError(('Expected %s I3Live service "%s", not "%s"' +
                                  ' in "%s"') %
                                 (name, SERVICE_NAME, svcName, msg))
            return False

        if varName != self.__varName:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:VAR: %s (%s)' % \
                        (name, self.__varName, self._getValue())
                    checker.setError(('Expected %s I3Live varName "%s",' +
                                      ' not "%s" in "%s"') %
                                     (name, self.__varName, varName, msg))
            return False

        typeStr = self._getValueType()
        if varType != typeStr:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:TYPE: %s (%s)' % \
                        (name, typeStr, self._getValue())
                checker.setError(('Expected %s I3Live type "%s", not "%s"' +
                                  ' in %s') % (name, typeStr, varType, msg))
            return False

        # ignore priority
        # ignore time

        if not self._checkText(checker, msgText, debug, setError):
            return False

        return True


class ExactChecker(BaseChecker):
    def __init__(self, text):
        self.__text = text
        super(ExactChecker, self).__init__()

    def __str__(self):
        return 'EXACT:%s' % self.__text

    def check(self, checker, msg, debug, setError=True):
        if msg != self.__text:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:XACT: %s' % (name, self.__text)
                checker.setError(('Expected %s exact log message "%s",' +
                                  ' not "%s"') % (name, self.__text, msg))
            return False

        return True


class LiveChecker(BaseLiveChecker):
    def __init__(self, varName, value, varType=None):
        self.__value = value
        self.__type = varType

        super(LiveChecker, self).__init__(varName)

    def __fixValue(self, val):
        if type(val) == str:
            return "\"%s\"" % val

        if type(val) == long:
            vstr = str(val)
            if vstr.endswith("L"):
                return vstr[:-1]
            return vstr

        if type(val) == bool:
            return self.__value and "true" or "false"

        return str(val)

    def _checkText(self, checker, msg, debug, setError):
        if self.__type is None or self.__type != "json":
            valStr = str(self.__value)
        elif type(self.__value) == list or type(self.__value) == tuple:
            valStr = "["
            for v in self.__value:
                if len(valStr) > 1:
                    valStr += ", "
                valStr += self.__fixValue(v)
            valStr += "]"
        elif type(self.__value) == dict:
            valStr = "{"
            for k in self.__value.keys():
                if len(valStr) > 1:
                    valStr += ", "
                valStr += self.__fixValue(k)
                valStr += ": "
                valStr += self.__fixValue(self.__value[k])
            valStr += "}"
        else:
            valStr = str(self.__value)

        if msg != valStr:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:LIVE: %s' % (name, valStr)
                checker.setError(('Expected %s live log message '
                                  '"%s", not "%s"') % \
                                     (name, valStr, msg))
            return False

        return True

    def _getShortName(self):
        return 'LIVE'

    def _getValue(self):
        return self.__value

    def _getValueType(self):
        if self.__type is not None:
            return self.__type
        return type(self.__value).__name__


class LiveRegexpChecker(BaseLiveChecker):
    def __init__(self, varName, pattern):
        self.__regexp = re.compile(pattern)
        super(LiveRegexpChecker, self).__init__(varName)

    def _checkText(self, checker, msg, debug, setError):
        m = self.__regexp.match(msg)
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:RLIV: %s' % \
                        (name, self.__regexp.pattern)
                checker.setError(('Expected %s I3Live regexp message "%s",' +
                                  ' not "%s"') %
                                 (name, self.__regexp.pattern, msg))
            return False

        return True

    def _getShortName(self):
        return 'LIVREX'

    def _getValue(self):
        return self.__regexp.pattern

    def _getValueType(self):
        return 'str'


class RegexpChecker(BaseChecker):
    def __init__(self, pattern):
        self.__regexp = re.compile(pattern)
        super(RegexpChecker, self).__init__()

    def __str__(self):
        return 'REGEXP:%s' % self.__regexp.pattern

    def check(self, checker, msg, debug, setError=True):
        m = self.__regexp.match(msg)
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:REXP: %s' % \
                        (name, self.__regexp.pattern)
                checker.setError(('Expected %s regexp log message of "%s",' +
                                  ' not "%s"') %
                                 (name, self.__regexp.pattern, msg))
            return False

        return True


class RegexpTextChecker(BaseChecker):
    def __init__(self, pattern):
        self.__regexp = re.compile(pattern)
        super(RegexpTextChecker, self).__init__()

    def __str__(self):
        return 'RETEXT:%s' % self.__regexp.pattern

    def check(self, checker, msg, debug, setError=True):
        m = BaseChecker.PAT_DAQLOG.match(msg)
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:RFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern)
                checker.setError('Bad format for %s log message "%s"' %
                                 (name, msg))
            return False

        m = self.__regexp.match(m.group(3))
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:RTXT: %s' % \
                        (name, self.__regexp.pattern)
                checker.setError(('Expected %s regexp text log message,' +
                                  ' of "%s" not "%s"') %
                                 (name, self.__regexp.pattern, msg))
            return False

        return True


class TextChecker(BaseChecker):
    def __init__(self, text):
        self.__text = text
        super(TextChecker, self).__init__()

    def __str__(self):
        return 'TEXT:%s' % self.__text

    def check(self, checker, msg, debug, setError=True):
        m = BaseChecker.PAT_DAQLOG.match(msg)
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:TFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern)
                checker.setError('Bad format for %s log message "%s"' %
                                 (name, msg))
            return False

        if m.group(3).find(self.__text) == -1:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:TEXT: %s' % (name, self.__text)
                checker.setError(('Expected %s partial log message of "%s",' +
                                  ' not "%s"') %
                                 (name, self.__text, m.group(3)))
            return False

        return True


class LogChecker(object):
    DEBUG = False

    TYPE_EXACT = 1
    TYPE_TEXT = 2
    TYPE_REGEXP = 3
    TYPE_RETEXT = 4
    TYPE_LIVE = 5

    def __init__(self, prefix, name, isLive=False, depth=None):
        self.__prefix = prefix
        self.__name = name
        self.__isLive = isLive
        if depth is None:
            self.__depth = 5
        else:
            self.__depth = depth

        self.__expMsgs = []

    def __str__(self):
        return '%s-%s' % (self.__prefix, self.__name)

    def __checkEmpty(self):
        if len(self.__expMsgs) != 0:
            fixed = []
            for m in self.__expMsgs:
                fixed.append(str(m))
            raise Exception("Didn't receive %d expected %s log messages: %s" %
                            (len(fixed), self.__name, str(fixed)))

    def _checkError(self):
        pass

    def _checkMsg(self, msg):
        if LogChecker.DEBUG:
            print >>sys.stderr, "Check(%s): %s" % (str(self), msg)

        if len(self.__expMsgs) == 0:
            if LogChecker.DEBUG:
                print >>sys.stderr, '*** %s:UNEX' % str(self)
            self.setError('Unexpected %s log message: %s' % (str(self), msg))
            return False

        found = None
        for i in range(len(self.__expMsgs)):
            if i >= self.__depth:
                break
            if self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, False):
                found = i
                break

        if found is None:
            print >>sys.stderr, '--- Missing %s log msg ---' % str(self)
            print msg
            if len(self.__expMsgs) > 0:
                print >>sys.stderr, '--- Expected %s messages ---' % str(self)
                for i in range(len(self.__expMsgs)):
                    if i >= self.__depth:
                        break
                    print "--- %s" % str(self.__expMsgs[i])
                    self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, True)
            print >>sys.stderr, '----------------------------'
            self.setError('Missing %s log message: %s' % (str(self), msg))
            return False

        del self.__expMsgs[found]

        return True

    def addExpectedExact(self, msg):
        if LogChecker.DEBUG:
            print >>sys.stderr, "AddExact(%s): %s" % (str(self), msg)
        self.__expMsgs.append(ExactChecker(msg))

    def addExpectedLiveMoni(self, varName, value, valType=None):
        if LogChecker.DEBUG:
            print >>sys.stderr, "AddLiveMoni(%s): %s=%s%s" % \
                (str(self), varName, value,
                 valType is None and "" or "(%s)" % str(valType))
        self.__expMsgs.append(LiveChecker(varName, value, valType))

    def addExpectedRegexp(self, msg):
        if LogChecker.DEBUG:
            print >>sys.stderr, "AddRegexp(%s): %s" % (str(self), msg)
        self.__expMsgs.append(RegexpChecker(msg))

    def addExpectedText(self, msg):
        if self.__isLive:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddLive(%s): %s" % (str(self), msg)
            self.__expMsgs.append(LiveChecker('log', str(msg)))
        else:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddText(%s): %s" % (str(self), msg)
            self.__expMsgs.append(TextChecker(msg))

    def addExpectedTextRegexp(self, msg):
        if self.__isLive:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddLiveRE(%s): %s" % (str(self), msg)
            self.__expMsgs.append(LiveRegexpChecker('log', msg))
        else:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddTextRE(%s): %s" % (str(self), msg)
            self.__expMsgs.append(RegexpTextChecker(msg))

    def checkStatus(self, reps):
        count = 0
        while len(self.__expMsgs) > 0 and count < reps:
            time.sleep(.001)
            count += 1
        self._checkError()
        self.__checkEmpty()
        return True

    def isEmpty(self):
        return len(self.__expMsgs) == 0

    def setCheckDepth(self, depth):
        self.__depth = depth

    def setError(self, msg):
        raise NotImplementedError()


class MockAppender(LogChecker):
    def __init__(self, name, depth=None):
        super(MockAppender, self).__init__('LOG', name, depth=depth)

    def close(self):
        pass

    def setError(self, msg):
        raise Exception(msg)

    def write(self, m, time=None):
        self._checkMsg(m)


class MockClusterComponent(Component):
    def __init__(self, fullname, jvm, jvmArgs, host):
        sep = fullname.rfind("#")
        if sep < 0:
            sep = fullname.rfind("-")

        if sep < 0:
            name = fullname
            num = 0
        else:
            name = fullname[:sep]
            num = int(fullname[sep + 1:])

        self.__jvm = jvm
        self.__jvmArgs = jvmArgs
        self.__host = host

        super(MockClusterComponent, self).__init__(name, num, None)

    def __str__(self):
        return "%s(%s)" % (self.fullName(), self.__host)

    def dump(self, fd, indent):
        print >>fd, "%s<location name=\"%s\" host=\"%s\>" % \
            (indent, self.__host, self.__host)
        print >>fd, "%s    <module name=\"%s\" id=\"%02d\"/?>" % \
            (indent, self.name(), self.id())
        print >>fd, "%s</location>" % indent

    def host(self):
        return self.__host

    def jvm(self):
        return self.__jvm

    def jvmArgs(self):
        return self.__jvmArgs


class MockClusterNode(object):
    def __init__(self, host):
        self.__host = host
        self.__comps = []

    def add(self, comp, jvm, jvmArgs, host):
        self.__comps.append(MockClusterComponent(comp, jvm, jvmArgs, host))

    def components(self):
        return self.__comps[:]


class MockClusterConfig(object):
    def __init__(self, name):
        self.__configName = name
        self.__nodes = {}

    def __repr__(self):
        return "MockClusterConfig(%s)" % self.__configName

    def addComponent(self, comp, jvm, jvmArgs, host):
        if not host in self.__nodes:
            self.__nodes[host] = MockClusterNode(host)
        self.__nodes[host].add(comp, jvm, jvmArgs, host)

    def configName(self):
        return self.__configName

    def nodes(self):
        return self.__nodes.values()


class MockCnCLogger(CnCLogger):
    def __init__(self, appender, quiet=False, extraLoud=False):
        #if appender is None: raise Exception('Appender cannot be None')
        self.__appender = appender

        super(MockCnCLogger, self).__init__(appender, quiet=quiet,
                                            extraLoud=extraLoud)


class MockConnection(object):
    INPUT = "a"
    OPT_INPUT = "b"
    OUTPUT = "c"
    OPT_OUTPUT = "d"

    def __init__(self, name, connCh, port=None):
        "port is set for input connections, None for output connections"
        self.__name = name
        self.__connCh = connCh
        self.__port = port

    def __str__(self):
        if self.__port is not None:
            return '%d=>%s' % (self.__port, self.__name)
        return '=>' + self.__name

    def isInput(self):
        return self.__connCh == self.INPUT or self.__connCh == self.OPT_INPUT

    def isOptional(self):
        return self.__connCh == self.OPT_INPUT or \
               self.__connCh == self.OPT_OUTPUT

    def name(self):
        return self.__name

    def port(self):
        return self.__port


class MockComponent(object):
    def __init__(self, name, num=0, host='localhost'):
        self.__name = name
        self.__num = num
        self.__host = host

        self.__connectors = []
        self.__cmdOrder = None

        self.runNum = None

        self.__isBldr = name.endswith("Builder")
        self.__isSrc = name.endswith("Hub") or name == "amandaTrigger"
        self.__connected = False
        self.__configured = False
        self.__configWait = 0
        self.__monitorCount = 0
        self.__monitorState = None
        self.__isBadHub = False
        self.__hangType = 0
        self.__stopping = 0
        self.__updatedRates = False
        self.__deadCount = 0

        self.__beanData = {}

    def __cmp__(self, other):
        val = cmp(self.__name, other.__name)
        if val == 0:
            val = cmp(self.__num, other.__num)
        return val

    def __repr__(self):
        return str(self)

    def __str__(self):
        outStr = self.fullName()
        extra = []
        if self.__isSrc:
            extra.append('SRC')
        if self.__isBldr:
            extra.append('BLD')
        if self.__configured:
            extra.append('CFG')
        for conn in self.__connectors:
            extra.append(str(conn))

        if len(extra) > 0:
            outStr += '[' + ','.join(extra) + ']'
        return outStr

    def addBeanData(self, beanName, fieldName, value):

        if self.checkBeanField(beanName, fieldName):
            raise Exception("Value for %c bean %s field %s already exists" %
                            (self, beanName, fieldName))

        if not beanName in self.__beanData:
            self.__beanData[beanName] = {}

        self.__beanData[beanName][fieldName] = value

    def addDeadCount(self):
        self.__deadCount += 1

    def addInput(self, name, port, optional=False):
        if not optional:
            connCh = MockConnection.INPUT
        else:
            connCh = MockConnection.OPT_INPUT
        self.__connectors.append(MockConnection(name, connCh, port))

    def addOutput(self, name, optional=False):
        if not optional:
            connCh = MockConnection.OUTPUT
        else:
            connCh = MockConnection.OPT_OUTPUT
        self.__connectors.append(MockConnection(name, connCh))

    def checkBeanField(self, beanName, fieldName):
        return beanName in self.__beanData and \
            fieldName in self.__beanData[beanName]

    def close(self):
        pass

    def commitSubrun(self, id, startTime):
        pass

    def configure(self, configName=None):
        if not self.__connected:
            self.__connected = True
        self.__configured = True
        return 'OK'

    def connect(self, conn=None):
        self.__connected = True
        return 'OK'

    def connectors(self):
        return self.__connectors[:]

    def forcedStop(self):
        if self.__stopping == 1:
            if self.__hangType != 2:
                self.runNum = None
                self.__stopping = 0
            else:
                self.__stopping = 2

    def fullName(self):
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    def fileName(self):
        return '%s-%d' % (self.__name, self.__num)

    def getBeanFields(self, beanName):
        return self.__beanData[beanName].keys()

    def getBeanNames(self, reload=False):
        return self.__beanData.keys()

    def getConfigureWait(self):
        return self.__configWait

    def getMultiBeanFields(self, beanName, fieldList):
        rtnMap = {}
        for f in fieldList:
            rtnMap[f] = self.getSingleBeanField(beanName, f)

            if isinstance(rtnMap[f], Exception):
                raise rtnMap[f]
        return rtnMap

    def getNonstoppedConnectorsString(self):
        return ""

    def getRunData(self, runnum):
        if self.__num == 0:
            if self.__name.startswith("event"):
                evtData = self.getSingleBeanField("backEnd", "EventData")
                numEvts = int(evtData[0])
                lastTime = long(evtData[1])

                val = self.getSingleBeanField("backEnd", "FirstEventTime")
                firstTime = long(val)
                return (numEvts, firstTime, lastTime)
            elif self.__name.startswith("secondary"):
                for bldr in ("tcal", "sn", "moni"):
                    val = self.getSingleBeanField(bldr + "Builder",
                                                  "TotalDispatchedData")
                    if bldr == "tcal":
                        numTcal = long(val)
                    elif bldr == "sn":
                        numSN = long(val)
                    elif bldr == "moni":
                        numMoni = long(val)

                return (numTcal, numSN, numMoni)

        return (None, None, None)

    def getSingleBeanField(self, beanName, fieldName):
        if not self.checkBeanField(beanName, fieldName):
            raise Exception("No %s data for bean %s field %s" %
                            (self, beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def host(self):
        return self.__host

    def isBuilder(self):
        return self.__isBldr

    def isComponent(self, name, num=-1):
        return self.__name == name

    def isConfigured(self):
        return self.__configured

    def isHanging(self):
        return self.__hangType != 0

    def isSource(self):
        return self.__isSrc

    def logTo(self, logIP, logPort, liveIP, livePort):
        pass

    def monitorCount(self):
        return self.__monitorCount

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def order(self):
        return self.__cmdOrder

    def prepareSubrun(self, id):
        pass

    def reloadBeanInfo(self):
        pass

    def reset(self):
        self.__connected = False
        self.__configured = False
        self.__updatedRates = False
        self.runNum = None

    def resetLogging(self):
        pass

    def setBadHub(self):
        self.__isBadHub = True

    def setBeanData(self, beanName, fieldName, value):

        if not self.checkBeanField(beanName, fieldName):
            raise Exception("%c bean %s field %s has not been added" %
                            (self, beanName, fieldName))

        self.__beanData[beanName][fieldName] = value

    def setConfigureWait(self, waitNum):
        self.__configWait = waitNum

    def setFirstGoodTime(self, time):
        self.__firstGoodTime = time

    def setHangType(self, hangType):
        self.__hangType = hangType

    def setLastGoodTime(self, time):
        self.__lastGoodTime = time

    def setMonitorState(self, newState):
        self.__monitorState = newState

    def setOrder(self, num):
        self.__cmdOrder = num

    def startRun(self, runNum):
        if not self.__configured:
            raise Exception(self.__name + ' has not been configured')

        self.runNum = runNum

    def startSubrun(self, data):
        if self.__isBadHub:
            return None
        return 100

    def state(self):
        if self.__monitorState is not None:
            self.__monitorCount += 1
            return self.__monitorState

        if not self.__connected:
            return 'idle'
        if not self.__configured or self.__configWait > 0:
            if self.__configured and self.__configWait > 0:
                self.__configWait -= 1
            return 'connected'
        if self.__stopping == 1:
            return "stopping"
        elif self.__stopping == 2:
            return "forcingStop"
        if not self.runNum:
            return 'ready'

        return 'running'

    def stopRun(self):
        if self.runNum is None:
            raise Exception(self.__name + ' is not running')

        if self.__hangType > 0:
            self.__stopping = 1
        else:
            self.runNum = None

    def updateRates(self):
        self.__updatedRates = True

    def wasUpdated(self):
        return self.__updatedRates


class MockDeployComponent(Component):
    def __init__(self, name, id, logLevel, jvm, jvmArgs):
        self.__jvm = jvm
        self.__jvmArgs = jvmArgs

        super(MockDeployComponent, self).__init__(name, id, logLevel)

    def isControlServer(self):
        return False

    def jvm(self):
        return self.__jvm

    def jvmArgs(self):
        return self.__jvmArgs


class MockDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors,
                 appender, outLinks=None, extraLoud=False):

        self.__appender = appender
        self.__extraLoud = extraLoud

        self.outLinks = outLinks
        self.__state = 'idle'

        super(MockDAQClient, self).__init__(name, num, host, port, mbeanPort,
                                            connectors, True)

    def __str__(self):
        tmpStr = super(MockDAQClient, self).__str__()
        return 'Mock' + tmpStr

    def closeLog(self):
        pass

    def configure(self, cfgName=None):
        self.__state = 'ready'
        return super(MockDAQClient, self).configure(cfgName)

    def connect(self, links=None):
        self.__state = 'connected'
        return super(MockDAQClient, self).connect(links)

    def createClient(self, host, port):
        return MockRPCClient(self.name(), self.num(), self.outLinks)

    def createLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet, self.__extraLoud)

    def createMBeanClient(self, host, port):
        return MockRPCClient(self.name(), self.num(), self.outLinks)

    def reset(self):
        self.__state = 'idle'
        return super(MockDAQClient, self).reset()

    def startRun(self, runNum):
        self.__state = 'running'
        return super(MockDAQClient, self).startRun(runNum)

    def state(self):
        return self.__state


class MockIntervalTimer(object):
    def __init__(self, name, waitSecs=1.0):
        self.__name = name
        self.__isTime = False
        self.__gotTime = False
        self.__waitSecs = waitSecs

    def __str__(self):
        return "Timer#%s%s" % \
            (self.__name, self.__isTime and "!isTime!" or "")

    def gotTime(self):
        return self.__gotTime

    def isTime(self, now=None):
        self.__gotTime = True
        return self.__isTime

    def name(self):
        return self.__name

    def reset(self):
        self.__isTime = False
        self.__gotTime = False

    def timeLeft(self):
        if self.__isTime:
            return 0.0
        return self.__waitSecs

    def trigger(self):
        self.__isTime = True
        self.__gotTime = False

    def waitSecs(self):
        return self.__waitSecs


class MockLogger(LogChecker):
    def __init__(self, name):
        super(MockLogger, self).__init__('LOG', name)

        self.__err = None

    def _checkError(self):
        if self.__err is not None:
            raise Exception(self.__err)

    def addAppender(self, app):
        print >>sys.stderr, "Not adding appender %s to MockLogger" % app

    def close(self):
        pass

    def debug(self, m):
        self._checkMsg(m)

    def error(self, m):
        self._checkMsg(m)

    def fatal(self, m):
        self._checkMsg(m)

    def info(self, m):
        self._checkMsg(m)

    def isDebugEnabled(self):
        return True

    def isErrorEnabled(self):
        return True

    def isFatalEnabled(self):
        return True

    def isInfoEnabled(self):
        return True

    def isTraceEnabled(self):
        return True

    def isWarnEnabled(self):
        return True

    def setError(self, msg):
        self.__err = msg
        raise Exception(msg)

    def trace(self, m):
        self._checkMsg(m)

    def warn(self, m):
        self._checkMsg(m)


class MockParallelShell(object):
    BINDIR = os.path.join(METADIR, 'target', 'pDAQ-%s-dist' % RELEASE, 'bin')

    def __init__(self, isParallel=True, debug=False):
        self.__exp = []
        self.__rtnCodes = []
        self.__results = []
        self.__isParallel = isParallel
        self.__debug = debug

    def __addExpected(self, cmd):
        if cmd.find("/bin/StringHub") > 0 and cmd.find(".componentId=") < 0:
            raise Exception("Missing componentId: %s" % cmd)
        self.__exp.append(cmd)

    def __checkCmd(self, cmd):
        expLen = len(self.__exp)
        if expLen == 0:
            raise Exception('Did not expect command "%s"' % cmd)

        if self.__debug:
            print >>sys.stderr, "PSh got: " + cmd

        found = None
        for i in range(expLen):
            if cmd == self.__exp[i]:
                found = i
                if self.__debug:
                    print >>sys.stderr, "PSh found cmd"
                break
            if self.__debug:
                print >>sys.stderr, "PSh not: " + self.__exp[i]

        if found is None:
            raise Exception('Command not found in expected command list: ' \
                                'cmd="%s"' % (cmd))

        del self.__exp[found]

    def __isLocalhost(self, host):
        return host == 'localhost' or host == '127.0.0.1'

    def add(self, cmd):
        self.__checkCmd(cmd)

    def addExpectedJava(self, comp, configDir, daqDataDir, logPort, livePort,
                        verbose, eventCheck, host):

        ipAddr = ip.getLocalIpAddr(host)
        jarPath = os.path.join(MockParallelShell.BINDIR,
                               getCompJar(comp.name()))

        if verbose:
            redir = ''
        else:
            redir = ' </dev/null >/dev/null 2>&1'

        cmd = '%s %s' % (comp.jvm(), comp.jvmArgs())

        if comp.isHub():
            cmd += " -Dicecube.daq.stringhub.componentId=%d" % comp.id()
        if eventCheck and comp.isBuilder():
            cmd += ' -Dicecube.daq.eventBuilder.validateEvents'

        cmd += ' -jar %s' % jarPath
        cmd += ' -g %s' % configDir
        if daqDataDir is not None:
            cmd += ' -d %s' % daqDataDir
        cmd += ' -c %s:%d' % (ipAddr, DAQPort.CNCSERVER)

        if logPort is not None:
            cmd += ' -l %s:%d,%s' % (ipAddr, logPort, comp.logLevel())
        if livePort is not None:
            cmd += ' -L %s:%d,%s' % (ipAddr, livePort, comp.logLevel())
        cmd += ' %s &' % redir

        if not self.__isLocalhost(host):
            qCmd = "ssh -n %s 'sh -c \"%s\"%s &'" % (host, cmd, redir)
            cmd = qCmd

        self.__addExpected(cmd)

    def addExpectedJavaKill(self, compName, compId, killWith9, verbose, host):
        if killWith9:
            nineArg = '-9'
        else:
            nineArg = ''

        user = os.environ['USER']

        if compName.endswith("hub"):
            killPat = "stringhub.componentId=%d" % compId
        else:
            killPat = getCompJar(compName)

        if self.__isLocalhost(host):
            sshCmd = ''
            pkillOpt = ' -fu %s' % user
        else:
            sshCmd = 'ssh %s ' % host
            pkillOpt = ' -f'

        self.__addExpected('%spkill %s%s %s' %
                           (sshCmd, nineArg, pkillOpt, killPat))

        if not killWith9:
            self.__addExpected('sleep 2; %spkill -9%s %s' %
                               (sshCmd, pkillOpt, killPat))

    def addExpectedPython(self, doCnC, dashDir, configDir, logDir, daqDataDir,
                          spadeDir, cfgName, copyDir, logPort, livePort):
        if doCnC:
            cmd = os.path.join(dashDir, 'CnCServer.py')
            cmd += ' -c %s' % configDir
            cmd += ' -o %s' % logDir
            cmd += ' -q %s' % daqDataDir
            cmd += ' -s %s' % spadeDir
            if logPort is not None:
                cmd += ' -l localhost:%d' % logPort
            if livePort is not None:
                cmd += ' -L localhost:%d' % livePort
            cmd += ' -a %s' % copyDir
            cmd += ' -d'

            self.__addExpected(cmd)

    def addExpectedPythonKill(self, doCnC, dashDir, killWith9):
        pass

    def addExpectedRsync(self, dir, subdirs, delete, dryRun, remoteHost,
                         rtnCode, result="",
                         niceAdj=DeployPDAQ.NICE_ADJ_DEFAULT,
                         express=DeployPDAQ.EXPRESS_DEFAULT):

        if express:
            rCmd = "rsync"
        else:
            rCmd = 'nice rsync --rsync-path "nice -n %d rsync"' % (niceAdj)

        if not delete:
            dOpt = ""
        else:
            dOpt = " --delete"

        if not dryRun:
            drOpt = ""
        else:
            drOpt = " --dry-run"

        group = "{" + ",".join(subdirs) + "}"

        cmd = "%s -azLC%s%s %s %s:%s" % \
            (rCmd, dOpt, drOpt, os.path.join(dir, group), remoteHost, dir)
        self.__addExpected(cmd)
        self.__rtnCodes.append(rtnCode)
        self.__results.append(result)

    def addExpectedUndeploy(self, homeDir, pdaqDir, remoteHost):
        cmd = "ssh %s \"\\rm -rf ~%s/.m2 %s\"" % \
            (remoteHost, os.environ["USER"], pdaqDir)
        self.__addExpected(cmd)

    def check(self):
        if len(self.__exp) > 0:
            raise Exception(('ParallelShell did not receive expected commands:'
                             ' %s') % str(self.__exp))

    def getMetaPath(self, subdir):
        return os.path.join(METADIR, subdir)

    def getResult(self, idx):
        if idx < 0 or idx >= len(self.__results):
            raise Exception("Cannot return result %d (only %d available)" %
                            (idx, len(self.__results)))

        return self.__results[idx]

    def getReturnCodes(self):
        return self.__rtnCodes

    def isParallel(self):
        return self.__isParallel

    def showAll(self):
        raise Exception('SHOWALL')

    def start(self):
        pass

    def system(self, cmd):
        self.__checkCmd(cmd)

    def wait(self, monitorIval=None):
        pass

    def getCmdResults(self):

        # commands are in self.__exp
        ret = {}
        for exp, rtncode in zip(self.__exp, self.__rtnCodes):
            ret[exp] = (rtncode, "")

        return ret


class MockRPCClient(object):
    def __init__(self, name, num, outLinks=None):
        self.xmlrpc = MockXMLRPC(name, num, outLinks)


class MockRunComponent(object):
    def __init__(self, name, id, inetAddr, rpcPort, mbeanPort):
        self.__name = name
        self.__id = id
        self.__inetAddr = inetAddr
        self.__rpcPort = rpcPort
        self.__mbeanPort = mbeanPort

    def __str__(self):
        return "%s#%s" % (str(self.__name), str(self.__id))

    def id(self):
        return self.__id

    def inetAddress(self):
        return self.__inetAddr

    def isHub(self):
        return self.__name.endswith("Hub")

    def mbeanPort(self):
        return self.__mbeanPort

    def name(self):
        return self.__name

    def rpcPort(self):
        return self.__rpcPort


class SimDOMXML(object):
    def __init__(self, mbid):
        self.__mbid = mbid

    def printXML(self, fd, indent):
        print >>fd, "%s<domConfig mbid=\"%s\">" % (indent, self.__mbid)
        print >>fd, "%s</domConfig>"


class MockRunConfigFile(object):
    def __init__(self, configDir):
        self.__configDir = configDir

    def __makeDomConfig(self, cfgName, domList):
        cfgDir = os.path.join(self.__configDir, "domconfigs")
        if not os.path.exists(cfgDir):
            os.mkdir(cfgDir)

        if cfgName.endswith(".xml"):
            fileName = cfgName
        else:
            fileName = cfgName + ".xml"

        with open(os.path.join(cfgDir, fileName), 'w') as fd:
            print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            print >>fd, "<domConfigList>"
            if domList is not None:
                for d in domList:
                    d.printXML(fd, "  ")
            print >>fd, "</domConfigList>"

    def __makeTriggerConfig(self, cfgName):
        cfgDir = os.path.join(self.__configDir, "trigger")
        if not os.path.exists(cfgDir):
            os.mkdir(cfgDir)

        if cfgName.endswith(".xml"):
            fileName = cfgName
        else:
            fileName = cfgName + ".xml"

        with open(os.path.join(cfgDir, fileName), "w") as fd:
            print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"

    def create(self, compList, domList):
        path = tempfile.mktemp(suffix=".xml", dir=self.__configDir)

        domCfg = "empty-dom-config"
        self.__makeDomConfig(domCfg, domList)

        trigCfg = "empty-trigger"
        self.__makeTriggerConfig(trigCfg)

        with open(path, 'w') as fd:
            print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            print >>fd, "<runConfig>"
            print >>fd, "    <domConfigList>%s</domConfigList>" % domCfg
            print >>fd, "    <triggerConfig>%s</triggerConfig>" % trigCfg
            for c in compList:
                pound = c.rfind("#")
                if pound > 0:
                    val = int(c[pound + 1:])
                    if val == 0:
                        c = c[:pound]
                print >>fd, "    <runComponent name=\"%s\"/>" % c
            print >>fd, "</runConfig>"

        name = os.path.basename(path)
        if name.endswith(".xml"):
            name = name[:-4]

        return name

    @staticmethod
    def createDOM(mbid):
        return SimDOMXML(mbid)


class MockXMLRPC(object):
    LOUD = False

    def __init__(self, name, num, outLinks):
        self.name = name
        self.num = num

        self.outLinks = outLinks

    def configure(self, name=None):
        pass

    def connect(self, list=None):
        if list is None or self.outLinks is None:
            return 'OK'

        if MockXMLRPC.LOUD:
            print >>sys.stderr, 'Conn[%s:%s]' % (self.name, self.num)
            for l in list:
                print >>sys.stderr, '  %s:%s#%d' % \
                    (l['type'], l['compName'], l['compNum'])

        # make a copy of the links
        #
        tmpLinks = {}
        for k in self.outLinks.keys():
            tmpLinks[k] = []
            tmpLinks[k][0:] = self.outLinks[k][0:len(self.outLinks[k])]

        for l in list:
            if not l['type'] in tmpLinks:
                raise ValueError(('Component %s#%d should not have a "%s"' +
                                  ' connection') %
                                 (self.name, self.num, l['type']))

            comp = None
            for t in tmpLinks[l['type']]:
                if t.name == l['compName'] and t.num == l['compNum']:
                    comp = t
                    tmpLinks[l['type']].remove(t)
                    if len(tmpLinks[l['type']]) == 0:
                        del tmpLinks[l['type']]
                    break

            if not comp:
                raise ValueError(("Component %s#%d "
                                  "should not connect to %s:%s#%d") % \
                                     (self.name,
                                      self.num,
                                      l['type'],
                                      l['compName'],
                                      l.getCompNum()))

        if len(tmpLinks) > 0:
            errMsg = 'Component ' + self.name + '#' + str(self.num) + \
                ' is not connected to '

            first = True
            for k in tmpLinks.keys():
                for t in tmpLinks[k]:
                    if first:
                        first = False
                    else:
                        errMsg += ', '
                    errMsg += k + ':' + t.name + '#' + str(t.num)
            raise ValueError(errMsg)

        return 'OK'

    def getState(self):
        pass

    def getVersionInfo(self):
        return ''

    def logTo(self, logIP, logPort, liveIP, livePort):
        pass

    def reset(self):
        pass

    def resetLogging(self):
        pass

    def startRun(self, runNum):
        pass

    def stopRun(self):
        pass


class SocketReader(LogChecker):
    def __init__(self, name, port, depth=None):
        self.__name = name
        self.__port = port

        self.__errMsg = None

        self.__thread = None
        self.__serving = False

        isLive = (self.__port == DAQPort.I3LIVE)
        super(SocketReader, self).__init__('SOC', name,
                                           isLive=isLive, depth=depth)

    def __bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.__port))
        except socket.error as e:
            raise socket.error('Cannot bind SocketReader to port %d: %s' %
                               (self.__port, str(e)))
        return sock

    def __listener(self, sock):
        """
        Create listening, non-blocking UDP socket, read from it, and write
        to file; close socket and end thread if signaled via self.__thread
        variable.
        """
        self.__serving = True
        try:
            pr = [sock]
            pw = []
            pe = [sock]
            while self.__thread is not None:
                rd, rw, re = select.select(pr, pw, pe, 0.5)
                if len(re) != 0:
                    raise Exception("Error on select was detected.")
                if len(rd) == 0:
                    continue
                # Slurp up waiting packets, return to select if EAGAIN
                while 1:
                    try:
                        data = sock.recv(8192, socket.MSG_DONTWAIT)
                    except:
                        break  # Go back to select so we don't busy-wait
                    if not self._checkMsg(data):
                        break
        finally:
            if sock is not None:
                sock.close()
            self.__serving = False

    def __win_bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #sock.setblocking(1)
        #sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.__port))
        return sock

    def __win_listener(self, sock):
        """
        Windows version of listener - no select().
        """
        self.__serving = True
        try:
            while self.__thread is not None:
                data = sock.recv(8192)
                self._checkMsg(data)
        finally:
            sock.close()
            self.__serving = False

    def _checkError(self):
        if self.__errMsg is not None:
            raise Exception(self.__errMsg)

    def getPort(self):
        return self.__port

    def serving(self):
        return self.__serving

    def setError(self, msg):
        if self.__errMsg is None:
            self.__errMsg = msg

    def stopServing(self):
        "Signal listening thread to exit; wait for thread to finish"
        if self.__thread is not None:
            thread = self.__thread
            self.__thread = None
            thread.join()

    def startServing(self):
        if self.__thread is not None:
            raise Exception('Socket reader %s is already running' % \
                                self.__name)

        if os.name == "nt":
            sock = self.__win_bind()
            listener = self.__win_listener
        else:
            sock = self.__bind()
            listener = self.__listener

        self.__thread = threading.Thread(target=listener, name=str(self),
                                         args=(sock, ))

        self.__thread.setDaemon(True)
        self.__thread.start()
        while not self.__serving:
            time.sleep(.001)


class SocketReaderFactory(object):
    def __init__(self):
        self.__logList = []

    def createLog(self, name, port, expectStartMsg=True, depth=None,
                  startServer=True):
        log = SocketReader(name, port, depth)
        self.__logList.append(log)

        if expectStartMsg:
            log.addExpectedTextRegexp(r'^Start of log at LOG=(\S+:\d+|' +
                                      r'log\(\S+:\d+\)(\slive\(\S+:\d+\))?)$')
        if startServer:
            log.startServing()

        return log

    def tearDown(self):
        for l in self.__logList:
            l.stopServing()

        for l in self.__logList:
            l.checkStatus(0)

        del self.__logList[:]


class SocketWriter(object):
    def __init__(self, node, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.connect((node, port))
            self.__loc = (node, port)
        except socket.error as err:
            raise socket.error('Cannot connect to %s:%d: %s' %
                               (node, port, str(err)))

    def __str__(self):
        return '%s@%d' % self.__loc

    def write(self, s):
        "Write message to remote logger"
        self.socket.send(s)

    def write_ts(self, s, time=None):
        "Write time-stamped log msg to remote logger"
        if time is None:
            time = datetime.datetime.now()
        self.socket.send("- - [%s] %s" % (time, s))

    def close(self):
        "Shut down socket to remote server - do this to avoid stale sockets"
        self.socket.close()


class RunXMLValidator:

    @classmethod
    def setUp(cls):
        if os.path.exists("run.xml"):
            try:
                os.remove("run.xml")
            except:
                raise ValueError("Cannot remove lingering run.xml file")

    @classmethod
    def tearDown(cls):
        if os.path.exists("run.xml"):
            try:
                os.remove("run.xml")
            except Exception as ex:
                print "Cannot remove run.xml: %s" % ex
            raise ValueError("Found unexpected run.xml file")

    @classmethod
    def validate(cls, test_case, runNum, cfgName, startTime, endTime, numEvts,
                 numMoni, numSN, numTcal, failed):
        try:
            if not os.path.exists("run.xml"):
                test_case.fail("run.xml was not created")

            run = DashXMLLog.parse()

            test_case.assertEqual(run.getRun(), runNum,
                                  "Expected run number %s, not %s" % \
                                      (runNum,
                                       run.getRun()))

            test_case.assertEqual(run.getConfig(), cfgName,
                             "Expected config \"%s\", not \"%s\"" %
                             (cfgName, run.getConfig()))

            if startTime is not None:
                test_case.assertEqual(run.getStartTime(), startTime,
                                      ("Expected start time %s<%s>, "
                                       "not %s<%s>") % \
                                          (startTime,
                                           type(startTime),
                                           run.getStartTime(),
                                           type(run.getStartTime())))
            if endTime is not None:
                test_case.assertEqual(run.getEndTime(), endTime,
                                      ("Expected end time %s<%s>, "
                                       "not %s<%s>") % \
                                          (endTime,
                                           type(endTime),
                                           run.getEndTime(),
                                           type(run.getEndTime())))

            test_case.assertEqual(run.getTermCond(), failed,
                                  "Expected terminal condition %s, not %s" %
                                  (failed, run.getTermCond()))

            test_case.assertEqual(run.getEvents(), numEvts,
                                  "Expected number of events %s, not %s" %
                                  (numEvts, run.getEvents()))

            test_case.assertEqual(run.getMoni(), numMoni,
                                  ("Expected number of monitoring events %s, "
                                   "not %s") % \
                                      (numMoni, run.getMoni()))

            test_case.assertEqual(run.getTcal(), numTcal,
                                  ("Expected number of time cal events %s, "
                                   "not %s") % \
                                      (numTcal, run.getTcal()))

            test_case.assertEqual(run.getSN(), numSN,
                                  ("Expected number of supernova events %s, "
                                   "not %s") % \
                                      (numSN, run.getSN()))
        finally:
            try:
                os.remove("run.xml")
            except:
                pass


class MockRunSet(object):
    def __init__(self, comps):
        self.__comps = comps
        self.__running = False

        self.__numEvts = 10
        self.__rate = 123.45
        self.__numMoni = 11
        self.__numSN = 12
        self.__numTcal = 13

    def components(self):
        return self.__comps[:]

    def getRates(self):
        return (self.__numEvts, self.__rate, self.__numMoni, self.__numSN,
                self.__numTcal)

    def isRunning(self):
        return self.__running

    def startRunning(self):
        self.__running = True

    def stopRunning(self):
        self.__running = False

    def updateRates(self):
        for c in self.__comps:
            c.updateRates()
        return self.getRates()


class MockTaskManager(object):
    def __init__(self):
        self.__timerDict = {}
        self.__error = False

    def addIntervalTimer(self, timer):
        if timer.name() in self.__timerDict:
            raise Exception("Cannot add multiple timers named \"%s\"" %
                            timer.name())
        self.__timerDict[timer.name()] = timer

    def createIntervalTimer(self, name, period):
        if not name in self.__timerDict:
            raise Exception("Cannot find timer named \"%s\"" % name)
        return self.__timerDict[name]

    def hasError(self):
        return self.__error

    def setError(self):
        self.__error = True


class MockLiveMoni(object):
    def __init__(self):
        self.__expMoni = {}

    def addExpected(self, var, val, prio):
        if not var in self.__expMoni:
            self.__expMoni[var] = []
        self.__expMoni[var].append((val, prio))

    def hasAllMoni(self):
        return len(self.__expMoni) == 0

    def sendMoni(self, var, val, prio, time=datetime.datetime.now()):
        if not var in self.__expMoni:
            raise Exception(("Unexpected live monitor data" +
                             " (var=%s, val=%s, prio=%d)") % (var, val, prio))

        expData = None
        for index, (val_tmp, prio_tmp) in enumerate(self.__expMoni[var]):
            if val == val_tmp and prio == prio_tmp:
                # found the right entry
                expData = self.__expMoni[var].pop(index)
                break

        if len(self.__expMoni[var]) == 0:
            del self.__expMoni[var]

        if expData is None:
            raise Exception(("Expected live monitor data from (%s/%s), not "
                             "(var=%s, val=%s, prio=%d)") % \
                                (var, self.__expMoni[var], var, val, prio))

        return True
