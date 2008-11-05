#!/usr/bin/env python

import thread, unittest, xmlrpclib

from CnCServer import CnCServer, DAQClient
from DAQRPC import RPCServer

from DAQMocks \
    import MockAppender, MockCnCLogger, SocketReaderFactory, SocketWriter

class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet)

class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, logIP='localhost', logPort=-1):
        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              logIP=logIP, logPort=logPort,
                                              quiet=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        key = '%s#%d' % (name, num)
        key = 'server'
        if not MostlyCnCServer.APPENDERS.has_key(key):
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MostlyDAQClient(name, num, host, port, mbeanPort, connectors,
                               MostlyCnCServer.APPENDERS[key])

    def createCnCLogger(self, quiet):
        key = 'server'
        if not MostlyCnCServer.APPENDERS.has_key(key):
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(MostlyCnCServer.APPENDERS[key], quiet)

    def monitorLoop(self):
        pass

class RealComponent(object):
    APPENDERS = {}

    def __init__(self, name, num, cmdPort, mbeanPort, cncPort, verbose=False):
        self.__name = name
        self.__num = num

        self.__state = 'FOO'

        self.__logger = None
        self.__expRunPort = None

        self.__cmd = RPCServer(cmdPort)
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__getVersionInfo,
                                     'xmlrpc.getVersionInfo')
        self.__cmd.register_function(self.__logTo, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__resetLogging, 'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__startRun, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__stopRun, 'xmlrpc.stopRun')
        thread.start_new_thread(self.__cmd.serve_forever, ())

        self.__mbean = RPCServer(mbeanPort)
        thread.start_new_thread(self.__mbean.serve_forever, ())

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' % cncPort,
                                           verbose=verbose)
        self.__cnc.rpc_register_component(self.__name, self.__num,
                                                 'localhost', cmdPort,
                                                 mbeanPort, [])

    def __configure(self, cfgName=None):
        if self.__logger is None:
            raise Exception('No logging for %s#%d' % (self.__name, self.__num))

        if cfgName is None:
            cfgStr = ''
        else:
            cfgStr = ' with %s' % cfgName

        self.__logger.write('Config %s#%d%s' %
                            (self.__name, self.__num, cfgStr))

        self.__state = 'ready'
        return 'CFG'

    def __connect(self, *args):
        self.__state = 'connected'
        return 'CONN'

    def __getState(self):
        return self.__state

    def __getVersionInfo(self):
        return '$Id: filename revision date time author xxx'

    def __logTo(self, host, port):
        if port != self.__expRunPort:
            raise Exception('Expected runlog port %d, not %d' %
                            (self.__expRunPort, port))

        self.__logger = SocketWriter(host, port)
        self.__logger.write('Test msg')
        return 'OK'

    def __reset(self):
        self.__state = 'idle'
        return 'RESET'

    def __resetLogging(self):
        self.__expRunPort = None
        self.__logger = None

        self.__state = 'reset'
        return 'RLOG'

    def __startRun(self, runNum):
        if self.__logger is None:
            raise Exception('No logging for %s#%d' % (self.__name, self.__num))

        self.__logger.write('Start #%d on %s#%d' %
                            (runNum, self.__name, self.__num))

        self.__state = 'running'
        return 'RUN#%d' % runNum

    def __stopRun(self):
        if self.__logger is None:
            raise Exception('No logging for %s#%d' % (self.__name, self.__num))

        self.__logger.write('Stop %s#%d' % (self.__name, self.__num))

        self.__state = 'stopped'
        return 'STOP'

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    def createCnCLogger(self, quiet=True):
        key = '%s#%d' % (self.__name, self.__num)
        if not RealComponent.APPENDERS.has_key(key):
            RealComponent.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(RealComponent.APPENDERS[key], quiet)

    def getState(self):
        return self.__getState()

    def setExpectedRunLogPort(self, port):
        self.__expRunPort = port

