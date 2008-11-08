#!/usr/bin/env python
#
# Glue server which hooks pDAQ to IceCube Live

import optparse, os, socket, sys, time
import DAQRunIface

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

try:
    from live.control.component import Component
    from live.transport.Queue import Prio
except ImportError:
    print >>sys.stderr, """\
Warning: Can't import IceCube Live code. Probably DAQLive isn't installed.
DAQ should work ok, but IceCube Live won't be able to control it."""
    sys.exit(1)

SVN_ID  = "$Id: DAQRun.py 3084 2008-05-27 21:44:21Z dglo $"

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
import SVNVersionInfo

class LiveArgs(object):
    "Command-line argument handler for DAQLive"
    def __init__(self):
        self.__livePort = None
        self.__verbose = False

    def __build_parser(self):
        ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
            "%(release)s %(repo_rev)s" % SVNVersionInfo.get_version_info(SVN_ID)
        usage = "%prog [options]\nversion: " + ver_info
        p = optparse.OptionParser(usage=usage, version=ver_info)

        p.add_option("-v", "--verbose",
                     action="store_true",
                     dest="verbose",
                     help="Print lots of status messages")

        p.add_option("-P", "--live-port",
                     action="store",      type="int",
                     dest="livePort",     default=6659,
                     help="Listening port for Icecube Live commands")

        return p

    def __process_options(self, opt):
        self.__livePort = opt.livePort
        self.__verbose = opt.verbose

    def getPort(self):   return self.__livePort
    def isVerbose(self): return self.__verbose

    def parse(self):
        p = self.__build_parser()
        opt, args = p.parse_args()
        self.__process_options(opt)

