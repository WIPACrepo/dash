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

import DeployPDAQ

from ClusterDescription import ClusterDescription
from CnCLogger import CnCLogger
from Component import Component
from ComponentManager import ComponentManager
from DAQClient import DAQClient
from DAQConst import DAQPort
from DefaultDomGeometry import DefaultDomGeometry
from LiveImports import MoniPort, SERVICE_NAME
from RunCluster import RunCluster
from RunSet import RunSet
from leapseconds import leapseconds, MJD
from locate_pdaq import find_pdaq_trunk
from utils import ip
from utils.DashXMLLog import DashXMLLog


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
        if m is None:
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
        # msgPrio = m.group(4)
        # msgTime = m.group(5)
        msgText = m.group(6)

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
        if isinstance(val, str):
            return "\"%s\"" % val

        if isinstance(val, long):
            vstr = str(val)
            if vstr.endswith("L"):
                return vstr[:-1]
            return vstr

        if isinstance(val, bool):
            return self.__value and "true" or "false"

        return str(val)

    def _checkText(self, checker, msg, debug, setError):
        if self.__type is None or self.__type != "json":
            valStr = str(self.__value)
        elif isinstance(self.__value, list) or isinstance(self.__value, tuple):
            valStr = "["
            for v in self.__value:
                if len(valStr) > 1:
                    valStr += ", "
                valStr += self.__fixValue(v)
            valStr += "]"
        elif isinstance(self.__value, dict):
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
                checker.setError('Expected %s live log message '
                                 '"%s", not "%s"' % (name, valStr, msg))
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
        m = self.__regexp.search(msg)
        if m is None:
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
        if m is None:
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
        if m is None:
            if setError:
                name = str(checker)
                if debug:
                    print >>sys.stderr, '*** %s:RFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern)
                checker.setError('Bad format for %s log message "%s"' %
                                 (name, msg))
            return False

        m = self.__regexp.search(m.group(3))
        if m is None:
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
        if m is None:
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
            print >>sys.stderr, "Check(%s): %s" % (self, msg)

        if len(self.__expMsgs) == 0:
            if LogChecker.DEBUG:
                print >>sys.stderr, '*** %s:UNEX(%s)' % (self, msg)
            self.setError('Unexpected %s log message: %s' % (self, msg))
            return False

        found = None
        for i in range(len(self.__expMsgs)):
            if i >= self.__depth:
                break
            if self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, False):
                found = i
                break

        if found is None:
            print >>sys.stderr, '--- Missing %s log msg ---' % (self, )
            print >>sys.stderr, msg
            if len(self.__expMsgs) > 0:
                print >>sys.stderr, '--- Expected %s messages ---' % (self, )
                for i in range(len(self.__expMsgs)):
                    if i >= self.__depth:
                        break
                    print >>sys.stderr, "--- %s" % str(self.__expMsgs[i])
                    self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, True)
            print >>sys.stderr, '----------------------------'
            self.setError('Missing %s log message: %s' % (self, msg))
            return False

        del self.__expMsgs[found]

        return True

    def addExpectedExact(self, msg):
        if LogChecker.DEBUG:
            print >>sys.stderr, "AddExact(%s): %s" % (self, msg)
        self.__expMsgs.append(ExactChecker(msg))

    def addExpectedLiveMoni(self, varName, value, valType=None):
        if LogChecker.DEBUG:
            print >>sys.stderr, "AddLiveMoni(%s): %s=%s%s" % \
                (self, varName, value,
                 valType is None and "" or "(%s)" % (valType, ))
        self.__expMsgs.append(LiveChecker(varName, value, valType))

    def addExpectedRegexp(self, msg):
        if LogChecker.DEBUG:
            print >>sys.stderr, "AddRegexp(%s): %s" % (self, msg)
        self.__expMsgs.append(RegexpChecker(msg))

    def addExpectedText(self, msg):
        if self.__isLive:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddLive(%s): %s" % (self, msg)
            self.__expMsgs.append(LiveChecker('log', str(msg)))
        else:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddText(%s): %s" % (self, msg)
            self.__expMsgs.append(TextChecker(msg))

    def addExpectedTextRegexp(self, msg):
        if self.__isLive:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddLiveRE(%s): %s" % (self, msg)
            self.__expMsgs.append(LiveRegexpChecker('log', msg))
        else:
            if LogChecker.DEBUG:
                print >>sys.stderr, "AddTextRE(%s): %s" % (self, msg)
            self.__expMsgs.append(RegexpTextChecker(msg))

    def checkStatus(self, reps):
        count = 0
        while len(self.__expMsgs) > 0 and count < reps:
            time.sleep(.001)
            count += 1
        self._checkError()
        self.__checkEmpty()
        return True

    @property
    def isEmpty(self):
        return len(self.__expMsgs) == 0

    def setCheckDepth(self, depth):
        self.__depth = depth

    def setError(self, msg):
        raise NotImplementedError()

    @staticmethod
    def setVerbose(val=True):
        # NOTE: need to hard-code LogChecker.DEBUG to make sure the correct
        # class-level DEBUG attribute is set
        LogChecker.DEBUG = val


class MockAppender(LogChecker):
    def __init__(self, name, depth=None):
        super(MockAppender, self).__init__('LOG', name, depth=depth)

    def close(self):
        pass

    def setError(self, msg):
        raise Exception(msg)

    def write(self, m, time=None, level=None):
        self._checkMsg(m)


class MockClusterWriter(object):
    """Base class for MockClusterConfigFile classes"""
    @classmethod
    def __appendAttr(cls, oldStr, attrName, newStr):
        if newStr is not None:
            if oldStr is None:
                oldStr = ""
            else:
                oldStr += " "
            oldStr += "%s=\"%s\"" % (attrName, newStr)
        return oldStr

    @classmethod
    def writeHSXML(cls, fd, indent, path, interval, maxFiles):

        jStr = "hitspool"
        jStr = cls.__appendAttr(jStr, 'directory', path)
        jStr = cls.__appendAttr(jStr, 'interval', interval)
        jStr = cls.__appendAttr(jStr, 'maxfiles', maxFiles)
        print >>fd, "%s<%s/>" % (indent, jStr)

    @classmethod
    def writeJVMXML(cls, fd, indent, path, isServer, heapInit, heapMax, args,
                    extraArgs):

        if path is not None or isServer or heapInit is not None or \
           heapMax is not None or args is not None or extraArgs is not None:
            jStr = "jvm"
            jStr = cls.__appendAttr(jStr, 'path', path)
            if isServer:
                jStr = cls.__appendAttr(jStr, 'server', isServer)
            jStr = cls.__appendAttr(jStr, 'heapInit', heapInit)
            jStr = cls.__appendAttr(jStr, 'heapMax', heapMax)
            jStr = cls.__appendAttr(jStr, 'args', args)
            jStr = cls.__appendAttr(jStr, 'extraArgs', extraArgs)
            print >>fd, "%s<%s/>" % (indent, jStr)

    @classmethod
    def writeLine(cls, fd, indent, name, value):
        if value is None or value == "":
            print >>fd, "%s<%s/>" % (indent, name)
        else:
            print >>fd, "%s<%s>%s</%s>" % (indent, name, value, name)


