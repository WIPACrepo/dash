#!/usr/bin/env python

#
# DAQ Run Server
#  Top level DAQ control object - used by Experiment Control to start/stop/monitor runs
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006

from DAQConst import DAQPort
from DAQLog import LogSocketServer
from DAQLogClient import BothSocketAppender, DAQLog, FileAppender, \
    LiveSocketAppender, LogSocketAppender, MoniClient, Prio
from DAQMoni import DAQMoni
from RunWatchdog import RunWatchdog
from DAQRPC import RPCClient, RPCServer
from os.path import exists, abspath, join, basename, isdir
from os import listdir, mkdir
from Process import processList, findProcess
from DAQLaunch import cyclePDAQ
from DAQConfig import DAQConfig, DAQConfigNotFound, DOMNotInConfigException
from tarfile import TarFile
from shutil import move, copyfile
from GetIP import getIP
from re import search
from xmlrpclib import Fault
from IntervalTimer import IntervalTimer
from RateCalc import RateCalc
import datetime
import optparse
import Daemon
import socket
import threading
import time
import os
import sys

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID  = "$Id: DAQRun.py 4799 2009-12-14 21:17:26Z dglo $"

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class RequiredComponentsNotAvailableException(Exception): pass
class IncorrectDAQState                      (Exception): pass
class InvalidFlasherArgList                  (Exception): pass
class RunawayGeneratorException              (Exception): pass

class LiveInfo(object):
    def __init__(self, host, port):
        self.__host = host
        self.__port = port

    def __str__(self): return 'Live+%s:%d' % (self.__host, self.__port)
    def getHost(self): return self.__host
    def getPort(self): return self.__port

class RunArgs(object):
    def __init__(self):
        pass

    def __build_parser(self):
        ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
            "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
        usage = "%prog [options]\nversion: " + ver_info
        p = optparse.OptionParser(usage=usage, version=ver_info)

        p.add_option("-a", "--copy-dir",
                     action="store",      type="string",
                     dest="copyDir",
                     help="Directory for copies of files sent to SPADE")

        p.add_option("-B", "--log-to-files-and-i3live",
                     action="store_true",
                     dest="bothMode",
                     help="Send log messages to both I3Live and to local files")

        p.add_option("-c", "--config-dir",
                     action="store",      type="string",
                     dest="configDir",
                     help="Directory where run configurations are stored")

        p.add_option("-C", "--cluster-desc",
                     action="store",      type="string",
                     dest="clusterDesc",
                     help="Cluster description name")

        p.add_option("-f", "--force-reconfig",
                     action="store_true",
                     dest="forceConfig",
                     help="Force 'configure' opration between runs")

        p.add_option("-k", "--kill",
                     action="store_true",
                     dest="kill",
                     help="Kill existing instance(s) of DAQRun")

        p.add_option("-l", "--log-dir",
                     action="store",      type="string",
                     dest="logDir",
                     help="Directory where pDAQ logs/monitoring should be stored")

        p.add_option("-L", "--log-to-i3live",
                     action="store_true",
                     dest="liveMode",
                     help="Send log messages to I3Live")

        p.add_option("-n", "--no-daemon",
                     action="store_true",
                     dest="nodaemon",
                     help="Do not daemonize process")

        p.add_option("-p", "--port",
                     action="store",      type="int",
                     dest="port",
                     help="Listening port for Exp. Control RPC commands")

        p.add_option("-q", "--quiet",
                     action="store_true",
                     dest="quiet",
                     help="Do not write log messages to console")

        p.add_option("-r", "--relaunch",
                     action="store_true",
                     dest="doRelaunch",
                     help="Relaunch pDAQ components during recovery from failed runs")

        p.add_option("-s", "--spade-dir",
                     action="store",      type="string",
                     dest="spadeDir",
                     help="Directory where SPADE will pick up tar'ed logs/moni files")

        p.add_option("-u", "--cluster-config",
                     action="store",      type="string",
                     dest="clusterConfigName",
                     help="Configuration to relaunch [if --relaunch]")

        p.set_defaults(kill              = False,
                       clusterDesc       = None,
                       clusterConfigName = None,
                       nodaemon          = False,
                       quiet             = False,
                       forceConfig       = False,
                       doRelaunch        = False,
                       configDir         = "/usr/local/icecube/config",
                       spadeDir          = "/mnt/data/pdaq/runs",
                       copyDir           = None,
                       logDir            = "/tmp",
                       port              = DAQPort.DAQRUN,
                       liveMode          = False,
                       bothMode          = False)

        return p

    def __process_options(self, opt):
        pids = list(findProcess(basename(sys.argv[0]), processList()))

        if opt.kill:
            pid = int(os.getpid())
            for p in pids:
                if pid != p:
                    # print "Killing %d..." % p
                    import signal
                    os.kill(p, signal.SIGKILL)

            raise SystemExit

        if len(pids) > 1:
            print "ERROR: More than one instance of %s is already running!" % \
                basename(sys.argv[0])
            raise SystemExit

        opt.configDir    = abspath(opt.configDir)
        opt.logDir       = abspath(opt.logDir)
        opt.spadeDir     = abspath(opt.spadeDir)
        if opt.copyDir: opt.copyDir = abspath(opt.copyDir)

        dashDir          = join(metaDir, 'dash')

        try:
            clusterConfig = \
                DAQConfig.getClusterConfiguration(opt.clusterConfigName,
                                                  clusterDesc=opt.clusterDesc)
        except DAQConfigNotFound:
            print "ERROR: No configuration was found!"
            raise SystemExit

        if not exists(opt.configDir):
            print ("Configuration directory '%s' doesn't exist!  "+\
                   "Use the -c option, or -h for help.") % opt.configDir
            raise SystemExit

        if not exists(opt.logDir):
            print ("Log directory '%s' doesn't exist!  Use the -l option, "+\
                   " or -h for help.") % opt.logDir
            raise SystemExit

        if not exists(opt.spadeDir):
            print ("Spade directory '%s' doesn't exist!  Use the -s option, "+\
                   " or -h for help.") % opt.spadeDir
            raise SystemExit

        if opt.copyDir and not exists(opt.copyDir):
            print "Log copies directory '%s' doesn't exist!" % opt.copyDir
            raise SystemExit

        if opt.liveMode and opt.bothMode:
            print "Cannot specify both --log-to-files-and-i3live and" + \
                " --log-to-i3live"
            raise SystemExit

        if not opt.nodaemon: Daemon.Daemon().Daemonize()

        self.port = opt.port
        self.dashDir = dashDir
        self.clusterConfig = clusterConfig
        self.configDir = opt.configDir
        self.logDir = opt.logDir
        self.spadeDir = opt.spadeDir
        self.copyDir = opt.copyDir
        self.forceConfig = opt.forceConfig
        self.doRelaunch = opt.doRelaunch
        self.quiet = opt.quiet
        self.liveMode = opt.liveMode
        self.bothMode = opt.bothMode

    def parse(self):
        p = self.__build_parser()
        opt, args = p.parse_args()
        self.__process_options(opt)

