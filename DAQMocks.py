#!/usr/bin/env python
"""
A collection of hand-coded mock objects used by unit tests
"""

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
from leapseconds import LeapSeconds, MJD
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
    def __init__(self, var_name):
        self.__var_name = var_name
        super(BaseLiveChecker, self).__init__()

    def __str__(self):
        return '%s:%s=%s' % \
            (self.short_name, self.__var_name, self._value)

    def _check_text(self, checker, msg, debug, set_error):
        raise NotImplementedError()

    @property
    def short_name(self):
        raise NotImplementedError()

    @property
    def _value(self):
        raise NotImplementedError()

    @property
    def _value_type(self):
        raise NotImplementedError()

    def check(self, checker, msg, debug, set_error=True):
        mtch = BaseChecker.PAT_LIVELOG.match(msg)
        if mtch is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:LFMT: %s' % (name, msg), file=sys.stderr)
                checker.set_error('Bad format for %s I3Live message "%s"' %
                                  (name, msg))
            return False

        svc_name = mtch.group(1)
        var_name = mtch.group(2)
        var_type = mtch.group(3)
        # msgPrio = mtch.group(4)
        # msg_time = mtch.group(5)
        msg_text = mtch.group(6)

        if svc_name != SERVICE_NAME:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:SVC: %s (%s)' %
                          (name, SERVICE_NAME, self._value), file=sys.stderr)
                checker.set_error('Expected %s I3Live service "%s", not "%s"'
                                  ' in "%s"' %
                                  (name, SERVICE_NAME, svc_name, msg))
            return False

        if var_name != self.__var_name:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:VAR: %s (%s)' %
                          (name, self.__var_name, self._value),
                          file=sys.stderr)
                    checker.set_error('Expected %s I3Live var_name "%s",'
                                      ' not "%s" in "%s"' %
                                      (name, self.__var_name, var_name, msg))
            return False

        type_str = self._value_type
        if var_type != type_str:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:TYPE: %s (%s)' %
                          (name, type_str, self._value), file=sys.stderr)
                checker.set_error('Expected %s I3Live type "%s", not "%s"'
                                  ' in %s' % (name, type_str, var_type, msg))
            return False

        # ignore priority
        # ignore time

        if not self._check_text(checker, msg_text, debug, set_error):
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
                    print('*** %s:XACT: %s' % (name, self.__text),
                          file=sys.stderr)
                checker.set_error('Expected %s exact log message "%s",'
                                  ' not "%s"' % (name, self.__text, msg))
            return False

        return True


class LiveChecker(BaseLiveChecker):
    def __init__(self, var_name, value, var_type=None):
        self.__value = value
        self.__type = var_type

        super(LiveChecker, self).__init__(var_name)

    def __fix_value(self, val):
        if isinstance(val, str):
            return "\"%s\"" % val

        if isinstance(val, int):
            vstr = str(val)
            if vstr.endswith("L"):
                return vstr[:-1]
            return vstr

        if isinstance(val, bool):
            return "true" if self.__value else "false"

        return str(val)

    def _check_text(self, checker, msg, debug, set_error):
        if self.__type is None or self.__type != "json":
            val_str = str(self.__value)
        elif isinstance(self.__value, (list, tuple)):
            val_str = "["
            for val in self.__value:
                if len(val_str) > 1:
                    val_str += ", "
                val_str += self.__fix_value(val)
            val_str += "]"
        elif isinstance(self.__value, dict):
            val_str = "{"
            for key, val in self.__value.items():
                if len(val_str) > 1:
                    val_str += ", "
                val_str += self.__fix_value(key)
                val_str += ": "
                val_str += self.__fix_value(val)
            val_str += "}"
        else:
            val_str = str(self.__value)

        if msg != val_str:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:LIVE: %s' % (name, val_str), file=sys.stderr)
                checker.set_error('Expected %s live log message '
                                  '"%s", not "%s"' % (name, val_str, msg))
            return False

        return True

    @property
    def short_name(self):
        return 'LIVE'

    @property
    def _value(self):
        return self.__value

    @property
    def _value_type(self):
        if self.__type is not None:
            return self.__type
        return type(self.__value).__name__


class LiveRegexpChecker(BaseLiveChecker):
    def __init__(self, var_name, pattern):
        self.__regexp = re.compile(pattern)
        super(LiveRegexpChecker, self).__init__(var_name)

    def _check_text(self, checker, msg, debug, set_error):
        mtch = self.__regexp.search(msg)
        if mtch is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:RLIV: %s' %
                          (name, self.__regexp.pattern), file=sys.stderr)
                checker.set_error('Expected %s I3Live regexp message "%s",'
                                  ' not "%s"' %
                                  (name, self.__regexp.pattern, msg))
            return False

        return True

    @property
    def short_name(self):
        return 'LIVREX'

    @property
    def _value(self):
        return self.__regexp.pattern

    @property
    def _value_type(self):
        return 'str'


class RegexpChecker(BaseChecker):
    def __init__(self, pattern):
        self.__regexp = re.compile(pattern)
        super(RegexpChecker, self).__init__()

    def __str__(self):
        return 'REGEXP:%s' % self.__regexp.pattern

    def check(self, checker, msg, debug, set_error=True):
        mtch = self.__regexp.match(msg)
        if mtch is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:REXP: %s' %
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
        mtch = BaseChecker.PAT_DAQLOG.match(msg)
        if mtch is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:RFMT: %s' %
                          (name, BaseChecker.PAT_DAQLOG.pattern),
                          file=sys.stderr)
                checker.set_error('Bad format for %s log message "%s"' %
                                  (name, msg))
            return False

        mtch = self.__regexp.search(mtch.group(3))
        if mtch is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:RTXT: %s' %
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
        mtch = BaseChecker.PAT_DAQLOG.match(msg)
        if mtch is None:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:TFMT: %s' %
                          (name, BaseChecker.PAT_DAQLOG.pattern),
                          file=sys.stderr)
                checker.set_error('Bad format for %s log message "%s"' %
                                  (name, msg))
            return False

        if mtch.group(3).find(self.__text) == -1:
            if set_error:
                name = str(checker)
                if debug:
                    print('*** %s:TEXT: %s' % (name, self.__text),
                          file=sys.stderr)
                checker.set_error('Expected %s partial log message of "%s",'
                                  ' not "%s"' %
                                  (name, self.__text, mtch.group(3)))
            return False

        return True


