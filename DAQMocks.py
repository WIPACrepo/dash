#!/usr/bin/env python
#
# Classes used for pDAQ unit testing

import datetime, os, re, select, socket, threading, time

from CnCServer import CnCLogger, DAQClient

class LogChecker(object):
    DEBUG = False

    TYPE_EXACT = 1
    TYPE_TEXT = 2
    TYPE_REGEXP = 3
    TYPE_RETEXT = 4

    PAT_DAQLOG = re.compile(r'^([^\]]+)\s+\[([^\]]+)\]\s+(.*)$', re.MULTILINE)

    def __init__(self, prefix, name, debug):
        self.__prefix = prefix
        self.__name = name
        self.__debug = debug

        self.__expMsgs = []

    def __str__(self):
        return '%s-%s(exp#%d)' % \
            (self.__prefix, self.__name, len(self.__expMsgs))

    def addExpectedExact(self, msg):
        self.__expMsgs.append((msg, LogChecker.TYPE_EXACT))

    def addExpectedRegexp(self, msg):
        pat = re.compile(msg)
        self.__expMsgs.append((pat, LogChecker.TYPE_REGEXP))

    def addExpectedText(self, msg):
        self.__expMsgs.append((msg, LogChecker.TYPE_TEXT))

    def addExpectedTextRegexp(self, msg):
        pat = re.compile(msg)
        self.__expMsgs.append((pat, LogChecker.TYPE_RETEXT))

    def checkEmpty(self):
        if len(self.__expMsgs) != 0:
            fixed = []
            for m in self.__expMsgs:
                (expMsg, matchType) = m
                if matchType == LogChecker.TYPE_EXACT:
                    fixed.append('EXACT:%s' % expMsg)
                elif matchType == LogChecker.TYPE_TEXT:
                    fixed.append('TEXT:%s' % expMsg)
                elif matchType == LogChecker.TYPE_REGEXP:
                    fixed.append('REGEXP:%s' % expMsg.pattern)
                elif matchType == LogChecker.TYPE_RETEXT:
                    fixed.append('RETEXT:%s' % expMsg.pattern)

            raise Exception("Didn't receive %d expected %s log messages: %s" %
                            (len(fixed), self.__name, str(fixed)))

    def checkMsg(self, msg):
        if self.__debug:
            print '%s-%s: %s' % (self.__prefix, self.__name, msg)

        if len(self.__expMsgs) == 0:
            if self.__debug:
                print '%s-%s:UNEX' % (self.__prefix, self.__name)
            self.setError('Unexpected %s log message: %s' %
                            (self.__name, msg))
            return

        (expMsg, matchType) = self.__expMsgs[0]

        if matchType == LogChecker.TYPE_EXACT:
            if msg != expMsg:
                if self.__debug:
                    print '%s-%s:XACT: %s' % (self.__prefix, self.__name,
                                              expMsg)
                self.setError('Expected %s exact log message "%s", not "%s"' %
                              (self.__name, expMsg, msg))
                return

        elif matchType == LogChecker.TYPE_REGEXP:
            m = expMsg.match(msg)
            if not m:
                if self.__debug:
                    print '%s-%s:REXP: %s' % (self.__prefix, self.__name,
                                              expMsg.pattern)
                self.setError(('Expected %s regexp log message of "%s",' +
                               ' not "%s"') %
                              (self.__name, expMsg.pattern, msg))
                return

        elif matchType == LogChecker.TYPE_TEXT or \
                matchType == LogChecker.TYPE_RETEXT:
            m = LogChecker.PAT_DAQLOG.match(msg)
            if not m:
                if self.__debug:
                    print '%s-%s:FMT: %s' % (self.__prefix, self.__name,
                                             expMsg)
                self.setError('Bad format for %s log message "%s"' %
                              (self.__name, msg))
                return

            txt = m.group(3)
            if matchType == LogChecker.TYPE_TEXT and \
                    txt.find(expMsg) == -1:
                if self.__debug:
                    print '%s-%s:TEXT: %s' % (self.__prefix, self.__name,
                                              expMsg)
                self.setError(('Expected %s partial log message of "%s",' +
                               ' not "%s"') % (self.__name, expMsg, txt))
                return

            elif matchType == LogChecker.TYPE_RETEXT:
                m = expMsg.match(txt)
                if not m:
                    if self.__debug:
                        print '%s-%s:RTXT: %s' % (self.__prefix, self.__name,
                                                  expMsg.pattern)
                    self.setError(('Expected %s regexp text log message,' +
                                   ' of "%s" not "%s"') %
                                  (self.__name, expMsg.pattern, msg))
                    return

        else:
            if self.__debug:
                print '%s-%s:????: Unknown match type %s' % \
                    (self.__prefix, self.__name, str(matchType))
                self.setError('Unknown match type %s' % str(matchType))
                return

        del self.__expMsgs[0]

    def isEmpty(self):
        return len(self.__expMsgs) == 0

    def waitForEmpty(self, reps):
        count = 0
        while len(self.__expMsgs) > 0 and count < reps:
            time.sleep(.001)
            count += 1
        return len(self.__expMsgs) == 0

class MockAppender(LogChecker):
    def __init__(self, name):
        super(MockAppender, self).__init__('LOG', name, LogChecker.DEBUG)

    def close(self):
        pass

    def setError(self, msg):
        raise Exception(msg)

    def write(self, m):
        self.checkMsg(m)

class MockCnCLogger(CnCLogger):
    def __init__(self, appender, quiet=False):
        if appender is None: raise Exception('Appender cannot be None')
        self.__appender = appender

        super(MockCnCLogger, self).__init__(appender, True)

