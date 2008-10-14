#!/usr/bin/env python

import time, unittest
from CnCServer import DAQClient, DAQServer
from DAQLog import SocketLogger

class MockXMLRPC:
    def __init__(self):
        pass

    def configure(self, name=None):
        pass

    def connect(self, name=None):
        return 'OK'

    def getState(self):
        pass

    def getVersionInfo(self):
        return ''

    def logTo(self, logIP, port):
        pass

    def reset(self):
        pass

    def resetLogging(self):
        pass

    def startRun(self, runNum):
        pass

    def stopRun(self):
        pass

class MockRPCClient:
    def __init__(self, host, port):
        self.xmlrpc = MockXMLRPC()

class MockLogger(object):
    def __init__(self):
        self.expMsgs = []

    def __checkMsg(self, msg):
        if len(self.expMsgs) == 0:
            raise Exception('Unexpected log message: %s' % msg)
        if self.expMsgs[0] != msg:
            raise Exception('Expected log message "%s", not "%s"' %
                            (self.expMsgs[0], msg))
        del self.expMsgs[0]

    def addExpected(self, msg):
        self.expMsgs.append(msg)

    def checkEmpty(self):
        if len(self.expMsgs) != 0:
            raise Exception("Didn't receive %d expected log messages: %s" %
                            (len(self.expMsgs), str(self.expMsgs)))

    def log(self, s):
        self.__checkMsg(s)

    def write_ts(self, s):
        self.__checkMsg(s)

class MockClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors):

        self.state = 'idle'
        self.logger = None

        super(MockClient, self).__init__(name, num, host, port, mbeanPort,
                                         connectors)

    def configure(self, cfgName):
        self.state = 'ready'
        return super(MockClient, self).configure(cfgName)

    def connect(self, connMap=None):
        self.state = 'connected'
        return super(MockClient, self).connect(connMap)

    def createClient(self, host, port):
        return MockRPCClient(host, port)

    def createLogger(self, host, port):
        return self.logger

    def getState(self):
        return self.state

    def reset(self):
        self.state = 'idle'
        return super(MockClient, self).reset()

    def setLogger(self, logger):
        self.logger = logger

    def startRun(self, runNum):
        self.state = 'running'
        return super(MockClient, self).startRun(runNum)

class MockServer(DAQServer):
    def __init__(self, logger):
        self.__logger = logger

        super(MockServer, self).__init__(testOnly=True)

    def checkLog(self, expHost, expPort):
        return self.logIP == expHost and self.logPort == expPort

    def closeLog(self):
        self.logIP = None
        self.logPort = None

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return MockClient(name, num, host, port, mbeanPort, connectors)

    def logmsg(self, msg):
        self.__logger.log(msg)

    def openLog(self, host, port):
        self.logIP = host
        self.logPort = port

class TestDAQServer(unittest.TestCase):
    def testRegister(self):
        logger = MockLogger()

        dc = MockServer(logger)

        self.assertEqual(dc.rpc_show_components(), [])

        compId = DAQClient.ID
        compName = 'foo'
        compNum = 0
        compHost = 'localhost'
        compPort = 666
        compMBean = 0

        logger.addExpected('Got registration for ID#%d %s#%d at %s:%d' %
                           (compId, compName, compNum, compHost, compPort))

        rtnArray = dc.rpc_register_component(compName, compNum, compHost,
                                             compPort, compMBean, [])

        self.assertEqual(dc.rpc_get_num_components(), 1)

        fooStr = 'ID#%d %s#%d at %s:%d %s' % \
            (DAQClient.ID - 1, compName, compNum, compHost, compPort, 'idle')
        self.assertEqual(dc.rpc_show_components(), [fooStr])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], DAQClient.ID - 1)
        self.assertEqual(rtnArray[1], '')
        self.assertEqual(rtnArray[2], 0)

        logger.checkEmpty()

    def testRegisterWithLog(self):
        logger = MockLogger()

        dc = MockServer(logger)

        logHost = 'localhost'
        logPort = 12345

        dc.rpc_log_to(logHost, logPort)
        logger.checkEmpty()

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID

        logger.addExpected('Got registration for ID#%d %s#%d at %s:%d M#%d' %
                           (expId, name, num, host, port, mPort))

        rtnArray = dc.rpc_register_component(name, num, host, port, mPort, [])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], expId)
        self.assertEqual(rtnArray[1], logHost)
        self.assertEqual(rtnArray[2], logPort)

        dc.rpc_close_log()
        logger.checkEmpty()

    def testNoRunset(self):
        dc = MockServer(None)

        self.assertRaises(ValueError, dc.rpc_runset_break, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1, 'xxx')
        self.assertRaises(ValueError, dc.rpc_runset_log_to, 1, 'xxx', [])
        self.assertRaises(ValueError, dc.rpc_runset_start_run, 1, 1)
        self.assertRaises(ValueError, dc.rpc_runset_status, 1)
        self.assertRaises(ValueError, dc.rpc_runset_stop_run, 1)

    def testRunset(self):
        logger = MockLogger()

        dc = MockServer(logger)

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 0)
        self.assertEqual(dc.rpc_show_components(), [])

        id = DAQClient.ID
        name = 'foo'
        num = 99
        host = 'localhost'
        port = 666
        mPort = 0

        compName = 'ID#%d %s#%d at %s:%d' % (id, name, num, host, port)

        logger.addExpected('Got registration for %s' % compName)

        dc.rpc_register_component(name, num, host, port, mPort, [])

        self.assertEqual(dc.rpc_get_num_components(), 1)
        self.assertEqual(dc.rpc_num_sets(), 0)

        logger.addExpected('Built runset with the following components:\n%s\n' %
                           compName)
        logger.addExpected('%s connected' % compName)

        setId = dc.rpc_runset_make([name])

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 1)

        self.assertEqual(dc.rpc_runset_status(setId), 'OK')

        self.assertEqual(dc.rpc_runset_log_to(setId, 'abc',
                                              [[name, num, 777, 'fatal'], ]),
                         'OK')

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

if __name__ == '__main__':
    unittest.main()