class LogChecker(object):
    DEBUG = False

    TYPE_EXACT = 1
    TYPE_TEXT = 2
    TYPE_REGEXP = 3
    TYPE_RETEXT = 4
    TYPE_LIVE = 5

    def __init__(self, prefix, name, is_live=False, depth=None):
        self.__prefix = prefix
        self.__name = name
        self.__is_live = is_live
        if depth is None:
            self.__depth = 5
        else:
            self.__depth = depth

        self.__exp_msgs = []

    def __str__(self):
        return '%s-%s' % (self.__prefix, self.__name)

    def __check_empty(self):
        if len(self.__exp_msgs) != 0:  # pylint: disable=len-as-condition
            fixed = []
            for msg in self.__exp_msgs:
                fixed.append(str(msg))
            raise Exception("Didn't receive %d expected %s log messages: %s" %
                            (len(fixed), self.__name, str(fixed)))

    def _check_error(self):
        pass

    def _check_msg(self, msg):
        if LogChecker.DEBUG:
            print("Check(%s): %s" % (self, msg), file=sys.stderr)

        if len(self.__exp_msgs) == 0:  # pylint: disable=len-as-condition
            if LogChecker.DEBUG:
                print('*** %s:UNEX(%s)' % (self, msg), file=sys.stderr)
            self.set_error('Unexpected %s log message: %s' % (self, msg))
            return False

        found = None
        for i in range(len(self.__exp_msgs)):
            if i >= self.__depth:
                break
            if self.__exp_msgs[i].check(self, msg, LogChecker.DEBUG, False):
                found = i
                break

        if found is None:
            print('--- Missing %s log msg ---' % (self, ), file=sys.stderr)
            print(msg, file=sys.stderr)
            if len(self.__exp_msgs) > 0:  # pylint: disable=len-as-condition
                print('--- Expected %s messages ---' % (self, ),
                      file=sys.stderr)
                for i in range(len(self.__exp_msgs)):
                    if i >= self.__depth:
                        break
                    print("--- %s" % str(self.__exp_msgs[i]), file=sys.stderr)
                    self.__exp_msgs[i].check(self, msg, LogChecker.DEBUG, True)
            print('----------------------------', file=sys.stderr)
            self.set_error('Missing %s log message: %s' % (self, msg))
            return False

        del self.__exp_msgs[found]

        return True

    def add_expected_exact(self, msg):
        if LogChecker.DEBUG:
            print("AddExact(%s): %s" % (self, msg), file=sys.stderr)
        self.__exp_msgs.append(ExactChecker(msg))

    def add_expected_live_moni(self, var_name, value, val_type=None):
        if LogChecker.DEBUG:
            print("AddLiveMoni(%s): %s=%s%s" %
                  (self, var_name, value,
                   val_type is None and "" or "(%s)" % (val_type, )),
                  file=sys.stderr)
        self.__exp_msgs.append(LiveChecker(var_name, value, val_type))

    def add_expected_regexp(self, msg):
        if LogChecker.DEBUG:
            print("AddRegexp(%s): %s" % (self, msg), file=sys.stderr)
        self.__exp_msgs.append(RegexpChecker(msg))

    def add_expected_text(self, msg):
        if self.__is_live:
            if LogChecker.DEBUG:
                print("AddLive(%s): %s" % (self, msg), file=sys.stderr)
            self.__exp_msgs.append(LiveChecker('log', str(msg)))
        else:
            if LogChecker.DEBUG:
                print("AddText(%s): %s" % (self, msg), file=sys.stderr)
            self.__exp_msgs.append(TextChecker(msg))

    def add_expected_text_regexp(self, msg):
        if self.__is_live:
            if LogChecker.DEBUG:
                print("AddLiveRE(%s): %s" % (self, msg), file=sys.stderr)
            self.__exp_msgs.append(LiveRegexpChecker('log', msg))
        else:
            if LogChecker.DEBUG:
                print("AddTextRE(%s): %s" % (self, msg), file=sys.stderr)
            self.__exp_msgs.append(RegexpTextChecker(msg))

    def check_status(self, reps):
        count = 0
        explen = len(self.__exp_msgs)
        while explen > 0 and count < reps:
            time.sleep(.001)
            count += 1
        self._check_error()
        self.__check_empty()
        return True

    @property
    def is_empty(self):
        return len(self.__exp_msgs) == 0

    def set_check_depth(self, depth):
        self.__depth = depth

    def set_error(self, msg):
        raise NotImplementedError()

    @staticmethod
    def set_verbose(val=True):
        # NOTE: need to hard-code LogChecker.DEBUG to make sure the correct
        # class-level DEBUG attribute is set
        LogChecker.DEBUG = val


class MockClusterWriter(object):
    """Base class for MockClusterConfigFile classes"""
    @classmethod
    def __append_attr(cls, old_str, attr_name, new_str):
        if new_str is not None:
            if old_str is None:
                old_str = ""
            else:
                old_str += " "
            old_str += "%s=\"%s\"" % (attr_name, new_str)
        return old_str

    @classmethod
    def write_hs_xml(cls, file_handle, indent, path, interval, max_files):

        hs_str = "hitspool"
        hs_str = cls.__append_attr(hs_str, 'directory', path)
        hs_str = cls.__append_attr(hs_str, 'interval', interval)
        hs_str = cls.__append_attr(hs_str, 'maxfiles', max_files)
        print("%s<%s/>" % (indent, hs_str), file=file_handle)

    @classmethod
    def write_jvm_xml(cls, file_handle, indent, path, is_server, heap_init,
                      heap_max, args, extra_args):

        # if any field has a non-standard value, print this entry
        nonstandard = path is not None or is_server or heap_init is not None
        nonstandard = nonstandard or heap_max is not None or args is not None
        nonstandard = nonstandard or extra_args is not None
        if nonstandard:
            jstr = "jvm"
            jstr = cls.__append_attr(jstr, 'path', path)
            if is_server:
                jstr = cls.__append_attr(jstr, 'server', is_server)
            jstr = cls.__append_attr(jstr, 'heapInit', heap_init)
            jstr = cls.__append_attr(jstr, 'heapMax', heap_max)
            jstr = cls.__append_attr(jstr, 'args', args)
            jstr = cls.__append_attr(jstr, 'extraArgs', extra_args)
            print("%s<%s/>" % (indent, jstr), file=file_handle)

    @classmethod
    def write_line(cls, file_handle, indent, name, value):
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

    @classmethod
    def write(cls, file_handle, indent):
        print(indent + "<controlServer/>", file=file_handle)


