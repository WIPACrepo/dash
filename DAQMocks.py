#!/usr/bin/env python
#
# Classes used for pDAQ unit testing

import datetime, os, re, select, socket, threading, time

from CnCServer import CnCLogger, DAQClient
from DAQConst import DAQPort
from DAQLaunch import RELEASE, getCompJar
import GetIP

try:
    from DAQLive import DAQLive
except:
    class DAQLive:
        SERVICE_NAME = 'unimported'

if os.environ.has_key("PDAQ_HOME"):
    METADIR = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    METADIR = find_pdaq_trunk()


class UnimplementedException(Exception):
    def __init__(self):
        super(UnimplementedException, self).__init__('Unimplemented')

class BaseChecker(object):
    PAT_DAQLOG = re.compile(r'^([^\]]+)\s+\[([^\]]+)\]\s+(.*)$', re.MULTILINE)
    PAT_LIVELOG = re.compile(r'^(\S+)\((\S+):(\S+)\)\s+(\d+)\s+\[([^\]]+)\]' +
                             r'\s+(.*)$', re.MULTILINE)

    def __init__(self):
        pass

    def check(self, checker, msg, debug, setError=True):
        raise UnimplementedException()

class BaseLiveChecker(BaseChecker):
    def __init__(self, varName):
        self.__varName = varName
        super(BaseLiveChecker, self).__init__()

    def __str__(self):
        return '%s:%s=%s' % \
            (self._getShortName(), self.__varName, self._getValue())

    def _checkText(self, checker, msg, debug, setError):
        raise UnimplementedException()

    def _getShortName(self):
        raise UnimplementedException()

    def _getValue(self):
        raise UnimplementedException()

    def _getValueType(self):
        raise UnimplementedException()

    def check(self, checker, msg, debug, setError=True):
        m = BaseChecker.PAT_LIVELOG.match(msg)
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print '*** %s:LFMT: %s' % (name, msg)
                checker.setError('Bad format for %s I3Live message "%s"' %
                                 (name, msg))
            return False

        svcName = m.group(1)
        varName = m.group(2)
        varType = m.group(3)
        msgPrio = m.group(4)
        msgTime = m.group(5)
        msgText = m.group(6)

        if svcName != DAQLive.SERVICE_NAME:
            if setError:
                name = str(checker)
                if debug:
                    print '*** %s:SVC: %s (%s)' % \
                        (name, DAQLive.SERVICE_NAME, self._getValue())
                checker.setError(('Expected %s I3Live service "%s", not "%s"' +
                                  ' in "%s"') %
                                 (name, DAQLive.SERVICE_NAME, svcName, msg))
            return False

        if varName != self.__varName:
            if setError:
                name = str(checker)
                if debug:
                    print '*** %s:VAR: %s (%s)' % \
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
                    print '*** %s:TYPE: %s (%s)' % \
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
                    print '*** %s:XACT: %s' % (name, self.__text)
                checker.setError(('Expected %s exact log message "%s",' +
                                  ' not "%s"') % (name, self.__text, msg))
            return False

        return True

