#!/usr/bin/env python
#
# Glue server which hooks pDAQ to IceCube Live

import optparse, os, socket, sys, time
import DAQRunIface, Process
from DAQConst import DAQPort

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

try:
    from live.control.component import Component
    from live.transport.Queue import Prio
    from live.control.log \
        import LOG_FATAL, LOG_ERROR, LOG_WARN, LOG_INFO, LOG_DEBUG, LOG_TRACE
except ImportError:
    print >>sys.stderr, """\
Warning: Can't import IceCube Live code. Probably DAQLive isn't installed.
DAQ should work ok, but IceCube Live won't be able to control it."""
    raise SystemExit

SVN_ID  = "$Id: DAQLive.py 3084 2008-05-27 21:44:21Z dglo $"

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
        self.__kill = False
        self.__livePort = None
        self.__verbose = False

    def __build_parser(self):
        ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
            "%(release)s %(repo_rev)s" % SVNVersionInfo.get_version_info(SVN_ID)
        usage = "%prog [options]\nversion: " + ver_info
        p = optparse.OptionParser(usage=usage, version=ver_info)

        p.add_option("-k", "--kill",
                     action="store_true",
                     dest="kill",
                     help="Kill existing instance(s) of DAQLive")

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
        self.__kill = opt.kill
        self.__livePort = opt.livePort
        self.__verbose = opt.verbose

    def getPort(self):   return self.__livePort
    def isKill(self): return self.__kill
    def isVerbose(self): return self.__verbose

    def parse(self):
        p = self.__build_parser()
        opt, args = p.parse_args()
        self.__process_options(opt)

class LiveLog(object):
    def __init__(self, liveComp, verbose):
        self.__liveComp = liveComp
        if verbose:
            self.__level = LOG_DEBUG
        else:
            self.__level = LOG_ERROR

    def __send(self, level, msg):
        if self.__liveComp.moniClient:
            self.__liveComp.moniClient.sendLog(level, msg)
        else:
            print >>sys.stderr, msg

    def debug(self, msg):
        "Log debugging message"
        if self.__level >= LOG_DEBUG:
            self.__send(LOG_DEBUG, msg)

    def error(self, msg):
        "Log error message"
        if self.__level >= LOG_ERROR:
            self.__send(LOG_ERROR, msg)

    def info(self, msg):
        "Log informational message"
        if self.__level >= LOG_INFO:
            self.__send(LOG_INFO, msg)

    def errorException(self, msg):
        "Log error message plus exception stack trace"
        if self.__level >= LOG_ERROR:
            self.__send(LOG_ERROR, msg + ': ' + exc_string())

