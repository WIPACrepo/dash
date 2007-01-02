#!/usr/bin/env python

import unittest
from CnCServer import DAQClient, DAQServer

class MockXMLRPC:
    def __init__(self):
        pass

    def configure(self, id, name=None):
        pass

    def connect(self, id, name=None):
        return 'OK'

    def getState(self, id):
        pass

    def logTo(self, id, logIP, port, level):
        pass

    def reset(self, id):
        pass

    def startRun(self, id, runNum):
        pass

    def stopRun(self, id):
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

        super(MockClient, self).__init__(name, num, host, port, mbeanPort,
                                         connectors)

    def createClient(self, host, port):
        return MockRPCClient(host, port)

    def createLogger(self, host, port):
        return MockLogger(host, port)

class MockServer(DAQServer):
    def __init__(self):
        super(MockServer, self).__init__(testOnly=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return MockClient(name, num, host, port, mbeanPort, connectors)

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
                                             compPort, 0, [])

        self.assertEqual(dc.rpc_get_num_components(), 1)

        fooStr = 'ID#' + str(DAQClient.ID - 1) + ' ' + compName + '#' + \
            str(compNum) + ' at ' + compHost + ':' + str(compPort) + ' ' + \
            DAQClient.STATE_MISSING
        self.assertEqual(dc.rpc_show_components(), [fooStr])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], DAQClient.ID - 1)
        self.assertEqual(rtnArray[1], '')
        self.assertEqual(rtnArray[2], 0)
        self.assertEqual(rtnArray[3], DAQServer.DEFAULT_LOG_LEVEL)

    def testRegisterWithLog(self):
        dc = MockServer()

        logHost = 'localhost'
        logPort = 123

        dc.rpc_log_to(logHost, logPort)
        self.failIf(dc.socketlog is None, 'socketlog is None')
        self.assertEqual(dc.logIP, logHost)
        self.assertEqual(dc.logPort, logPort)

        rtnArray = dc.rpc_register_component('foo', 0, 'localhost', 666, 0, [])

        self.assertEqual(len(rtnArray), 4)
        self.assertEqual(rtnArray[0], DAQClient.ID - 1)
        self.assertEqual(rtnArray[1], logHost)
        self.assertEqual(rtnArray[2], logPort)
        self.assertEqual(rtnArray[3], DAQServer.DEFAULT_LOG_LEVEL)

        dc.rpc_close_log()
        self.failIf(dc.socketlog is not None, 'socketlog is not None')
        self.assertEqual(dc.logIP, None)
        self.assertEqual(dc.logPort, None)

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

        rtnArray = dc.rpc_register_component('foo', 0, 'localhost', 666, 0, [])

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