class LiveChecker(BaseLiveChecker):
    def __init__(self, varName, value):
        self.__value = value
        super(LiveChecker, self).__init__(varName)

    def _checkText(self, checker, msg, debug, setError):
        if msg != str(self.__value):
            if setError:
                name = str(checker)
                if debug:
                    print '*** %s:LIVE: %s' % (name, str(self.__value))
                checker.setError('Expected %s live log message "%s", not "%s"' %
                                 (name, str(self.__value), msg))
            return False

        return True

    def _getShortName(self):
        return 'LIVE'

    def _getValue(self):
        return self.__value

    def _getValueType(self):
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
                    print '*** %s:RLIV: %s' % (name, self.__regexp.pattern)
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
                    print '*** %s:REXP: %s' % (name, self.__regexp.pattern)
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
                    print '*** %s:RFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern)
                checker.setError('Bad format for %s log message "%s"' %
                                 (name, msg))
            return False

        m = self.__regexp.match(m.group(3))
        if not m:
            if setError:
                name = str(checker)
                if debug:
                    print '*** %s:RTXT: %s' % (name, self.__regexp.pattern)
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
                    print '*** %s:TFMT: %s' % \
                        (name, BaseChecker.PAT_DAQLOG.pattern)
                checker.setError('Bad format for %s log message "%s"' %
                                 (name, msg))
            return False

        if m.group(3).find(self.__text) == -1:
            if setError:
                name = str(checker)
                if debug:
                    print '*** %s:TEXT: %s' % (name, self.__text)
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

    def __init__(self, prefix, name, isLive=False, depth=5):
        self.__prefix = prefix
        self.__name = name
        self.__isLive = isLive
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
            print '%s: %s' % (str(self), msg)

        if len(self.__expMsgs) == 0:
            if LogChecker.DEBUG:
                print '*** %s:UNEX' % str(self)
            self.setError('Unexpected %s log message: %s' % (str(self), msg))
            return False

        found = None
        for i in range(self.__depth):
            if i >= len(self.__expMsgs):
                break
            if self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, False):
                found = i
                break

        if found is None:
            print '----------'
            print msg
            print '----------'
            for i in range(self.__depth):
                if i >= len(self.__expMsgs):
                    break
                self.__expMsgs[i].check(self, msg, LogChecker.DEBUG, True)
            return False

        del self.__expMsgs[found]

        return True

    def addExpectedExact(self, msg):
        self.__expMsgs.append(ExactChecker(msg))

    def addExpectedLiveMoni(self, varName, value):
        self.__expMsgs.append(LiveChecker(varName, value))

    def addExpectedRegexp(self, msg):
        self.__expMsgs.append(RegexpChecker(msg))

    def addExpectedText(self, msg):
        if self.__isLive:
            self.__expMsgs.append(LiveChecker('log', str(msg)))
        else:
            self.__expMsgs.append(TextChecker(msg))

    def addExpectedTextRegexp(self, msg):
        if self.__isLive:
            self.__expMsgs.append(LiveRegexpChecker('log', msg))
        else:
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
        raise UnimplementedException()

class MockAppender(LogChecker):
    def __init__(self, name):
        super(MockAppender, self).__init__('LOG', name)

    def close(self):
        pass

    def setError(self, msg):
        raise Exception(msg)

    def write(self, m, time=None):
        self._checkMsg(m)

class MockCnCLogger(CnCLogger):
    def __init__(self, appender, quiet=False):
        #if appender is None: raise Exception('Appender cannot be None')
        self.__appender = appender

        super(MockCnCLogger, self).__init__(appender, True)

class MockConnection(object):
    def __init__(self, type, port=None):
        "port is set for input connections, None for output connections"
        self.type = type
        self.port = port

    def __str__(self):
        if self.port is not None:
            return '%d=>%s' % (self.port, self.type)
        return '=>' + self.type

    def isInput(self):
        return self.port is not None

class MockComponent(object):
    def __init__(self, name, num, host='localhost'):
        self.__name = name
        self.__num = num
        self.__host = host

        self.__connectors = []
        self.__cmdOrder = None

        self.runNum = None

        self.__isSrc = name.endswith("Hub") or name == "amandaTrigger"
        self.__connected = False
        self.__configured = False
        self.__configWait = 0;
        self.__monitorState = '???'

    def __str__(self):
        outStr = self.fullName()
        extra = []
        if self.__isSrc:
            extra.append('SRC')
        if self.__configured:
            extra.append('CFG')
        for conn in self.__connectors:
            extra.append(str(conn))
            
        if len(extra) > 0:
            outStr += '[' + ','.join(extra) + ']'
        return outStr

    def addInput(self, type, port):
        self.__connectors.append(MockConnection(type, port))

    def addOutput(self, type):
        self.__connectors.append(MockConnection(type, None))

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

    def fullName(self):
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    def getConfigureWait(self):
        return self.__configWait

    def host(self):
        return self.__host

    def isComponent(self, name, num):
        return self.__name == name

    def isConfigured(self):
        return self.__configured

    def isSource(self):
        return self.__isSrc

    def logTo(self, logIP, logPort, liveIP, livePort):
        pass

    def monitor(self):
        return self.__monitorState

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def order(self):
        return self.__cmdOrder

    def reset(self):
        self.__connected = False
        self.__configured = False
        self.runNum = None

    def setConfigureWait(self, waitNum):
        self.__configWait = waitNum

    def setOrder(self, num):
        self.__cmdOrder = num

    def startRun(self, runNum):
        if not self.__configured:
            raise Exception(self.__name + ' has not been configured')

        self.runNum = runNum

    def state(self):
        if not self.__connected:
            return 'idle'
        if not self.__configured or self.__configWait > 0:
            if self.__configured and self.__configWait > 0:
                self.__configWait -= 1
            return 'connected'
        if not self.runNum:
            return 'ready'

        return 'running'

    def stopRun(self):
        if self.runNum is None:
            raise Exception(self.__name + ' is not running')

        self.runNum = None