class DAQLive(Component):
    "Server which acts as the DAQ interface for IceCube Live"
    SERVICE_NAME = "pdaq"

    "Maximum number of loops to wait inside __waitForState()"
    MAX_WAIT = 120

    def __init__(self, liveArgs):
        "Initialize DAQLive"
        self.__liveArgs = liveArgs

        Component.__init__(self, self.SERVICE_NAME, self.__liveArgs.getPort(),
                           synchronous=True, lightSensitive=True,
                           makesLight=True)

        self.__log = self.getLiveLog()

        self.__runIface = None

        self.__connectToDAQRun(True)
        self.__runNumFile = None

        self.__runConfig = None

        self.__runNumber = 0
        self.__runState = None
        self.__runCallCount = 0

        self.__log.info('Started %s service on port %d' %
                        (self.SERVICE_NAME, self.__liveArgs.getPort()))

    def __connectToDAQRun(self, firstTime=False):
        "Connect to the DAQRun server"
        if firstTime:
            self.__log.info('Connecting to DAQRun')
        else:
            self.__log.info('Reconnecting to DAQRun')

        self.__runIface = DAQRunIface.DAQRunIface('localhost', DAQPort.DAQRUN)

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
                        self.__log.error('PDAQ went into %s state, wanted %s' %
                                         (str(state), expState))
                        return False
            self.__runState = state
            if state == expState:
                break
            time.sleep(1)
            n += 1
            if n > self.MAX_WAIT:
                self.__log.error('Waiting for state %s, but stuck at %s' %
                                 (expState, str(state)))
                return False

        return True

    def getLiveLog(self):
        return LiveLog(self, self.__liveArgs.isVerbose())

    def recovering(self, retry=True):
        "Try to recover (from an error state?)"
        self.__log.debug('Recovering pDAQ')

        try:
            self.__runIface.recover()
            recoveryStarted = True
        except socket.error:
            recoveryStarted = False
            if retry:
                self.__connectToDAQRun()
                self.recovering(retry=False)
            else:
                self.__log.errorException('Could not recover pDAQ')

        if recoveryStarted:
            if self.__waitForState('STOPPED'):
                self.__log.debug('Recovered DAQ')

    def release(self, retry=True):
        "This is only for debugging -- will never be called by I3Live"
        try:
            self.__runIface.release()
        except socket.error:
            if retry:
                self.__connectToDAQRun()
                self.release(retry=False)
            else:
                self.__log.errorException('Could not release pDAQ runset')

    def runChange(self, stateArgs=None):
        "Stop current pDAQ run and start a new run"
        self.__log.debug('RunChange pDAQ')
        self.stopping()
        self.starting()
        self.__log.debug('RunChanged pDAQ')

    def running(self, retry=True):
        "Check run state and puke if there's an error"
        state = self.__getState()
        if state is None or state == "ERROR":
            raise Exception("pDAQ encountered an error (state is '%s')" %
                            str(state))

        if state != self.__runState:
            self.__log.debug('pDAQ = %s (runState was %s)' %
                             (state, str(self.__runState)))
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

        self.__log.info('Starting run %d - %s' % (runNumber, self.__runConfig))

        self.__runCallCount = 0

        # tell DAQRun to start a run
        try:
            if not self.moniClient:
                logInfo = None
            else:
                logInfo = self.moniClient.getHostPortTuple()
            self.__runIface.start(runNumber, self.__runConfig, logInfo)
            runStarted = True
        except socket.error:
            runStarted = False
            if retry:
                self.__connectToDAQRun()
                self.starting(stateArgs, False)
            else:
                self.__log.errorException('Could not start pDAQ')

        if runStarted:
            # wait for DAQRun to indicate that the run has started
            if self.__waitForState('RUNNING',
                                   ('ERROR', 'STOPPED', 'RECOVERING')):
                self.__runNumber = runNumber
                self.__log.info('Started run %d' % self.__runNumber)
            else:
                self.__waitForState('STOPPED')
                self.__log.info('Failed to start run %d' % self.__runNumber)

    def stopping(self, retry=True):
        "Stop current pDAQ run"
        self.__log.info('Stopping run %d' % self.__runNumber)

        try:
            self.__runIface.stop()
            runStopped = True
        except socket.error:
            runStopped = False
            if retry:
                self.__connectToDAQRun()
                self.stopping(retry=False)
            else:
                self.__log.errorException('Could not stop pDAQ run %d' %
                                          self.__runNumber)

        if runStopped:
            # wait for DAQRun to indicate that the run has stopped
            if self.__waitForState('STOPPED'):
                self.__log.info('Stopped run %d' % self.__runNumber)

        self.__reportMoni()

    def subrun(self, subrunId, domList):
        """
        Start new subrun, basically a passthru to give <domList> to DAQRunIface.
        """
        if len(domList) > 0:
            action = 'Starting'
        else:
            action = 'Stopping'
        self.__log.info('%s subrun %d.%d' %
                        (action, self.__runNumber, subrunId))

        ret = self.__runIface.flasher(subrunId, domList)
        if ret != 1: return "New subrun FAILED.  See pDAQ logs for more info."
        return "OK"

if __name__ == "__main__":
    import signal

    liveArgs = LiveArgs()
    liveArgs.parse()

    pids = list(Process.findProcess(os.path.basename(sys.argv[0])))

    if liveArgs.isKill():
        pid = int(os.getpid())
        for p in pids:
            if pid != p:
                os.kill(p, signal.SIGKILL)

        raise SystemExit

    if len(pids) > 1:
        print "ERROR: More than one instance of %s is already running!" % \
            basename(sys.argv[0])
        raise SystemExit

    comp = DAQLive(liveArgs)
    try:
        comp.run()
    except:
        print exc_string()
