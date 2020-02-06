#!/usr/bin/env python
#
# Classes used for pDAQ unit testing

from __future__ import print_function

import copy
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
from DAQLog import LogSocketServer
from DefaultDomGeometry import DefaultDomGeometry
from LiveImports import MoniPort, SERVICE_NAME
from RunCluster import RunCluster
from RunSet import RunSet
from decorators import classproperty
from i3helper import Comparable
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

    def check(self, checker, msg, debug, set_error=True):
        raise NotImplementedError()


class BaseLiveChecker(BaseChecker):
    def __init__(self, varName):
        self.__varName = varName
        super(BaseLiveChecker, self).__init__()

    def __str__(self):
        return '%s:%s=%s' % \
            (self._getShortName(), self.__varName, self._getValue())

    def _checkText(self, checker, msg, debug, set_error):
        raise NotImplementedError()

    def _getShortName(self):
        raise NotImplementedError()

    def _getValue(self):
        raise NotImplementedError()

    def _getValueType(self):
        raise NotImplementedError()

    def check(self, checker, msg, debug, set_error=True):
        m = BaseChecker.PAT_LIVELOG.match(msg)
        if m is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:LFMT: %s' % (name, msg), file=sys.stderr)
                checker.set_error('Bad format for %s I3Live message "%s"' %
                                  (name, msg))
            return False

        svcName = m.group(1)
        varName = m.group(2)
        varType = m.group(3)
        # msgPrio = m.group(4)
        # msg_time = m.group(5)
        msgText = m.group(6)

        if svcName != SERVICE_NAME:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:SVC: %s (%s)' % \
                        (name, SERVICE_NAME, self._getValue()), file=sys.stderr)
                checker.set_error('Expected %s I3Live service "%s", not "%s"'
                                  ' in "%s"' %
                                  (name, SERVICE_NAME, svcName, msg))
            return False

        if varName != self.__varName:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:VAR: %s (%s)' % \
                          (name, self.__varName, self._getValue()),
                          file=sys.stderr)
                    checker.set_error('Expected %s I3Live varName "%s",'
                                      ' not "%s" in "%s"' %
                                      (name, self.__varName, varName, msg))
            return False

        typeStr = self._getValueType()
        if varType != typeStr:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:TYPE: %s (%s)' % \
                        (name, typeStr, self._getValue()), file=sys.stderr)
                checker.set_error('Expected %s I3Live type "%s", not "%s"'
                                  ' in %s' % (name, typeStr, varType, msg))
            return False

        # ignore priority
        # ignore time

        if not self._checkText(checker, msgText, debug, set_error):
            return False

        return True


class ExactChecker(BaseChecker):
    def __init__(self, text):
        self.__text = text
        super(ExactChecker, self).__init__()

    def __str__(self):
        return 'EXACT:%s' % self.__text

    def check(self, checker, msg, debug, set_error=True):
        if msg != self.__text:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:XACT: %s' % (name, self.__text), file=sys.stderr)
                checker.set_error('Expected %s exact log message "%s",'
                                  ' not "%s"' % (name, self.__text, msg))
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

        if isinstance(val, int):
            vstr = str(val)
            if vstr.endswith("L"):
                return vstr[:-1]
            return vstr

        if isinstance(val, bool):
            return self.__value and "true" or "false"

        return str(val)

    def _checkText(self, checker, msg, debug, set_error):
        if self.__type is None or self.__type != "json":
            valStr = str(self.__value)
        elif isinstance(self.__value, (list, tuple)):
            valStr = "["
            for v in self.__value:
                if len(valStr) > 1:
                    valStr += ", "
                valStr += self.__fixValue(v)
            valStr += "]"
        elif isinstance(self.__value, dict):
            valStr = "{"
            for k in list(self.__value.keys()):
                if len(valStr) > 1:
                    valStr += ", "
                valStr += self.__fixValue(k)
                valStr += ": "
                valStr += self.__fixValue(self.__value[k])
            valStr += "}"
        else:
            valStr = str(self.__value)

        if msg != valStr:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:LIVE: %s' % (name, valStr), file=sys.stderr)
                checker.set_error('Expected %s live log message '
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

    def _checkText(self, checker, msg, debug, set_error):
        m = self.__regexp.search(msg)
        if m is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:RLIV: %s' % \
                        (name, self.__regexp.pattern), file=sys.stderr)
                checker.set_error('Expected %s I3Live regexp message "%s",'
                                  ' not "%s"' %
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

    def check(self, checker, msg, debug, set_error=True):
        m = self.__regexp.match(msg)
        if m is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:REXP: %s' % \
                        (name, self.__regexp.pattern), file=sys.stderr)
                checker.set_error('Expected %s regexp log message of "%s",'
                                  ' not "%s"' %
                                  (name, self.__regexp.pattern, msg))
            return False

        return True


class RegexpTextChecker(BaseChecker):
    def __init__(self, pattern):
        self.__regexp = re.compile(pattern)
        super(RegexpTextChecker, self).__init__()

    def __str__(self):
        return 'RETEXT:%s' % self.__regexp.pattern

    def check(self, checker, msg, debug, set_error=True):
        m = BaseChecker.PAT_DAQLOG.match(msg)
        if m is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:RFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern), file=sys.stderr)
                checker.set_error('Bad format for %s log message "%s"' %
                                  (name, msg))
            return False

        m = self.__regexp.search(m.group(3))
        if m is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:RTXT: %s' % \
                        (name, self.__regexp.pattern), file=sys.stderr)
                checker.set_error('Expected %s regexp text log message,'
                                  ' of "%s" not "%s"' %
                                  (name, self.__regexp.pattern, msg))
            return False

        return True


class TextChecker(BaseChecker):
    def __init__(self, text):
        self.__text = text
        super(TextChecker, self).__init__()

    def __str__(self):
        return 'TEXT:%s' % self.__text

    def check(self, checker, msg, debug, set_error=True):
        m = BaseChecker.PAT_DAQLOG.match(msg)
        if m is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:TFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern), file=sys.stderr)
                checker.set_error('Bad format for %s log message "%s"' %
                                  (name, msg))
            return False

        if m.group(3).find(self.__text) == -1:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:TEXT: %s' % (name, self.__text),
                          file=sys.stderr)
                checker.set_error('Expected %s partial log message of "%s",'
                                  ' not "%s"' %
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
            print("Check(%s): %s" % (self, msg), file=sys.stderr)

        if len(self.__expMsgs) == 0:
            if LogChecker.DEBUG:
                print('*** %s:UNEX(%s)' % (self, msg), file=sys.stderr)
            self.set_error('Unexpected %s log message: %s' % (self, msg))
            return False

        found = None
        for i in range(len(self.__expMsgs)):
            if i >= self.__depth:
                break
            if self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, False):
                found = i
                break

        if found is None:
            print('--- Missing %s log msg ---' % (self, ), file=sys.stderr)
            print(msg, file=sys.stderr)
            if len(self.__expMsgs) > 0:
                print('--- Expected %s messages ---' % (self, ),
                      file=sys.stderr)
                for i in range(len(self.__expMsgs)):
                    if i >= self.__depth:
                        break
                    print("--- %s" % str(self.__expMsgs[i]), file=sys.stderr)
                    self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, True)
            print('----------------------------', file=sys.stderr)
            self.set_error('Missing %s log message: %s' % (self, msg))
            return False

        del self.__expMsgs[found]

        return True

    def addExpectedExact(self, msg):
        if LogChecker.DEBUG:
            print("AddExact(%s): %s" % (self, msg), file=sys.stderr)
        self.__expMsgs.append(ExactChecker(msg))

    def addExpectedLiveMoni(self, varName, value, valType=None):
        if LogChecker.DEBUG:
            print("AddLiveMoni(%s): %s=%s%s" % \
                (self, varName, value,
                 valType is None and "" or "(%s)" % (valType, )), file=sys.stderr)
        self.__expMsgs.append(LiveChecker(varName, value, valType))

    def addExpectedRegexp(self, msg):
        if LogChecker.DEBUG:
            print("AddRegexp(%s): %s" % (self, msg), file=sys.stderr)
        self.__expMsgs.append(RegexpChecker(msg))

    def addExpectedText(self, msg):
        if self.__isLive:
            if LogChecker.DEBUG:
                print("AddLive(%s): %s" % (self, msg), file=sys.stderr)
            self.__expMsgs.append(LiveChecker('log', str(msg)))
        else:
            if LogChecker.DEBUG:
                print("AddText(%s): %s" % (self, msg), file=sys.stderr)
            self.__expMsgs.append(TextChecker(msg))

    def addExpectedTextRegexp(self, msg):
        if self.__isLive:
            if LogChecker.DEBUG:
                print("AddLiveRE(%s): %s" % (self, msg), file=sys.stderr)
            self.__expMsgs.append(LiveRegexpChecker('log', msg))
        else:
            if LogChecker.DEBUG:
                print("AddTextRE(%s): %s" % (self, msg), file=sys.stderr)
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

    def set_error(self, msg):
        raise NotImplementedError()

    @staticmethod
    def setVerbose(val=True):
        # NOTE: need to hard-code LogChecker.DEBUG to make sure the correct
        # class-level DEBUG attribute is set
        LogChecker.DEBUG = val