class TestCnCServer(unittest.TestCase):
    def createLog(self, name, port):
        return self.__logFactory.createLog(name, port)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.comp = None
        self.cnc = None

        MostlyCnCServer.APPENDERS.clear()
        RealComponent.APPENDERS.clear()

    def tearDown(self):
        for key in RealComponent.APPENDERS:
            RealComponent.APPENDERS[key].checkEmpty()
        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkEmpty()

        if self.comp is not None:
            self.comp.close()
        if self.cnc is not None:
            self.cnc.closeServer()

        self.__logFactory.tearDown()

    def __runEverything(self):
        catchall = self.createLog('master', 18999)

        catchall.addExpectedText("I'm server %s running on port %d" %
                                 (MostlyCnCServer.SERVER_NAME, CnCServer.DEFAULT_PORT))
        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        self.cnc = MostlyCnCServer(logPort=catchall.getPort())
        thread.start_new_thread(self.cnc.run, ())

        catchall.waitForEmpty(100)
        catchall.checkEmpty()

        compName = 'foo'
        compNum = 1
        host = 'localhost'
        cmdPort = 19001
        mbeanPort = 19002
        verbose = False

        catchall.addExpectedText(('Got registration for ID#%d %s#%d at' +
                                  ' localhost:%d M#%d') %
                                 (DAQClient.ID, compName, compNum, cmdPort,
                                  mbeanPort))

        self.comp = RealComponent(compName, compNum, cmdPort, mbeanPort,
                                  self.cnc.port, verbose)

        catchall.waitForEmpty(100)
        if catchall.isError():
            self.fail(catchall.getError())

        s = self.cnc.rpc_list_components()
        self.assertEquals(1, len(s),
                          'Expected 1 listed component, not %d' % len(s))
        self.assertEquals(compName, s[0][1],
                          'Expected component %s, not %s' % (compName, s[0][1]))
        self.assertEquals(compNum, s[0][2],
                          'Expected %s #%d, not #%d' %
                          (compName, compNum, s[0][2]))
        self.assertEquals(host, s[0][3],
                          'Expected %s#%d host %s, not %s' %
                          (compName, compNum, host, s[0][3]))
        self.assertEquals(cmdPort, s[0][4],
                          'Expected %s#%d cmdPort %d, not %d' %
                          (compName, compNum, cmdPort, s[0][4]))
        self.assertEquals(mbeanPort, s[0][5],
                          'Expected %s#%d mbeanPort %d, not %d' %
                          (compName, compNum, mbeanPort, s[0][5]))

        compId = s[0][0]

        catchall.addExpectedText('Built runset with the following components:')

        setId = self.cnc.rpc_runset_make([compName])
        self.assertEquals('connected', self.comp.getState(),
                          'Unexpected state %s' % self.comp.getState())

        catchall.waitForEmpty(100)
        if catchall.isError():
            self.fail(catchall.getError())

        catchall.addExpectedText('ID#%d %s#%d at %s:%d M#%s %s' % \
                                     (compId, compName, compNum, host, cmdPort,
                                      mbeanPort, 'connected'))

        self.assertEqual(self.cnc.rpc_runset_status(setId), 'OK')

        catchall.waitForEmpty(100)
        catchall.checkEmpty()

        runPort = 18998

        runlog = self.createLog('runlog', runPort)

        self.comp.setExpectedRunLogPort(runPort)

        runlog.addExpectedExact('Test msg')
        runlog.addExpectedText('filename revision date time author')

        logList = [(compName, compNum, runPort), ]
        self.assertEqual(self.cnc.rpc_runset_log_to(setId, host, logList), 'OK')

        runlog.waitForEmpty(100)
        runlog.checkEmpty()

        runlog.addExpectedExact('Config %s#%d' % (compName, compNum))

        self.assertEqual(self.cnc.rpc_runset_configure(setId), 'OK')

        runlog.waitForEmpty(100)
        runlog.checkEmpty()

        cfgName = 'zzz'

        runlog.addExpectedExact('Config %s#%d with %s' % (compName, compNum,
                                                          cfgName))

        self.assertEqual(self.cnc.rpc_runset_configure(setId, cfgName), 'OK')

        runlog.waitForEmpty(100)
        runlog.checkEmpty()

        runNum = 444

        runlog.addExpectedExact('Start #%d on %s#%d' %
                                (runNum, compName, compNum))

        self.assertEqual(self.cnc.rpc_runset_start_run(setId, runNum), 'OK')

        runlog.waitForEmpty(100)
        runlog.checkEmpty()

        runlog.addExpectedExact('Stop %s#%d' % (compName, compNum))

        self.assertEqual(self.cnc.rpc_runset_stop_run(setId), 'OK')

        runlog.waitForEmpty(100)
        runlog.checkEmpty()

        self.assertEqual(self.cnc.rpc_get_num_components(), 0)
        self.assertEqual(self.cnc.rpc_num_sets(), 1)

        serverAppender = MostlyCnCServer.APPENDERS['server']
        serverAppender.addExpectedExact('End of log')

        self.assertEquals(self.cnc.rpc_runset_break(setId), 'OK')

        serverAppender.waitForEmpty(100)
        serverAppender.checkEmpty()

        self.assertEqual(self.cnc.rpc_get_num_components(), 1)
        self.assertEqual(self.cnc.rpc_num_sets(), 0)

        serverAppender.waitForEmpty(100)
        serverAppender.checkEmpty()

        runlog.waitForEmpty(100)
        if runlog.isError():
            self.fail(runlog.getError())
        runlog.checkEmpty()

        catchall.waitForEmpty(100)
        if catchall.isError():
            self.fail(catchall.getError())
        catchall.checkEmpty()

    def testEverything(self):
        self.__runEverything()

    def testEverythingAgain(self):
        self.__runEverything()

if __name__ == '__main__':
    unittest.main()
