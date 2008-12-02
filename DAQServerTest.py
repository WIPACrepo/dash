#!/usr/bin/env python

import socket, unittest
from CnCServer import DAQClient, DAQServer

from DAQMocks import MockAppender, MockCnCLogger, \
    SocketReaderFactory, SocketWriter

class TinyClient(object):
    def __init__(self, name, num, host, port, mbeanPort, connectors):
        self.name = name
        self.num = num
        self.connectors = connectors

        self.id = DAQClient.ID
        DAQClient.ID += 1

        self.__host = host
        self.__port = port
        self.__mbeanPort = mbeanPort

        self.__state = 'idle'
        self.__order = None

    def __str__(self):
        if self.__mbeanPort == 0:
            mStr = ''
        else:
            mStr = ' M#%d' % self.__mbeanPort
        return 'ID#%d %s#%d at %s:%d%s' % \
            (self.id, self.name, self.num, self.__host, self.__port, mStr)

    def configure(self, cfgName=None):
        self.__state = 'ready'

    def connect(self, connList=None):
        self.__state = 'connected'

    def getName(self):
        return self.name

    def getOrder(self):
        return self.__order

    def getState(self):
        return self.__state

    def isComponent(self, name, num=-1):
        return self.name == name and (num < 0 or self.num == num)

    def isSource(self):
        return True

    def logTo(self, logIP, logPort, liveIP, livePort):
        if liveIP is not None and livePort is not None:
            raise Exception('Cannot log to I3Live')

        self.__log = SocketWriter(logIP, logPort)
        self.__log.write_ts('Start of log at %s:%d' % (logIP, logPort))
        self.__log.write_ts('Version info: unknown unknown unknown unknown' +
                            ' unknown BRANCH 0:0')

    def reset(self):
        self.__state = 'idle'

    def resetLogging(self):
        pass

    def setOrder(self, orderNum):
        self.__order = orderNum

    def startRun(self, runNum):
        self.__state = 'running'

    def stopRun(self):
        self.__state = 'ready'