class MockClusterWriter(object):
    """Base class for MockClusterConfigFile classes"""
    @classmethod
    def __append_attr(cls, oldStr, attrName, newStr):
        if newStr is not None:
            if oldStr is None:
                oldStr = ""
            else:
                oldStr += " "
            oldStr += "%s=\"%s\"" % (attrName, newStr)
        return oldStr

    @classmethod
    def writeHSXML(cls, file_handle, indent, path, interval, max_files):

        jStr = "hitspool"
        jStr = cls.__append_attr(jStr, 'directory', path)
        jStr = cls.__append_attr(jStr, 'interval', interval)
        jStr = cls.__append_attr(jStr, 'maxfiles', max_files)
        print("%s<%s/>" % (indent, jStr), file=file_handle)

    @classmethod
    def writeJVMXML(cls, file_handle, indent, path, is_server, heap_init,
                    heap_max, args, extra_args):

        if path is not None or is_server or heap_init is not None or \
           heap_max is not None or args is not None or extra_args is not None:
            jStr = "jvm"
            jStr = cls.__append_attr(jStr, 'path', path)
            if is_server:
                jStr = cls.__append_attr(jStr, 'server', is_server)
            jStr = cls.__append_attr(jStr, 'heapInit', heap_init)
            jStr = cls.__append_attr(jStr, 'heapMax', heap_max)
            jStr = cls.__append_attr(jStr, 'args', args)
            jStr = cls.__append_attr(jStr, 'extraArgs', extra_args)
            print("%s<%s/>" % (indent, jStr), file=file_handle)

    @classmethod
    def writeLine(cls, file_handle, indent, name, value):
        if value is None or value == "":
            print("%s<%s/>" % (indent, name), file=file_handle)
        else:
            print("%s<%s>%s</%s>" % (indent, name, value, name),
                  file=file_handle)


class MockCluCfgCtlSrvr(object):
    """Used by MockClusterConfigFile for <controlServer>>"""
    def __init__(self):
        pass

    @property
    def hitspool_directory(self):
        return None

    @property
    def hitspool_interval(self):
        return None

    @property
    def hitspool_max_files(self):
        return None

    @property
    def is_control_server(self):
        return True

    @property
    def is_sim_hub(self):
        return False

    @property
    def jvm_args(self):
        return None

    @property
    def jvm_extra_args(self):
        return None

    @property
    def jvm_heap_init(self):
        return None

    @property
    def jvm_heap_max(self):
        return None

    @property
    def jvm_path(self):
        return None

    @property
    def jvm_server(self):
        return False

    @property
    def log_level(self):
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

    def write(self, file_handle, indent):
        print(indent + "<controlServer/>", file=file_handle)


class MockCluCfgFileComp(MockClusterWriter):
    """Used by MockClusterConfigFile for <component>"""
    def __init__(self, name, num=0, required=False, hitspool_directory=None,
                 hitspool_interval=None, hitspool_max_files=None, jvm_path=None,
                 jvm_server=None, jvm_heap_init=None, jvm_heap_max=None,
                 jvm_args=None, jvm_extra_args=None, log_level=None):
        self.__name = name
        self.__num = num
        self.__required = required

        self.__hitspoolDir = hitspool_directory
        self.__hitspool_interval = hitspool_interval
        self.__hitspool_max_files = hitspool_max_files

        self.__jvm_path = jvm_path
        self.__jvm_server = jvm_server is True
        self.__jvm_heap_init = jvm_heap_init
        self.__jvm_heap_max = jvm_heap_max
        self.__jvm_args = jvm_args
        self.__jvm_extra_args = jvm_extra_args

        self.__log_level = log_level

    def __str__(self):
        return "%s#%s" % (self.__name, self.__num)

    @property
    def hitspool_directory(self):
        return self.__hitspoolDir

    @property
    def hitspool_interval(self):
        return self.__hitspool_interval

    @property
    def hitspool_max_files(self):
        return self.__hitspool_max_files

    @property
    def is_control_server(self):
        return False

    @property
    def is_sim_hub(self):
        return False

    @property
    def jvm_args(self):
        return self.__jvm_args

    @property
    def jvm_extra_args(self):
        return self.__jvm_extra_args

    @property
    def jvm_heap_init(self):
        return self.__jvm_heap_init

    @property
    def jvm_heap_max(self):
        return self.__jvm_heap_max

    @property
    def jvm_path(self):
        return self.__jvm_path

    @property
    def jvm_server(self):
        return self.__jvm_server

    @property
    def log_level(self):
        if self.__log_level is not None:
            return self.__log_level

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
        self.__hitspool_interval = value

    def setHitspoolMaxFiles(self, value):
        self.__hitspool_max_files = value

    def set_jvm_args(self, value):
        self.__jvm_args = value

    def set_jvm_extra_args(self, value):
        self.__jvm_extra_args = value

    def set_jvm_heap_init(self, value):
        self.__jvm_heap_init = value

    def set_jvm_heap_max(self, value):
        self.__jvm_heap_max = value

    def set_jvm_server(self, value):
        self.__jvm_server = value

    def set_jvm_path(self, value):
        self.__jvm_path = value

    def set_log_level(self, value):
        self.__log_level = value

    def write(self, file_handle, indent):
        if self.__num == 0:
            numstr = ""
        else:
            numstr = " id=\"%d\"" % self.__num

        if not self.__required:
            reqstr = ""
        else:
            reqstr = " required=\"true\""

        hasHSFields = self.__hitspoolDir is not None or \
                      self.__hitspool_interval is not None or \
                      self.__hitspool_max_files is not None
        hasJVMFields = self.__jvm_path is not None or \
                       self.__jvm_args is not None or \
                       self.__jvm_extra_args is not None or \
                       self.__jvm_heap_init is not None or \
                       self.__jvm_heap_max is not None or \
                       self.__jvm_server is not None
        multiline = hasHSFields or hasJVMFields or self.__log_level is not None

        if multiline:
            endstr = ""
        else:
            endstr = "/"

        print("%s<component name=\"%s\"%s%s%s>" % \
            (indent, self.__name, numstr, reqstr, endstr), file=file_handle)

        if multiline:
            indent2 = indent + "  "

            if hasHSFields:
                self.writeHSXML(file_handle, indent2, self.__hitspoolDir,
                                self.__hitspool_interval,
                                self.__hitspool_max_files)
            if hasJVMFields:
                self.writeJVMXML(file_handle, indent2, self.__jvm_path,
                                 self.__jvm_server, self.__jvm_heap_init,
                                 self.__jvm_heap_max, self.__jvm_args,
                                 self.__jvm_extra_args)

            if self.__log_level is not None:
                self.writeLine(file_handle, indent2, "logLevel",
                               self.__log_level)

            print("%s</component>" % indent, file=file_handle)