class MockDeployComponent(object):
    def __init__(self, name, id, level, jvm, jvmArgs):
        self.compName = name
        self.compID = id
        self.logLevel = level
        self.jvm = jvm
        self.jvmArgs = jvmArgs

class MockDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors,
                 appender, outLinks=None):

        self.__appender = appender

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

    def createCnCLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet)

    def reset(self):
        self.__state = 'idle'
        return super(MockDAQClient, self).reset()

    def startRun(self, runNum):
        self.__state = 'running'
        return super(MockDAQClient, self).startRun(runNum)

    def state(self):
        return self.__state

class MockIntervalTimer(object):
    def __init__(self, interval):
        self.__isTime = False
        self.__gotTime = False

    def gotTime(self):
        return self.__gotTime

    def isTime(self):
        self.__gotTime = True
        return self.__isTime

    def reset(self):
        self.__isTime = False
        self.__gotTime = False

    def trigger(self):
        self.__isTime = True
        self.__gotTime = False

class MockLogger(LogChecker):
    def __init__(self, name):
        super(MockLogger, self).__init__('LOG', name)

    def close(self):
        pass

    def debug(self, m): self._checkMsg(m)

    def error(self, m): self._checkMsg(m)

    def fatal(self, m): self._checkMsg(m)

    def info(self, m): self._checkMsg(m)

    def setError(self, msg):
        raise Exception(msg)

    def trace(self, m): self._checkMsg(m)

    def warn(self, m): self._checkMsg(m)