class MockCluCfgCtlSrvr(object):
    """Used by MockClusterConfigFile for <controlServer>>"""
    def __init__(self):
        pass

    @property
    def hitspoolDirectory(self):
        return None

    @property
    def hitspoolInterval(self):
        return None

    @property
    def hitspoolMaxFiles(self):
        return None

    @property
    def isControlServer(self):
        return True

    @property
    def isSimHub(self):
        return False

    @property
    def jvmArgs(self):
        return None

    @property
    def jvmExtraArgs(self):
        return None

    @property
    def jvmHeapInit(self):
        return None

    @property
    def jvmHeapMax(self):
        return None

    @property
    def jvmPath(self):
        return None

    @property
    def jvmServer(self):
        return False

    @property
    def logLevel(self):
        return None

    @property
    def name(self):
        return "CnCServer"

    @property
    def num(self):
        return 0

    @property
    def required(self):
        return True

    def write(self, fd, indent):
        print >>fd, indent + "<controlServer/>"


class MockCluCfgFileComp(MockClusterWriter):
    """Used by MockClusterConfigFile for <component>"""
    def __init__(self, name, num=0, required=False, hitspoolDirectory=None,
                 hitspoolInterval=None, hitspoolMaxFiles=None, jvmPath=None,
                 jvmServer=None, jvmHeapInit=None, jvmHeapMax=None,
                 jvmArgs=None, jvmExtraArgs=None, logLevel=None):
        self.__name = name
        self.__num = num
        self.__required = required

        self.__hitspoolDir = hitspoolDirectory
        self.__hitspoolInterval = hitspoolInterval
        self.__hitspoolMaxFiles = hitspoolMaxFiles

        self.__jvmPath = jvmPath
        self.__jvmServer = jvmServer is True
        self.__jvmHeapInit = jvmHeapInit
        self.__jvmHeapMax = jvmHeapMax
        self.__jvmArgs = jvmArgs
        self.__jvmExtraArgs = jvmExtraArgs

        self.__logLevel = logLevel

    def __str__(self):
        return "%s#%s" % (self.__name, self.__num)

    @property
    def hitspoolDirectory(self):
        return self.__hitspoolDir

    @property
    def hitspoolInterval(self):
        return self.__hitspoolInterval

    @property
    def hitspoolMaxFiles(self):
        return self.__hitspoolMaxFiles

    @property
    def isControlServer(self):
        return False

    @property
    def isSimHub(self):
        return False

    @property
    def jvmArgs(self):
        return self.__jvmArgs

    @property
    def jvmExtraArgs(self):
        return self.__jvmExtraArgs

    @property
    def jvmHeapInit(self):
        return self.__jvmHeapInit

    @property
    def jvmHeapMax(self):
        return self.__jvmHeapMax

    @property
    def jvmPath(self):
        return self.__jvmPath

    @property
    def jvmServer(self):
        return self.__jvmServer

    @property
    def logLevel(self):
        if self.__logLevel is not None:
            return self.__logLevel

        return ClusterDescription.DEFAULT_LOG_LEVEL

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def required(self):
        return self.__required

    def setHitspoolDirectory(self, value):
        self.__hitspoolDir = value

    def setHitspoolInterval(self, value):
        self.__hitspoolInterval = value

    def setHitspoolMaxFiles(self, value):
        self.__hitspoolMaxFiles = value

    def setJVMArgs(self, value):
        self.__jvmArgs = value

    def setJVMExtraArgs(self, value):
        self.__jvmExtraArgs = value

    def setJVMHeapInit(self, value):
        self.__jvmHeapInit = value

    def setJVMHeapMax(self, value):
        self.__jvmHeapMax = value

    def setJVMServer(self, value):
        self.__jvmServer = value

    def setJVMPath(self, value):
        self.__jvmPath = value

    def setLogLevel(self, value):
        self.__logLevel = value

    def write(self, fd, indent):
        if self.__num == 0:
            numstr = ""
        else:
            numstr = " id=\"%d\"" % self.__num

        if not self.__required:
            reqstr = ""
        else:
            reqstr = " required=\"true\""

        hasHSFields = self.__hitspoolDir is not None or \
                      self.__hitspoolInterval is not None or \
                      self.__hitspoolMaxFiles is not None
        hasJVMFields = self.__jvmPath is not None or \
                       self.__jvmArgs is not None or \
                       self.__jvmExtraArgs is not None or \
                       self.__jvmHeapInit is not None or \
                       self.__jvmHeapMax is not None or \
                       self.__jvmServer is not None
        multiline = hasHSFields or hasJVMFields or self.__logLevel is not None

        if multiline:
            endstr = ""
        else:
            endstr = "/"

        print >>fd, "%s<component name=\"%s\"%s%s%s>" % \
            (indent, self.__name, numstr, reqstr, endstr)

        if multiline:
            indent2 = indent + "  "

            if hasHSFields:
                self.writeHSXML(fd, indent2, self.__hitspoolDir,
                                self.__hitspoolInterval,
                                self.__hitspoolMaxFiles)
            if hasJVMFields:
                self.writeJVMXML(fd, indent2, self.__jvmPath, self.__jvmServer,
                                 self.__jvmHeapInit, self.__jvmHeapMax,
                                 self.__jvmArgs, self.__jvmExtraArgs)

            if self.__logLevel is not None:
                self.writeLine(fd, indent2, "logLevel", self.__logLevel)

            print >>fd, "%s</component>" % indent