class MockCluCfgFileCtlSrvr(object):
    """Used by MockClusterConfigFile for <controlServer/>"""
    def __init__(self):
        pass

    @property
    def hitspool_directory(self):
        return None

    @property
    def hitspool_interval(self):
        return None

    @property
    def hitspool_max_files(self):
        return None

    @property
    def is_control_server(self):
        return True

    @property
    def is_sim_hub(self):
        return False

    @property
    def jvm_args(self):
        return None

    @property
    def jvm_extra_args(self):
        return None

    @property
    def jvm_heap_init(self):
        return None

    @property
    def jvm_heap_max(self):
        return None

    @property
    def jvm_path(self):
        return None

    @property
    def jvm_server(self):
        return False

    @property
    def log_level(self):
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

    def write(self, file_handle, indent):
        print(indent + "<controlServer/>", file=file_handle)


class MockCluCfgFileHost(object):
    """Used by MockClusterConfigFile for <host/>"""
    def __init__(self, name, parent):
        self.__name = name
        self.__parent = parent
        self.__comps = None

    def __add_comp(self, comp):
        if self.__comps is None:
            self.__comps = []
        self.__comps.append(comp)
        return comp

    def add_component(self, name, num=0, required=False):
        c = MockCluCfgFileComp(name, num=num, required=required)

        return self.__add_comp(c)

    def addControlServer(self):
        return self.__add_comp(MockCluCfgCtlSrvr())

    def addSimHubs(self, number, priority, if_unused=False):
        return self.__add_comp(MockCluCfgFileSimHubs(number, priority,
                                                    if_unused=if_unused))

    @property
    def components(self):
        return self.__comps[:]

    @property
    def name(self):
        return self.__name

    def write(self, file_handle, indent, split_hosts=False):
        printed_host = False
        indent2 = indent + "  "
        if self.__comps:
            for c in self.__comps:
                if split_hosts or not printed_host:
                    print("%s<host name=\"%s\">" % (indent, self.__name),
                          file=file_handle)
                    printed_host = True

                c.write(file_handle, indent2)

                if split_hosts:
                    print("%s</host>" % indent, file=file_handle)

            if printed_host and not split_hosts:
                print("%s</host>" % indent, file=file_handle)


class MockCluCfgFileSimHubs(MockClusterWriter):
    """Used by MockClusterConfigFile for <simulatedHub/>"""
    def __init__(self, number, priority=1, if_unused=False):
        self.__number = number
        self.__priority = priority
        self.__if_unused = if_unused

    @property
    def hitspool_directory(self):
        return None

    @property
    def hitspool_interval(self):
        return None

    @property
    def hitspool_max_files(self):
        return None

    @property
    def is_control_server(self):
        return False

    @property
    def is_sim_hub(self):
        return True

    @property
    def jvm_args(self):
        return None

    @property
    def jvm_extra_args(self):
        return None

    @property
    def jvm_heap_init(self):
        return None

    @property
    def jvm_heap_max(self):
        return None

    @property
    def jvm_path(self):
        return None

    @property
    def jvm_server(self):
        return False

    @property
    def log_level(self):
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

    def write(self, file_handle, indent):
        if self.__if_unused:
            iustr = " ifUnused=\"true\""
        else:
            iustr = ""

        print("%s<simulatedHub number=\"%d\" priority=\"%d\"%s/>" % \
            (indent, self.__number, self.__priority, iustr), file=file_handle)


class MockClusterComponent(Component):
    def __init__(self, fullname, jvm_path, jvm_args, host):
        sep = fullname.rfind("#")
        if sep < 0:
            sep = fullname.rfind("-")

        if sep < 0:
            name = fullname
            num = 0
        else:
            name = fullname[:sep]
            num = int(fullname[sep + 1:])

        self.__jvm_path = jvm_path
        self.__jvm_args = jvm_args
        self.__host = host

        super(MockClusterComponent, self).__init__(name, num, None)

    def __str__(self):
        return "%s(%s)" % (self.fullname, self.__host)

    def dump(self, file_handle, indent):
        print("%s<location name=\"%s\" host=\"%s\">" % \
            (indent, self.__host, self.__host), file=file_handle)
        print("%s    <module name=\"%s\" id=\"%02d\"/?>" % \
            (indent, self.name, self.id), file=file_handle)
        print("%s</location>" % indent, file=file_handle)

    @property
    def host(self):
        return self.__host

    @property
    def is_localhost(self):
        return True

    def jvm_path(self):
        return self.__jvm_path

    def jvm_args(self):
        return self.__jvm_args


class MockClusterConfig(object):
    """Simulate a cluster config object"""
    def __init__(self, name, descName="test-cluster"):
        self.__config_name = name
        self.__nodes = {}
        self.__descName = descName

    def __repr__(self):
        return "MockClusterConfig(%s)" % self.__config_name

    def add_component(self, comp, jvm_path, jvm_args, host):
        if host not in self.__nodes:
            self.__nodes[host] = MockClusterNode(host)
        self.__nodes[host].add(comp, jvm_path, jvm_args, host)

    @property
    def config_name(self):
        return self.__config_name

    @property
    def description(self):
        return self.__descName

    def extract_components(self, masterList):
        node_comps = list(self.__nodes.values())
        return RunCluster.extract_components_from_nodes(node_comps,
                                                        masterList)

    @property
    def name(self):
        return self.__config_name

    def nodes(self):
        return list(self.__nodes.values())