class MockConnection(object):
    def __init__(self, type, isInput):
        self.type = type
        self.isInput = isInput

class MockComponent(object):
    def __init__(self, name, num, host='localhost', isSrc=False):
        self.name = name
        self.num = num
        self.host = host

        self.connectors = []
        self.cmdOrder = None

        self.runNum = None

        self.__isSrc = isSrc
        self.__connected = False
        self.__configured = False
        self.__configWait = 0;
        self.__monitorState = '???'

    def __str__(self):
        if self.__configured:
            cfgStr = ' [Configured]'
        else:
            cfgStr = ''
        return self.getName() + cfgStr

    def addInput(self, type):
        self.connectors.append(MockConnection(type, True))

    def addOutput(self, type):
        self.connectors.append(MockConnection(type, False))

    def configure(self, configName=None):
        if not self.__connected:
            self.__connected = True
        self.__configured = True
        return 'OK'

    def connect(self, conn=None):
        self.__connected = True
        return 'OK'

    def getConfigureWait(self):
        return self.__configWait

    def getName(self):
        if self.num == 0 and self.name[-3:].lower() != 'hub':
            return self.name
        return '%s#%d' % (self.name, self.num)

    def getOrder(self):
        return self.cmdOrder

    def getState(self):
        if not self.__connected:
            return 'idle'
        if not self.__configured or self.__configWait > 0:
            if self.__configured and self.__configWait > 0:
                self.__configWait -= 1
            return 'connected'
        if not self.runNum:
            return 'ready'

        return 'running'

    def isComponent(self, name, num):
        return self.name == name

    def isConfigured(self):
        return self.__configured

    def isSource(self):
        return self.__isSrc

    def logTo(self, logIP, logPort):
        pass

    def monitor(self):
        return self.__monitorState

    def reset(self):
        self.__connected = False
        self.__configured = False
        self.runNum = None

    def setConfigureWait(self, waitNum):
        self.__configWait = waitNum

    def setOrder(self, num):
        self.cmdOrder = num

    def startRun(self, runNum):
        if not self.__configured:
            raise Exception(self.name + ' has not been configured')

        self.runNum = runNum

    def stopRun(self):
        if self.runNum is None:
            raise Exception(self.name + ' is not running')

        self.runNum = None

class MockDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors,
                 appender, outLinks=None):

        self.__appender = appender

        self.outLinks = outLinks
        self.state = 'idle'

        super(MockDAQClient, self).__init__(name, num, host, port, mbeanPort,
                                            connectors, True)

    def __str__(self):
        tmpStr = super(MockDAQClient, self).__str__()
        return 'Mock' + tmpStr

    def closeLog(self):
        pass

    def configure(self, cfgName):
        self.state = 'ready'
        return super(MockDAQClient, self).configure(cfgName)

    def connect(self, links=None):
        self.state = 'connected'
        return super(MockDAQClient, self).connect(links)

    def createClient(self, host, port):
        return MockRPCClient(self.name, self.num, self.outLinks)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet)

    def getState(self):
        return self.state

    def reset(self):
        self.state = 'idle'
        return super(MockDAQClient, self).reset()

    def startRun(self, runNum):
        self.state = 'running'
        return super(MockDAQClient, self).startRun(runNum)

class MockLogger(LogChecker):
    def __init__(self, name):
        super(MockLogger, self).__init__('LOG', name, LogChecker.DEBUG)

    def close(self):
        pass

    def debug(self, m): self.checkMsg(m)

    def error(self, m): self.checkMsg(m)

    def fatal(self, m): self.checkMsg(m)

    def info(self, m): self.checkMsg(m)

    def setError(self, msg):
        raise Exception(msg)

    def trace(self, m): self.checkMsg(m)

    def warn(self, m): self.checkMsg(m)

class MockRPCClient(object):
    def __init__(self, name, num, outLinks=None):
        self.xmlrpc = MockXMLRPC(name, num, outLinks)

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

    def logTo(self, logIP, port, level=None):
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

        super(SocketReader, self).__init__('SOC', name, SocketReader.DEBUG)

    def __listener(self):
        """
        Create listening, non-blocking UDP socket, read from it, and write to file;
        close socket and end thread if signaled via self.__thread variable.
        """
                 
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.__port))
        except:
            print 'Cannot bind SocketReader to port %d' % self.__port
            raise

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
                        self.checkMsg(data)
                    except Exception:
                        break # Go back to select so we don't busy-wait
        finally:
            sock.close()
            self.__serving = False

    def __win_listener(self):
        """
        Windows version of listener - no select().
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #sock.setblocking(1)
        #sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.__port))

        self.__serving = True
        try:
            while self.__thread is not None:
                data = sock.recv(8192)
                self.checkMsg(data)
        finally:
            sock.close()
            self.__serving = False

    def getError(self): return self.__errMsg

    def getPort(self): return self.__port

    def isError(self): return self.__errMsg is not None

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
            self.__thread = threading.Thread(target=self.__win_listener)
        else:
            self.__thread = threading.Thread(target=self.__listener)

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
            log.addExpectedTextRegexp(r'^Start of log at \S+:\d+$')
        log.startServing()

        return log

    def tearDown(self):
        for l in self.__logList:
            l.stopServing()

        for l in self.__logList:
            l.checkEmpty()
            if l.isError():
                raise Exception(l.getError())

        del self.__logList[:]

class SocketWriter(object):
    def __init__(self, node, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.connect((node, port))

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