class MockCluCfgFileComp(MockClusterWriter):
    """Used by MockClusterConfigFile for <component>"""
    def __init__(self, name, num=0, required=False, hitspool_directory=None,
                 hitspool_interval=None, hitspool_max_files=None,
                 jvm_path=None, jvm_server=None, jvm_heap_init=None,
                 jvm_heap_max=None, jvm_args=None, jvm_extra_args=None,
                 log_level=None):
        self.__name = name
        self.__num = num
        self.__required = required

        self.__hitspool_dir = hitspool_directory
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
        return self.__hitspool_dir

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

    def set_hitspool_directory(self, value):
        self.__hitspool_dir = value

    def set_hitspool_interval(self, value):
        self.__hitspool_interval = value

    def set_hitspool_max_files(self, value):
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

        has_hs_flds = self.__hitspool_dir is not None or \
          self.__hitspool_interval is not None or \
          self.__hitspool_max_files is not None
        has_jvm_flds = self.__jvm_path is not None or \
          self.__jvm_args is not None or \
          self.__jvm_extra_args is not None or \
          self.__jvm_heap_init is not None or \
          self.__jvm_heap_max is not None or \
          self.__jvm_server is not None
        multiline = has_hs_flds or has_jvm_flds or self.__log_level is not None

        if multiline:
            endstr = ""
        else:
            endstr = "/"

        print("%s<component name=\"%s\"%s%s%s>" %
              (indent, self.__name, numstr, reqstr, endstr), file=file_handle)

        if multiline:
            indent2 = indent + "  "

            if has_hs_flds:
                self.write_hs_xml(file_handle, indent2, self.__hitspool_dir,
                                  self.__hitspool_interval,
                                  self.__hitspool_max_files)
            if has_jvm_flds:
                self.write_jvm_xml(file_handle, indent2, self.__jvm_path,
                                   self.__jvm_server, self.__jvm_heap_init,
                                   self.__jvm_heap_max, self.__jvm_args,
                                   self.__jvm_extra_args)

            if self.__log_level is not None:
                self.write_line(file_handle, indent2, "logLevel",
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

    @classmethod
    def write(cls, file_handle, indent):
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
        comp = MockCluCfgFileComp(name, num=num, required=required)

        return self.__add_comp(comp)

    def add_control_server(self):
        return self.__add_comp(MockCluCfgCtlSrvr())

    def add_sim_hubs(self, number, priority, if_unused=False):
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
            for comp in self.__comps:
                if split_hosts or not printed_host:
                    print("%s<host name=\"%s\">" % (indent, self.__name),
                          file=file_handle)
                    printed_host = True

                comp.write(file_handle, indent2)

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

        print("%s<simulatedHub number=\"%d\" priority=\"%d\"%s/>" %
              (indent, self.__number, self.__priority, iustr),
              file=file_handle)


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
        print("%s<location name=\"%s\" host=\"%s\">" %
              (indent, self.__host, self.__host), file=file_handle)
        print("%s    <module name=\"%s\" id=\"%02d\"/?>" %
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
        self.__desc_name = descName

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
        return self.__desc_name

    def extract_components(self, master_list):
        node_comps = list(self.__nodes.values())
        return RunCluster.extract_components_from_nodes(node_comps,
                                                        master_list)

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

    def add_default_component(self, comp):
        if not self.__default_comps:
            self.__default_comps = []

        self.__default_comps.append(comp)

    def add_host(self, name):
        if name in self.__hosts:
            host = self.__hosts[name]
        else:
            host = MockCluCfgFileHost(name, self)
            self.__hosts[name] = host
        return host

    def create(self, split_hosts=False):
        path = os.path.join(self.__config_dir, "%s-cluster.cfg" % self.__name)

        if not os.path.exists(self.__config_dir):
            os.makedirs(self.__config_dir)

        with open(path, 'w') as file_handle:
            print("<cluster name=\"%s\">" % self.__name, file=file_handle)

            indent = "  "

            if self.__data_dir is not None:
                self.write_line(file_handle, indent, "daqDataDir",
                                self.__data_dir)
            if self.__log_dir is not None:
                self.write_line(file_handle, indent, "daqLogDir",
                                self.__log_dir)
            if self.__spade_dir is not None:
                self.write_line(file_handle, indent, "logDirForSpade",
                                self.__spade_dir)

            has_hs_xml = self.__default_hs_dir is not None or \
              self.__default_hs_interval is not None or \
              self.__default_hs_max_files is not None

            has_jvm_xml = self.__default_jvm_args is not None or \
                          self.__default_jvm_extra_args is not None or \
                          self.__default_jvm_heap_init is not None or \
                          self.__default_jvm_heap_max is not None or \
                          self.__default_jvm_path is not None or \
                          self.__default_jvm_server is not None

            has_hub_xml = self.__default_alert_email is not None or \
              self.__default_ntp_host is not None

            if has_hs_xml or has_jvm_xml or has_hub_xml or \
               self.__default_log_level is not None or \
               self.__default_comps is not None:
                print(indent + "<default>", file=file_handle)

                indent2 = indent + "  "

                if has_hs_xml:
                    self.write_hs_xml(file_handle, indent2,
                                      self.__default_hs_dir,
                                      self.__default_hs_interval,
                                      self.__default_hs_max_files)

                if has_jvm_xml:
                    self.write_jvm_xml(file_handle, indent2,
                                       self.__default_jvm_path,
                                       self.__default_jvm_server,
                                       self.__default_jvm_heap_init,
                                       self.__default_jvm_heap_max,
                                       self.__default_jvm_args,
                                       self.__default_jvm_extra_args)

                if has_hub_xml:
                    # self.writeHubXML(file_handle, indent2,
                    #                  self.__default_alert_email,
                    #                  self.__default_ntp_host)
                    raise NotImplementedError("writeHubXML")

                if self.__default_log_level is not None:
                    self.write_line(file_handle, indent2, "logLevel",
                                    self.__default_log_level)

                if self.__default_comps:
                    for comp in self.__default_comps:
                        comp.write(file_handle, indent2)

                print(indent + "</default>", file=file_handle)

            for host in list(self.__hosts.values()):
                host.write(file_handle, indent, split_hosts=split_hosts)

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

    def default_log_level(self, _=None):
        if self.__default_log_level is None:
            return ClusterDescription.DEFAULT_LOG_LEVEL

        return self.__default_log_level

    def default_ntp_host(self, _=None):
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

    def set_data_dir(self, value):
        self.__data_dir = value

    def set_default_alert_email(self, value):
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

    def set_default_log_level(self, value):
        self.__default_log_level = value

    def set_default_ntp_host(self, value):
        self.__default_ntp_host = value

    def set_log_dir(self, value):
        self.__log_dir = value

    def set_spade_dir(self, value):
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

    @property
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

    def __init__(self, name, conn_type, port=None):
        "port is set for input connections, None for output connections"
        self.__name = name
        self.__conn_type = conn_type
        self.__port = port

    def __repr__(self):
        return str(self)

    def __str__(self):
        if self.__port is not None:
            return '%d=>%s' % (self.__port, self.__name)
        return '=>' + self.__name

    @property
    def is_input(self):
        return self.__conn_type == self.INPUT or \
          self.__conn_type == self.OPT_INPUT

    @property
    def is_optional(self):
        return self.__conn_type == self.OPT_INPUT or \
               self.__conn_type == self.OPT_OUTPUT

    @property
    def name(self):
        return self.__name

    @property
    def port(self):
        return self.__port


class MockDeployComponent(Component):
    def __init__(self, name, num, log_level, hs_dir, hs_interval, hs_max_files,
                 jvm_path, jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                 jvm_extra_args, alert_email, ntp_host, num_replay_files=None,
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
        self.__num_replay_files = num_replay_files
        self.__host = host

        super(MockDeployComponent, self).__init__(name, num, log_level)

    @property
    def alert_email(self):
        return self.__alert_email

    @property
    def has_hitspool_options(self):
        return self.__hs_dir is not None or self.__hs_interval is not None or \
            self.__hs_max_files is not None

    @property
    def has_replay_options(self):
        return self.__num_replay_files is not None

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
        return self.__num_replay_files


class MockMBeanClient(object):
    def __init__(self, name):
        self.__name = name
        self.__bean_data = {}

    def __str__(self):
        return self.__name

    def add_mock_data(self, bean_name, field_name, value):
        if self.check(bean_name, field_name):
            raise Exception("Value for %s bean %s field %s already exists" %
                            (self, bean_name, field_name))

        if bean_name not in self.__bean_data:
            self.__bean_data[bean_name] = {}

        self.__bean_data[bean_name][field_name] = value

    def __add_or_set(self, bean_name, field_name, value):
        if bean_name not in self.__bean_data:
            self.__bean_data[bean_name] = {}

        self.__bean_data[bean_name][field_name] = value

    def check(self, bean_name, field_name):
        return bean_name in self.__bean_data and \
            field_name in self.__bean_data[bean_name]

    def get(self, bean_name, field_name):
        if bean_name not in self.__bean_data:
            raise Exception("Unknown bean %s for %s (valid beans: %s)" %
                            (bean_name, self, list(self.__bean_data.keys())))
        if field_name not in self.__bean_data[bean_name]:
            raise Exception("No %s data for bean %s field %s"
                            " (valid fields: %s)" %
                            (self, bean_name, field_name,
                             list(self.__bean_data[bean_name].keys())))

        return self.__bean_data[bean_name][field_name]

    def get_attributes(self, bean_name, field_list):
        rtn_map = {}
        for fld in field_list:
            rtn_map[fld] = self.get(bean_name, fld)

            if isinstance(rtn_map[fld], Exception):
                raise rtn_map[fld]
        return rtn_map

    def get_bean_fields(self, bean_name):
        return list(self.__bean_data[bean_name].keys())

    def get_bean_names(self):
        return list(self.__bean_data.keys())

    def get_dictionary(self):
        return copy.deepcopy(self.__bean_data)

    def reload(self):
        pass

    def set_data(self, bean_name, field_name, value):
        if not self.check(bean_name, field_name):
            raise Exception("%s bean %s field %s has not been added" %
                            (self, bean_name, field_name))

        self.__bean_data[bean_name][field_name] = value


class MockComponent(Comparable):
    def __init__(self, name, num=0, host='localhost'):
        self.__name = name
        self.__num = num
        self.__host = host

        self.__connectors = []
        self.__cmd_order = None

        self.__run_number = None
        self.__dom_mode = None

        self.__is_bldr = name.endswith("Builder") or name.endswith("Builders")
        self.___is_src = name.endswith("Hub") or name == "amandaTrigger"
        self.__connected = False
        self.__configured = False
        self.__config_wait = 0
        self.__monitor_count = 0
        self.__monitor_state = None
        self.__is_bad_hub = False
        self.__hang_type = 0
        self.__stopping = 0
        self.__updated_rates = False
        self.__dead_count = 0
        self.__stop_fail = False
        self.__first_good_time = None
        self.__last_good_time = None
        self.__mbean_client = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        out_str = self.fullname
        extra = []
        if self.___is_src:
            extra.append('SRC')
        if self.__is_bldr:
            extra.append('BLD')
        if self.__configured:
            extra.append('CFG')
        for conn in self.__connectors:
            extra.append(str(conn))

        if len(extra) > 0:  # pylint: disable=len-as-condition
            out_str += '[' + ','.join(extra) + ']'
        return out_str

    def add_dead_count(self):
        self.__dead_count += 1

    def add_mock_input(self, name, port, optional=False):
        if not optional:
            conn_type = MockConnection.INPUT
        else:
            conn_type = MockConnection.OPT_INPUT
        self.__connectors.append(MockConnection(name, conn_type, port))

    def add_mock_output(self, name, optional=False):
        if not optional:
            conn_type = MockConnection.OUTPUT
        else:
            conn_type = MockConnection.OPT_OUTPUT
        self.__connectors.append(MockConnection(name, conn_type))

    def close(self):
        pass

    def commit_subrun(self, subrun_num, start_time):
        pass

    @property
    def compare_key(self):
        "Return the keys to be used by the Comparable methods"
        return (self.__name, self.__num)

    def configure(self, _=None):
        if not self.__connected:
            self.__connected = True
        self.__configured = True
        return 'OK'

    @property
    def configure_wait(self):
        return self.__config_wait

    @configure_wait.setter
    def configure_wait(self, wait_num):
        self.__config_wait = wait_num

    def connect(self, _=None):
        self.__connected = True
        return 'OK'

    def connectors(self):
        return self.__connectors[:]

    def _create_mbean_client(self):
        return MockMBeanClient(self.fullname)

    def create_mbean_client(self):
        if self.__mbean_client is None:
            self.__mbean_client = self._create_mbean_client()
        return self.__mbean_client

    @property
    def dom_mode(self):
        return self.__dom_mode

    def forced_stop(self):
        if self.__stop_fail:
            pass
        elif self.__stopping == 1:
            if self.__hang_type != 2:
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

    def get_run_data(self, _):
        if self.__mbean_client is None:
            self.__mbean_client = self.create_mbean_client()

        if self.__num == 0:
            if self.__name.startswith("event"):
                num_evts, last_time = self.__mbean_client.get("backEnd",
                                                              "EventData")

                val = self.__mbean_client.get("backEnd", "FirstEventTime")
                first_time = int(val)

                good = self.__mbean_client.get("backEnd", "GoodTimes")
                first_good = int(good[0])
                last_good = int(good[1])
                return (num_evts, first_time, last_time, first_good, last_good)

            if self.__name.startswith("secondary"):
                for bldr in ("tcal", "sn", "moni"):
                    val = self.__mbean_client.get(bldr + "Builder",
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
        return self.__is_bldr

    def is_component(self, name, _=None):
        return self.__name == name

    @property
    def is_configured(self):
        return self.__configured

    @property
    def is_hanging(self):
        return self.__hang_type != 0

    @property
    def is_replay_hub(self):
        return False

    @property
    def is_source(self):
        return self.___is_src

    @classmethod
    def list_connector_states(cls):
        return ""

    def log_to(self, log_host, log_port, live_host, live_port):
        pass

    @property
    def mbean(self):
        if self.__mbean_client is None:
            self.__mbean_client = self.create_mbean_client()

        return self.__mbean_client

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

    def prepare_subrun(self, subrun_num):
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

    def set_bad_hub(self):
        self.__is_bad_hub = True

    def set_stop_fail(self):
        self.__stop_fail = True

    def set_first_good_time(self,
                            time):  # pylint: disable=redefined-outer-name
        self.__first_good_time = time

    def set_hang_type(self, hang_type):
        self.__hang_type = hang_type

    def set_last_good_time(self,
                           time):  # pylint: disable=redefined-outer-name
        self.__last_good_time = time

    def set_monitor_state(self, new_state):
        self.__monitor_state = new_state

    def start_run(self, run_num, dom_mode):
        if not self.__configured:
            raise Exception(self.__name + ' has not been configured')

        self.__run_number = run_num
        self.__dom_mode = dom_mode

    def start_subrun(self, _):
        if self.__is_bad_hub:
            return None
        return 100

    @property
    def state(self):  # pylint: disable=too-many-return-statements
        if self.__monitor_state is not None:
            self.__monitor_count += 1
            return self.__monitor_state

        if not self.__connected:
            return 'idle'
        if not self.__configured or self.__config_wait > 0:
            if self.__configured and self.__config_wait > 0:
                self.__config_wait -= 1
            return 'connected'
        if self.__stopping == 1:
            return "stopping"
        if self.__stopping == 2:
            return "forcingStop"
        if not self.__run_number:
            return 'ready'

        return 'running'

    def stop_run(self):
        if self.__run_number is None:
            raise Exception(self.__name + ' is not running')

        if self.__hang_type > 0 or self.__stop_fail:
            self.__stopping = 1
        else:
            self.__run_number = None

    def update_rates(self):
        self.__updated_rates = True

    def was_updated(self):
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
                        print("      <productionId>%s</productionId>" %
                              dom.prod_id, file=file_handle)
                        print("    </dom>", file=file_handle)
                    print("  </string>", file=file_handle)

                print("</domGeometry>", file=file_handle)


class MockDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbean_port, connectors,
                 appender, out_links=None, extra_loud=False):

        self.__appender = appender
        self.__extra_loud = extra_loud

        self.__out_links = out_links
        self.__state = 'idle'

        super(MockDAQClient, self).__init__(name, num, host, port, mbean_port,
                                            connectors, True)

    def __str__(self):
        tmp_str = super(MockDAQClient, self).__str__()
        return 'Mock' + tmp_str

    def close_log(self):
        pass

    def configure(self, config_name=None):
        self.__state = 'ready'
        return super(MockDAQClient, self).configure(config_name)

    def connect(self, conn_list=None):
        self.__state = 'connected'
        return super(MockDAQClient, self).connect(conn_list)

    def create_client(self, host, port):
        return MockRPCClient(self.name, self.num, self.__out_links)

    def create_logger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet, extra_loud=self.__extra_loud)

    def __create_mbean_client(self):
        return MockRPCClient(self.name, self.num, self.__out_links)

    def reset(self):
        self.__state = 'idle'
        return super(MockDAQClient, self).reset()

    def start_run(self, run_num, dom_mode):
        self.__state = 'running'
        return super(MockDAQClient, self).start_run(run_num, dom_mode)

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

    def is_time(self, now=None):  # pylint: disable=unused-argument
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

    def _check_error(self):
        if self.__err is not None:
            raise Exception(self.__err)

    @classmethod
    def add_appender(cls, app):
        print("Not adding appender %s to MockLogger" % app, file=sys.stderr)

    def close(self):
        pass

    def debug(self, msg):
        self._check_msg(msg)

    def error(self, msg):
        self._check_msg(msg)

    def fatal(self, msg):
        self._check_msg(msg)

    def info(self, msg):
        self._check_msg(msg)

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

    def trace(self, msg):
        self._check_msg(msg)

    def warn(self, msg):
        self._check_msg(msg)

    # pylint: disable=redefined-outer-name,unused-argument
    def write(self, msg, time=None,
              level=None):
        self._check_msg(msg)
    # pylint: enable=redefined-outer-name,unused-argument


class MockParallelShell(object):
    BINDIR = os.path.join(find_pdaq_trunk(), 'target', 'pDAQ-%s-dist' %
                          ComponentManager.RELEASE, 'bin')

    def __init__(self, is_parallel=True, debug=False):
        self.__exp = []
        self.__rtn_codes = []
        self.__results = []
        self.__is_parallel = is_parallel
        self.__debug = debug

    def __add_expected(self, cmd):
        # pylint: disable=chained-comparison
        if cmd.find("/bin/StringHub") > 0 and cmd.find(".componentId=") < 0:
            raise Exception("Missing componentId: %s" % cmd)
        self.__exp.append(cmd)

    def __check_cmd(self, cmd):
        exp_len = len(self.__exp)
        if exp_len == 0:
            raise Exception('Did not expect command "%s"' % cmd)

        if self.__debug:
            print("PSh got: " + cmd, file=sys.stderr)

        found = None
        for i in range(exp_len):
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

    @classmethod
    def __is_localhost(cls, host):
        return host in ('localhost', '127.0.0.1')

    def add(self, cmd):
        self.__check_cmd(cmd)

    def add_expected_java(self, comp, config_dir, daq_data_dir, log_port,
                          live_port, verbose, event_check, host):

        ip_addr = ip.get_local_address(host)
        jar_path = os.path.join(MockParallelShell.BINDIR,
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

        cmd += ' -jar %s' % jar_path
        if daq_data_dir is not None:
            cmd += ' -d %s' % daq_data_dir
        cmd += ' -c %s:%d' % (ip_addr, DAQPort.CNCSERVER)

        if log_port is not None:
            cmd += ' -l %s:%d,%s' % (ip_addr, log_port, comp.log_level)
        if live_port is not None:
            cmd += ' -L %s:%d,%s' % (ip_addr, live_port, comp.log_level)
            cmd += ' -M %s:%d' % (ip_addr, MoniPort)
        cmd += ' %s &' % redir

        if not self.__is_localhost(host):
            cmd = "ssh -n %s 'sh -c \"%s\"%s &'" % (host, cmd, redir)

        self.__add_expected(cmd)

    def add_expected_java_kill(self, comp_name, comp_id, kill_with_9, host):
        if kill_with_9:
            nine_arg = '-9'
        else:
            nine_arg = ''

        user = os.environ['USER']

        if comp_name.endswith("hub"):
            kill_pat = "stringhub.componentId=%d " % comp_id
        else:
            kill_pat = ComponentManager.get_component_jar(comp_name)

        if self.__is_localhost(host):
            ssh_cmd = ''
            pkill_opt = ' -fu %s' % user
        else:
            ssh_cmd = 'ssh %s ' % host
            pkill_opt = ' -f'

        self.__add_expected('%spkill %s%s \"%s\"' %
                            (ssh_cmd, nine_arg, pkill_opt, kill_pat))

        if not kill_with_9:
            self.__add_expected('sleep 2; %spkill -9%s \"%s\"' %
                                (ssh_cmd, pkill_opt, kill_pat))

    def add_expected_python(self, do_cnc, dash_dir, config_dir, log_dir,
                            daq_data_dir, spade_dir, clu_cfg_name, copy_dir,
                            log_port, live_port, force_restart=True):
        if do_cnc:
            cmd = os.path.join(dash_dir, 'CnCServer.py')
            cmd += ' -c %s' % config_dir
            cmd += ' -o %s' % log_dir
            cmd += ' -q %s' % daq_data_dir
            cmd += ' -s %s' % spade_dir
            if clu_cfg_name is not None:
                if clu_cfg_name.endswith("-cluster"):
                    cmd += ' -C %s' % clu_cfg_name
                else:
                    cmd += ' -C %s-cluster' % clu_cfg_name
            if log_port is not None:
                cmd += ' -l localhost:%d' % log_port
            if live_port is not None:
                cmd += ' -L localhost:%d' % live_port
            if copy_dir is not None:
                cmd += ' -a %s' % copy_dir
            if not force_restart:
                cmd += ' -F'
            cmd += ' -d'

            self.__add_expected(cmd)

    def add_expected_python_kill(self, do_cnc, kill_with_9):
        pass

    def __add_expected_rsync(self, srcdir, subdirs, delete, dry_run,
                             remote_host, rtn_code, result="",
                             express=DeployPDAQ.EXPRESS_DEFAULT):

        if express:
            rcmd = "rsync"
        else:
            rcmd = 'nice rsync --rsync-path "nice -n %d rsync"' % \
              DeployPDAQ.NICE_LEVEL_DEFAULT

        if not delete:
            del_opt = ""
        else:
            del_opt = " --delete"

        if not dry_run:
            dr_opt = ""
        else:
            dr_opt = " --dry-run"

        group = "{" + ",".join(subdirs) + "}"

        cmd = "%s -azLC%s%s %s %s:%s" % \
            (rcmd, del_opt, dr_opt, os.path.join(srcdir, group), remote_host,
             srcdir)
        self.__add_expected(cmd)
        self.__rtn_codes.append(rtn_code)
        self.__results.append(result)

    def __add_expected_undeploy(self, pdaq_dir, remote_host):
        cmd = "ssh %s \"\\rm -rf ~%s/config %s\"" % \
            (remote_host, os.environ["USER"], pdaq_dir)
        self.__add_expected(cmd)

    def check(self):
        if len(self.__exp) > 0:  # pylint: disable=len-as-condition
            raise Exception(('ParallelShell did not receive expected commands:'
                             ' %s') % str(self.__exp))

    def get_result(self, idx):
        if idx < 0 or idx >= len(self.__results):
            raise Exception("Cannot return result %d (only %d available)" %
                            (idx, len(self.__results)))

        return self.__results[idx]

    def __get_return_codes(self):
        return self.__rtn_codes

    @property
    def is_parallel(self):
        return self.__is_parallel

    def show_all(self):
        raise NotImplementedError('show_all')

    def shuffle(self):
        pass

    def start(self):
        pass

    def system(self, cmd):
        self.__check_cmd(cmd)

    def wait(self, monitor_ival=None):
        pass

    @property
    def command_results(self):

        # commands are in self.__exp
        ret = {}
        for exp, rtncode in zip(self.__exp, self.__rtn_codes):
            ret[exp] = (rtncode, "")

        return ret


class MockRPCClient(object):
    def __init__(self, name, num, out_links=None):
        self.xmlrpc = MockXMLRPC(name, num, out_links)


class MockRunComponent(object):
    def __init__(self, name, comp_id, inetAddr, rpc_port, mbean_port):
        self.__name = name
        self.__id = comp_id
        self.__inet_addr = inetAddr
        self.__rpc_port = rpc_port
        self.__mbean_port = mbean_port

    def __str__(self):
        return "%s#%s" % (self.__name, self.__id)

    @property
    def id(self):  # pylint: disable=invalid-name
        return self.__id

    @property
    def __internet_address(self):
        return self.__inet_addr

    @property
    def is_hub(self):
        return self.__name.endswith("Hub")

    @property
    def is_replay(self):  # XXX unused?
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

    def print_xml(self, file_handle, indent):
        print("%s<domConfig mbid=\"%012x\">" % (indent, self.__mbid),
              file=file_handle)
        print("%s%s<xxx>xxx</xxx>" % (indent, indent), file=file_handle)
        print("%s</domConfig>" % indent, file=file_handle)


class MockAlgorithm(object):
    def __init__(self, src_id, name, trigtype, cfg_id):
        self.__src_id = src_id
        self.__name = name
        self.__type = trigtype
        self.__cfg_id = cfg_id
        self.__param_dict = {}
        self.__readouts = []

    @classmethod
    def __print_element(cls, file_handle, indent, tag, val):
        print("%s<%s>%s</%s>" % (indent, tag, val, tag), file=file_handle)

    def __add_parameter(self, name, value):
        self.__param_dict[name] = value

    def __add_readout(self, rdout_type, offset, minus, plus):
        self.__readouts.append((rdout_type, offset, minus, plus))

    def print_xml(self, file_handle, indent):
        indent2 = indent + "    "
        print("%s<triggerConfig>" % indent, file=file_handle)

        self.__print_element(file_handle, indent2, "triggerType", self.__type)
        self.__print_element(file_handle, indent2, "triggerConfigId",
                             self.__cfg_id)
        self.__print_element(file_handle, indent2, "sourceId", self.__src_id)
        self.__print_element(file_handle, indent2, "triggerName", self.__name)

        for key, val in self.__param_dict.items():
            print("%s<parameterConfig>", file=file_handle)
            print("%s    <parameterName>%s<parameterName>" % (indent2, key),
                  file=file_handle)
            print("%s    <parameterValue>%s<parameterValue>" % (indent2, val),
                  file=file_handle)
            print("%s</parameterConfig>", file=file_handle)

        for rdout in self.__readouts:
            tag = ("readoutType", "timeOffset", "timeMinus", "timePlus")

            print("%s<readoutConfig>", file=file_handle)
            for idx in range(4):
                print("%s    <%s>%d<%s>" % (indent2, tag[idx], rdout[idx],
                                            tag[idx]),
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

        filepath = os.path.join(nist_path, LeapSeconds.DEFAULT_FILENAME)
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

    def add(self, src_id, name, trigtype, cfg_id):
        algo = MockAlgorithm(src_id, name, trigtype, cfg_id)
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
            if len(self.__algorithms) == 0:  # pylint: disable=len-as-condition
                print("<activeTriggers/>", file=file_handle)
            else:
                print("<activeTriggers>", file=file_handle)
                need_nl = False
                for algo in self.__algorithms:
                    if not need_nl:
                        need_nl = True
                    else:
                        print(file=file_handle)
                    algo.print_xml(file_handle, "    ")
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

    def __make_dom_config(self, cfg_name, dom_list, debug=False):
        cfg_dir = os.path.join(self.__config_dir, "domconfigs")
        if not os.path.exists(cfg_dir):
            os.makedirs(cfg_dir)

        if cfg_name.endswith(".xml"):
            file_name = cfg_name
        else:
            file_name = cfg_name + ".xml"

        path = os.path.join(cfg_dir, file_name)
        with open(path, 'w') as file_handle:
            print("<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                  file=file_handle)
            print("<domConfigList>", file=file_handle)
            if dom_list is not None:
                for dom in dom_list:
                    dom.print_xml(file_handle, "  ")
            print("</domConfigList>", file=file_handle)

        if debug:
            with open(path, "r") as file_handle:
                print("=== %s ===" % path)
                for line in file_handle:
                    print(line, end=' ')

    def create(self, comp_list, hub_dom_dict, trig_cfg=None, debug=False):
        path = tempfile.mktemp(suffix=".xml", dir=self.__config_dir)
        if not os.path.exists(self.__config_dir):
            os.makedirs(self.__config_dir)

        if trig_cfg is None:
            trig_cfg = MockTriggerConfig("empty-trigger")
        trig_cfg.create(self.__config_dir, debug=debug)

        with open(path, 'w') as file_handle:
            print("<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                  file=file_handle)
            print("<runConfig>", file=file_handle)
            for hub, dom_list in list(hub_dom_dict.items()):
                dom_cfg = "string-%d-config" % hub
                self.__make_dom_config(dom_cfg, dom_list, debug=debug)

                print("    <stringHub hubId=\"%s\" domConfig=\"%s\"/>" %
                      (hub, dom_cfg), file=file_handle)

            print("    <triggerConfig>%s</triggerConfig>" % trig_cfg.name,
                  file=file_handle)
            for comp in comp_list:
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
    def create_dom(mbid, pos=None, name=None, prod_id=None):
        return SimDOMXML(mbid, pos=pos, name=name, prod_id=prod_id)


class MockXMLRPC(object):
    "Simulate an XML-RPC connection to a Java client"

    LOUD = False

    # Class methods use CamelCase because they're simulating Java RPC stubs

    def __init__(self, name, num, out_links):
        self.name = name
        self.num = num

        self.__out_links = out_links

    def configure(self, name=None):
        pass

    def connect(self, connlist=None):
        if connlist is None or self.__out_links is None:
            return 'OK'

        if MockXMLRPC.LOUD:
            print('Conn[%s:%s]' % (self.name, self.num), file=sys.stderr)
            for conn in connlist:
                print('  %s:%s#%d' % (conn['type'], conn['compName'],
                                      conn['compNum']), file=sys.stderr)

        # make a copy of the links
        #
        tmp_links = {}
        for key in list(self.__out_links.keys()):
            tmp_links[key] = []
            tmp_links[key][0:] = \
              self.__out_links[key][0:len(self.__out_links[key])]

        for link in connlist:
            if link['type'] not in tmp_links:
                raise ValueError(('Component %s#%d should not have a "%s"' +
                                  ' connection') %
                                 (self.name, self.num, link['type']))

            comp = None
            for tmp in tmp_links[link['type']]:
                if tmp.name == link['compName'] and tmp.num == link['compNum']:
                    comp = tmp

                    key = link['type']
                    tmp_links[key].remove(tmp)
                    keylen = tmp_links[key]
                    if len(keylen) == 0:  # pylint: disable=len-as-condition
                        del tmp_links[key]
                    break

            if not comp:
                raise ValueError("Component %s#%d should not connect to"
                                 " %s:%s#%d" %
                                 (self.name, self.num, link['type'],
                                  link['compName'], link.getCompNum()))

        if len(tmp_links) > 0:  # pylint: disable=len-as-condition
            errmsg = 'Component ' + self.name + '#' + str(self.num) + \
                ' is not connected to '

            first = True
            for key in tmp_links:
                for link in tmp_links[key]:
                    if first:
                        first = False
                    else:
                        errmsg += ', '
                    errmsg += key + ':' + link.name + '#' + str(link.num)
            raise ValueError(errmsg)

        return 'OK'

    def getState(self):           # pylint: disable=invalid-name
        pass

    @property
    def getVersionInfo(self):     # pylint: disable=invalid-name
        return (None, None)

    def logTo(self, log_host,     # pylint: disable=invalid-name
              log_port, live_host, live_port):
        pass

    def reset(self):
        pass

    def resetLogging(self):       # pylint: disable=invalid-name
        pass

    def startRun(self, run_num):  # pylint: disable=invalid-name
        pass

    def stopRun(self):            # pylint: disable=invalid-name
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

        is_live = (self.__port == DAQPort.I3LIVE)
        super(SocketReader, self).__init__('SOC', name,
                                           is_live=is_live, depth=depth)

    def __bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.__port is not None:
            try:
                sock.bind(("", self.__port))
            except socket.error as exc:
                raise socket.error('Cannot bind SocketReader to port %d: %s' %
                                   (self.__port, str(exc)))
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
            prd = [sock]
            pwr = []
            per = [sock]
            while self.__thread is not None:
                rdat, _, rerr = select.select(prd, pwr, per, 0.5)
                if len(rerr) != 0:  # pylint: disable=len-as-condition
                    raise Exception("Error on select was detected.")
                if len(rdat) == 0:  # pylint: disable=len-as-condition
                    continue
                # Slurp up waiting packets, return to select if EAGAIN
                while True:
                    try:
                        data = sock.recv(8192, socket.MSG_DONTWAIT)
                    except:  # pylint: disable=bare-except
                        break  # Go back to select so we don't busy-wait
                    if not self._check_msg(data.decode("utf-8")):
                        break
        finally:
            if sock is not None:
                sock.close()
            self.__serving = False

    @classproperty
    def __next_port(cls):  # pylint: disable=no-self-argument
        port = cls.NEXT_PORT
        cls.NEXT_PORT += 1  # pylint: disable=invalid-name
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
                self._check_msg(data)
        finally:
            sock.close()
            self.__serving = False

    def _check_error(self):
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
        self.__log_list = []

    def create_log(self, name, port, expect_start_msg=True, depth=None,
                   start_server=True):
        log = SocketReader(name, port, depth)
        self.__log_list.append(log)

        if expect_start_msg:
            log.add_expected_text_regexp(r"Start of log at LOG=(\S+:\d+|"
                                         r"log\(\S+:\d+\)"
                                         r"(\slive\(\S+:\d+\))?)")
        if start_server:
            log.start_serving()

        return log

    def tearDown(self):  # pylint: disable=invalid-name
        for log in self.__log_list:
            log.stop_serving()

        for log in self.__log_list:
            log.check_status(0)

        del self.__log_list[:]


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

    def write(self, msg):
        "Write message to remote logger"
        self.socket.send(msg.encode("utf-8"))

    def write_ts(self, tstamp, logtime=None):
        "Write time-stamped log msg to remote logger"
        if logtime is None:
            logtime = datetime.datetime.now()
        output = "- - [%s] %s" % (logtime, tstamp)
        self.socket.send(output.encode("utf-8"))

    def close(self):
        "Shut down socket to remote server - do this to avoid stale sockets"
        self.socket.close()


class RunXMLValidator(object):
    @classmethod
    def setUp(cls):  # pylint: disable=invalid-name
        if os.path.exists("run.xml"):
            try:
                os.remove("run.xml")
            except:
                raise ValueError("Cannot remove lingering run.xml file")

    @classmethod
    def tearDown(cls):  # pylint: disable=invalid-name
        if os.path.exists("run.xml"):
            try:
                os.remove("run.xml")
            except Exception as exc:  # pylint: disable=broad-except
                print("Cannot remove run.xml: %s" % exc)
            raise ValueError("Found unexpected run.xml file")

    @classmethod
    def validate(cls, test_case, run_num, cfg_name, cluster, start_time,
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

            test_case.assertEqual(run.run_number, run_num,
                                  "Expected run number %s, not %s" %
                                  (run_num, run.run_number))

            test_case.assertEqual(run.run_config_name, cfg_name,
                                  "Expected config \"%s\", not \"%s\"" %
                                  (cfg_name, run.run_config_name))

            test_case.assertEqual(run.cluster_config_name, cluster,
                                  "Expected cluster \"%s\", not \"%s\"" %
                                  (cluster, run.cluster_config_name))

            if start_time is not None:
                test_case.assertEqual(run.start_time, start_time,
                                      "Expected start time %s<%s>,"
                                      " not %s<%s>" %
                                      (start_time, type(start_time).__name__,
                                       run.start_time,
                                       type(run.start_time).__name__))
            if end_time is not None:
                test_case.assertEqual(run.end_time, end_time,
                                      "Expected end time %s<%s>, not %s<%s>" %
                                      (end_time, type(end_time).__name__,
                                       run.end_time,
                                       type(run.end_time).__name__))

            test_case.assertEqual(run.run_status, failed,
                                  "Expected terminal condition %s, not %s" %
                                  (failed, run.run_status))

            test_case.assertEqual(run.num_physics, num_evts,
                                  "Expected number of events %s, not %s" %
                                  (num_evts, run.num_physics))

            test_case.assertEqual(run.num_moni, num_moni,
                                  "Expected number of monitoring events %s, "
                                  "not %s" % (num_moni, run.num_moni))

            test_case.assertEqual(run.num_tcal, num_tcal,
                                  "Expected number of time cal events %s, "
                                  "not %s" % (num_tcal, run.num_tcal))

            test_case.assertEqual(run.num_sn, num_sn,
                                  "Expected number of supernova events %s, "
                                  "not %s" % (num_sn, run.num_sn))
        finally:
            try:
                os.remove("run.xml")
            except:  # pylint: disable=bare-except
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

    @property
    def client_statistics(self):
        return {}

    @property
    def components(self):
        return self.__comps[:]

    @property
    def rates(self):
        return (self.__num_evts, self.__rate, self.__num_moni, self.__num_sn,
                self.__num_tcal)

    @property
    def id(self):  # pylint: disable=invalid-name
        return self.__id

    @property
    def is_running(self):
        return self.__running

    def run_number(self):
        return self.__run_number

    @property
    def server_statistics(self):
        return {}

    def set_run_number(self, new_number):
        self.__run_number = new_number

    def start_mock(self):
        self.__running = True

    def stop_mock(self):
        self.__running = False

    def update_rates(self):
        for comp in self.__comps:
            comp.update_rates()
        return self.rates


class MockTaskManager(object):
    def __init__(self):
        self.__timer_dict = {}
        self.__error = False

    def add_interval_timer(self, timer):
        if timer.name in self.__timer_dict:
            raise Exception("Cannot add multiple timers named \"%s\"" %
                            timer.name)
        self.__timer_dict[timer.name] = timer

    def create_interval_timer(self, name, _):
        if name not in self.__timer_dict:
            raise Exception("Cannot find timer named \"%s\"" % name)
        return self.__timer_dict[name]

    @property
    def has_error(self):
        return self.__error

    def set_error(self, caller_name):  # pylint: disable=unused-argument
        self.__error = True


class MockLiveMoni(object):
    "Emulate LiveMoni"

    def __init__(self):
        self.__exp_moni = {}

    def add_expected(self, var, val, prio, match_dict_values=True):
        if var not in self.__exp_moni:
            self.__exp_moni[var] = []
        self.__exp_moni[var].append((val, prio, match_dict_values))

    @property
    def sent_all_moni(self):
        return len(self.__exp_moni) == 0

    # pylint: disable=redefined-outer-name
    def sendMoni(self, var, val, prio,  # pylint: disable=invalid-name
                 time=None):  # pylint: disable=unused-argument
        if var not in self.__exp_moni:
            raise Exception(("Unexpected live monitor data"
                             " (var=%s, val=%s, prio=%d)") % (var, val, prio))

        exp_data = None
        for index, (val_tmp, prio_tmp, match) in \
          enumerate(self.__exp_moni[var]):
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
            exp_data = self.__exp_moni[var].pop(index)
            break

        if len(self.__exp_moni[var]) == 0:  # pylint: disable=len-as-condition
            del self.__exp_moni[var]

        if exp_data is None:
            raise Exception(("Expected live monitor data "
                             " (var=%s, datapairs=%s), not "
                             "(var=%s, val=%s, prio=%d)") %
                            (var, self.__exp_moni[var], var, val, prio))

        return True
    # pylint: enable=redefined-outer-name