class MockClusterConfigFile(MockClusterWriter):
    """Write a cluster config file"""
    def __init__(self, config_dir, name):
        self.__config_dir = config_dir
        self.__name = name

        self.__data_dir = None
        self.__log_dir = None
        self.__spade_dir = None

        self.__default_hs_dir = None
        self.__default_hs_interval = None
        self.__default_hs_max_files = None

        self.__default_jvm_args = None
        self.__default_jvm_extra_args = None
        self.__default_jvm_heap_init = None
        self.__default_jvm_heap_max = None
        self.__default_jvm_path = None
        self.__default_jvm_server = None

        self.__default_alert_email = None
        self.__default_ntp_host = None

        self.__default_log_level = None

        self.__default_comps = None

        self.__hosts = {}

    def addDefaultComponent(self, comp):
        if not self.__default_comps:
            self.__default_comps = []

        self.__default_comps.append(comp)

    def addHost(self, name):
        if name in self.__hosts:
            h = self.__hosts[name]
        else:
            h = MockCluCfgFileHost(name, self)
            self.__hosts[name] = h
        return h

    def create(self, split_hosts=False):
        path = os.path.join(self.__config_dir, "%s-cluster.cfg" % self.__name)

        if not os.path.exists(self.__config_dir):
            os.makedirs(self.__config_dir)

        with open(path, 'w') as file_handle:
            print("<cluster name=\"%s\">" % self.__name, file=file_handle)

            indent = "  "

            if self.__data_dir is not None:
                self.writeLine(file_handle, indent, "daqDataDir",
                               self.__data_dir)
            if self.__log_dir is not None:
                self.writeLine(file_handle, indent, "daqLogDir",
                               self.__log_dir)
            if self.__spade_dir is not None:
                self.writeLine(file_handle, indent, "logDirForSpade",
                               self.__spade_dir)

            hasHSXML = self.__default_hs_dir is not None or \
                       self.__default_hs_interval is not None or \
                       self.__default_hs_max_files is not None

            hasJVMXML = self.__default_jvm_args is not None or \
                        self.__default_jvm_extra_args is not None or \
                        self.__default_jvm_heap_init is not None or \
                        self.__default_jvm_heap_max is not None or \
                        self.__default_jvm_path is not None or \
                        self.__default_jvm_server is not None

            hasHubXML = self.__default_alert_email is not None or \
                        self.__default_ntp_host is not None

            if hasHSXML or hasJVMXML or hasHubXML or \
               self.__default_log_level is not None or \
               self.__default_comps is not None:
                print(indent + "<default>", file=file_handle)

                indent2 = indent + "  "

                if hasHSXML:
                    self.writeHSXML(file_handle, indent2,
                                    self.__default_hs_dir,
                                    self.__default_hs_interval,
                                    self.__default_hs_max_files)

                if hasJVMXML:
                    self.writeJVMXML(file_handle, indent2,
                                     self.__default_jvm_path,
                                     self.__default_jvm_server,
                                     self.__default_jvm_heap_init,
                                     self.__default_jvm_heap_max,
                                     self.__default_jvm_args,
                                     self.__default_jvm_extra_args)

                if hasHubXML:
                    #self.writeHubXML(file_handle, indent2,
                    #                 self.__default_alert_email,
                    #                 self.__default_ntp_host)
                    raise NotImplementedError("writeHubXML")

                if self.__default_log_level is not None:
                    self.writeLine(file_handle, indent2, "logLevel",
                                   self.__default_log_level)

                if self.__default_comps:
                    for c in self.__default_comps:
                        c.write(file_handle, indent2)

                print(indent + "</default>", file=file_handle)

            for h in list(self.__hosts.values()):
                h.write(file_handle, indent, split_hosts=split_hosts)

            print("</cluster>", file=file_handle)

    @property
    def data_dir(self):
        if self.__data_dir is None:
            return ClusterDescription.DEFAULT_DATA_DIR

        return self.__data_dir

    def default_alert_email(self):
        return self.__default_alert_email

    def default_hs_directory(self):
        return self.__default_hs_dir

    def default_hs_interval(self):
        return self.__default_hs_interval

    def default_hs_max_files(self):
        return self.__default_hs_max_files

    def default_jvm_args(self):
        return self.__default_jvm_args

    def default_jvm_extra_args(self):
        return self.__default_jvm_extra_args

    def default_jvm_heap_init(self):
        return self.__default_jvm_heap_init

    def default_jvm_heap_max(self):
        return self.__default_jvm_heap_max

    def default_jvm_path(self):
        return self.__default_jvm_path

    def default_jvm_server(self):
        return self.__default_jvm_server

    @property
    def default_log_level(self):
        if self.__default_log_level is None:
            return ClusterDescription.DEFAULT_LOG_LEVEL

        return self.__default_log_level

    def default_ntp_host(self):
        return self.__default_ntp_host

    @property
    def hosts(self):
        return self.__hosts.copy()

    @property
    def log_dir(self):
        if self.__log_dir is None:
            return ClusterDescription.DEFAULT_LOG_DIR

        return self.__log_dir

    @property
    def name(self):
        return self.__name

    def setDataDir(self, value):
        self.__data_dir = value

    def setDefault_alert_email(self, value):
        self.__default_alert_email = value

    def set_default_hs_directory(self, value):
        self.__default_hs_dir = value

    def set_default_hs_interval(self, value):
        self.__default_hs_interval = value

    def set_default_hs_max_files(self, value):
        self.__default_hs_max_files = value

    def set_default_jvm_args(self, value):
        self.__default_jvm_args = value

    def set_default_jvm_extra_args(self, value):
        self.__default_jvm_extra_args = value

    def set_default_jvm_heap_init(self, value):
        self.__default_jvm_heap_init = value

    def set_default_jvm_heap_max(self, value):
        self.__default_jvm_heap_max = value

    def set_default_jvm_path(self, value):
        self.__default_jvm_path = value

    def set_default_jvm_server(self, value):
        self.__default_jvm_server = value

    def setDefaultLogLevel(self, value):
        self.__default_log_level = value

    def setDefaultNTPHost(self, value):
        self.__default_ntp_host = value

    def setLogDir(self, value):
        self.__log_dir = value

    def setSpadeDir(self, value):
        self.__spade_dir = value

    @property
    def spade_dir(self):
        return self.__spade_dir


class MockClusterNode(object):
    def __init__(self, host):
        self.__host = host
        self.__comps = []

    def add(self, comp, jvm_path, jvm_args, host):
        self.__comps.append(MockClusterComponent(comp, jvm_path, jvm_args,
                                                 host))

    def components(self):
        return self.__comps[:]


class MockCnCLogger(CnCLogger):
    def __init__(self, name, appender=None, quiet=False, extra_loud=False):
        self.__appender = appender

        super(MockCnCLogger, self).__init__(name, appender=appender,
                                            quiet=quiet, extra_loud=extra_loud)


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

    def __repr__(self):
        return str(self)

    def __str__(self):
        if self.__port is not None:
            return '%d=>%s' % (self.__port, self.__name)
        return '=>' + self.__name

    @property
    def is_input(self):
        return self.__connCh == self.INPUT or self.__connCh == self.OPT_INPUT

    @property
    def is_optional(self):
        return self.__connCh == self.OPT_INPUT or \
               self.__connCh == self.OPT_OUTPUT

    @property
    def name(self):
        return self.__name

    @property
    def port(self):
        return self.__port


class MockDeployComponent(Component):
    def __init__(self, name, id, log_level, hs_dir, hs_interval, hs_max_files,
                 jvm_path, jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                 jvm_extra_args, alert_email, ntp_host, numReplayFiles=None,
                 host=None):
        self.__hs_dir = hs_dir
        self.__hs_interval = hs_interval
        self.__hs_max_files = hs_max_files
        self.__jvm_path = jvm_path
        self.__jvm_server = jvm_server is True
        self.__jvm_heap_init = jvm_heap_init
        self.__jvm_heap_max = jvm_heap_max
        self.__jvm_args = jvm_args
        self.__jvm_extra_args = jvm_extra_args
        self.__alert_email = alert_email
        self.__ntp_host = ntp_host
        self.__numReplayFiles = numReplayFiles
        self.__host = host

        super(MockDeployComponent, self).__init__(name, id, log_level)

    @property
    def alert_email(self):
        return self.__alert_email

    @property
    def has_hitspool_options(self):
        return self.__hs_dir is not None or self.__hs_interval is not None or \
            self.__hs_max_files is not None

    @property
    def has_replay_options(self):
        return self.__numReplayFiles is not None

    @property
    def hitspool_directory(self):
        return self.__hs_dir

    @property
    def hitspool_interval(self):
        return self.__hs_interval

    @property
    def hitspool_max_files(self):
        return self.__hs_max_files

    @property
    def is_control_server(self):
        return False

    @property
    def host(self):
        return self.__host

    @property
    def is_localhost(self):
        return self.__host is not None and self.__host == "localhost"

    @property
    def jvm_args(self):
        return self.__jvm_args

    @property
    def jvm_extra_args(self):
        return self.__jvm_extra_args

    @property
    def jvm_heap_init(self):
        return self.__jvm_heap_init

    @property
    def jvm_heap_max(self):
        return self.__jvm_heap_max

    @property
    def jvm_path(self):
        return self.__jvm_path

    @property
    def jvm_server(self):
        return self.__jvm_server

    @property
    def ntp_host(self):
        return self.__ntp_host

    @property
    def num_replay_files_to_skip(self):
        return self.__numReplayFiles


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
        if not beanName in self.__beanData:
            raise Exception("Unknown bean %s for %s (valid beans: %s)" %
                            (beanName, self, list(self.__beanData.keys())))
        if not fieldName in self.__beanData[beanName]:
            raise Exception("No %s data for bean %s field %s"
                            " (valid fields: %s)" %
                            (self, beanName, fieldName,
                             list(self.__beanData[beanName].keys())))

        return self.__beanData[beanName][fieldName]

    def get_attributes(self, beanName, fieldList):
        rtnMap = {}
        for f in fieldList:
            rtnMap[f] = self.get(beanName, f)

            if isinstance(rtnMap[f], Exception):
                raise rtnMap[f]
        return rtnMap

    def get_bean_fields(self, beanName):
        return list(self.__beanData[beanName].keys())

    def get_bean_names(self):
        return list(self.__beanData.keys())

    def get_dictionary(self):
        return copy.deepcopy(self.__beanData)

    def reload(self):
        pass

    def setData(self, beanName, fieldName, value):
        if not self.check(beanName, fieldName):
            raise Exception("%s bean %s field %s has not been added" %
                            (self, beanName, fieldName))

        self.__beanData[beanName][fieldName] = value