class MockCluCfgFileCtlSrvr(object):
    """Used by MockClusterConfigFile for <controlServer/>"""
    def __init__(self):
        pass

    @property
    def hitspoolDirectory(self):
        return None

    @property
    def hitspoolInterval(self):
        return None

    @property
    def hitspoolMaxFiles(self):
        return None

    @property
    def isControlServer(self):
        return True

    @property
    def isSimHub(self):
        return False

    @property
    def jvmArgs(self):
        return None

    @property
    def jvmExtraArgs(self):
        return None

    @property
    def jvmHeapInit(self):
        return None

    @property
    def jvmHeapMax(self):
        return None

    @property
    def jvmPath(self):
        return None

    @property
    def jvmServer(self):
        return False

    @property
    def logLevel(self):
        return None

    @property
    def name(self):
        return "CnCServer"

    @property
    def num(self):
        return 0

    @property
    def required(self):
        return True

    def write(self, fd, indent):
        print >>fd, indent + "<controlServer/>"


class MockCluCfgFileHost(object):
    """Used by MockClusterConfigFile for <host/>"""
    def __init__(self, name, parent):
        self.__name = name
        self.__parent = parent
        self.__comps = None

    def __addComp(self, comp):
        if self.__comps is None:
            self.__comps = []
        self.__comps.append(comp)
        return comp

    def addComponent(self, name, num=0, required=False):
        c = MockCluCfgFileComp(name, num=num, required=required)

        return self.__addComp(c)

    def addControlServer(self):
        return self.__addComp(MockCluCfgCtlSrvr())

    def addSimHubs(self, number, priority, ifUnused=False):
        return self.__addComp(MockCluCfgFileSimHubs(number, priority,
                                                    ifUnused=ifUnused))

    @property
    def name(self):
        return self.__name

    def write(self, fd, indent):
        print >>fd, "%s<host name=\"%s\">" % (indent, self.__name)

        indent2 = indent + "  "
        if self.__comps:
            for c in self.__comps:
                c.write(fd, indent2)

        print >>fd, "%s</host>" % indent


class MockCluCfgFileSimHubs(MockClusterWriter):
    """Used by MockClusterConfigFile for <simulatedHub/>"""
    def __init__(self, number, priority=1, ifUnused=False):
        self.__number = number
        self.__priority = priority
        self.__ifUnused = ifUnused

    @property
    def hitspoolDirectory(self):
        return None

    @property
    def hitspoolInterval(self):
        return None

    @property
    def hitspoolMaxFiles(self):
        return None

    @property
    def isControlServer(self):
        return False

    @property
    def isSimHub(self):
        return True

    @property
    def jvmArgs(self):
        return None

    @property
    def jvmExtraArgs(self):
        return None

    @property
    def jvmHeapInit(self):
        return None

    @property
    def jvmHeapMax(self):
        return None

    @property
    def jvmPath(self):
        return None

    @property
    def jvmServer(self):
        return False

    @property
    def logLevel(self):
        return None

    @property
    def name(self):
        return "SimHub"

    @property
    def num(self):
        return 0

    @property
    def required(self):
        return False

    def write(self, fd, indent):
        if self.__ifUnused:
            iustr = " ifUnused=\"true\""
        else:
            iustr = ""

        print >>fd, "%s<simulatedHub number=\"%d\" priority=\"%d\"%s/>" % \
            (indent, self.__number, self.__priority, iustr)


class MockClusterComponent(Component):
    def __init__(self, fullname, jvmPath, jvmArgs, host):
        sep = fullname.rfind("#")
        if sep < 0:
            sep = fullname.rfind("-")

        if sep < 0:
            name = fullname
            num = 0
        else:
            name = fullname[:sep]
            num = int(fullname[sep + 1:])

        self.__jvmPath = jvmPath
        self.__jvmArgs = jvmArgs
        self.__host = host

        super(MockClusterComponent, self).__init__(name, num, None)

    def __str__(self):
        return "%s(%s)" % (self.fullname, self.__host)

    def dump(self, fd, indent):
        print >>fd, "%s<location name=\"%s\" host=\"%s\">" % \
            (indent, self.__host, self.__host)
        print >>fd, "%s    <module name=\"%s\" id=\"%02d\"/?>" % \
            (indent, self.name, self.id)
        print >>fd, "%s</location>" % indent

    @property
    def host(self):
        return self.__host

    @property
    def isLocalhost(self):
        return True

    def jvmPath(self):
        return self.__jvmPath

    def jvmArgs(self):
        return self.__jvmArgs


class MockClusterConfig(object):
    """Simulate a cluster config object"""
    def __init__(self, name, descName="test-cluster"):
        self.__configName = name
        self.__nodes = {}
        self.__descName = descName

    def __repr__(self):
        return "MockClusterConfig(%s)" % self.__configName

    def addComponent(self, comp, jvmPath, jvmArgs, host):
        if host not in self.__nodes:
            self.__nodes[host] = MockClusterNode(host)
        self.__nodes[host].add(comp, jvmPath, jvmArgs, host)

    @property
    def configName(self):
        return self.__configName

    @property
    def description(self):
        return self.__descName

    def extractComponents(self, masterList):
        return RunCluster.extractComponentsFromNodes(self.__nodes.values(),
                                                     masterList)

    @property
    def name(self):
        return self.__configName

    def nodes(self):
        return self.__nodes.values()