class MockParallelShell(object):
    BINDIR = os.path.join(METADIR, 'target', 'pDAQ-%s-dist' % RELEASE, 'bin')

    def __init__(self):
        self.__exp = []

    def __checkCmd(self, cmd):
        expLen = len(self.__exp)
        if expLen == 0:
            raise Exception('Did not expect command "%s"' % cmd)

        found = None
        for i in range(expLen):
            if cmd == self.__exp[i]:
                found = i
                break

        if found is None:
            raise Exception('Command not found in expected command list: ' \
                                'cmd="%s"' % (cmd))

        del self.__exp[found]

    def __isLocalhost(self, host):
        return host == 'localhost' or host == '127.0.0.1'

    def add(self, cmd):
        self.__checkCmd(cmd)

    def addExpectedJava(self, comp, configDir, logPort, livePort,
                        verbose, eventCheck, host):

        ipAddr = GetIP.getIP(host)
        jarPath = os.path.join(MockParallelShell.BINDIR,
                               getCompJar(comp.compName))

        if verbose:
            redir = ''
        else:
            redir = ' </dev/null >/dev/null 2>&1'

        cmd = '%s %s' % (comp.jvm, comp.jvmArgs)

        if eventCheck and comp.compName == 'eventBuilder':
            cmd += ' -Dicecube.daq.eventBuilder.validateEvents'

        cmd += ' -jar %s' % jarPath
        cmd += ' -g %s' % configDir
        cmd += ' -c %s:%d' % (ipAddr, DAQPort.CNCSERVER)

        if logPort is not None:
            cmd += ' -l %s:%d,%s' % (ipAddr, logPort, comp.logLevel)
        if livePort is not None:
            cmd += ' -L %s:%d,%s' % (ipAddr, livePort, comp.logLevel)
        cmd += ' %s &' % redir

        if self.__isLocalhost(host):
            self.__exp.append(cmd)
        else:
            self.__exp.append(('ssh -n %s \'sh -c "%s"%s &\'') %
                              (host, cmd, redir))

    def addExpectedJavaKill(self, compName, killWith9, verbose, host):
        if killWith9:
            nineArg = '-9'
        else:
            nineArg = ''

        user = os.environ['USER']
        jar = getCompJar(compName)

        if self.__isLocalhost(host):
            sshCmd = ''
            pkillOpt = ' -fu %s' % user
        else:
            sshCmd = 'ssh %s ' % host
            pkillOpt = ' -f'

        self.__exp.append('%spkill %s%s %s' % (sshCmd, nineArg, pkillOpt, jar))

        if not killWith9:
            self.__exp.append('sleep 2; %spkill -9%s %s' %
                              (sshCmd, pkillOpt, jar))

    def addExpectedPython(self, doLive, doDAQRun, doCnC, dashDir, configDir,
                          logDir, spadeDir, cfgName, copyDir, logPort,
                          livePort):
        if doLive:
            cmd = os.path.join(dashDir, 'DAQLive.py')
            cmd += ' &'
            self.__exp.append(cmd)

        if doDAQRun:
            cmd = os.path.join(dashDir, 'DAQRun.py')
            cmd += ' -r -f'
            cmd += ' -c %s' % configDir
            cmd += ' -l %s' % logDir
            cmd += ' -s %s' % spadeDir
            cmd += ' -u %s' % cfgName
            if livePort is not None:
                if logPort is not None:
                    cmd += " -B"
                else:
                    cmd += " -L"
            cmd += ' -a %s' % copyDir
            self.__exp.append(cmd)

        if doCnC:
            cmd = os.path.join(dashDir, 'CnCServer.py')
            if logPort is not None:
                cmd += ' -l localhost:%d' % logPort
            if livePort is not None:
                cmd += ' -L localhost:%d' % livePort
            cmd += ' -d'
            self.__exp.append(cmd)

    def addExpectedPythonKill(self, doLive, doDAQRun, doCnC, dashDir,
                              killWith9):
        if killWith9:
            nineArg = '-9 '
        else:
            nineArg = ''

        user = os.environ['USER']

        if doLive:
            path = os.path.join(dashDir, 'DAQLive.py')
            self.__exp.append('%s -k' % path)

        if doDAQRun:
            path = os.path.join(dashDir, 'DAQRun.py')
            self.__exp.append('%s -k' % path)

        if doCnC:
            path = os.path.join(dashDir, 'CnCServer.py')
            self.__exp.append('%s -k' % path)

    def check(self):
        if len(self.__exp) > 0:
            raise Exception('ParallelShell did not receive expected commands:' +
                            ' %s' % str(self.__exp))

    def getMetaPath(self, subdir):
        return os.path.join(METADIR, subdir)

    def showAll(self):
        raise Exception('SHOWALL')

    def start(self):
        pass

    def system(self, cmd):
        self.__checkCmd(cmd)

    def wait(self):
        pass

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

    def id(self): return self.__id
    def inetAddress(self): return self.__inetAddr
    def isHub(self): return self.__name.endswith("Hub")
    def mbeanPort(self): return self.__mbeanPort
    def name(self): return self.__name
    def rpcPort(self): return self.__rpcPort

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
            print 'Conn[%s:%s]' % (self.name, self.num)
            for l in list:
                print '  %s:%s#%d' % (l['type'], l['compName'], l['compNum'])

        # make a copy of the links
        #
        tmpLinks = {}
        for k in self.outLinks.keys():
            tmpLinks[k] = []
            tmpLinks[k][0:] = self.outLinks[k][0:len(self.outLinks[k])]

        for l in list:
            if not tmpLinks.has_key(l['type']):
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
                raise ValueError(('Component %s#%d should not connect to' +
                                  ' %s:%s%%d') %
                                 (self.name, self.num, l['type'], l['compName'],
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
    def __init__(self, name, port):
        self.__port = port

        self.__errMsg = None

        self.__thread = None
        self.__serving = False

        isLive = (self.__port == DAQPort.I3LIVE)
        super(SocketReader, self).__init__('SOC', name,
                                           isLive=isLive)

    def __bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.__port))
        except socket.error, e:
            raise socket.error('Cannot bind SocketReader to port %d: %s' %
                               (self.__port, str(e)))
        return sock

    def __listener(self, sock):
        """
        Create listening, non-blocking UDP socket, read from it, and write to file;
        close socket and end thread if signaled via self.__thread variable.
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
                while 1: # Slurp up waiting packets, return to select if EAGAIN
                    try:
                        data = sock.recv(8192, socket.MSG_DONTWAIT)
                    except Exception:
                        break # Go back to select so we don't busy-wait
                    if not self._checkMsg(data):
                        break
        finally:
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

    def getPort(self): return self.__port

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
            raise Exception('Socket reader %s is already running' % self.__name)

        if os.name == "nt":
            sock = self.__win_bind()
            listener = self.__win_listener
        else:
            sock = self.__bind()
            listener = self.__listener

        self.__thread = threading.Thread(target=listener, args=(sock, ))

        self.__thread.start()
        while not self.__serving:
            time.sleep(.001)

class SocketReaderFactory(object):
    def __init__(self):
        self.__logList = []

    def createLog(self, name, port, expectStartMsg=True):
        log = SocketReader(name, port)
        self.__logList.append(log)

        if expectStartMsg:
            log.addExpectedTextRegexp(r'^Start of log at (\S+:\d+|' +
                                      r'log\(\S+:\d+\)\+live\(\S+:\d+\))$')
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
        except socket.error, err:
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