class MockComponent(Comparable):
    def __init__(self, name, num=0, host='localhost'):
        self.__name = name
        self.__num = num
        self.__host = host

        self.__connectors = []
        self.__cmd_order = None

        self.__run_number = None

        self.__isBldr = name.endswith("Builder") or name.endswith("Builders")
        self.__isSrc = name.endswith("Hub") or name == "amandaTrigger"
        self.__connected = False
        self.__configured = False
        self.__configWait = 0
        self.__monitor_count = 0
        self.__monitor_state = None
        self.__isBadHub = False
        self.__hangType = 0
        self.__stopping = 0
        self.__updated_rates = False
        self.__deadCount = 0
        self.__stopFail = False
        self.__replayHub = False
        self.__first_good_time = None
        self.__last_good_time = None
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

    def add_dead_count(self):
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

    def commit_subrun(self, id, start_time):
        pass

    @property
    def compare_tuple(self):
        return (self.__name, self.__num)

    def configure(self, config_name=None):
        if not self.__connected:
            self.__connected = True
        self.__configured = True
        return 'OK'

    def connect(self, conn=None):
        self.__connected = True
        return 'OK'

    def connectors(self):
        return self.__connectors[:]

    def _create_mbean_client(self):
        return MockMBeanClient(self.fullname)

    def create_mbean_client(self):
        if self.__mbeanClient is None:
            self.__mbeanClient = self._create_mbean_client()
        return self.__mbeanClient

    def forced_stop(self):
        if self.__stopFail:
            pass
        elif self.__stopping == 1:
            if self.__hangType != 2:
                self.__run_number = None
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

    def get_run_data(self, run_num):
        if self.__mbeanClient is None:
            self.__mbeanClient = self.create_mbean_client()

        if self.__num == 0:
            if self.__name.startswith("event"):
                evtData = self.__mbeanClient.get("backEnd", "EventData")
                num_evts = int(evtData[0])
                last_time = int(evtData[1])

                val = self.__mbeanClient.get("backEnd", "FirstEventTime")
                first_time = int(val)

                good = self.__mbeanClient.get("backEnd", "GoodTimes")
                firstGood = int(good[0])
                lastGood = int(good[1])
                return (num_evts, first_time, last_time, firstGood, lastGood)
            elif self.__name.startswith("secondary"):
                for bldr in ("tcal", "sn", "moni"):
                    val = self.__mbeanClient.get(bldr + "Builder",
                                                 "NumDispatchedData")
                    if bldr == "tcal":
                        num_tcal = int(val)
                    elif bldr == "sn":
                        num_sn = int(val)
                    elif bldr == "moni":
                        num_moni = int(val)

                return (num_tcal, num_sn, num_moni)

        return (None, None, None)

    @property
    def host(self):
        return self.__host

    @property
    def is_dying(self):
        return False

    @property
    def is_builder(self):
        return self.__isBldr

    def is_component(self, name, num=-1):
        return self.__name == name

    @property
    def isConfigured(self):
        return self.__configured

    @property
    def isHanging(self):
        return self.__hangType != 0

    @property
    def is_replay_hub(self):
        return self.__replayHub

    @property
    def is_source(self):
        return self.__isSrc

    def list_connector_states(self):
        return ""

    def log_to(self, log_host, log_port, live_host, live_port):
        pass

    @property
    def mbean(self):
        if self.__mbeanClient is None:
            self.__mbeanClient = self.create_mbean_client()

        return self.__mbeanClient

    @property
    def monitor_count(self):
        return self.__monitor_count

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def order(self):
        return self.__cmd_order

    @order.setter
    def order(self, num):
        self.__cmd_order = num

    def prepare_subrun(self, id):
        pass

    def reset(self):
        self.__connected = False
        self.__configured = False
        self.__updated_rates = False
        self.__run_number = None

    def reset_logging(self):
        pass

    @property
    def run_number(self):
        return self.__run_number

    def setBadHub(self):
        self.__isBadHub = True

    def setConfigureWait(self, waitNum):
        self.__configWait = waitNum

    def setStopFail(self):
        self.__stopFail = True

    def set_first_good_time(self, time):
        self.__first_good_time = time

    def set_hang_type(self, hangType):
        self.__hangType = hangType

    def set_last_good_time(self, time):
        self.__last_good_time = time

    def setMonitorState(self, new_state):
        self.__monitor_state = new_state

    def start_run(self, run_num):
        if not self.__configured:
            raise Exception(self.__name + ' has not been configured')

        self.__run_number = run_num

    def start_subrun(self, data):
        if self.__isBadHub:
            return None
        return 100

    @property
    def state(self):
        if self.__monitor_state is not None:
            self.__monitor_count += 1
            return self.__monitor_state

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
        if not self.__run_number:
            return 'ready'

        return 'running'

    def stop_run(self):
        if self.__run_number is None:
            raise Exception(self.__name + ' is not running')

        if self.__hangType > 0 or self.__stopFail:
            self.__stopping = 1
        else:
            self.__run_number = None

    def update_rates(self):
        self.__updated_rates = True

    def wasUpdated(self):
        return self.__updated_rates


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
            with open(path, "w") as file_handle:
                print("<domGeometry>", file=file_handle)
                for hub in hub_dom_dict:
                    print("  <string>", file=file_handle)
                    print("    <number>%d</number>" % hub, file=file_handle)
                    for dom in hub_dom_dict[hub]:
                        print("    <dom>", file=file_handle)
                        print("      <mainBoardId>%012x</mainBoardId>" %
                              dom.mbid, file=file_handle)
                        print("      <position>%d</position>" % dom.pos,
                              file=file_handle)
                        print("      <name>%s</name>" % dom.name,
                              file=file_handle)
                        print("      <productionId>%s</productionId>" % \
                            dom.prod_id, file=file_handle)
                        print("    </dom>", file=file_handle)
                    print("  </string>", file=file_handle)

                print("</domGeometry>", file=file_handle)


class MockDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbean_port, connectors,
                 appender, outLinks=None, extra_loud=False):

        self.__appender = appender
        self.__extra_loud = extra_loud

        self.outLinks = outLinks
        self.__state = 'idle'

        super(MockDAQClient, self).__init__(name, num, host, port, mbean_port,
                                            connectors, True)

    def __str__(self):
        tmpStr = super(MockDAQClient, self).__str__()
        return 'Mock' + tmpStr

    def close_log(self):
        pass

    def configure(self, cfgName=None):
        self.__state = 'ready'
        return super(MockDAQClient, self).configure(cfgName)

    def connect(self, links=None):
        self.__state = 'connected'
        return super(MockDAQClient, self).connect(links)

    def create_client(self, host, port):
        return MockRPCClient(self.name, self.num, self.outLinks)

    def create_logger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet, extra_loud=self.__extra_loud)

    def create_mbean_client(self, host, port):
        return MockRPCClient(self.name, self.num, self.outLinks)

    def reset(self):
        self.__state = 'idle'
        return super(MockDAQClient, self).reset()

    def start_run(self, run_num):
        self.__state = 'running'
        return super(MockDAQClient, self).start_run(run_num)

    @property
    def state(self):
        return self.__state


