#!/usr/bin/env python

import sys, threading, unittest
from DAQConst import DAQPort
from DAQRPC import RPCServer

TEST_LIVE = True
try:
    from DAQLive import DAQLive, LiveArgs
except SystemExit:
    TEST_LIVE = False
    class DAQLive:
        pass

from DAQMocks import SocketReaderFactory

class MockLive(DAQLive):
    def __init__(self, port):
        super(MockLive, self).__init__(self.__buildArgs(port))

    def __buildArgs(self, port, extraArgs=None):
        stdArgs = { '-v' : '',
                    '-P' : str(port) }

        oldArgv = sys.argv
        try:
            sys.argv = ['foo']

            for k in stdArgs.keys():
                if extraArgs is None or not extraArgs.has_key(k):
                    sys.argv.append(k)
                    if len(stdArgs[k]) > 0:
                        sys.argv.append(stdArgs[k])

            if extraArgs is not None:
                for k in extraArgs.keys():
                    sys.argv.append(k)
                    if len(extraArgs[k]) > 0:
                        sys.argv.append(extraArgs[k])

            args = LiveArgs()
            args.parse()
        finally:
            sys.argv = oldArgv

        # don't check for DAQRun
        #
        args.ignoreRunThread()

        return args

class MockRun(object):
    def __init__(self, id):
        self.__id = id

        self.__state = 'IDLE'

        self.__evtCounts = {}

        self.__rpc = RPCServer(DAQPort.DAQRUN)
        self.__rpc.register_function(self.__recover, 'rpc_recover')
        self.__rpc.register_function(self.__monitor, 'rpc_run_monitoring')
        self.__rpc.register_function(self.__getState, 'rpc_run_state')
        self.__rpc.register_function(self.__startRun, 'rpc_start_run')
        self.__rpc.register_function(self.__stopRun, 'rpc_stop_run')
        self.__rpc.register_function(self.__ping, 'rpc_ping')
        threading.Thread(target=self.__rpc.serve_forever, args=()).start()

    def __getState(self):
        return self.__state

    def __monitor(self):
        return self.__evtCounts

    def __ping(self):
        return self.__id

    def __recover(self):
        self.__state = 'STOPPED'
        return 1

    def __startRun(self, runNum, subRunNum, cfgName, logInfo=None):
        self.__state = 'RUNNING'
        return 1

    def __stopRun(self):
        self.__state = 'STOPPED'
        return 1

    def close(self):
        self.__rpc.server_close()

    def setEventCounts(self, physics, payTime, wallTime, moni, moniTime,
                       sn, snTime, tcal, tcalTime):
        self.__evtCounts.clear()
        self.__evtCounts["physicsEvents"] = physics
        self.__evtCounts["eventPayloadTime"] = payTime
        self.__evtCounts["eventTime"] = wallTime
        self.__evtCounts["moniEvents"] = moni
        self.__evtCounts["moniTime"] = moniTime
        self.__evtCounts["snEvents"] = sn
        self.__evtCounts["snTime"] = snTime
        self.__evtCounts["tcalEvents"] = tcal
        self.__evtCounts["tcalTime"] = tcalTime

class TestDAQLive(unittest.TestCase):
    def setUp(self):
        self.__live = None
        self.__run = None
        self.__logFactory = SocketReaderFactory()

    def tearDown(self):
        self.__logFactory.tearDown()
        if self.__run is not None:
            self.__run.close()
        if self.__live is not None:
            self.__live.close()

    def testStartNoConfig(self):
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        log = self.__logFactory.createLog('liveMoni', DAQPort.I3LIVE, False)

        port = 9876

        log.addExpectedText('Connecting to DAQRun')
        log.addExpectedText('Started pdaq service on port %d' % port)

        self.__run = MockRun(1)

        self.__live = MockLive(port)

        self.assertRaises(Exception, self.__live.starting, {})

        log.checkStatus(10)

    def testStart(self):
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        log = self.__logFactory.createLog('liveMoni', DAQPort.I3LIVE, False)

        port = 9876

        log.addExpectedText('Connecting to DAQRun')
        log.addExpectedText('Started pdaq service on port %d' % port)

        self.__run = MockRun(2)

        self.__live = MockLive(port)

        runConfig = 'xxxCfg'
        runNum = 543
        
        log.addExpectedText('Starting run %d - %s'% (runNum, runConfig))
        log.addExpectedText("DAQ state is RUNNING")
        log.addExpectedText('Started run %d'% runNum)

        args = {'runConfig':runConfig, 'runNumber':runNum}
        self.__live.starting(args)

    def testStop(self):
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        log = self.__logFactory.createLog('liveMoni', DAQPort.I3LIVE, False)

        port = 9876

        log.addExpectedText('Connecting to DAQRun')
        log.addExpectedText('Started pdaq service on port %d' % port)

        self.__run = MockRun(3)

        self.__live = MockLive(port)

        runNum = 0

        log.addExpectedText('Stopping run %d'% runNum)
        log.addExpectedText("DAQ state is STOPPED")
        log.addExpectedText('Stopped run %d'% runNum)

        numPhysics = 5
        payloadTime = 1234
        wallTime = 5432
        numMoni = 10
        moniTime = 12345
        numSn = 15
        snTime = 23456
        numTcal = 20
        tcalTime = 34567

        self.__run.setEventCounts(numPhysics, payloadTime, wallTime, numMoni,
                                  moniTime, numSn, snTime, numTcal, tcalTime)

        log.addExpectedLiveMoni('tcalEvents', numTcal)
        log.addExpectedLiveMoni('moniEvents', numMoni)
        log.addExpectedLiveMoni('snEvents', numSn)
        log.addExpectedLiveMoni('physicsEvents', numPhysics)
        log.addExpectedLiveMoni('walltimeEvents', numPhysics)

        self.__live.stopping()

    def testRecover(self):
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        log = self.__logFactory.createLog('liveMoni', DAQPort.I3LIVE, False)

        port = 9876

        log.addExpectedText('Connecting to DAQRun')
        log.addExpectedText('Started pdaq service on port %d' % port)

        self.__run = MockRun(4)

        self.__live = MockLive(port)

        log.addExpectedText('Recovering pDAQ')
        log.addExpectedText('DAQ state is STOPPED')
        log.addExpectedText('Recovered pDAQ')

        self.__live.recovering()

if __name__ == '__main__':
    unittest.main()