class PayloadTime(object):
    # number of seconds in 11 months
    ELEVEN_MONTHS = 60 * 60 * 24 * (365 - 31)

    # offset from epoch to start of year
    TIME_OFFSET = None

    # previous payload time
    PREV_TIME = None

    def toDateTime(cls, payTime):
        if payTime is None:
            return None

        # recompute start-of-year offset?
        recompute = (PayloadTime.PREV_TIME is None or
                     abs(payTime - PayloadTime.PREV_TIME) >
                     PayloadTime.ELEVEN_MONTHS)

        if recompute:
            now = time.gmtime()
            jan1 = time.struct_time((now.tm_year, 1, 1, 0, 0, 0, 0, 0, -1))
            PayloadTime.TIME_OFFSET = time.mktime(jan1)

        PayloadTime.PREV_TIME = payTime

        curTime = PayloadTime.TIME_OFFSET + (payTime / 10000000000.0)
        ts = time.gmtime(curTime)

        return datetime.datetime(ts.tm_year, ts.tm_mon, ts.tm_mday, ts.tm_hour,
                                 ts.tm_min, ts.tm_sec,
                                 int((curTime * 1000000) % 1000000))

    toDateTime = classmethod(toDateTime)

class RunStats(object):
    def __init__(self):
        self.__runNum = None
        self.__startPayTime = None
        self.__numEvts = None
        self.__evtTime = None
        self.__evtPayTime = None
        self.__numMoni = None
        self.__moniTime = None
        self.__numSN = None
        self.__snTime = None
        self.__numTcal = None
        self.__tcalTime = None

        # Calculates rate over latest 5min interval
        self.__physicsRate = RateCalc(300.)

    def addRate(self, dateTime, numEvts):
        self.__physicsRate.add(dateTime, numEvts)

    def clear(self):
        "Clear run-related statistics"
        self.__startPayTime = None
        self.__numEvts = 0
        self.__evtTime = None
        self.__evtPayTime = None
        self.__numMoni = 0
        self.__moniTime = None
        self.__numSN = 0
        self.__snTime = None
        self.__numTcal = 0
        self.__tcalTime = None
        self.__physicsRate.reset()

    def currentData(self):
        return (self.__runNum, self.__evtTime, self.__numEvts,
                self.__numMoni, self.__numSN, self.__numTcal)

    def getDiskUsage(self, daqRun):
        "Gather disk usage for builder machines"
        (ebDiskAvail, ebDiskSize) = daqRun.getEBDiskUsage()
        (sbDiskAvail, sbDiskSize) = daqRun.getSBDiskUsage()
        return (ebDiskAvail, ebDiskSize, sbDiskAvail, sbDiskSize)

    def getRunNumber(self):
        return self.__runNum

    def hasRunNumber(self):
        return self.__runNum is not None

    def monitorData(self):
        evtDT = PayloadTime.toDateTime(self.__evtPayTime)
        return (self.__numEvts, self.__evtTime, evtDT,
                self.__numMoni, self.__moniTime,
                self.__numSN, self.__snTime,
                self.__numTcal, self.__tcalTime)

    def rate(self):
        return self.__physicsRate.rate()

    def rateEntries(self):
        return self.__physicsRate.entries()

    def setRunNumber(self, runNum):
        self.__runNum = runNum

    def start(self):
        "Initialize statistics for the current run"
        pass

    def stop(self, daqRun):
        "Gather and return end-of-run statistics"
        # get final event counts
        self.updateEventCounts(daqRun)

        if self.__startPayTime is None or self.__evtPayTime is None:
            duration = 0
        else:
            duration = (self.__evtPayTime - self.__startPayTime) / 10000000000

        return (self.__numEvts, self.__numMoni, self.__numSN, self.__numTcal,
                duration)

    def summaryData(self):
        return (self.__runNum, PayloadTime.toDateTime(self.__startPayTime),
                self.__evtTime, self.__numEvts, self.__numMoni, self.__numSN,
                self.__numTcal)

    def updateEventCounts(self, daqRun, addRate=False):
        "Gather run statistics"
        evtData = daqRun.getEventData()

        if evtData is not None:
            (self.__numEvts, self.__evtTime, self.__evtPayTime,
             self.__numMoni, self.__moniTime,
             self.__numSN, self.__snTime,
             self.__numTcal, self.__tcalTime) = evtData

            if addRate and self.__numEvts > 0:
                if self.__startPayTime is None:
                    self.__startPayTime = daqRun.getFirstEventTime()
                    startDT = PayloadTime.toDateTime(self.__startPayTime)
                    self.__physicsRate.add(startDT, 1)
                self.__physicsRate.add(PayloadTime.toDateTime(self.__evtPayTime),
                                       self.__numEvts)

        return evtData

def linkOrCopy(src, dest):
    try:
        os.link(src, dest)
    except OSError, e:
        if e.errno == 18: # Cross-device link
            copyfile(src, dest)
        else:
            raise

class RateThread(threading.Thread):
    "A thread which reports the current event rates"
    def __init__(self, runStats, daqRun, log):
        self.__runStats = runStats
        self.__daqRun = daqRun
        self.__log = log
        self.__done = False

        threading.Thread.__init__(self)

        self.setName("DAQRun:RateThread")

    def done(self):
        return self.__done

    def run(self):
        self.__runStats.updateEventCounts(self.__daqRun, True)

        rateStr = ""
        rate = self.__runStats.rate()
        if rate == 0.0:
            rateStr = ""
        else:
            rateStr = " (%2.2f Hz)" % rate

        (runNum, evtTime, numEvts, numMoni, numSN, numTcal) = \
            self.__runStats.currentData()

        self.__log.error(("\t%s physics events%s, %s moni events," +
                          " %s SN events, %s tcals")  %
                         (numEvts, rateStr, numMoni, numSN, numTcal))
        self.__done = True

class ActiveDOMThread(threading.Thread):
    "A thread which reports the active DOM counts"
    def __init__(self, moni, activeMoni, comps, log, sendDetails):
        self.__moni = moni
        self.__activeMonitor = activeMoni
        self.__comps = comps
        self.__log = log
        self.__sendDetails = sendDetails
        self.__done = False

        threading.Thread.__init__(self)

        self.setName("DAQRun:ActiveDOMThread")

    def done(self):
        return self.__done

    def run(self):
        total = 0
        hubDOMs = {}

        for cid, comp in self.__comps.iteritems():
            if comp.name() == "stringHub":
                nStr = self.__moni.getSingleBeanField(cid, "stringhub",
                                                      "NumberOfActiveChannels")
                num = int(nStr)
                total += num
                if self.__sendDetails:
                    hubDOMs[str(comp.id())] = num

        now = datetime.datetime.now()

        self.__activeMonitor.sendMoni("activeDOMs", total, Prio.ITS)

        if self.__sendDetails:
            if not self.__activeMonitor.sendMoni("activeStringDOMs", hubDOMs,
                                                 Prio.ITS):
                self.__log.error("Failed to send active DOM report")

        self.__done = True