class MockIntervalTimer(object):
    def __init__(self, name, wait_secs=1.0):
        self.__name = name
        self.__is_time = False
        self.__got_time = False
        self.__wait_secs = wait_secs

    def __str__(self):
        return "Timer#%s%s" % \
            (self.__name, self.__is_time and "!is_time!" or "")

    def is_time(self, now=None):
        self.__got_time = True
        return self.__is_time

    @property
    def name(self):
        return self.__name

    def reset(self):
        self.__is_time = False
        self.__got_time = False

    def time_left(self):
        if self.__is_time:
            return 0.0
        return self.__wait_secs

    def trigger(self):
        self.__is_time = True
        self.__got_time = False

    def wait_secs(self):
        return self.__wait_secs


class MockLogger(LogChecker):
    def __init__(self, name, depth=None):
        super(MockLogger, self).__init__('LOG', name, depth=depth)

        self.__err = None

    def _checkError(self):
        if self.__err is not None:
            raise Exception(self.__err)

    def add_appender(self, app):
        print("Not adding appender %s to MockLogger" % app, file=sys.stderr)

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
    def is_debug_enabled(self):
        return True

    @property
    def is_error_enabled(self):
        return True

    @property
    def is_fatal_enabled(self):
        return True

    @property
    def is_info_enabled(self):
        return True

    @property
    def is_trace_enabled(self):
        return True

    @property
    def is_warn_enabled(self):
        return True

    @property
    def live_port(self):
        return None

    @property
    def log_port(self):
        return None

    def set_error(self, msg):
        self.__err = msg
        raise Exception(msg)

    def trace(self, m):
        self._checkMsg(m)

    def warn(self, m):
        self._checkMsg(m)

    def write(self, m, time=None, level=None):
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
            print("PSh got: " + cmd, file=sys.stderr)

        found = None
        for i in range(expLen):
            if cmd == self.__exp[i]:
                found = i
                if self.__debug:
                    print("PSh found cmd", file=sys.stderr)
                break
            if self.__debug:
                print("PSh not: " + self.__exp[i], file=sys.stderr)

        if found is None:
            raise Exception("Command not found in expected command list:"
                            " cmd=\"%s\"" % (cmd, ))

        del self.__exp[found]

    def __is_localhost(self, host):
        return host == 'localhost' or host == '127.0.0.1'

    def add(self, cmd):
        self.__checkCmd(cmd)

    def addExpectedJava(self, comp, config_dir, daq_data_dir, log_port,
                        live_port, verbose, event_check, host):

        ipAddr = ip.getLocalIpAddr(host)
        jarPath = os.path.join(MockParallelShell.BINDIR,
                               ComponentManager.get_component_jar(comp.name))

        if verbose:
            redir = ''
        else:
            redir = ' </dev/null >/dev/null 2>&1'

        cmd = comp.jvm_path
        cmd += " -Dicecube.daq.component.configDir='%s'" % config_dir

        if comp.jvm_server is not None and comp.jvm_server:
            cmd += " -server"
        if comp.jvm_heap_init is not None:
            cmd += " -Xms" + comp.jvm_heap_init
        if comp.jvm_heap_max is not None:
            cmd += " -Xmx" + comp.jvm_heap_max
        if comp.jvm_args is not None:
            cmd += " " + comp.jvm_args
        if comp.jvm_extra_args is not None:
            cmd += " " + comp.jvm_extra_args

        if comp.is_real_hub:
            if comp.ntp_host is not None:
                cmd += " -Dicecube.daq.time.monitoring.ntp-host=" + \
                       comp.ntp_host
            if comp.alert_email is not None:
                cmd += " -Dicecube.daq.stringhub.alert-email=" + \
                       comp.alert_email

        if comp.hitspool_directory is not None:
            cmd += " -Dhitspool.directory=\"%s\"" % comp.hitspool_directory
        if comp.hitspool_interval is not None:
            cmd += " -Dhitspool.interval=%.4f" % comp.hitspool_interval
        if comp.hitspool_max_files is not None:
            cmd += " -Dhitspool.maxfiles=%d" % comp.hitspool_max_files

        if comp.is_hub:
            cmd += " -Dicecube.daq.stringhub.componentId=%d" % comp.id
        if event_check and comp.is_builder:
            cmd += ' -Dicecube.daq.eventBuilder.validateEvents'

        cmd += ' -jar %s' % jarPath
        if daq_data_dir is not None:
            cmd += ' -d %s' % daq_data_dir
        cmd += ' -c %s:%d' % (ipAddr, DAQPort.CNCSERVER)

        if log_port is not None:
            cmd += ' -l %s:%d,%s' % (ipAddr, log_port, comp.log_level)
        if live_port is not None:
            cmd += ' -L %s:%d,%s' % (ipAddr, live_port, comp.log_level)
            cmd += ' -M %s:%d' % (ipAddr, MoniPort)
        cmd += ' %s &' % redir

        if not self.__is_localhost(host):
            qCmd = "ssh -n %s 'sh -c \"%s\"%s &'" % (host, cmd, redir)
            cmd = qCmd

        self.__addExpected(cmd)

    def addExpectedJavaKill(self, compName, compId, kill_with_9, verbose, host):
        if kill_with_9:
            nineArg = '-9'
        else:
            nineArg = ''

        user = os.environ['USER']

        if compName.endswith("hub"):
            killPat = "stringhub.componentId=%d " % compId
        else:
            killPat = ComponentManager.get_component_jar(compName)

        if self.__is_localhost(host):
            sshCmd = ''
            pkillOpt = ' -fu %s' % user
        else:
            sshCmd = 'ssh %s ' % host
            pkillOpt = ' -f'

        self.__addExpected('%spkill %s%s \"%s\"' %
                           (sshCmd, nineArg, pkillOpt, killPat))

        if not kill_with_9:
            self.__addExpected('sleep 2; %spkill -9%s \"%s\"' %
                               (sshCmd, pkillOpt, killPat))

    def addExpectedPython(self, doCnC, dash_dir, config_dir, log_dir,
                          daq_data_dir, spade_dir, cluCfgName, cfgName,
                          copy_dir, log_port, live_port, force_restart=True):
        if doCnC:
            cmd = os.path.join(dash_dir, 'CnCServer.py')
            cmd += ' -c %s' % config_dir
            cmd += ' -o %s' % log_dir
            cmd += ' -q %s' % daq_data_dir
            cmd += ' -s %s' % spade_dir
            if cluCfgName is not None:
                if cluCfgName.endswith("-cluster"):
                    cmd += ' -C %s' % cluCfgName
                else:
                    cmd += ' -C %s-cluster' % cluCfgName
            if log_port is not None:
                cmd += ' -l localhost:%d' % log_port
            if live_port is not None:
                cmd += ' -L localhost:%d' % live_port
            if copy_dir is not None:
                cmd += ' -a %s' % copy_dir
            if not force_restart:
                cmd += ' -F'
            cmd += ' -d'

            self.__addExpected(cmd)

    def addExpectedPythonKill(self, doCnC, kill_with_9):
        pass

    def addExpectedRsync(self, dir, subdirs, delete, dry_run, remoteHost,
                         rtnCode, result="",
                         niceAdj=DeployPDAQ.NICE_LEVEL_DEFAULT,
                         express=DeployPDAQ.EXPRESS_DEFAULT):

        if express:
            rCmd = "rsync"
        else:
            rCmd = 'nice rsync --rsync-path "nice -n %d rsync"' % (niceAdj)

        if not delete:
            dOpt = ""
        else:
            dOpt = " --delete"

        if not dry_run:
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
    def __init__(self, name, id, inetAddr, rpc_port, mbean_port):
        self.__name = name
        self.__id = id
        self.__inetAddr = inetAddr
        self.__rpc_port = rpc_port
        self.__mbean_port = mbean_port

    def __str__(self):
        return "%s#%s" % (self.__name, self.__id)

    @property
    def id(self):
        return self.__id

    def inetAddress(self):
        return self.__inetAddr

    @property
    def is_hub(self):
        return self.__name.endswith("Hub")

    @property
    def isReplay(self):
        return self.is_hub and self.__name.lower().find("replay") >= 0

    @property
    def mbean_port(self):
        return self.__mbean_port

    @property
    def name(self):
        return self.__name

    @property
    def rpc_port(self):
        return self.__rpc_port


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

    def printXML(self, file_handle, indent):
        print("%s<domConfig mbid=\"%012x\">" % (indent, self.__mbid),
              file=file_handle)
        print("%s%s<xxx>xxx</xxx>" % (indent, indent), file=file_handle)
        print("%s</domConfig>" % indent, file=file_handle)