class MockServer(DAQServer):
    APPENDER = MockAppender('server')

    def __init__(self, logPort, livePort):
        super(MockServer, self).__init__(logIP='localhost', logPort=logPort,
                                         liveIP='localhost', livePort=livePort,
                                         testOnly=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return TinyClient(name, num, host, port, mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(MockServer.APPENDER, quiet)

class TestDAQServer(unittest.TestCase):
    def __createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def __verifyRegArray(self, rtnArray, expId, logHost, logPort,
                         liveHost, livePort):
        numElem = 6
        self.assertEquals(numElem, len(rtnArray),
                          'Expected %d-element array, not %d elements' %
                          (numElem, len(rtnArray)))
        self.assertEquals(expId, rtnArray[0],
                          'Registration should return client ID#%d, not %d' %
                          (expId, rtnArray[0]))
        self.assertEquals(logHost, rtnArray[1],
                          'Registration should return host %s, not %s' %
                          (logHost, rtnArray[1]))
        self.assertEquals(logPort, rtnArray[2],
                          'Registration should return port#%d, not %d' %
                          (logPort, rtnArray[2]))
        self.assertEquals(liveHost, rtnArray[3],
                          'Registration should return livehost %s, not %s' %
                          (liveHost, rtnArray[3]))
        self.assertEquals(livePort, rtnArray[4],
                          'Registration should return liveport#%d, not %d' %
                          (livePort, rtnArray[4]))

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

    def tearDown(self):
        self.__logFactory.tearDown()

        MockServer.APPENDER.checkStatus(10)

    def testRegister(self):
        logHost = 'localhost'
        logPort = 11853

        logger = self.__createLog('file', logPort)

        liveHost = 'localhost'
        livePort = 35811

        liver = self.__createLog('live', livePort, False)

        dc = MockServer(logPort, livePort)

        self.assertEqual(dc.rpc_show_components(), [])

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID

        logger.addExpectedText('Got registration for ID#%d %s#%d at %s:%d' %
                               (expId, name, num, host, port))
        liver.addExpectedText('Got registration for ID#%d %s#%d at %s:%d' %
                              (expId, name, num, host, port))

        rtnArray = dc.rpc_register_component(name, num, host, port, mPort, [])

        localAddr = socket.gethostbyaddr(socket.gethostname())[2][0]

        self.__verifyRegArray(rtnArray, expId, localAddr, logPort,
                              localAddr, livePort)

        self.assertEqual(dc.rpc_get_num_components(), 1)

        fooStr = 'ID#%d %s#%d at %s:%d M#%d %s' % \
            (DAQClient.ID - 1, name, num, host, port, mPort, 'idle')
        self.assertEqual(dc.rpc_show_components(), [fooStr])

        logger.checkStatus(100)
        liver.checkStatus(100)

    def testRegisterWithLog(self):
        oldPort = 12345
        
        oldLog = self.__createLog('old', oldPort)

        dc = MockServer(oldPort, None)

        oldLog.checkStatus(100)

        logHost = 'localhost'
        logPort = 23456

        logger = self.__createLog('file', logPort)

        liveHost = ''
        livePort = 0

        dc.rpc_log_to(logHost, logPort, liveHost, livePort)

        logger.checkStatus(100)

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID

        logger.addExpectedText(('Got registration for ID#%d %s#%d at %s:%d' +
                                ' M#%d') %
                               (expId, name, num, host, port, mPort))

        rtnArray = dc.rpc_register_component(name, num, host, port, mPort, [])

        localAddr = socket.gethostbyaddr(socket.gethostname())[2][0]

        self.__verifyRegArray(rtnArray, expId, localAddr, logPort,
                              localAddr, livePort)

        logger.checkStatus(100)

        logger.addExpectedText('End of log')
        oldLog.addExpectedText('Reset log to localhost:%d' % oldPort)

        dc.rpc_close_log()

        logger.checkStatus(100)
        oldLog.checkStatus(100)

    def testNoRunset(self):
        logPort = 11545

        logger = self.__createLog('main', logPort)

        dc = MockServer(logPort, None)

        logger.checkStatus(100)

        self.assertRaises(ValueError, dc.rpc_runset_break, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1, 'xxx')
        self.assertRaises(ValueError, dc.rpc_runset_log_to, 1, 'xxx', [])
        self.assertRaises(ValueError, dc.rpc_runset_start_run, 1, 1)
        self.assertRaises(ValueError, dc.rpc_runset_status, 1)
        self.assertRaises(ValueError, dc.rpc_runset_stop_run, 1)

        logger.checkStatus(100)

    def testRunset(self):
        logPort = 21765

        logger = self.__createLog('main', logPort)

        dc = MockServer(logPort, None)

        logger.checkStatus(100)

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 0)
        self.assertEqual(dc.rpc_show_components(), [])

        id = DAQClient.ID
        name = 'foo'
        num = 99
        host = 'localhost'
        port = 666
        mPort = 0

        clientHost = 'localhost'
        clientPort = 21567

        clientLogger = self.__createLog('client', clientPort)

        compName = 'ID#%d %s#%d at %s:%d' % (id, name, num, host, port)

        logger.addExpectedText('Got registration for %s' % compName)

        dc.rpc_register_component(name, num, host, port, mPort, [])

        logger.checkStatus(100)

        self.assertEqual(dc.rpc_get_num_components(), 1)
        self.assertEqual(dc.rpc_num_sets(), 0)

        logger.addExpectedText('Built runset with the following components:')

        setId = dc.rpc_runset_make([name])

        logger.checkStatus(100)

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 1)

        logger.addExpectedText('%s connected' % compName)

        self.assertEqual(dc.rpc_runset_status(setId), 'OK')

        logger.checkStatus(100)

        clientLogger.addExpectedTextRegexp(r'Version info: unknown unknown' +
                                           ' unknown unknown unknown \S+ \S+')

        self.assertEqual(dc.rpc_runset_log_to(setId, clientHost,
                                              [[name, num, clientPort, 'fatal'],
                                               ]), 'OK')

        clientLogger.checkStatus(100)

        self.assertEqual(dc.rpc_runset_configure(setId), 'OK')

        self.assertEqual(dc.rpc_runset_configure(setId, 'zzz'), 'OK')

        self.assertEqual(dc.rpc_runset_start_run(setId, 444), 'OK')

        self.assertEqual(dc.rpc_runset_stop_run(setId), 'OK')

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 1)

        self.assertEquals(dc.rpc_runset_break(setId), 'OK')

        self.assertEqual(dc.rpc_get_num_components(), 1)
        self.assertEqual(dc.rpc_num_sets(), 0)

        logger.checkStatus(10)
        clientLogger.checkStatus(10)

if __name__ == '__main__':
    unittest.main()