class MockClusterConfigFile(MockClusterWriter):
    """Write a cluster config file"""
    def __init__(self, configDir, name):
        self.__configDir = configDir
        self.__name = name

        self.__dataDir = None
        self.__logDir = None
        self.__spadeDir = None

        self.__defaultHSDir = None
        self.__defaultHSInterval = None
        self.__defaultHSMaxFiles = None

        self.__defaultJVMArgs = None
        self.__defaultJVMExtraArgs = None
        self.__defaultJVMHeapInit = None
        self.__defaultJVMHeapMax = None
        self.__defaultJVMPath = None
        self.__defaultJVMServer = None

        self.__defaultAlertEMail = None
        self.__defaultNTPHost = None

        self.__defaultLogLevel = None

        self.__defaultComps = None

        self.__hosts = {}

    def addDefaultComponent(self, comp):
        if not self.__defaultComps:
            self.__defaultComps = []

        self.__defaultComps.append(comp)

    def addHost(self, name):
        if name in self.__hosts:
            raise Exception("Host \"%s\" is already added" % name)

        h = MockCluCfgFileHost(name, self)
        self.__hosts[name] = h
        return h

    def create(self):
        path = os.path.join(self.__configDir, "%s-cluster.cfg" % self.__name)

        if not os.path.exists(self.__configDir):
            os.makedirs(self.__configDir)

        with open(path, 'w') as fd:
            print >>fd, "<cluster name=\"%s\">" % self.__name

            indent = "  "

            if self.__dataDir is not None:
                self.writeLine(fd, indent, "daqDataDir", self.__dataDir)
            if self.__logDir is not None:
                self.writeLine(fd, indent, "daqLogDir", self.__logDir)
            if self.__spadeDir is not None:
                self.writeLine(fd, indent, "logDirForSpade", self.__spadeDir)

            hasHSXML = self.__defaultHSDir is not None or \
                       self.__defaultHSInterval is not None or \
                       self.__defaultHSMaxFiles is not None

            hasJVMXML = self.__defaultJVMArgs is not None or \
                        self.__defaultJVMExtraArgs is not None or \
                        self.__defaultJVMHeapInit is not None or \
                        self.__defaultJVMHeapMax is not None or \
                        self.__defaultJVMPath is not None or \
                        self.__defaultJVMServer is not None

            hasHubXML = self.__defaultAlertEMail is not None or \
                        self.__defaultNTPHost is not None

            if hasHSXML or hasJVMXML or hasHubXML or \
               self.__defaultLogLevel is not None or \
               self.__defaultComps is not None:
                print >>fd, indent + "<default>"

                indent2 = indent + "  "

                if hasHSXML:
                    self.writeHSXML(fd, indent2, self.__defaultHSDir,
                                    self.__defaultHSInterval,
                                    self.__defaultHSMaxFiles)

                if hasJVMXML:
                    self.writeJVMXML(fd, indent2, self.__defaultJVMPath,
                                     self.__defaultJVMServer,
                                     self.__defaultJVMHeapInit,
                                     self.__defaultJVMHeapMax,
                                     self.__defaultJVMArgs,
                                     self.__defaultJVMExtraArgs)

                if hasHubXML:
                    self.writeHubXML(fd, indent2, self.__defaultAlertEMail,
                                     self.__defaultNTPHost)

                if self.__defaultLogLevel is not None:
                    self.writeLine(fd, indent2, "logLevel",
                                   self.__defaultLogLevel)

                if self.__defaultComps:
                    for c in self.__defaultComps:
                        c.write(fd, indent2)

                print >>fd, indent + "</default>"

            for h in self.__hosts.itervalues():
                h.write(fd, indent)

            print >>fd, "</cluster>"

    @property
    def dataDir(self):
        if self.__dataDir is None:
            return ClusterDescription.DEFAULT_DATA_DIR

        return self.__dataDir

    def defaultAlertEMail(self):
        return self.__defaultAlertEMail

    def defaultHSDirectory(self):
        return self.__defaultHSDir

    def defaultHSInterval(self):
        return self.__defaultHSInterval

    def defaultHSMaxFiles(self):
        return self.__defaultHSMaxFiles

    def defaultJVMArgs(self):
        return self.__defaultJVMArgs

    def defaultJVMExtraArgs(self):
        return self.__defaultJVMExtraArgs

    def defaultJVMHeapInit(self):
        return self.__defaultJVMHeapInit

    def defaultJVMHeapMax(self):
        return self.__defaultJVMHeapMax

    def defaultJVMPath(self):
        return self.__defaultJVMPath

    def defaultJVMServer(self):
        return self.__defaultJVMServer

    @property
    def defaultLogLevel(self):
        if self.__defaultLogLevel is None:
            return ClusterDescription.DEFAULT_LOG_LEVEL

        return self.__defaultLogLevel

    def defaultNTPHost(self):
        return self.__defaultNTPHost

    @property
    def logDir(self):
        if self.__logDir is None:
            return ClusterDescription.DEFAULT_LOG_DIR

        return self.__logDir

    @property
    def name(self):
        return self.__name

    def setDataDir(self, value):
        self.__dataDir = value

    def setDefaultAlertEMail(self, value):
        self.__defaultAlertEMail = value

    def setDefaultHSDirectory(self, value):
        self.__defaultHSDir = value

    def setDefaultHSInterval(self, value):
        self.__defaultHSInterval = value

    def setDefaultHSMaxFiles(self, value):
        self.__defaultHSMaxFiles = value

    def setDefaultJVMArgs(self, value):
        self.__defaultJVMArgs = value

    def setDefaultJVMExtraArgs(self, value):
        self.__defaultJVMExtraArgs = value

    def setDefaultJVMHeapInit(self, value):
        self.__defaultJVMHeapInit = value

    def setDefaultJVMHeapMax(self, value):
        self.__defaultJVMHeapMax = value

    def setDefaultJVMPath(self, value):
        self.__defaultJVMPath = value

    def setDefaultJVMServer(self, value):
        self.__defaultJVMServer = value

    def setDefaultLogLevel(self, value):
        self.__defaultLogLevel = value

    def setDefaultNTPHost(self, value):
        self.__defaultNTPHost = value

    def setLogDir(self, value):
        self.__logDir = value

    def setSpadeDir(self, value):
        self.__spadeDir = value

    @property
    def spadeDir(self):
        return self.__spadeDir


class MockClusterNode(object):
    def __init__(self, host):
        self.__host = host
        self.__comps = []

    def add(self, comp, jvmPath, jvmArgs, host):
        self.__comps.append(MockClusterComponent(comp, jvmPath, jvmArgs, host))

    def components(self):
        return self.__comps[:]


class MockCnCLogger(CnCLogger):
    def __init__(self, name, appender=None, quiet=False, extraLoud=False):
        self.__appender = appender

        super(MockCnCLogger, self).__init__(name, appender=appender,
                                            quiet=quiet, extraLoud=extraLoud)


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

    @property
    def isInput(self):
        return self.__connCh == self.INPUT or self.__connCh == self.OPT_INPUT

    @property
    def isOptional(self):
        return self.__connCh == self.OPT_INPUT or \
               self.__connCh == self.OPT_OUTPUT

    @property
    def name(self):
        return self.__name

    @property
    def port(self):
        return self.__port