class DAQLive(Component):
    "Server which acts as the DAQ interface for IceCube Live"
    SERVICE_NAME = "pdaq"

    "Maximum number of loops to wait inside __waitForState()"
    MAX_WAIT = 120

    def __init__(self):
        "Initialize DAQLive"
        self.__runArgs = LiveArgs()
        self.__runArgs.parse()

        self.__runIface = None

        self.__connectToDAQRun(True)
        self.__runNumFile = None

        self.__runConfig = None

        self.__runNumber = 0
        self.__runState = None
        self.__runCallCount = 0


        Component.__init__(self, self.SERVICE_NAME, self.__runArgs.getPort(),
                           synchronous=True, lightSensitive=True,
                           makesLight=True)
        self.logInfo('Started %s service on port %d' %
                     (self.SERVICE_NAME, self.__runArgs.getPort()))

    def __connectToDAQRun(self, firstTime=False):
        "Connect to the DAQRun server"
        if firstTime:
            self.logInfo('Connecting to DAQRun')
        else:
            self.logInfo('Reconnecting to DAQRun')

        self.__runIface = DAQRunIface.DAQRunIface('localhost', 9000)

    def __getNextRunNumber(self):
        "Get the next run number from $HOME/.last_pdaq_run"
        if self.__runNumFile is None:
            self.__runNumFile = \
                os.path.join(os.environ["HOME"], ".last_pdaq_run")

        # attempt to read a run number from the file
        try:
            f = open(self.__runNumFile, "r")
            rStr = f.readline()
            f.close()
            runNum = int(rStr.rstrip("\r\n")) + 1
        except:
            runNum = None

        # if we've gotten a run number, update the file
        if runNum is not None:
            fd = open(self.__runNumFile, "w")
            print >>fd, str(runNum)
            fd.close()

        return runNum

    def __getState(self, retry=True):
        "Get the current pDAQ state"
        try:
            state = self.__runIface.getState()
        except socket.error:
            if retry:
                self.__connectToDAQRun()
                state = self.__getState(False)
            else:
                state = None

        return state

    def __reportMoni(self):
        "Report run monitoring quantities"
        if self.moniClient:
            moniData = self.__runIface.monitorRun()
            for k in moniData.keys():
                self.moniClient.sendMoni(k, moniData[k], Prio.SCP)

    def __waitForState(self, expState, badStates=('ERROR')):
        "Wait for pDAQ to reach the expected state"
        n = 0
        while True:
            state = self.__getState()
            if state is None:
                break
            if badStates is not None and len(badStates) > 0:
                for bs in badStates:
                    if state == bs:
                        raise Exception("PDAQ went into %s state, wanted %s" %
                                        (state, expState))
            self.__runState = state
            if state == expState:
                break
            time.sleep(1)
            n += 1
            if n > self.MAX_WAIT:
                self.logError('Waiting for state %s, but stuck at %s' %
                              (expState, str(state)))
                return False

        return True

    def logInfo(self, msg):
        "Log informational message"
        if self.__runArgs.isVerbose():
            print >>sys.stdout, msg

    def logError(self, msg):
        "Log error message"
        print >>sys.stderr, msg + '\n' + exc_string()

    def recovering(self, retry=True):
        "Try to recover (from an error state?)"
        self.logInfo('Recovering pDAQ')

        try:
            self.__runIface.recover()
            recoveryStarted = True
        except socket.error:
            recoveryStarted = False
            if retry:
                self.__connectToDAQRun()
                self.recovering(retry=False)
            else:
                self.logError('Could not recover pDAQ')

        if recoveryStarted:
            if self.__waitForState('STOPPED'):
                self.logInfo('Recovered DAQ')

    def runChange(self, stateArgs=None):
        "Stop current pDAQ run and start a new run"
        self.logInfo('RunChange pDAQ')
        self.stopping()
        self.starting()

    def running(self, retry=True):
        "Check run state and puke if there's an error"
        state = self.__getState()
        if state is None or state == "ERROR":
            raise Exception("pDAQ encountered an error (state is '%s')" % state)

        if state != self.__runState:
            self.logInfo('pDAQ = ' + state)
            self.__runState = state

        if self.__runState == "RUNNING":
            self.__runCallCount += 1
            if self.__runCallCount >= 200:
                self.__reportMoni()
                self.__runCallCount = 0

    def starting(self, stateArgs=None, retry=True):
        """
        Start a new pDAQ run
        stateArgs - should be a dictionary of run data:
            'runConfig' - the name of the run configuration
            'runNumber' - run number
            'subRunNumber' - subrun number
        retry - if True, reopen a bad socket connection to DAQRun
                otherwise,
        """

        # either use specified runConfig or reuse previous value
        if stateArgs is not None and stateArgs.has_key('runConfig'):
            self.__runConfig = stateArgs['runConfig']
        elif self.__runConfig is None:
            raise Exception('No configuration specified')

        runNumber = stateArgs.get('runNumber')
        if runNumber is None:
            runNumber = self.__getNextRunNumber()

        self.logInfo('Starting run %d - %s' % (runNumber, self.__runConfig))

        self.__runCallCount = 0

        # tell DAQRun to start a run
        try:
            self.__runIface.start(runNumber, self.__runConfig)
            runStarted = True
        except socket.error:
            runStarted = False
            if retry:
                self.__connectToDAQRun()
                self.starting(stateArgs, False)
            else:
                self.logError('Could not start pDAQ')

        if runStarted:
            # wait for DAQRun to indicate that the run has started
            if self.__waitForState('RUNNING',
                                   ('ERROR', 'STOPPED', 'RECOVERING')):
                self.__runNumber = runNumber
                self.logInfo('Started run %d' % self.__runNumber)
            else:
                self.__waitForState('STOPPED')
                self.logInfo('Failed to start run %d' % self.__runNumber)

    def stopping(self, retry=True):
        "Stop current pDAQ run"
        self.logInfo('Stopping run %d' % self.__runNumber)

        try:
            self.__runIface.stop()
            runStopped = True
        except socket.error:
            runStopped = False
            if retry:
                self.__connectToDAQRun()
                self.stopping(retry=False)
            else:
                self.logError('Could not stop pDAQ')

        if runStopped:
            # wait for DAQRun to indicate that the run has stopped
            if self.__waitForState('STOPPED'):
                self.logInfo('Stopped run %d' % self.__runNumber)

        self.__reportMoni()

    def subrun(self, subrunId, domList):
        """
        Start new subrun, basically a passthru to give <domList> to DAQRunIface.
        """
        ret = self.__runIface.flasher(subrunId, domList)
        if ret != 1: return "New subrun FAILED.  See pDAQ logs for more info."
        return "OK"
        
if __name__ == "__main__":
    comp = DAQLive()
    try:
        comp.run()
    except:
        print exc_string()
