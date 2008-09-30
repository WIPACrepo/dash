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
    def __init__(self, host, port):
        pass

    def write_ts(self, s):
        pass

class MockClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors):

        self.state = 'idle'

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
        return MockLogger(host, port)

    def getState(self):
        return self.state

    def reset(self):
        self.state = 'idle'
        return super(MockClient, self).reset()

    def startRun(self, runNum):
        self.state = 'running'
        return super(MockClient, self).startRun(runNum)

class MockServer(DAQServer):
    def __init__(self):
        self._logLines = []

        super(MockServer, self).__init__(testOnly=True)

    def checkLog(self, expHost, expPort):
        return self.logIP == expHost and self.logPort == expPort

    def clearLog(self):
        self._logLines[:] = []

    def closeLog(self):
        self.logIP = None
        self.logPort = None

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return MockClient(name, num, host, port, mbeanPort, connectors)

    def logLine(self, idx):
        return self._logLines[idx]

    def logmsg(self, msg):
        self._logLines.append(msg)

    def numLines(self):
        return len(self._logLines)

    def openLog(self, host, port):
        self.logIP = host
        self.logPort = port

class TestDAQServer(unittest.TestCase):
    def testRegister(self):
        dc = MockServer()

        self.assertEqual(dc.rpc_show_components(), [])

        compName = 'foo'
        compNum = 0
        compHost = 'localhost'
        compPort = 666
        compMBean = 0
        rtnArray = dc.rpc_register_component(compName, compNum, compHost,
                                             compPort, compMBean, [])

        self.assertEqual(dc.rpc_get_num_components(), 1)

        fooStr = 'ID#' + str(DAQClient.ID - 1) + ' ' + compName + '#' + \
            str(compNum) + ' at ' + compHost + ':' + str(compPort) + ' ' + \
            'idle'
        self.assertEqual(dc.rpc_show_components(), [fooStr])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], DAQClient.ID - 1)
        self.assertEqual(rtnArray[1], '')
        self.assertEqual(rtnArray[2], 0)

    def testRegisterWithLog(self):
        dc = MockServer()

        logHost = 'localhost'
        logPort = 12345

        dc.rpc_log_to(logHost, logPort)
        self.assertEqual(dc.numLines(), 0)
        self.failUnless(dc.checkLog(logHost, logPort), 'Logging problem')

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID

        rtnArray = dc.rpc_register_component(name, num, host, port, mPort, [])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], expId)
        self.assertEqual(rtnArray[1], logHost)
        self.assertEqual(rtnArray[2], logPort)

        expMsg = 'Got registration for ID#%d %s#%d at %s:%d M#%d' % \
            (expId, name, num, host, port, mPort)
        self.assertEqual(dc.numLines(), 1)
        self.failUnless(dc.checkLog(logHost, logPort), 'Logging problem')
        self.assertEqual(dc.logLine(0), expMsg)
        dc.clearLog()

        dc.rpc_close_log()
        self.assertEqual(dc.numLines(), 0)
        self.failUnless(dc.checkLog(None, None), 'Logging problem')

    def testNoRunset(self):
        dc = MockServer()

        self.assertRaises(ValueError, dc.rpc_runset_break, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1)
        self.assertRaises(ValueError, dc.rpc_runset_configure, 1, 'xxx')
        self.assertRaises(ValueError, dc.rpc_runset_log_to, 1, 'xxx', [])
        self.assertRaises(ValueError, dc.rpc_runset_start_run, 1, 1)
        self.assertRaises(ValueError, dc.rpc_runset_status, 1)
        self.assertRaises(ValueError, dc.rpc_runset_stop_run, 1)

    def testRunset(self):
        dc = MockServer()

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 0)
        self.assertEqual(dc.rpc_show_components(), [])

        dc.rpc_register_component('foo', 0, 'localhost', 666, 0, [])

        self.assertEqual(dc.rpc_get_num_components(), 1)
        self.assertEqual(dc.rpc_num_sets(), 0)

        setId = dc.rpc_runset_make(['foo'])

        self.assertEqual(dc.rpc_get_num_components(), 0)
        self.assertEqual(dc.rpc_num_sets(), 1)

        self.assertEqual(dc.rpc_runset_status(setId), 'OK')

        self.assertEqual(dc.rpc_runset_log_to(setId, 'abc',
                                              [['foo', 0, 777, 'fatal'], ]),
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

if __name__ == '__main__':
    unittest.main()