class MockAlgorithm(object):
    def __init__(self, srcId, name, trigtype, cfgId):
        self.__srcId = srcId
        self.__name = name
        self.__type = trigtype
        self.__cfgId = cfgId
        self.__paramDict = {}
        self.__readouts = []

    def __printElement(self, file_handle, indent, tag, val):
        print("%s<%s>%s</%s>" % (indent, tag, val, tag), file=file_handle)

    def addParameter(self, name, value):
        self.__paramDict[name] = value

    def addReadout(self, rdoutType, offset, minus, plus):
        self.__readouts.append((rdoutType, offset, minus, plus))

    def printXML(self, file_handle, indent):
        i2 = indent + "    "
        print("%s<triggerConfig>" % indent, file=file_handle)

        self.__printElement(file_handle, i2, "triggerType", self.__type)
        self.__printElement(file_handle, i2, "triggerConfigId", self.__cfgId)
        self.__printElement(file_handle, i2, "sourceId", self.__srcId)
        self.__printElement(file_handle, i2, "triggerName", self.__name)

        for k, v in self.__paramDict:
            print("%s<parameterConfig>", file=file_handle)
            print("%s    <parameterName>%s<parameterName>" % (i2, k),
                  file=file_handle)
            print("%s    <parameterValue>%s<parameterValue>" % (i2, v),
                  file=file_handle)
            print("%s</parameterConfig>", file=file_handle)

        for r in self.__readouts:
            tag = ["readoutType", "timeOffset", "timeMinus", "timePlus"]

            print("%s<readoutConfig>", file=file_handle)
            for i in range(4):
                print("%s    <%s>%d<%s>" % (i2, tag[i], r[i], tag[i]),
                      file=file_handle)
            print("%s</readoutConfig>", file=file_handle)

        print("%s</triggerConfig>" % indent, file=file_handle)


class MockLeapsecondFile(object):
    def __init__(self, config_dir):
        self.__config_dir = config_dir

    def create(self):
        known_times = (
            (35, 3550089600),
            (36, 3644697600),
            (37, 3692217600),
        )

        # set expiration to one day before warnings would appear
        expiration = MJD.now().ntp + \
                     ((RunSet.LEAPSECOND_FILE_EXPIRY + 1) * 24 * 3600)

        nist_path = os.path.join(self.__config_dir, "nist")
        if not os.path.isdir(nist_path):
            os.mkdir(nist_path)

        filepath = os.path.join(nist_path, leapseconds.DEFAULT_FILENAME)
        with open(filepath, "w") as out:
            print("# Mock NIST leapseconds file", file=out)
            print("#@\t%d" % (expiration, ), file=out)
            print("#", file=out)

            for pair in known_times:
                print("%d\t%d" % (pair[1], pair[0]), file=out)


