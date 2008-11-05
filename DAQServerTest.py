#!/usr/bin/env python

import unittest
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

    def logTo(self, logIP, logPort):
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

    def __init__(self, logPort):
        super(MockServer, self).__init__(logIP='localhost', logPort=logPort,
                                         testOnly=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return TinyClient(name, num, host, port, mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(MockServer.APPENDER, quiet)

class TestDAQServer(unittest.TestCase):
    def createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

    def tearDown(self):
        self.__logFactory.tearDown()

        MockServer.APPENDER.checkEmpty()

    def testRegister(self):
        logHost = 'localhost'
        logPort = 11853

        logger = self.createLog('main', logPort)

        dc = MockServer(logPort)

        self.assertEqual(dc.rpc_show_components(), [])

        compId = DAQClient.ID
        compName = 'foo'
        compNum = 0
        compHost = 'localhost'
        compPort = 666
        compMBean = 765

        logger.addExpectedText(('Got registration for ID#%d %s#%d at' +
                                ' %s:%d') %
                               (compId, compName, compNum, compHost, compPort))

        rtnArray = dc.rpc_register_component(compName, compNum, compHost,
                                             compPort, compMBean, [])
        self.assertEquals(4, len(rtnArray),
                          'Expected %d-element array, not %d elements' %
                          (4, len(rtnArray)))
        self.assertEquals(compId, rtnArray[0],
                          'Registration should return client ID#%d, not %d' %
                          (compId, rtnArray[0]))
        self.assertEquals(logHost, rtnArray[1],
                          'Registration should return host %s, not %s' %
                          (logHost, rtnArray[1]))
        self.assertEquals(logPort, rtnArray[2],
                          'Registration should return port#%d, not %d' %
                          (logPort, rtnArray[2]))

        self.assertEqual(dc.rpc_get_num_components(), 1)

        fooStr = 'ID#%d %s#%d at %s:%d M#%d %s' % \
            (DAQClient.ID - 1, compName, compNum, compHost, compPort,
             compMBean, 'idle')
        self.assertEqual(dc.rpc_show_components(), [fooStr])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], DAQClient.ID - 1)
        self.assertEqual(rtnArray[1], 'localhost')
        self.assertEqual(rtnArray[2], logPort)

        logger.checkEmpty()

    def testRegisterWithLog(self):
        logPort = 12345
        
        logger = self.createLog('main', logPort)

        dc = MockServer(logPort)

        logger.waitForEmpty(100)
        logger.checkEmpty()

        newPort = 23456

        newLog = self.createLog('new', newPort)

        dc.rpc_log_to('localhost', newPort)

        newLog.waitForEmpty(100)
        newLog.checkEmpty()

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID

        newLog.addExpectedText(('Got registration for ID#%d %s#%d' +
                                ' at %s:%d M#%d') %
                               (expId, name, num, host, port, mPort))

        rtnArray = dc.rpc_register_component(name, num, host, port, mPort, [])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], expId)
        self.assertEqual(rtnArray[1], 'localhost')
        self.assertEqual(rtnArray[2], newPort)

        newLog.waitForEmpty(100)
        newLog.checkEmpty()

        newLog.addExpectedText('End of log')
        logger.addExpectedText('Reset log to localhost:%d' % logPort)

        dc.rpc_close_log()

        newLog.waitForEmpty(100)
        newLog.checkEmpty()

        logger.waitForEmpty(100)
        logger.checkEmpty()

    def testNoRunset(self):
        logPort = 11545

        logger = self.createLog('main', logPort)

        dc = MockServer(logPort)

        logger.waitForEmpty(100)
        logger.checkEmpty()

        self.assertRaises(ValueError, dc.rpc_runset_break, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1, 'xxx')
        self.assertRaises(ValueError, dc.rpc_runset_log_to, 1, 'xxx', [])
        self.assertRaises(ValueError, dc.rpc_runset_start_run, 1, 1)
        self.assertRaises(ValueError, dc.rpc_runset_status, 1)
        self.assertRaises(ValueError, dc.rpc_runset_stop_run, 1)

        logger.checkEmpty()

    def testRunset(self):
        logPort = 21765

        logger = self.createLog('main', logPort)

        dc = MockServer(logPort)

        logger.waitForEmpty(100)
        logger.checkEmpty()

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

        clientLogger = self.createLog('client', clientPort)

        compName = 'ID#%d %s#%d at %s:%d' % (id, name, num, host, port)

        logger.addExpectedText('Got registration for %s' % compName)

        dc.rpc_register_component(name, num, host, port, mPort, [])

        logger.waitForEmpty(100)
        logger.checkEmpty()

        self.assertEqual(dc.rpc_get_num_components(), 1)
        self.assertEqual(dc.rpc_num_sets(), 0)

        logger.addExpectedText('Built runset with the following components:')

        setId = dc.rpc_runset_make([name])

        logger.waitForEmpty(100)
        logger.checkEmpty()

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 1)

        logger.addExpectedText('%s connected' % compName)

        self.assertEqual(dc.rpc_runset_status(setId), 'OK')

        logger.waitForEmpty(100)
        logger.checkEmpty()

        clientLogger.addExpectedTextRegexp(r'Version info: unknown unknown' +
                                           ' unknown unknown unknown \S+ \S+')

        self.assertEqual(dc.rpc_runset_log_to(setId, clientHost,
                                              [[name, num, clientPort, 'fatal'],
                                               ]), 'OK')

        clientLogger.waitForEmpty(100)
        clientLogger.checkEmpty()

        self.assertEqual(dc.rpc_runset_configure(setId), 'OK')

        self.assertEqual(dc.rpc_runset_configure(setId, 'zzz'), 'OK')

        self.assertEqual(dc.rpc_runset_start_run(setId, 444), 'OK')

        self.assertEqual(dc.rpc_runset_stop_run(setId), 'OK')

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 1)

        self.assertEquals(dc.rpc_runset_break(setId), 'OK')

        self.assertEqual(dc.rpc_get_num_components(), 1)
        self.assertEqual(dc.rpc_num_sets(), 0)

        logger.checkEmpty()

        clientLogger.checkEmpty()

if __name__ == '__main__':
    unittest.main()