class MockMBeanClient(object):
    def __init__(self, name):
        self.__name = name
        self.__beanData = {}

    def __str__(self):
        return self.__name

    def addData(self, beanName, fieldName, value):
        if self.check(beanName, fieldName):
            raise Exception("Value for %s bean %s field %s already exists" %
                            (self, beanName, fieldName))

        if beanName not in self.__beanData:
            self.__beanData[beanName] = {}

        self.__beanData[beanName][fieldName] = value

    def addOrSet(self, beanName, fieldName, value):
        if beanName not in self.__beanData:
            self.__beanData[beanName] = {}

        self.__beanData[beanName][fieldName] = value

    def check(self, beanName, fieldName):
        return beanName in self.__beanData and \
            fieldName in self.__beanData[beanName]

    def get(self, beanName, fieldName):
        if not self.check(beanName, fieldName):
            raise Exception("No %s data for bean %s field %s" %
                            (self, beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def getAttributes(self, beanName, fieldList):
        rtnMap = {}
        for f in fieldList:
            rtnMap[f] = self.get(beanName, f)

            if isinstance(rtnMap[f], Exception):
                raise rtnMap[f]
        return rtnMap

    def getBeanFields(self, beanName):
        return self.__beanData[beanName].keys()

    def getBeanNames(self):
        return self.__beanData.keys()

    def reload(self):
        pass

    def setData(self, beanName, fieldName, value):
        if not self.check(beanName, fieldName):
            raise Exception("%s bean %s field %s has not been added" %
                            (self, beanName, fieldName))

        self.__beanData[beanName][fieldName] = value


class MockComponent(object):
    def __init__(self, name, num=0, host='localhost'):
        self.__name = name
        self.__num = num
        self.__host = host

        self.__connectors = []
        self.__cmdOrder = None

        self.runNum = None

        self.__isBldr = name.endswith("Builder") or name.endswith("Builders")
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
        self.__stopFail = False
        self.__replayHub = False
        self.__firstGoodTime = None
        self.__lastGoodTime = None
        self.__mbeanClient = None

    def __cmp__(self, other):
        val = cmp(self.__name, other.__name)
        if val == 0:
            val = cmp(self.__num, other.__num)
        return val

    def __repr__(self):
        return str(self)

    def __str__(self):
        outStr = self.fullname
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

    def _createMBeanClient(self):
        return MockMBeanClient(self.fullname)

    def createMBeanClient(self):
        if self.__mbeanClient is None:
            self.__mbeanClient = self._createMBeanClient()
        return self.__mbeanClient

    def forcedStop(self):
        if self.__stopFail:
            pass
        elif self.__stopping == 1:
            if self.__hangType != 2:
                self.runNum = None
                self.__stopping = 0
            else:
                self.__stopping = 2

    @property
    def fullname(self):
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    @property
    def filename(self):
        return '%s-%d' % (self.__name, self.__num)

    def getConfigureWait(self):
        return self.__configWait

    def getRunData(self, runnum):
        if self.__mbeanClient is None:
            self.__mbeanClient = self.createMBeanClient()

        if self.__num == 0:
            if self.__name.startswith("event"):
                evtData = self.__mbeanClient.get("backEnd", "EventData")
                numEvts = int(evtData[0])
                lastTime = long(evtData[1])

                val = self.__mbeanClient.get("backEnd", "FirstEventTime")
                firstTime = long(val)

                good = self.__mbeanClient.get("backEnd", "GoodTimes")
                firstGood = long(good[0])
                lastGood = long(good[1])
                return (numEvts, firstTime, lastTime, firstGood, lastGood)
            elif self.__name.startswith("secondary"):
                for bldr in ("tcal", "sn", "moni"):
                    val = self.__mbeanClient.get(bldr + "Builder",
                                                 "NumDispatchedData")
                    if bldr == "tcal":
                        numTcal = long(val)
                    elif bldr == "sn":
                        numSN = long(val)
                    elif bldr == "moni":
                        numMoni = long(val)

                return (numTcal, numSN, numMoni)

        return (None, None, None)

    @property
    def host(self):
        return self.__host

    @property
    def is_dying(self):
        return False

    @property
    def isBuilder(self):
        return self.__isBldr

    def isComponent(self, name, num=-1):
        return self.__name == name

    @property
    def isConfigured(self):
        return self.__configured

    @property
    def isHanging(self):
        return self.__hangType != 0

    @property
    def isReplayHub(self):
        return self.__replayHub

    @property
    def isSource(self):
        return self.__isSrc

    def listConnectorStates(self):
        return ""

    def logTo(self, logIP, logPort, liveIP, livePort):
        pass

    @property
    def mbean(self):
        if self.__mbeanClient is None:
            self.__mbeanClient = self.createMBeanClient()

        return self.__mbeanClient

    def monitorCount(self):
        return self.__monitorCount

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    def order(self):
        return self.__cmdOrder

    def prepareSubrun(self, id):
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

    def setConfigureWait(self, waitNum):
        self.__configWait = waitNum

    def setStopFail(self):
        self.__stopFail = True

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

    @property
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

        if self.__hangType > 0 or self.__stopFail:
            self.__stopping = 1
        else:
            self.runNum = None

    def updateRates(self):
        self.__updatedRates = True

    def wasUpdated(self):
        return self.__updatedRates


class MockDefaultDomGeometryFile(object):
    @classmethod
    def create(cls, config_dir, hub_dom_dict):
        """
        Create a default-dom-geometry.xml file in directory `config_dir`
        using the dictionary with integer hub numbers as keys and
        lists of SimDOMXML objects as values
        """
        path = os.path.join(config_dir, DefaultDomGeometry.FILENAME)
        if not os.path.exists(path):
            with open(path, "w") as fd:
                print >>fd, "<domGeometry>"
                for hub in hub_dom_dict:
                    print >>fd, "  <string>"
                    print >>fd, "    <number>%d</number>" % hub
                    for dom in hub_dom_dict[hub]:
                        print >>fd, "    <dom>"
                        print >>fd, \
                            "      <mainBoardId>%012x</mainBoardId>" % dom.mbid
                        print >>fd, "      <position>%d</position>" % dom.pos
                        print >>fd, "      <name>%s</name>" % dom.name
                        print >>fd, "      <productionId>%s</productionId>" % \
                            dom.prod_id
                        print >>fd, "    </dom>"
                    print >>fd, "  </string>"

                print >>fd, "</domGeometry>"


class MockDeployComponent(Component):
    def __init__(self, name, id, logLevel, hsDir, hsInterval, hsMaxFiles,
                 jvmPath, jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs,
                 jvmExtraArgs, alertEMail, ntpHost, numReplayFiles=None,
                 host=None):
        self.__hsDir = hsDir
        self.__hsInterval = hsInterval
        self.__hsMaxFiles = hsMaxFiles
        self.__jvmPath = jvmPath
        self.__jvmServer = jvmServer is True
        self.__jvmHeapInit = jvmHeapInit
        self.__jvmHeapMax = jvmHeapMax
        self.__jvmArgs = jvmArgs
        self.__jvmExtraArgs = jvmExtraArgs
        self.__alertEMail = alertEMail
        self.__ntpHost = ntpHost
        self.__numReplayFiles = numReplayFiles
        self.__host = host

        super(MockDeployComponent, self).__init__(name, id, logLevel)

    @property
    def alertEMail(self):
        return self.__alertEMail

    @property
    def hasHitSpoolOptions(self):
        return self.__hsDir is not None or self.__hsInterval is not None or \
            self.__hsMaxFiles is not None

    @property
    def hasReplayOptions(self):
        return self.__numReplayFiles is not None

    @property
    def hitspoolDirectory(self):
        return self.__hsDir

    @property
    def hitspoolInterval(self):
        return self.__hsInterval

    @property
    def hitspoolMaxFiles(self):
        return self.__hsMaxFiles

    @property
    def isControlServer(self):
        return False

    @property
    def host(self):
        return self.__host

    @property
    def isLocalhost(self):
        return self.__host is not None and self.__host == "localhost"

    @property
    def jvmArgs(self):
        return self.__jvmArgs

    @property
    def jvmExtraArgs(self):
        return self.__jvmExtraArgs

    @property
    def jvmHeapInit(self):
        return self.__jvmHeapInit

    @property
    def jvmHeapMax(self):
        return self.__jvmHeapMax

    @property
    def jvmPath(self):
        return self.__jvmPath

    @property
    def jvmServer(self):
        return self.__jvmServer

    @property
    def ntpHost(self):
        return self.__ntpHost

    @property
    def numReplayFilesToSkip(self):
        return self.__numReplayFiles


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
        return MockRPCClient(self.name, self.num, self.outLinks)

    def createLogger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet, extraLoud=self.__extraLoud)

    def createMBeanClient(self, host, port):
        return MockRPCClient(self.name, self.num, self.outLinks)

    def reset(self):
        self.__state = 'idle'
        return super(MockDAQClient, self).reset()

    def startRun(self, runNum):
        self.__state = 'running'
        return super(MockDAQClient, self).startRun(runNum)

    @property
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

    @property
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

    @property
    def isDebugEnabled(self):
        return True

    @property
    def isErrorEnabled(self):
        return True

    @property
    def isFatalEnabled(self):
        return True

    @property
    def isInfoEnabled(self):
        return True

    @property
    def isTraceEnabled(self):
        return True

    @property
    def isWarnEnabled(self):
        return True

    @property
    def livePort(self):
        return None

    @property
    def logPort(self):
        return None

    def setError(self, msg):
        self.__err = msg
        raise Exception(msg)

    def trace(self, m):
        self._checkMsg(m)

    def warn(self, m):
        self._checkMsg(m)


class MockParallelShell(object):
    BINDIR = os.path.join(find_pdaq_trunk(), 'target', 'pDAQ-%s-dist' %
                          ComponentManager.RELEASE, 'bin')

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
            raise Exception("Command not found in expected command list:"
                            " cmd=\"%s\"" % (cmd, ))

        del self.__exp[found]

    def __isLocalhost(self, host):
        return host == 'localhost' or host == '127.0.0.1'

    def add(self, cmd):
        self.__checkCmd(cmd)

    def addExpectedJava(self, comp, configDir, daqDataDir, logPort, livePort,
                        verbose, eventCheck, host):

        ipAddr = ip.getLocalIpAddr(host)
        jarPath = os.path.join(MockParallelShell.BINDIR,
                               ComponentManager.getComponentJar(comp.name))

        if verbose:
            redir = ''
        else:
            redir = ' </dev/null >/dev/null 2>&1'

        cmd = comp.jvmPath
        cmd += " -Dicecube.daq.component.configDir='%s'" % configDir

        if comp.jvmServer is not None and comp.jvmServer:
            cmd += " -server"
        if comp.jvmHeapInit is not None:
            cmd += " -Xms" + comp.jvmHeapInit
        if comp.jvmHeapMax is not None:
            cmd += " -Xmx" + comp.jvmHeapMax
        if comp.jvmArgs is not None:
            cmd += " " + comp.jvmArgs
        if comp.jvmExtraArgs is not None:
            cmd += " " + comp.jvmExtraArgs

        if comp.isRealHub:
            if comp.ntpHost is not None:
                cmd += " -Dicecube.daq.time.monitoring.ntp-host=" + \
                       comp.ntpHost
            if comp.alertEMail is not None:
                cmd += " -Dicecube.daq.stringhub.alert-email=" + \
                       comp.alertEMail

        if comp.hitspoolDirectory is not None:
            cmd += " -Dhitspool.directory=\"%s\"" % comp.hitspoolDirectory
        if comp.hitspoolInterval is not None:
            cmd += " -Dhitspool.interval=%.4f" % comp.hitspoolInterval
        if comp.hitspoolMaxFiles is not None:
            cmd += " -Dhitspool.maxfiles=%d" % comp.hitspoolMaxFiles

        if comp.isHub:
            cmd += " -Dicecube.daq.stringhub.componentId=%d" % comp.id
        if eventCheck and comp.isBuilder:
            cmd += ' -Dicecube.daq.eventBuilder.validateEvents'

        cmd += ' -jar %s' % jarPath
        if daqDataDir is not None:
            cmd += ' -d %s' % daqDataDir
        cmd += ' -c %s:%d' % (ipAddr, DAQPort.CNCSERVER)

        if logPort is not None:
            cmd += ' -l %s:%d,%s' % (ipAddr, logPort, comp.logLevel)
        if livePort is not None:
            cmd += ' -L %s:%d,%s' % (ipAddr, livePort, comp.logLevel)
            cmd += ' -M %s:%d' % (ipAddr, MoniPort)
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
            killPat = "stringhub.componentId=%d " % compId
        else:
            killPat = ComponentManager.getComponentJar(compName)

        if self.__isLocalhost(host):
            sshCmd = ''
            pkillOpt = ' -fu %s' % user
        else:
            sshCmd = 'ssh %s ' % host
            pkillOpt = ' -f'

        self.__addExpected('%spkill %s%s \"%s\"' %
                           (sshCmd, nineArg, pkillOpt, killPat))

        if not killWith9:
            self.__addExpected('sleep 2; %spkill -9%s \"%s\"' %
                               (sshCmd, pkillOpt, killPat))

    def addExpectedPython(self, doCnC, dashDir, configDir, logDir, daqDataDir,
                          spadeDir, cluCfgName, cfgName, copyDir, logPort,
                          livePort, forceRestart=True):
        if doCnC:
            cmd = os.path.join(dashDir, 'CnCServer.py')
            cmd += ' -c %s' % configDir
            cmd += ' -o %s' % logDir
            cmd += ' -q %s' % daqDataDir
            cmd += ' -s %s' % spadeDir
            if cluCfgName is not None:
                if cluCfgName.endswith("-cluster"):
                    cmd += ' -C %s' % cluCfgName
                else:
                    cmd += ' -C %s-cluster' % cluCfgName
            if logPort is not None:
                cmd += ' -l localhost:%d' % logPort
            if livePort is not None:
                cmd += ' -L localhost:%d' % livePort
            if copyDir is not None:
                cmd += ' -a %s' % copyDir
            if not forceRestart:
                cmd += ' -F'
            cmd += ' -d'

            self.__addExpected(cmd)

    def addExpectedPythonKill(self, doCnC, killWith9):
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

    def addExpectedUndeploy(self, pdaqDir, remoteHost):
        cmd = "ssh %s \"\\rm -rf ~%s/config %s\"" % \
            (remoteHost, os.environ["USER"], pdaqDir)
        self.__addExpected(cmd)

    def check(self):
        if len(self.__exp) > 0:
            raise Exception(('ParallelShell did not receive expected commands:'
                             ' %s') % str(self.__exp))

    def getMetaPath(self, subdir):
        return os.path.join(find_pdaq_trunk(), subdir)

    def getResult(self, idx):
        if idx < 0 or idx >= len(self.__results):
            raise Exception("Cannot return result %d (only %d available)" %
                            (idx, len(self.__results)))

        return self.__results[idx]

    def getReturnCodes(self):
        return self.__rtnCodes

    @property
    def isParallel(self):
        return self.__isParallel

    def showAll(self):
        raise Exception('SHOWALL')

    def shuffle(self):
        pass

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
        return "%s#%s" % (self.__name, self.__id)

    @property
    def id(self):
        return self.__id

    def inetAddress(self):
        return self.__inetAddr

    @property
    def isHub(self):
        return self.__name.endswith("Hub")

    @property
    def isReplay(self):
        return self.isHub and self.__name.lower().find("replay") >= 0

    @property
    def mbeanPort(self):
        return self.__mbeanPort

    @property
    def name(self):
        return self.__name

    @property
    def rpcPort(self):
        return self.__rpcPort


class SimDOMXML(object):
    def __init__(self, mbid, pos=None, name=None, prod_id=None):
        self.__mbid = mbid
        self.__pos = pos
        self.__name = name
        self.__prod_id = prod_id

    @property
    def mbid(self):
        return self.__mbid

    @property
    def name(self):
        return self.__name

    @property
    def pos(self):
        return self.__pos

    @property
    def prod_id(self):
        return self.__prod_id

    def printXML(self, fd, indent):
        print >>fd, "%s<domConfig mbid=\"%012x\">" % (indent, self.__mbid)
        print >>fd, "%s%s<xxx>xxx</xxx>" % (indent, indent)
        print >>fd, "%s</domConfig>" % indent


class MockAlgorithm(object):
    def __init__(self, srcId, name, trigtype, cfgId):
        self.__srcId = srcId
        self.__name = name
        self.__type = trigtype
        self.__cfgId = cfgId
        self.__paramDict = {}
        self.__readouts = []

    def __printElement(self, fd, indent, tag, val):
        print >>fd, "%s<%s>%s</%s>" % (indent, tag, val, tag)

    def addParameter(self, name, value):
        self.__paramDict[name] = value

    def addReadout(self, rdoutType, offset, minus, plus):
        self.__readouts.append((rdoutType, offset, minus, plus))

    def printXML(self, fd, indent):
        i2 = indent + "    "
        print >>fd, "%s<triggerConfig>" % indent

        self.__printElement(fd, i2, "triggerType", self.__type)
        self.__printElement(fd, i2, "triggerConfigId", self.__cfgId)
        self.__printElement(fd, i2, "sourceId", self.__srcId)
        self.__printElement(fd, i2, "triggerName", self.__name)

        for k, v in self.__paramDict:
            print >>fd, "%s<parameterConfig>"
            print >>fd, "%s    <parameterName>%s<parameterName>" % (i2, k)
            print >>fd, "%s    <parameterValue>%s<parameterValue>" % (i2, v)
            print >>fd, "%s</parameterConfig>"

        for r in self.__readouts:
            tag = ["readoutType", "timeOffset", "timeMinus", "timePlus"]

            print >>fd, "%s<readoutConfig>"
            for i in xrange(4):
                print >>fd, "%s    <%s>%d<%s>" % (i2, tag[i], r[i], tag[i])
            print >>fd, "%s</readoutConfig>"

        print >>fd, "%s</triggerConfig>" % indent


class MockLeapsecondFile(object):
    def __init__(self, configDir):
        self.__configDir = configDir

    def create(self):
        known_times = (
            (35, 3550089600),
            (36, 3644697600),
            (37, 3692217600),
        )

        # set expiration to one day before warnings would appear
        expiration = MJD.now().ntp + \
                     ((RunSet.LEAPSECOND_FILE_EXPIRY + 1) * 24 * 3600)

        nist_path = os.path.join(self.__configDir, "nist")
        if not os.path.isdir(nist_path):
            os.mkdir(nist_path)

        filepath = os.path.join(nist_path, leapseconds.DEFAULT_FILENAME)
        with open(filepath, "w") as out:
            print >>out, "# Mock NIST leapseconds file"
            print >>out, "#@\t%d" % (expiration, )
            print >>out, "#"

            for pair in known_times:
                print >>out, "%d\t%d" % (pair[1], pair[0])


class MockTriggerConfig(object):
    def __init__(self, name):
        self.__name = name
        self.__algorithms = []

    def add(self, srcId, name, trigtype, cfgId):
        algo = MockAlgorithm(srcId, name, trigtype, cfgId)
        self.__algorithms.append(algo)
        return algo

    def create(self, configDir, debug=False):
        cfgDir = os.path.join(configDir, "trigger")
        if not os.path.exists(cfgDir):
            os.makedirs(cfgDir)

        path = os.path.join(cfgDir, self.__name)
        if not path.endswith(".xml"):
            path = path + ".xml"
        with open(path, "w") as fd:
            print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            if len(self.__algorithms) == 0:
                print >>fd, "<activeTriggers/>"
            else:
                print >>fd, "<activeTriggers>"
                needNL = False
                for a in self.__algorithms:
                    if not needNL:
                        needNL = True
                    else:
                        print >>fd
                    a.printXML(fd, "    ")
                print >>fd, "</activeTriggers>"

        if debug:
            with open(path, "r") as fd:
                print "=== %s ===" % path
                for line in fd:
                    print line,

    @property
    def name(self):
        return self.__name


class MockRunConfigFile(object):
    def __init__(self, configDir):
        self.__configDir = configDir

    def __makeDomConfig(self, cfgName, domList, debug=False):
        cfgDir = os.path.join(self.__configDir, "domconfigs")
        if not os.path.exists(cfgDir):
            os.makedirs(cfgDir)

        if cfgName.endswith(".xml"):
            fileName = cfgName
        else:
            fileName = cfgName + ".xml"

        path = os.path.join(cfgDir, fileName)
        with open(path, 'w') as fd:
            print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            print >>fd, "<domConfigList>"
            if domList is not None:
                for d in domList:
                    d.printXML(fd, "  ")
            print >>fd, "</domConfigList>"

        if debug:
            with open(path, "r") as fd:
                print "=== %s ===" % path
                for line in fd:
                    print line,

    def create(self, compList, hubDomDict, trigCfg=None, debug=False):
        path = tempfile.mktemp(suffix=".xml", dir=self.__configDir)
        if not os.path.exists(self.__configDir):
            os.makedirs(self.__configDir)

        if trigCfg is None:
            trigCfg = MockTriggerConfig("empty-trigger")
        trigCfg.create(self.__configDir, debug=debug)

        with open(path, 'w') as fd:
            print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            print >>fd, "<runConfig>"
            for hub, domList in hubDomDict.items():
                domCfg = "string-%d-config" % hub
                self.__makeDomConfig(domCfg, domList, debug=debug)

                print >>fd, \
                    "    <stringHub hubId=\"%s\" domConfig=\"%s\"/>" % \
                    (hub, domCfg)

            print >>fd, "    <triggerConfig>%s</triggerConfig>" % trigCfg.name
            for c in compList:
                pound = c.rfind("#")
                if pound > 0:
                    val = int(c[pound + 1:])
                    if val == 0:
                        c = c[:pound]
                print >>fd, "    <runComponent name=\"%s\"/>" % c
            print >>fd, "</runConfig>"

        if debug:
            with open(path, "r") as fd:
                print "=== %s ===" % path
                for line in fd:
                    print line,

        name = os.path.basename(path)
        if name.endswith(".xml"):
            name = name[:-4]

        return name

    @staticmethod
    def createDOM(mbid, pos=None, name=None, prod_id=None):
        return SimDOMXML(mbid, pos=pos, name=name, prod_id=prod_id)


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
            if l['type'] not in tmpLinks:
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
                raise ValueError("Component %s#%d should not connect to"
                                 " %s:%s#%d" %
                                 (self.name, self.num, l['type'],
                                  l['compName'], l.getCompNum()))

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
            raise Exception("Socket reader %s is already running" %
                            (self.__name, ))

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
            log.addExpectedTextRegexp(r'Start of log at LOG=(\S+:\d+|' +
                                      r'log\(\S+:\d+\)(\slive\(\S+:\d+\))?)')
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


class RunXMLValidator(object):
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
    def validate(cls, test_case, runNum, cfgName, cluster, startTime, endTime,
                 numEvts, numMoni, numSN, numTcal, failed):
        try:
            if not os.path.exists("run.xml"):
                test_case.fail("run.xml was not created")

            run = DashXMLLog.parse()

            test_case.assertEqual(run.getRun(), runNum,
                                  "Expected run number %s, not %s" %
                                  (runNum, run.getRun()))

            test_case.assertEqual(run.getConfig(), cfgName,
                                  "Expected config \"%s\", not \"%s\"" %
                                  (cfgName, run.getConfig()))

            test_case.assertEqual(run.getCluster(), cluster,
                                  "Expected cluster \"%s\", not \"%s\"" %
                                  (cluster, run.getCluster()))

            if startTime is not None:
                test_case.assertEqual(run.getStartTime(), startTime,
                                      "Expected start time %s<%s>,"
                                      " not %s<%s>" %
                                      (startTime, type(startTime).__name__,
                                       run.getStartTime(),
                                       type(run.getStartTime()).__name__))
            if endTime is not None:
                test_case.assertEqual(run.getEndTime(), endTime,
                                      "Expected end time %s<%s>, not %s<%s>" %
                                      (endTime, type(endTime).__name__,
                                       run.getEndTime(),
                                       type(run.getEndTime()).__name__))

            test_case.assertEqual(run.getTermCond(), failed,
                                  "Expected terminal condition %s, not %s" %
                                  (failed, run.getTermCond()))

            test_case.assertEqual(run.getEvents(), numEvts,
                                  "Expected number of events %s, not %s" %
                                  (numEvts, run.getEvents()))

            test_case.assertEqual(run.getMoni(), numMoni,
                                  "Expected number of monitoring events %s, "
                                  "not %s" % (numMoni, run.getMoni()))

            test_case.assertEqual(run.getTcal(), numTcal,
                                  "Expected number of time cal events %s, "
                                  "not %s" % (numTcal, run.getTcal()))

            test_case.assertEqual(run.getSN(), numSN,
                                  "Expected number of supernova events %s, "
                                  "not %s" % (numSN, run.getSN()))
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

        self.__id = "MockRS"

    def components(self):
        return self.__comps[:]

    def getRates(self):
        return (self.__numEvts, self.__rate, self.__numMoni, self.__numSN,
                self.__numTcal)

    @property
    def id(self):
        return self.__id

    @property
    def isRunning(self):
        return self.__running

    def startRunning(self):
        self.__running = True

    def stopRunning(self):
        self.__running = False

    def update_rates(self):
        for c in self.__comps:
            c.updateRates()
        return self.getRates()


class MockTaskManager(object):
    def __init__(self):
        self.__timerDict = {}
        self.__error = False

    def addIntervalTimer(self, timer):
        if timer.name in self.__timerDict:
            raise Exception("Cannot add multiple timers named \"%s\"" %
                            timer.name)
        self.__timerDict[timer.name] = timer

    def createIntervalTimer(self, name, period):
        if name not in self.__timerDict:
            raise Exception("Cannot find timer named \"%s\"" % name)
        return self.__timerDict[name]

    def hasError(self):
        return self.__error

    def setError(self, callerName):
        self.__error = True


class MockLiveMoni(object):
    def __init__(self):
        self.__expMoni = {}

    def addExpected(self, var, val, prio):
        if var not in self.__expMoni:
            self.__expMoni[var] = []
        self.__expMoni[var].append((val, prio))

    def hasAllMoni(self):
        return len(self.__expMoni) == 0

    def sendMoni(self, var, val, prio, time=datetime.datetime.now()):
        if var not in self.__expMoni:
            raise Exception(("Unexpected live monitor data"
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
            raise Exception(("Expected live monitor data "
                             " (var=%s, datapairs=%s), not "
                             "(var=%s, val=%s, prio=%d)") %
                            (var, self.__expMoni[var], var, val, prio))

        return True