class MockTriggerConfig(object):
    def __init__(self, name):
        self.__name = name
        self.__algorithms = []

    def add(self, srcId, name, trigtype, cfgId):
        algo = MockAlgorithm(srcId, name, trigtype, cfgId)
        self.__algorithms.append(algo)
        return algo

    def create(self, config_dir, debug=False):
        cfg_dir = os.path.join(config_dir, "trigger")
        if not os.path.exists(cfg_dir):
            os.makedirs(cfg_dir)

        path = os.path.join(cfg_dir, self.__name)
        if not path.endswith(".xml"):
            path = path + ".xml"
        with open(path, "w") as file_handle:
            print("<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                  file=file_handle)
            if len(self.__algorithms) == 0:
                print("<activeTriggers/>", file=file_handle)
            else:
                print("<activeTriggers>", file=file_handle)
                needNL = False
                for a in self.__algorithms:
                    if not needNL:
                        needNL = True
                    else:
                        print(file=file_handle)
                    a.printXML(file_handle, "    ")
                print("</activeTriggers>", file=file_handle)

        if debug:
            with open(path, "r") as file_handle:
                print("=== %s ===" % path)
                for line in file_handle:
                    print(line, end=' ')

    @property
    def name(self):
        return self.__name


class MockRunConfigFile(object):
    def __init__(self, config_dir):
        self.__config_dir = config_dir

    def __makeDomConfig(self, cfgName, domList, debug=False):
        cfg_dir = os.path.join(self.__config_dir, "domconfigs")
        if not os.path.exists(cfg_dir):
            os.makedirs(cfg_dir)

        if cfgName.endswith(".xml"):
            fileName = cfgName
        else:
            fileName = cfgName + ".xml"

        path = os.path.join(cfg_dir, fileName)
        with open(path, 'w') as file_handle:
            print("<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                  file=file_handle)
            print("<domConfigList>", file=file_handle)
            if domList is not None:
                for d in domList:
                    d.printXML(file_handle, "  ")
            print("</domConfigList>", file=file_handle)

        if debug:
            with open(path, "r") as file_handle:
                print("=== %s ===" % path)
                for line in file_handle:
                    print(line, end=' ')

    def create(self, compList, hubDomDict, trigCfg=None, debug=False):
        path = tempfile.mktemp(suffix=".xml", dir=self.__config_dir)
        if not os.path.exists(self.__config_dir):
            os.makedirs(self.__config_dir)

        if trigCfg is None:
            trigCfg = MockTriggerConfig("empty-trigger")
        trigCfg.create(self.__config_dir, debug=debug)

        with open(path, 'w') as file_handle:
            print("<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                  file=file_handle)
            print("<runConfig>", file=file_handle)
            for hub, domList in list(hubDomDict.items()):
                domCfg = "string-%d-config" % hub
                self.__makeDomConfig(domCfg, domList, debug=debug)

                print("    <stringHub hubId=\"%s\" domConfig=\"%s\"/>" % \
                    (hub, domCfg), file=file_handle)

            print("    <triggerConfig>%s</triggerConfig>" % trigCfg.name,
                  file=file_handle)
            for comp in compList:
                pound = comp.rfind("#")
                if pound > 0:
                    val = int(comp[pound + 1:])
                    if val == 0:
                        comp = comp[:pound]
                print("    <runComponent name=\"%s\"/>" % comp,
                      file=file_handle)
            print("</runConfig>", file=file_handle)

        if debug:
            with open(path, "r") as file_handle:
                print("=== %s ===" % path)
                for line in file_handle:
                    print(line, end=' ')

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

    def connect(self, connlist=None):
        if connlist is None or self.outLinks is None:
            return 'OK'

        if MockXMLRPC.LOUD:
            print('Conn[%s:%s]' % (self.name, self.num), file=sys.stderr)
            for l in connlist:
                print('  %s:%s#%d' % \
                    (l['type'], l['compName'], l['compNum']), file=sys.stderr)

        # make a copy of the links
        #
        tmpLinks = {}
        for k in list(self.outLinks.keys()):
            tmpLinks[k] = []
            tmpLinks[k][0:] = self.outLinks[k][0:len(self.outLinks[k])]

        for l in connlist:
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
            errmsg = 'Component ' + self.name + '#' + str(self.num) + \
                ' is not connected to '

            first = True
            for k in list(tmpLinks.keys()):
                for t in tmpLinks[k]:
                    if first:
                        first = False
                    else:
                        errmsg += ', '
                    errmsg += k + ':' + t.name + '#' + str(t.num)
            raise ValueError(errmsg)

        return 'OK'

    def getState(self):
        pass

    def getVersionInfo(self):
        return ''

    def logTo(self, log_host, log_port, live_host, live_port):
        pass

    def reset(self):
        pass

    def resetLogging(self):
        pass

    def startRun(self, run_num):
        pass

    def stopRun(self):
        pass


class SocketReader(LogChecker):
    NEXT_PORT = DAQPort.EPHEMERAL_BASE

    def __init__(self, name, port, depth=None):
        if port is None:
            raise Exception("Reader port cannot be None")

        self.__name = name
        self.__port = port

        self.__errmsg = None

        self.__thread = None
        self.__serving = False

        isLive = (self.__port == DAQPort.I3LIVE)
        super(SocketReader, self).__init__('SOC', name,
                                           isLive=isLive, depth=depth)

    def __bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.__port is not None:
            try:
                sock.bind(("", self.__port))
            except socket.error as e:
                raise socket.error('Cannot bind SocketReader to port %d: %s' %
                                   (self.__port, str(e)))
        else:
            while True:
                self.__port = self.__next_port

                try:
                    sock.bind(("", self.__port))
                    break
                except socket.error:
                    pass

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
                rdat, _, rerr = select.select(pr, pw, pe, 0.5)
                if len(rerr) != 0:
                    raise Exception("Error on select was detected.")
                if len(rdat) == 0:
                    continue
                # Slurp up waiting packets, return to select if EAGAIN
                while True:
                    try:
                        data = sock.recv(8192, socket.MSG_DONTWAIT)
                    except:
                        break  # Go back to select so we don't busy-wait
                    if not self._checkMsg(data.decode("utf-8")):
                        break
        finally:
            if sock is not None:
                sock.close()
            self.__serving = False

    @classproperty
    def __next_port(cls):
        port = cls.NEXT_PORT
        cls.NEXT_PORT += 1
        if cls.NEXT_PORT > DAQPort.EPHEMERAL_MAX:
            cls.NEXT_PORT = DAQPort.EPHEMERAL_BASE
        return port

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
        if self.__errmsg is not None:
            raise Exception(self.__errmsg)

    @property
    def port(self):
        return self.__port

    def serving(self):
        return self.__serving

    def set_error(self, msg):
        if self.__errmsg is None:
            self.__errmsg = msg

    def stop_serving(self):
        "Signal listening thread to exit; wait for thread to finish"
        if self.__thread is not None:
            thread = self.__thread
            self.__thread = None
            thread.join()

    def start_serving(self):
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
            log.start_serving()

        return log

    def tearDown(self):
        for l in self.__logList:
            l.stop_serving()

        for l in self.__logList:
            l.checkStatus(0)

        del self.__logList[:]


class SocketWriter(object):
    def __init__(self, node, port):
        "Create a socket and connect it to the next port"
        if port is None:
            port = LogSocketServer.next_log_port

        self.__port = port

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.connect((node, port))
        except socket.error as err:
            raise socket.error('Cannot connect to %s:%d: %s' %
                               (node, port, str(err)))


        self.__loc = (node, port)

    def __str__(self):
        return '%s@%d' % self.__loc

    @property
    def port(self):
        return self.__port

    def write(self, s):
        "Write message to remote logger"
        self.socket.send(s.encode("utf-8"))

    def write_ts(self, s, time=None):
        "Write time-stamped log msg to remote logger"
        if time is None:
            time = datetime.datetime.now()
        output = "- - [%s] %s" % (time, s)
        self.socket.send(output.encode("utf-8"))

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
                print("Cannot remove run.xml: %s" % ex)
            raise ValueError("Found unexpected run.xml file")

    @classmethod
    def validate(cls, test_case, run_num, cfgName, cluster, start_time,
                 end_time, num_evts, num_moni, num_sn, num_tcal, failed,
                 run_dir=None):
        if run_dir is None:
            path = "run.xml"
        else:
            path = os.path.join(run_dir, "run.xml")

        try:
            if not os.path.exists(path):
                test_case.fail("run.xml was not created")

            run = DashXMLLog.parse(dir_name=run_dir)

            test_case.assertEqual(run.getRun(), run_num,
                                  "Expected run number %s, not %s" %
                                  (run_num, run.getRun()))

            test_case.assertEqual(run.getConfig(), cfgName,
                                  "Expected config \"%s\", not \"%s\"" %
                                  (cfgName, run.getConfig()))

            test_case.assertEqual(run.getCluster(), cluster,
                                  "Expected cluster \"%s\", not \"%s\"" %
                                  (cluster, run.getCluster()))

            if start_time is not None:
                test_case.assertEqual(run.getStartTime(), start_time,
                                      "Expected start time %s<%s>,"
                                      " not %s<%s>" %
                                      (start_time, type(start_time).__name__,
                                       run.getStartTime(),
                                       type(run.getStartTime()).__name__))
            if end_time is not None:
                test_case.assertEqual(run.getEndTime(), end_time,
                                      "Expected end time %s<%s>, not %s<%s>" %
                                      (end_time, type(end_time).__name__,
                                       run.getEndTime(),
                                       type(run.getEndTime()).__name__))

            test_case.assertEqual(run.getTermCond(), failed,
                                  "Expected terminal condition %s, not %s" %
                                  (failed, run.getTermCond()))

            test_case.assertEqual(run.getEvents(), num_evts,
                                  "Expected number of events %s, not %s" %
                                  (num_evts, run.getEvents()))

            test_case.assertEqual(run.getMoni(), num_moni,
                                  "Expected number of monitoring events %s, "
                                  "not %s" % (num_moni, run.getMoni()))

            test_case.assertEqual(run.getTcal(), num_tcal,
                                  "Expected number of time cal events %s, "
                                  "not %s" % (num_tcal, run.getTcal()))

            test_case.assertEqual(run.getSN(), num_sn,
                                  "Expected number of supernova events %s, "
                                  "not %s" % (num_sn, run.getSN()))
        finally:
            try:
                os.remove("run.xml")
            except:
                pass


class MockRunSet(object):
    def __init__(self, comps):
        self.__comps = comps
        self.__running = False

        self.__run_number = 123456
        self.__num_evts = 10
        self.__rate = 123.45
        self.__num_moni = 11
        self.__num_sn = 12
        self.__num_tcal = 13

        self.__id = "MockRS"

    def client_statistics(self):
        return {}

    def components(self):
        return self.__comps[:]

    def getRates(self):
        return (self.__num_evts, self.__rate, self.__num_moni, self.__num_sn,
                self.__num_tcal)

    @property
    def id(self):
        return self.__id

    @property
    def is_running(self):
        return self.__running

    def run_number(self):
        return self.__run_number

    def server_statistics(self):
        return {}

    def set_run_number(self, new_number):
        self.__run_number = new_number

    def startRunning(self):
        self.__running = True

    def stopRunning(self):
        self.__running = False

    def update_rates(self):
        for c in self.__comps:
            c.update_rates()
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

    def set_error(self, caller_name):
        self.__error = True


class MockLiveMoni(object):
    def __init__(self):
        self.__expMoni = {}

    def addExpected(self, var, val, prio, match_dict_values=True):
        if var not in self.__expMoni:
            self.__expMoni[var] = []
        self.__expMoni[var].append((val, prio, match_dict_values))

    def hasAllMoni(self):
        return len(self.__expMoni) == 0

    def sendMoni(self, var, val, prio, time=datetime.datetime.now()):
        if var not in self.__expMoni:
            raise Exception(("Unexpected live monitor data"
                             " (var=%s, val=%s, prio=%d)") % (var, val, prio))

        expData = None
        for index, (val_tmp, prio_tmp, match) in enumerate(self.__expMoni[var]):
            if prio != prio_tmp:
                continue
            if match or not isinstance(val, dict):
                if val != val_tmp:
                    continue
            else:
                matched = True
                for key in list(val.keys()):
                    if key not in val_tmp:
                        matched = False
                        break
                if not matched:
                    continue

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