class Component(object):
    def __init__(self, name, id, inetAddr, rpcPort, mbeanPort):
        self.__name = name
        self.__id = id
        self.__inetAddr = inetAddr
        self.__rpcPort = rpcPort
        self.__mbeanPort = mbeanPort
        self.__logger = None
        self.__logPort = None

    def __str__(self):
        return "%s#%s" % (str(self.__name), str(self.__id))

    def clearLogInfo(self):
        self.__logger = None
        self.__logPort = None

    def id(self): return self.__id
    def inetAddress(self): return self.__inetAddr
    def isHub(self): return self.__name.endswith("Hub")
    def logPort(self): return self.__logPort
    def logger(self): return self.__logger
    def mbeanPort(self): return self.__mbeanPort
    def name(self): return self.__name
    def rpcPort(self): return self.__rpcPort

    def setLogInfo(self, logger, logPort):
        self.__logger = logger
        self.__logPort = logPort

class DAQRun(object):
    "Serve requests to start/stop DAQ runs (exp control iface)"

    # active DOM total timer
    ACTIVE_NAME      = "activeTimer"
    ACTIVE_PERIOD    = 60

    # active DOM periodic report timer
    ACTIVERPT_NAME   = "activeRptTimer"
    ACTIVERPT_PERIOD = 600

    # monitoring timer
    MONI_NAME        = "moniTimer"
    MONI_PERIOD      = 100

    # event rate report timer
    RATE_NAME        = "rateTimer"
    RATE_PERIOD      = 60

    # watchdog timer
    WATCH_NAME       = "watchTimer"
    WATCH_PERIOD     = 10

    # max time to wait for components to register
    REGISTRATION_TIMEOUT = 60

    # note that these are bitmapped
    LOG_TO_FILE = 1
    LOG_TO_LIVE = 2
    LOG_TO_BOTH = 3

    # Logging level
    LOGLEVEL = DAQLog.WARN
    # I3Live priority
    LOGPRIO = Prio.ITS

    # number of sequential watchdog complaints to indicate a run is unhealthy
    MAX_UNHEALTHY_COUNT = 3

    # set to True after "could not import IceCube Live" warning is printed
    LIVE_WARNING = False

    def __init__(self, runArgs, startServer=True):

        self.runState         = "STOPPED"

        self.setPort(runArgs.port)

        self.__appender = BothSocketAppender(None, None, None, None,
                                             priority=DAQRun.LOGPRIO)
        self.log              = DAQLog(self.__appender, DAQRun.LOGLEVEL)

        if runArgs.bothMode:
            self.__logMode = DAQRun.LOG_TO_BOTH
        elif runArgs.liveMode:
            self.__logMode = DAQRun.LOG_TO_LIVE
        else:
            self.__logMode = DAQRun.LOG_TO_FILE
 
        if self.__logMode == DAQRun.LOG_TO_FILE or \
                self.__logMode == DAQRun.LOG_TO_BOTH:
            self.__appender.setLogAppender(self.createInitialAppender())
        else:
            self.__appender.setLogAppender(None)

        if self.__logMode == DAQRun.LOG_TO_LIVE or \
                self.__logMode == DAQRun.LOG_TO_BOTH:
            appender = LiveSocketAppender('localhost', DAQPort.I3LIVE,
                                          priority=DAQRun.LOGPRIO)
            self.__appender.setLiveAppender(appender)
        else:
            self.__appender.setLiveAppender(None)

        self.runSetID         = None
        self.CnCLogReceiver   = None
        self.forceConfig      = runArgs.forceConfig
        self.dashDir          = runArgs.dashDir
        self.configDir        = runArgs.configDir
        self.spadeDir         = runArgs.spadeDir
        self.copyDir          = runArgs.copyDir
        self.clusterConfig    = runArgs.clusterConfig
        self.logDir           = runArgs.logDir
        self.requiredComps    = []
        self.versionInfo      = get_version_info(SVN_ID)

        # component key is the ID returned by CnCServer
        self.components       = {}

        self.ip               = getIP()
        self.compPorts        = {} # Indexed by name
        self.cnc              = None
        self.lastConfig       = None
        self.restartOnError   = runArgs.doRelaunch
        self.prevRunStats     = None
        self.runStats         = RunStats()
        self.quiet            = runArgs.quiet
        self.running          = False

        self.moni             = None
        self.__moniTimer      = None

        self.watchdog         = None
        self.unHealthyCount   = 0

        self.rateTimer        = None
        self.rateThread       = None
        self.badRateCount     = 0

        self.__activeDOMTimer = None
        self.__activeMonitor = MoniClient("pdaq", "localhost", DAQPort.I3LIVE)
        if str(self.__activeMonitor).startswith("BOGUS"):
            self.__activeMonitor = None
            self.__activeDOMDetail = None
            if not DAQRun.LIVE_WARNING:
                print >>sys.stderr, "Cannot import IceCube Live code, so" + \
                    " per-string active DOM stats wil not be reported"
                DAQRun.LIVE_WARNING = True
        else:
            self.__activeDOMDetail = self.setup_timer(DAQRun.ACTIVERPT_NAME,
                                                      DAQRun.ACTIVERPT_PERIOD)
        self.__activeDOMThread   = None
        self.__badActiveDOMCount   = 0

        self.__liveInfo       = None
        self.__id = int(time.time())

        # After initialization, start run thread to handle state changes
        if startServer:
            self.runThread = threading.Thread(target=self.run_thread, args=())
            self.runThread.start()

    def __isLogToFile(self):
        return (self.__logMode & DAQRun.LOG_TO_FILE) == DAQRun.LOG_TO_FILE

    def __isLogToLive(self):
        return (self.__logMode & DAQRun.LOG_TO_LIVE) == DAQRun.LOG_TO_LIVE

    def createInitialAppender(self):
        return None

    def setPort(self, portnum):
        self.server = RPCServer(portnum, "localhost",
                                "DAQ Run Server for starting and" +
                                " stopping DAQ runs")

        self.server.register_function(self.rpc_ping)
        self.server.register_function(self.rpc_start_run)
        self.server.register_function(self.rpc_stop_run)
        self.server.register_function(self.rpc_run_state)
        self.server.register_function(self.rpc_daq_status)
        self.server.register_function(self.rpc_recover)
        self.server.register_function(self.rpc_release_runsets)
        self.server.register_function(self.rpc_daq_summary_xml)
        self.server.register_function(self.rpc_flash)
        self.server.register_function(self.rpc_run_monitoring)

    def validateFlashingDoms(config, domlist):
        "Make sure flasher arguments are valid and convert names or string/pos to mbid if needed"
        l = [] # Create modified list of arguments for downstream processing
        not_found = []
        for args in domlist:
            # Look for (dommb, f0, ..., f4) or (name, f0, ..., f4)
            if len(args) == 6:
                domid = args[0]
                if not config.hasDOM(domid):
                    # Look by DOM name
                    try:
                        args[0] = config.getIDbyName(domid)
                    except DOMNotInConfigException, e:
                        not_found.append("DOM %s not found in config!" % domid)
                        continue
            # Look for (str, pos, f0, ..., f4)
            elif len(args) == 7:
                try:
                    pos    = int(args[1])
                    string = int(args.pop(0))
                except ValueError:
                    raise InvalidFlasherArgList("Bad DOM arguments '%s'-'%s' (need integers)!" %
                                                (string, pos))
                try:
                    args[0] = config.getIDbyStringPos(string, pos)
                except DOMNotInConfigException, e:
                    not_found.append("DOM at %s-%s not found in config!" %
                                   (string, pos))
                    continue
            else:
                raise InvalidFlasherArgList("Too many args in %s" % str(args))
            l.append(args)
        return (l, not_found)
    validateFlashingDoms = staticmethod(validateFlashingDoms)

    def findMissing(target, reference):
        """
        Get the list of missing components
        """
        missing = []
        for t in target:
            if not t in reference: missing.append(str(t))
        return missing
    findMissing = staticmethod(findMissing)

    def waitForRequiredComponents(self, cncrpc, requiredList, timeOutSecs):
        """
        Verify that all components in requiredList are present on remote server;
        indicate to dash.log or catchall.log which ones are missing if we time out.
        """
        tstart = datetime.datetime.now()
        while True:
            compList = cncrpc.rpccall("rpc_list_components")
            nameList = []
            for c in compList:
                if c["compNum"] == 0 and not c["compName"].endswith("Hub"):
                    nameList.append(c["compName"])
                else:
                    nameList.append("%s#%d" % (c["compName"], c["compNum"]))
            waitList = DAQRun.findMissing(requiredList, nameList)
            if waitList == []:
                return requiredList

            if datetime.datetime.now()-tstart >= datetime.timedelta(seconds=timeOutSecs):
                raise RequiredComponentsNotAvailableException("Still waiting for "+
                                                              ",".join(waitList))
            self.log.info("Waiting for " + " ".join(waitList))
            time.sleep(5)

    def __configureCnCLogging(self, cncrpc, logIP, logPort, liveIP, livePort,
                              logpath):
        "Tell CnCServer where to log to"
        if logPort is not None and logpath is not None:
            self.CnCLogReceiver = \
                self.createLogSocketServer(logPort, "CnCServer",
                                           logpath + "/cncserver.log")
        if logIP is None:
            logIP = ''
        if logPort is None:
            logPort = 0
        if liveIP is None:
            liveIP = ''
        if livePort is None:
            livePort = 0
        cncrpc.rpccall("rpc_log_to", logIP, logPort, liveIP, livePort)
        self.log.info("Created logger for CnCServer")

    def stopCnCLogging(self, cncrpc):
        "Turn off CnC server logging"
        if self.CnCLogReceiver:
            self.CnCLogReceiver.stopServing()
            self.CnCLogReceiver = None

    def getComponentsFromGlobalConfig(self, configName, configDir):
        "Get and set global configuration"
        self.configuration = DAQConfig.load(configName, configDir)
        self.log.info("Loaded global configuration \"%s\"" % configName)
        requiredComps = []
        for comp in self.configuration.components():
            requiredComps.append(comp.fullname())
        for comp in requiredComps:
            self.log.info("Component list will require %s" % comp)
        return requiredComps

    def createLogSocketServer(cls, logPort, shortName, logFile):
        clr = LogSocketServer(logPort, shortName, logFile)
        clr.startServing()
        return clr
    createLogSocketServer = classmethod(createLogSocketServer)

    def logDirName(runNum):
        "Get log directory name, not including loggingDir portion of path"
        return "daqrun%05d" % runNum
    logDirName = staticmethod(logDirName)

    def createRunLogDirectory(self, runNum, logDir):
        self.setLogPath(runNum, logDir)

        if os.path.exists(self.__logpath):
            # rename unexpectedly lingering log directory
            basenum = 0
            path    = os.path.dirname(self.__logpath)
            name    = os.path.basename(self.__logpath)
            while 1:
                dest = os.path.join(path, "old_%s_%02d" % (name, basenum))
                if not os.path.exists(dest):
                    os.rename(self.__logpath, dest)
                    return
                basenum += 1

        os.mkdir(self.__logpath)

    def createFileAppender(self):
        "Return logger which writes to dash.log"
        return FileAppender("DAQRun", os.path.join(self.__logpath, "dash.log"))

    def getLogPath(self): return self.__logpath

    def setLogPath(self, runNum, logDir):
        if not os.path.exists(logDir):
            raise Exception("Directory %s not found!" % logDir)

        self.__logpath = os.path.join(logDir, DAQRun.logDirName(runNum))

    def setUpAllComponentLoggers(self):
        "Sets up loggers for remote components (other than CnCServer)"
        self.log.info("Setting up logging for %d components" %
                      len(self.components))

        keys = self.components.keys()
        keys.sort()

        for id in keys:
            comp = self.components[id]
            logPort = DAQPort.RUNCOMP_BASE + id
            logFile  = "%s/%s-%d.log" % \
                (self.__logpath, comp.name(), comp.id())
            logger = \
                self.createLogSocketServer(logPort, comp.name(), logFile)
            comp.setLogInfo(logger, logPort)
            self.log.info("%s(%d %s:%d) -> %s:%d" %
                          (comp.name(), id, comp.inetAddress(), comp.rpcPort(),
                           self.ip, logPort))

    def stopAllComponentLoggers(self):
        "Stops loggers for remote components"
        if self.runSetID:
            self.log.info("Stopping component logging")
            for comp in self.components.itervalues():
                if comp.logger():
                    comp.logger().stopServing()
                    comp.clearLogInfo()

    def createRunsetLoggerNameList(self):
        "Create a list of arguments in the form of (shortname, daqID, logport)"
        for comp in self.components.itervalues():
            yield [comp.name(), comp.id(), comp.logPort()]

    def isRequiredComponent(shortName, daqID, compList):
        "XXX - this seems to be unused"
        return "%s#%d" % (shortName, daqID) in compList
    isRequiredComponent = staticmethod(isRequiredComponent)

    def setup_run_logging(self, cncrpc, logDir, runNum, configName):
        "Set up logger for CnCServer and required components"
        if (self.__logMode & DAQRun.LOG_TO_FILE) == DAQRun.LOG_TO_FILE and \
                not (self.__logMode == DAQRun.LOG_TO_FILE and \
                         self.__liveInfo is not None):
            self.__appender.setLogAppender(self.createFileAppender())

        self.log.error(("Version info: %(filename)s %(revision)s %(date)s" +
                        " %(time)s %(author)s %(release)s %(repo_rev)s") %
                       self.versionInfo)
        self.log.error("Starting run %d..." % runNum)
        self.log.error("Run configuration: %s" % configName)
        self.log.error("Cluster configuration: %s" %
                       self.clusterConfig.configName)

        if self.__logMode == DAQRun.LOG_TO_FILE:
            self.__configureCnCLogging(cncrpc, self.ip, DAQPort.CNC2RUNLOG,
                                       None, None, self.__logpath)
        elif self.__logMode == DAQRun.LOG_TO_LIVE:
            self.__configureCnCLogging(cncrpc, None, None,
                                       self.__liveInfo.getHost(),
                                       self.__liveInfo.getPort(),
                                       self.__logpath)
        elif self.__logMode == DAQRun.LOG_TO_BOTH:
            self.__configureCnCLogging(cncrpc, self.ip, DAQPort.CNC2RUNLOG,
                                       self.__liveInfo.getHost(),
                                       self.__liveInfo.getPort(),
                                       self.__logpath)
        else:
            raise Exception('Unknown log mode %s' % self.__logMode)

    def recursivelyAddToTar(self, tar, absDir, file):
        toAdd = join(absDir, file)
        self.log.info("Add %s to tarball as %s..." % (toAdd, file))
        tar.add(toAdd, file, False)
        self.log.info("Done adding %s." % toAdd)
        if isdir(toAdd):
            fileList = listdir(toAdd)
            for f in fileList:
                newFile = join(file, f)
                self.recursivelyAddToTar(tar, absDir, newFile)

    def get_base_prefix(self, runNum, runTime, runDuration):
        return "SPS-pDAQ-run-%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
            (runNum, runTime.year, runTime.month, runTime.day, runTime.hour,
             runTime.minute, runTime.second, runDuration)

    def queue_for_spade(self, spadeDir, copyDir, logTopLevel, runNum, runTime,
                        runDuration):
        """
        Put tarball of log and moni files in SPADE directory as well as
        semaphore file to indicate to SPADE to effect the transfer
        """
        if not spadeDir: return
        if not exists(spadeDir):
            self.log.error("SPADE directory %s does not exist" % spadeDir)
            return
        runDir = DAQRun.logDirName(runNum)
        basePrefix = self.get_base_prefix(runNum, runTime, runDuration)
        try:
            self.move_spade_files(copyDir, basePrefix, logTopLevel, runDir,
                                  spadeDir)
            self.log.info(("Queued data for SPADE (spadeDir=%s, logDir=%s,"
                           " runNum=%s)...") % (spadeDir, logTopLevel, runNum))
        except Exception:
            self.log.error("FAILED to queue data for SPADE: %s" % exc_string())

    def move_spade_files(self, copyDir, basePrefix, logTopLevel, runDir, spadeDir):
        runPath = "%s/%s" % (logTopLevel, runDir)
        if not exists(runPath):
            mkdir(runPath, 0755)
            
        tarBall = "%s/%s.dat.tar" % (spadeDir, basePrefix)
        semFile = "%s/%s.sem"     % (spadeDir, basePrefix)
        self.log.info("Target files are:\n%s\n%s" % (tarBall, semFile))

        tarObj = TarFile(tarBall, "w")

        if isdir(runPath):
            move("%s/catchall.log" % logTopLevel, runPath)
            tarObj.add(runPath, runDir, True)

        # self.recursivelyAddToTar(tarObj, logTopLevel, runDir)
        tarObj.close()
        if copyDir:
            copyFile = "%s/%s.dat.tar" % (copyDir, basePrefix)
            self.log.info("Link or copy %s->%s" % (tarBall, copyFile))
            linkOrCopy(tarBall, copyFile)

        fd = open(semFile, "w")
        fd.close()

    def build_run_set(self, cncrpc, requiredComps):
        "build CnC run set"

        # Wait for required components
        self.log.error(("Starting run %d (waiting for required %d components" +
                       " to register w/ CnCServer)") %
                      (self.runStats.getRunNumber(), len(requiredComps)))
        self.waitForRequiredComponents(cncrpc, requiredComps,
                                       DAQRun.REGISTRATION_TIMEOUT)
        # Throws RequiredComponentsNotAvailableException

        self.runSetID = cncrpc.rpccall("rpc_runset_make", requiredComps)
        self.log.error("Created Run Set #%d" % self.runSetID)

    def fill_component_dictionaries(self, cncrpc):
        """
        Includes configuration, etc. -- can take some time
        Highest level must catch exceptions
        """

        # clear old components
        self.components.clear()

        # extract remote component data
        compList = cncrpc.rpccall("rpc_runset_list", self.runSetID)
        for comp in compList:
            self.components[comp["id"]] = \
                Component(comp["compName"], comp["compNum"], comp["host"],
                          comp["rpcPort"], comp["mbeanPort"])

    def setup_component_loggers(self, cncrpc, ip, runset):
        "Tell components where to log to"

        # Set up log receivers for remote components
        if self.__logMode == DAQRun.LOG_TO_LIVE or \
                (self.__logMode == DAQRun.LOG_TO_FILE and
                 self.__liveInfo is not None):
            # standard I3Live logging or
            # standard pDAQ logging  but the run has been started by I3Live
            cncrpc.rpccall("rpc_runset_livelog_to", runset,
                           self.__liveInfo.getHost(), self.__liveInfo.getPort())
        elif (self.__logMode & DAQRun.LOG_TO_FILE) == DAQRun.LOG_TO_FILE:
            # standard pDAQ logging or both I3Live and standard pDAQ logging
            self.setUpAllComponentLoggers()

            l = list(self.createRunsetLoggerNameList())
            if self.__logMode == DAQRun.LOG_TO_FILE:
                cncrpc.rpccall("rpc_runset_log_to", runset, ip, l)
            else:
                cncrpc.rpccall("rpc_runset_bothlog_to", runset,
                               self.__liveInfo.getHost(),
                               self.__liveInfo.getPort(), ip, l)
        else:
            raise Exception('Unknown log mode %s (info=%s)' %
                            (self.__logMode, str(self.__liveInfo)))

    def setup_monitoring(self, log, moniPath, comps, moniType):
        "Set up monitoring"
        return DAQMoni(log, moniPath, comps, moniType)

    def setup_watchdog(self, log, interval, comps):
        "Set up run watchdog"
        return RunWatchdog(log, interval, comps)

    def setup_timer(self, name, interval):
        "Indirectly create IntervalTimer to make unit testing easier"
        return IntervalTimer(interval)

    def runset_configure(self, rpc, runSetID, configName):
        "Configure the run set"
        self.log.info("Configuring run set...")
        rpc.rpccall("rpc_runset_configure", runSetID, configName)

    def start_run(self, cncrpc):
        cncrpc.rpccall("rpc_runset_start_run", self.runSetID,
                       self.runStats.getRunNumber())
        self.log.error("Started run %d on run set %d" %
                       (self.runStats.getRunNumber(), self.runSetID))

    def stop_run(self, cncrpc):
        self.log.error("Stopping run %d" % self.runStats.getRunNumber())
        cncrpc.rpccall("rpc_runset_stop_run", self.runSetID)

    def break_existing_runset(self, cncrpc):
        """
        See if runSetID is defined - if so, we have a runset to release
        """
        if self.runSetID:
            active = cncrpc.rpccall("rpc_runset_listIDs")
            if active.count(self.runSetID) > 0:
                #
                # CnCServer still knows about this runset, destroy it there
                #
                self.log.info("Breaking run set...")
                try:
                    cncrpc.rpccall("rpc_runset_break", self.runSetID)
                except Exception:
                    self.log.error("WARNING: failed to break run set - " +
                                   exc_string())

            self.components.clear()

            self.runSetID   = None
            self.lastConfig = None

    def getCountTime(self):
        return datetime.datetime.utcnow()

    def getEventData(self):
        if self.moni is None:
            return None

        nEvts = 0
        evtTime = -1
        payloadTime = -1
        nMoni = 0
        moniTime = -1
        nSN = 0
        snTime = -1
        nTCal = 0
        tcalTime = -1

        for cid, comp in self.components.iteritems():
            if comp.name() == "eventBuilder" and comp.id() == 0:
                evtData = self.moni.getSingleBeanField(cid, "backEnd",
                                                       "EventData")
                if type(evtData) == list or type(evtData) == tuple:
                    nEvts = int(evtData[0])
                    evtTime = self.getCountTime()
                    payloadTime = long(evtData[1])
            if comp.name() == "secondaryBuilders" and comp.id() == 0:
                nMoni = int(self.moni.getSingleBeanField(cid, "moniBuilder",
                                                         "TotalDispatchedData"))
                moniTime = self.getCountTime()
            if comp.name() == "secondaryBuilders" and comp.id() == 0:
                nSN = int(self.moni.getSingleBeanField(cid, "snBuilder",
                                                       "TotalDispatchedData"))
                snTime = self.getCountTime()
            if comp.name() == "secondaryBuilders" and comp.id() == 0:
                nTCal = int(self.moni.getSingleBeanField(cid, "tcalBuilder",
                                                         "TotalDispatchedData"))
                tcalTime = self.getCountTime()

        return (nEvts, evtTime, payloadTime, nMoni, moniTime, nSN, snTime,
                nTCal, tcalTime)

    def getEBSubRunNumber(self):
        for cid, comp in self.components.iteritems():
            if comp.name() == "eventBuilder" and comp.id() == 0:
                return int(self.moni.getSingleBeanField(cid, "backEnd",
                                                        "SubrunNumber"))
        return 0

    def getEBDiskUsage(self):
        for cid, comp in self.components.iteritems():
            if comp.name() == "eventBuilder" and comp.id() == 0:
                return [int(self.moni.getSingleBeanField(cid, "backEnd",
                                                         "DiskAvailable")),
                        int(self.moni.getSingleBeanField(cid, "backEnd",
                                                         "DiskSize"))]
        return [0, 0]

    def getFirstEventTime(self):
        firstTime = -1
        for cid, comp in self.components.iteritems():
            if comp.name() == "eventBuilder" and comp.id() == 0:
                firstTime = int(self.moni.getSingleBeanField(cid, "backEnd",
                                                             "FirstEventTime"))
        return firstTime

    def getSBDiskUsage(self):
        for cid, comp in self.components.iteritems():
            if comp.name() == "secondaryBuilders" and comp.id() == 0:
                return [int(self.moni.getSingleBeanField(cid, "tcalBuilder", "DiskAvailable")),
                        int(self.moni.getSingleBeanField(cid, "tcalBuilder", "DiskSize"))]
        return [0, 0]

    def setup_timers(self):
        if self.__logMode == DAQRun.LOG_TO_FILE:
            moniType = DAQMoni.TYPE_FILE
        elif self.__logMode == DAQRun.LOG_TO_LIVE:
            moniType = DAQMoni.TYPE_LIVE
        elif self.__logMode == DAQRun.LOG_TO_BOTH:
            moniType = DAQMoni.TYPE_BOTH
        else:
            raise Exception('Unknown log mode %s' % str(self.__logMode))

        self.moni = self.setup_monitoring(self.log, self.__logpath,
                                          self.components, moniType)
        self.__moniTimer = self.setup_timer(DAQRun.MONI_NAME,
                                            DAQRun.MONI_PERIOD)

        self.__activeDOMTimer = self.setup_timer(DAQRun.ACTIVE_NAME,
                                                 DAQRun.ACTIVE_PERIOD)

        self.rateTimer = self.setup_timer(DAQRun.RATE_NAME,
                                          DAQRun.RATE_PERIOD)

        self.watchdog = self.setup_watchdog(self.log, DAQRun.WATCH_PERIOD,
                                            self.components)

    def check_timers(self):
        if self.moni and self.__moniTimer and self.__moniTimer.isTime():
            self.__moniTimer.reset()
            try:
                self.moni.doMoni()
            except Exception:
                self.log.error("Exception in monitoring: %s" % exc_string())

        if self.__activeDOMTimer and self.__activeDOMTimer.isTime():
            self.__activeDOMTimer.reset()
            if self.__activeMonitor is not None and \
                    self.__activeDOMThread is not None and \
                    not self.__activeDOMThread.done():
                self.__badActiveDOMCount += 1
                if self.__badActiveDOMCount <= 3:
                    self.log.error(("WARNING: Active DOM thread" +
                                    " is hanging (#%d)") %
                                   self.__badActiveDOMCount)
                else:
                    self.log.error("ERROR: Active DOM monitoring seems to be" +
                                   " stuck, monitoring will not be done")
                    self.__activeDOMTimer = None
            else:
                self.__badActiveDOMCount = 0

                sendDetails = False
                if self.__activeDOMDetail is not None and \
                        self.__activeDOMDetail.isTime():
                    sendDetails = True
                    self.__activeDOMDetail.reset()

                self.__activeDOMThread = \
                    ActiveDOMThread(self.moni, self.__activeMonitor,
                                    self.components, self.log, sendDetails)
                self.__activeDOMThread.start()

        if self.rateTimer and self.rateTimer.isTime():
            self.rateTimer.reset()
            if self.rateThread is not None and not self.rateThread.done():
                self.badRateCount += 1
                if self.badRateCount <= 3:
                    self.log.error("WARNING: Rate thread is hanging (#%d)" %
                                   self.badRateCount)
                else:
                    self.log.error("ERROR: Rate calculation seems to be" +
                                   " stuck, stopping run")
                    self.runState = "ERROR"
            else:
                self.badRateCount = 0

                self.rateThread = RateThread(self.runStats, self, self.log)
                self.rateThread.start()

        if self.watchdog:
            if self.watchdog.inProgress():
                if self.watchdog.caughtError():
                    self.watchdog.clearThread()
                    return False

                if self.watchdog.isDone():
                    healthy = self.watchdog.isHealthy()
                    self.watchdog.clearThread()
                    if healthy:
                        self.unHealthyCount = 0
                    else:
                        self.unHealthyCount += 1
                        if self.unHealthyCount >= DAQRun.MAX_UNHEALTHY_COUNT:
                            self.unHealthyCount = 0
                            return False
            elif self.watchdog.timeToWatch():
                self.watchdog.startWatch()

        return True

    def restartComponents(self, pShell, checkExists=True, startMissing=True):
        try:
            self.log.error("Doing complete rip-down and restart of pDAQ " +
                           "(everything but DAQRun)")
            if self.__isLogToFile():
                logPort = DAQPort.CATCHALL
            else:
                logPort = None
            if self.__isLogToLive():
                livePort = DAQPort.I3LIVE
            else:
                livePort = None
            cyclePDAQ(self.dashDir, self.clusterConfig, self.configDir,
                      self.logDir, self.spadeDir, self.copyDir,
                      logPort, livePort, checkExists=checkExists,
                      startMissing=startMissing, parallel=pShell)
        except:
            self.log.error("Couldn't cycle pDAQ components ('%s')!!!" %
                            exc_string())

    def run_thread(self, cnc=None, pShell=None):
        """
        Handle state transitions.
        """

        if self.__isLogToFile():
            catchAllLogger = \
                self.createLogSocketServer(DAQPort.CATCHALL, "Catchall",
                                           self.logDir + "/catchall.log")

            self.__appender.setLogAppender(LogSocketAppender('localhost',
                                                             DAQPort.CATCHALL))

        if cnc is not None:
            self.cnc = cnc
        else:
            self.cnc = RPCClient("localhost", DAQPort.CNCSERVER)

        logDirCreated = False
        forceRestart  = True

        self.running = True
        while self.running:
            if self.runState == "STARTING":
                self.runStats.clear()
                logDirCreated = False
                try:
                    # once per config/runset
                    if self.forceConfig or (self.configName != self.lastConfig):
                        self.break_existing_runset(self.cnc)
                        requiredComps = \
                            self.getComponentsFromGlobalConfig(self.configName,
                                                               self.configDir)
                        self.build_run_set(self.cnc, requiredComps)

                    self.fill_component_dictionaries(self.cnc)

                    if self.__isLogToLive() and not self.__isLogToFile():
                        self.__logpath = None
                        logDirCreated = False
                    else:
                        self.createRunLogDirectory(self.runStats.getRunNumber(),
                                                   self.logDir)
                        logDirCreated = True

                    self.setup_run_logging(self.cnc, self.logDir,
                                           self.runStats.getRunNumber(),
                                           self.configName)
                    self.setup_component_loggers(self.cnc, self.ip,
                                                 self.runSetID)

                    if self.forceConfig or (self.configName != self.lastConfig):
                        self.runset_configure(self.cnc, self.runSetID,
                                              self.configName)

                    # Set up timers after configure to allow the late
                    # binding of the StringHub/datacollector MBeans
                    self.setup_timers()

                    self.lastConfig = self.configName
                    self.runStats.start()
                    self.start_run(self.cnc)
                    self.runState = "RUNNING"
                except Fault:
                    self.log.error("Run start failed: %s" % exc_string())
                    self.runState = "ERROR"
                except Exception:
                    self.log.error("Failed to start run: %s" % exc_string())
                    self.runState = "ERROR"

            elif self.runState == "STOPPING" or self.runState == "RECOVERING":
                hadError = False
                if self.runState == "RECOVERING":
                    if not self.runStats.hasRunNumber():
                        self.log.error("Recovering from failed initial state")
                    else:
                        self.log.error("Recovering from failed run %d..." %
                                       self.runStats.getRunNumber())
                    # "Forget" configuration so new run set
                    # will be made next time:
                    self.lastConfig = None
                    hadError = True
                else:
                    try:
                        # Points all loggers back to catchall
                        self.stop_run(self.cnc)
                    except:
                        self.log.error(exc_string())
                        # Wait for exp. control to signal for recovery:
                        self.runState = "ERROR"
                        continue

                try:
                    (nev, nmoni, nsn, ntcal, duration) = \
                        self.runStats.stop(self)
                except:
                    (nev, nmoni, nsn, ntcal, duration) = (0, 0, 0, 0, 0)
                    self.log.error("Could not get event count: %s" %
                                   exc_string())
                    hadError = True;

                if not hadError:
                    if duration == 0:
                        rateStr = ""
                    else:
                        rateStr = " (%2.2f Hz)" % (float(nev) / float(duration))
                    self.log.error(("%d physics events collected in %d " +
                                    "seconds%s") % (nev, duration, rateStr))
                    self.log.error("%d moni events, %d SN events, %d tcals" %
                                   (nmoni, nsn, ntcal))

                self.moni = None
                self.__moniTimer = None

                self.watchdog = None
                self.unHealthyCount = 0

                self.rateTimer = None
                self.badRateCount = 0

                self.__activeDOMTimer = None

                try:      self.stopAllComponentLoggers()
                except:   hadError = True; self.log.error(exc_string())

                try:      self.stopCnCLogging(self.cnc)
                except:   hadError = True; self.log.error(exc_string())

                self.log.info("RPC Call stats:\n%s" % self.cnc.showStats())

                if hadError:
                    self.log.error("Run terminated WITH ERROR.")
                else:
                    self.log.error("Run terminated SUCCESSFULLY.")

                if self.__isLogToFile() and logDirCreated:
                    catchAllLogger.stopServing()
                    self.queue_for_spade(self.spadeDir, self.copyDir,
                                         self.logDir,
                                         self.runStats.getRunNumber(),
                                         datetime.datetime.now(), duration)
                    catchAllLogger.startServing()

                if forceRestart or (hadError and self.restartOnError):
                    self.restartComponents(pShell)

                if self.__isLogToFile():
                    app = LogSocketAppender('localhost', DAQPort.CATCHALL)
                    self.__appender.setLogAppender(app)
                    if not self.__isLogToLive():
                        self.__appender.setLiveAppender(None)

                self.prevRunStats = self.runStats
                self.runStats = RunStats()

                self.runState = "STOPPED"

            elif self.runState == "RUNNING":
                if not self.check_timers():
                    self.log.error("Caught error in system," +
                                   " going to ERROR state...")
                    self.runState = "ERROR"
                else:
                    time.sleep(0.25)
            else:
                time.sleep(0.25)

        self.log.close()
        if self.__isLogToFile():
            catchAllLogger.stopServing()

    def rpc_run_state(self):
        r'Returns DAQ State, one of "STARTING", "RUNNING", "STOPPED",'
        r'"STOPPING", "ERROR", "RECOVERING"'
        return self.runState

    def rpc_ping(self):
        "Returns ID - use to see if object is reachable"
        return self.__id

    def rpc_flash(self, subRunID, flashingDomsList):
        if self.runState != "RUNNING" or self.runSetID == None:
            self.log.warn(("Warning: invalid state (%s) or runSet ID (%d)," +
                           " won't flash DOMs.") %
                          (self.runState, self.runSetID))
            return 0

        if len(flashingDomsList) > 0:
            try:
                (flashingDomsList,
                 missingDomWarnings) = DAQRun.validateFlashingDoms(self.configuration, flashingDomsList)
                for w in missingDomWarnings:
                    self.log.warn(("Subrun %d: will ignore missing DOM" +
                                   " ('%s')...") % (subRunID, w))
            except InvalidFlasherArgList, i:
                self.log.error("Subrun %d: invalid argument list ('%s')" %
                               (subRunID, i))
                return 0
            self.log.error("Subrun %d: flashing DOMs (%s)" %
                           (subRunID, str(flashingDomsList)))
        else:
            self.log.error("Subrun %d: Got command to stop flashers" %
                           subRunID)
        try:
            self.cnc.rpccall("rpc_runset_subrun", self.runSetID, subRunID, flashingDomsList)
        except Fault:
            self.log.error("CnCServer subrun transition failed: %s" %
                            exc_string())
            return 0
        return 1

    def rpc_start_run(self, runNumber, subRunNumber, configName, logInfo=None):
        """
        Start a run
        runNumber, subRunNumber - integers
        configName              - ASCII configuration name
        logInfo                 - tuple containing (host name/IP, log port)
        """
        self.runStats.setRunNumber(runNumber)
        self.configName = configName

        if logInfo is not None and len(logInfo) == 2:
            self.__liveInfo = LiveInfo(logInfo[0], logInfo[1])
            appender = LiveSocketAppender(logInfo[0], logInfo[1],
                                          priority=DAQRun.LOGPRIO)
            self.__appender.setLiveAppender(appender)
            if self.__logMode == DAQRun.LOG_TO_FILE:
                self.__appender.setLogAppender(None)
        elif (self.__logMode & DAQRun.LOG_TO_LIVE) == DAQRun.LOG_TO_LIVE:
            self.__liveInfo = LiveInfo('localhost', DAQPort.I3LIVE)
        else:
            self.__liveInfo = None

        if self.runState != "STOPPED": return 0
        self.runState   = "STARTING"
        return 1

    def rpc_stop_run(self):
        "Stop a run"
        if self.runState == "STOPPED":
            self.log.warn("Warning: run is already stopped.")
            return 1
        if self.runState != "RUNNING":
            self.log.warn("Warning: invalid state (%s), won't stop run." %
                            self.runState)
            return 0
        self.runState = "STOPPING"
        return 1

    def rpc_daq_status(self):
        "Get current DAQ Status"
        if self.runState != "ERROR":
            return "<ok/>"
        else:
            return "<ERROR/>"

    def rpc_recover(self):
        "Start the recovery from error state"
        self.runState = "RECOVERING"
        return 1

    def rpc_release_runsets(self):
        "Tell DAQ in STOPPED state to release any runsets it may be holding"
        if self.runState != "STOPPED":
            raise IncorrectDAQState("DAQ State is %s, need to be %s"
                                    % (self.runState, "STOPPED"))
        self.break_existing_runset(self.cnc)
        return 1

    def seqMap(n):
        """
        Return [0, -1, 1, -2, 2, ... n]
        """
        MAXSEQ = 10000
        x = 0
        while abs(x) < MAXSEQ:
            if x == n:
                yield n
                return
            if x < 0: yield x; x = -x
            else:     yield x; x = -(x+1)
        raise RunawayGeneratorException("x=%s n=%s", str(x), str(n))
    seqMap = staticmethod(seqMap)

    def rpc_daq_summary_xml(self):
        """
        XXX - this code was only used by anvil and could be removed

        Return DAQ status overview XML for Experiment Control
        """

        # Get summary for current run, if available
        currentRun   = ""
        prevRun      = ""
        if self.prevRunStats:
            (runNum, startTime, evtTime, numEvts, numMoni, numSN, numTcal) = \
                self.prevRunStats.summaryData()
            prevRun = """<run ordering="previous">
      <number>%s</number>
      <start-time>%s</start-time>
      <stop-time>%s</stop-time>
      <events><stream>physics</stream><count>%s</count></events>
      <events><stream>monitor</stream><count>%s</count></events>
      <events><stream>sn</stream>     <count>%s</count></events>
      <events><stream>tcal</stream>   <count>%s</count></events>
   </run>
""" % (runNum, startTime, evtTime, numEvts, numMoni, numSN, numTcal)

        if self.runState == "RUNNING" and self.runStats.hasRunNumber():
            try:
                (ebDiskAvail, ebDiskSize, sbDiskAvail, sbDiskSize) = \
                    self.runStats.getDiskUsage(self)
            except:
                (ebDiskAvail, ebDiskSize, sbDiskAvail, sbDiskSize) = \
                    (0, 0, 0, 0)
                self.log.error("Failed to update disk usage quantities "+
                               "for summary XML (%s)!" % exc_string())

            (runNum, evtTime, numEvts, numMoni, numSN, numTcal) = \
             self.runStats.currentData()
            currentRun = """\
   <run ordering="current">
      <number>%s</number>
      <start-time>%s</start-time>
      <events><stream>physics</stream><count>%s</count></events>
      <events><stream>monitor</stream><count>%s</count></events>
      <events><stream>sn</stream>     <count>%s</count></events>
      <events><stream>tcal</stream>   <count>%s</count></events>
   </run>
   <resource warning="10">
     <available>%s</available><capacity>%s</capacity><units>MB</units>
     <name>EventBuilder dispatch cache</name>
   </resource>
   <resource warning="10">
      <available>%s</available><capacity>%s</capacity><units>MB</units>
      <name>Secondary builders dispatch cache</name>
   </resource>
""" % (runNum, startTime, numEvts, numMoni, numSN, numTcal,
       ebDiskAvail, ebDiskSize, sbDiskAvail, sbDiskSize)

        # Add subrun counts
        subRunCounts = ""
        try:
            currentSubRun = self.getEBSubRunNumber()
            for i in DAQRun.seqMap(currentSubRun):
                subRunCounts += "      <subRun><subRunNum>%d</subRunNum><events>%s</events></subRun>\n" \
                                 % (i, self.cnc.rpccall("rpc_runset_events", self.runSetID, i))
        except AttributeError: # This happens after eventbuilder disappears
            pass
        except Exception:
            self.log.error(exc_string())

        subRunEventXML  = "   <subRunEventCounts>\n"
        subRunEventXML += subRunCounts
        subRunEventXML += "   </subRunEventCounts>\n"

        # Global summary
        ret = """<daq>\n%s%s%s</daq>""" % (prevRun, currentRun, subRunEventXML)
        return ret

    def rpc_run_monitoring(self):
        "Return monitoring data for the current run"

        monDict = {}

        if self.runStats.hasRunNumber() and self.runState == "RUNNING":
            self.runStats.updateEventCounts(self, True)
            (numEvts, evtTime, payTime, numMoni, moniTime, numSN, snTime,
             numTcal, tcalTime) = self.runStats.monitorData()
        elif self.prevRunStats.hasRunNumber() and self.runState == "STOPPED":
            (numEvts, evtTime, payTime, numMoni, moniTime, numSN, snTime,
             numTcal, tcalTime) = self.prevRunStats.monitorData()

        monDict["physicsEvents"] = numEvts
        monDict["eventTime"] = str(evtTime)
        monDict["eventPayloadTime"] = str(payTime)
        monDict["moniEvents"] = numMoni
        monDict["moniTime" ] = str(moniTime)
        monDict["snEvents"] = numSN
        monDict["snTime" ] = str(snTime)
        monDict["tcalEvents"] = numTcal
        monDict["tcalTime" ] = str(tcalTime)

        return monDict

if __name__ == "__main__":
    runArgs = RunArgs()
    runArgs.parse()

    while 1:
        try:
            cl = DAQRun(runArgs)
            try:
                cl.server.serve_forever()
            finally:
                cl.server.server_close()
        except KeyboardInterrupt:
            cl.server.server_close()
            raise SystemExit
        except socket.error:
            time.sleep(3)
        except Exception, e:
            print e
            raise SystemExit
