#!/usr/bin/env python

#
# DAQ Run Server
#  Top level DAQ control object - used by Experiment Control to start/stop/monitor runs
# 
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006

from sys import argv
from DAQLog import *
from DAQMoni import *
from time import sleep
from RunWatchdog import RunWatchdog
from DAQRPC import RPCClient, RPCServer
from os.path import exists, abspath, join
from Process import processList, findProcess
from DAQLaunch import cyclePDAQ, getDeployedClusterConfig
from tarfile import TarFile
from exc_string import *
from shutil import move
from GetIP import getIP
from re import search
import Rebootable
import DAQConfig
import datetime
import optparse
import DAQLog
import Daemon
import socket
import thread
import os

from locate_pdaq import find_pdaq_trunk
# add 'cluster-config' to Python library search path
#
metaDir = find_pdaq_trunk()
sys.path.append(join(metaDir, 'cluster-config'))
from ClusterConfig import *


class RequiredComponentsNotAvailableException(Exception): pass
class IncorrectDAQState                      (Exception): pass
class InsufficientRunInfoData                (Exception): pass

class RunInfo:
    def __init__(self, runNum=None, startTime=None, physicsEvents=None,
                 moniEvents=None, snEvents=None, tcalEvents=None):
        self.runNum        = runNum
        self.startTime     = startTime
        self.physicsEvents = physicsEvents
        self.moniEvents    = moniEvents
        self.snEvents      = snEvents
        self.tcalEvents    = tcalEvents
        if runNum == None or startTime == None or physicsEvents == None \
           or moniEvents == None or snEvents == None or tcalEvents == None:
            raise InsufficientRunInfoData()
        
class DAQRun(RPCServer, Rebootable.Rebootable):
    "Serve requests to start/stop DAQ runs (exp control iface)"
    LOGDIR         = "/tmp" 
    CFGDIR         = "/usr/local/icecube/config"
    SPADEDIR       = "/tmp"
    CATCHALL_PORT  = 9001
    CNC_PORT       = 8080
    MONI_PERIOD    = 30
    WATCH_PERIOD   = 30
    COMP_TOUT      = 300
    
    def __init__(self, portnum, dashDir, clusterConfig,
                 configDir=CFGDIR, logDir=LOGDIR, spadeDir=SPADEDIR, forceConfig=False,
                 doRelaunch=False):
        RPCServer.__init__(self, portnum, "localhost",
                           "DAQ Run Server - object for starting and stopping DAQ runs")
        
        # Can change reboot thread delay here if desired:
        Rebootable.Rebootable.__init__(self) 

        self.runState         = "STOPPED"
        self.register_function(self.rpc_ping)
        self.register_function(self.rpc_start_run)
        self.register_function(self.rpc_stop_run)
        self.register_function(self.rpc_run_state)
        self.register_function(self.rpc_daq_status)
        self.register_function(self.rpc_recover)
        self.register_function(self.rpc_daq_reboot)
        self.register_function(self.rpc_release_runsets)
        self.register_function(self.rpc_daq_summary_xml)
        self.log              = None
        self.runSetID         = None
        self.CnCLogReceiver   = None
        self.catchAllLogger   = None
        self.forceConfig      = forceConfig
        self.dashDir          = dashDir
        self.configDir        = configDir
        self.spadeDir         = spadeDir
        self.clusterConfig    = clusterConfig
        self.logDir           = logDir
        self.requiredComps    = []

        # setCompID is the ID returned by CnCServer
        # daqID is e.g. 21 for string 21
        self.setCompIDs       = []
        self.shortNameOf      = {} # indexed by setCompID
        self.daqIDof          = {} # "                  "
        self.rpcAddrOf        = {} # "                  "
        self.rpcPortOf        = {} # "                  "
        self.mbeanPortOf      = {} # "                  "
        self.loggerOf         = {} # "                  "
        self.logPortOf        = {} # "                  "
        
        self.ip               = getIP()
        self.compPorts        = {} # Indexed by name
        self.cnc              = None
        self.moni             = None
        self.watchdog         = None
        self.lastConfig       = None
        self.doViolentRestart = doRelaunch
        self.prevRunInfo      = None

        # After initialization, start run thread to handle state changes
        self.runThread = thread.start_new_thread(self.run_thread, ())
        
    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log:
            self.log.dashLog(m)
        elif self.catchAllLogger:
            self.catchAllLogger.localAppend(m)

    def parseComponentName(componentString):
        "Find component name in string returned by CnCServer"
        match = search(r'ID#(\d+) (\S+?)#(\d+) at (\S+?):(\d+) ', componentString)
        if not match: return ''
        setCompID = int(match.group(1))
        shortName = match.group(2)
        daqID     = int(match.group(3))
        compIP    = match.group(4)
        compPort  = int(match.group(5))
        return (setCompID, shortName, daqID, compIP, compPort)
    parseComponentName = staticmethod(parseComponentName)

    def getNameList(l):
        "Build list of parsed names from CnCServer"
        for x in l:
            parsed = DAQRun.parseComponentName(x)
            yield "%s#%d" % (parsed[1], parsed[2])
    getNameList = staticmethod(getNameList)

    def isInList(x, l):
        for y in l:
            if y == x: return True
        return False
    isInList = staticmethod(isInList)
    
    def listContains(target, reference):
        "See if list 'target' contained in list 'reference'"
        "(Would be much easier w/ Python 2.4!)"
        for t in target:
            if not DAQRun.isInList(t, reference): return False
        return True
    listContains = staticmethod(listContains)

    def waitForRequiredComponents(self, cncrpc, requiredList, timeOutSecs):
        "Verify that all components in requiredList are present on remote server"
        tstart = datetime.datetime.now()
        while(datetime.datetime.now()-tstart < datetime.timedelta(seconds=timeOutSecs)):
            remoteList = cncrpc.rpccall("rpc_show_components")
            if DAQRun.listContains(requiredList,
                                   list(DAQRun.getNameList(remoteList))):
                return remoteList
            sleep(5)

        # Do some debug logging to show what actually showed up:
        self.logmsg("Got the following %d remote components:" % len(remoteList))
        for x in remoteList:
            self.logmsg(x)
        raise RequiredComponentsNotAvailableException()

    def configureCnCLogging(self, cncrpc, ip, port, logpath):
        "Tell CnCServer where to log to"
        self.CnCLogReceiver = SocketLogger(port, "CnCServer", logpath + "/cncserver.log")
        self.CnCLogReceiver.startServing()
        cncrpc.rpccall("rpc_log_to", ip, port)
        self.logmsg("Created logger for CnCServer")

    def stopCnCLogging(self, cncrpc):
        "Turn off CnC server logging"
        #self.logmsg("Telling CNC Server to close log")
        #cncrpc.rpccall("rpc_close_log")
        if self.CnCLogReceiver:
            self.CnCLogReceiver.stopServing()
            self.CnCLogReceiver = None

    def getComponentsFromGlobalConfig(self, configName, configDir):
        # Get and set global configuration
        self.configuration = DAQConfig.DAQConfig(configName, configDir)
        stringlist = self.configuration.hubIDs()
        kindlist   = self.configuration.kinds()
        complist   = self.configuration.components()
        self.logmsg("Loaded global configuration \"%s\"" % configName)
        requiredComps = []
        for string in stringlist:
            self.logmsg("Configuration includes string/ID %d" % string)
            requiredComps.append("stringHub#%d" % string)
        for kind in kindlist:
            self.logmsg("Configuration includes detector %s" % kind)
        for comp in complist:
            requiredComps.append(comp)
        for comp in requiredComps:
            self.logmsg("Component list will require %s" % comp)
        return requiredComps
    
    def setUpOneComponentLogger(logPath, shortName, daqID, logPort):
        logFile  = "%s/%s-%d.log" % (logPath, shortName, daqID)
        clr = SocketLogger(logPort, shortName, logFile)
        clr.startServing()
        return clr
    setUpOneComponentLogger = staticmethod(setUpOneComponentLogger)
        
    def setUpAllComponentLoggers(self):
        "Sets up loggers for remote components (other than CnCServer)"
        self.logmsg("Setting up logging for %d components" % len(self.setCompIDs))
        for ic in range(0, len(self.setCompIDs)):
            compID = self.setCompIDs[ic]
            self.logPortOf[compID] = 9002 + ic
            self.loggerOf[compID]  = \
                                  DAQRun.setUpOneComponentLogger(self.log.logPath,
                                                                 self.shortNameOf[compID],
                                                                 self.daqIDof[compID],
                                                                 self.logPortOf[compID])
            self.logmsg("%s(%d %s:%d) -> %s:%d" % (self.shortNameOf[compID], compID,
                                                   self.rpcAddrOf[compID],
                                                   self.rpcPortOf[compID],
                                                   self.ip, self.logPortOf[compID]))

    def stopAllComponentLoggers(self):
        "Stops loggers for remote components"
        if self.runSetID:
            self.logmsg("Stopping component logging")
            for compID in self.setCompIDs:
                if self.loggerOf[compID]:
                    self.loggerOf[compID].stopServing()
                    self.loggerOf[compID] = None
            
    def createRunsetLoggerNameList(self):
        "Create a list of arguments in the form of (shortname, daqID, logport, logLevel)"
        for r in self.setCompIDs:
            yield [self.shortNameOf[r], self.daqIDof[r], self.logPortOf[r]]
            
    def isRequiredComponent(shortName, daqID, list):
        return DAQRun.isInList("%s#%d" % (shortName, daqID), list)
    isRequiredComponent = staticmethod(isRequiredComponent)

    def setup_run_logging(self, cncrpc, logDir, runNum, configName):
        # Log file is already defined since STARTING state does not get invoked otherwise
        # Set up logger for CnCServer and required components
        self.log = logCollector(runNum, logDir)
        self.logmsg("Starting run with run number %d, config name %s"
                    % (runNum, configName))
        self.configureCnCLogging(cncrpc, self.ip, 6667, self.log.logPath)

    def queue_for_spade(self, spadeDir, logTopLevel, runNum, runTime, runDuration):
        """
        Put tarball of log and moni files in SPADE directory as well as
        semaphore file to indicate to SPADE to effect the transfer
        """
        if not spadeDir: return
        if not exists(spadeDir): return
        self.logmsg("Queueing data for SPADE (spadeDir=%s, logDir=%s, runNum=%d..."
                    % (spadeDir, logTopLevel, runNum))
        runDir = logCollector.logDirName(runNum)
        basePrefix = "SPS-pDAQ-run-%03d_%04d%02d%02d_%02d%02d%02d_%06d"   \
                     % (runNum, runTime.year, runTime.month, runTime.day, \
                        runTime.hour, runTime.minute, runTime.second,     \
                        runDuration)
        tarBall = "%s/%s.dat.tar" % (spadeDir, basePrefix)
        semFile = "%s/%s.sem"     % (spadeDir, basePrefix)
        self.logmsg("Target files are:\n%s\n%s" % (tarBall, semFile))
        try:
            move("%s/catchall.log" % logTopLevel, "%s/%s" % (logTopLevel, runDir))
            tarObj = TarFile(tarBall, "w")
            tarObj.add("%s/%s" % (logTopLevel, runDir), runDir, True)
            tarObj.close()
            fd = open(semFile, "w")
            fd.close()
        except Exception, e:
            self.logmsg("FAILED to queue data for SPADE: %s" % exc_string())
            
    def build_run_set(self, cncrpc, configName, configDir):
        self.requiredComps = self.getComponentsFromGlobalConfig(configName, configDir)

        # Wait for required components
        self.logmsg("Starting run %d (waiting for required %d components to register w/ CnCServer)"
                    % (self.runNum, len(self.requiredComps)))
        remoteList = self.waitForRequiredComponents(cncrpc, self.requiredComps, DAQRun.COMP_TOUT)
        # Throws RequiredComponentsNotAvailableException
        
        # build CnC run set
        self.runSetID = cncrpc.rpccall("rpc_runset_make",
                                            self.requiredComps)
        self.logmsg("Created Run Set #%d" % self.runSetID)
        
    def fill_component_dictionaries(self, cncrpc):
        """
        Includes configuration, etc. -- can take some time
        Highest level must catch exceptions
        """

        # clear old components
        del self.setCompIDs[:]

        # extract remote component data
        compList = cncrpc.rpccall("rpc_runset_list", self.runSetID)
        for comp in compList:
            self.setCompIDs.append(comp[0])
            self.shortNameOf[ comp[0] ] = comp[1]
            self.daqIDof    [ comp[0] ] = comp[2]
            self.rpcAddrOf  [ comp[0] ] = comp[3]
            self.rpcPortOf  [ comp[0] ] = comp[4]
            self.mbeanPortOf[ comp[0] ] = comp[5]

    def setup_component_loggers(self, cncrpc, ip, runset):
        # Set up log receivers for remote components
        self.setUpAllComponentLoggers()            
        # Tell components where to log to
        l = list(self.createRunsetLoggerNameList())
        cncrpc.rpccall("rpc_runset_log_to", runset, ip, l)

    def setup_monitoring(self):
        # Set up monitoring
        self.moni = DAQMoni(self.log,
                            DAQRun.MONI_PERIOD,
                            self.setCompIDs, self.shortNameOf, self.daqIDof,
                            self.rpcAddrOf, self.mbeanPortOf)

    def setup_watchdog(self):
        # Set up run watchdog
        self.watchdog = RunWatchdog(self.log,
                                    DAQRun.WATCH_PERIOD,
                                    self.setCompIDs, self.shortNameOf,
                                    self.daqIDof, self.rpcAddrOf,
                                    self.mbeanPortOf)

    def runset_configure(self, rpc, runSetID, configName):
        "Configure the run set"
        self.logmsg("Configuring run set...")
        rpc.rpccall("rpc_runset_configure", runSetID, configName)

    def start_run(self, cncrpc):
        cncrpc.rpccall("rpc_runset_start_run", self.runSetID, self.runNum)
        self.logmsg("Started run %d on run set %d" % (self.runNum, self.runSetID))

    def stop_run(self, cncrpc):
        self.logmsg("Stopping run %d" % self.runNum)
        cncrpc.rpccall("rpc_runset_stop_run", self.runSetID)

    def break_existing_runset(self, cncrpc):
        """
        See if runSetID is defined - if so, we have a runset to release
        """
        if self.runSetID:
            self.logmsg("Breaking run set...")
            try:
                cncrpc.rpccall("rpc_runset_break", self.runSetID)
            except Exception, e:
                self.logmsg("WARNING: failed to break run set - CnC Server restarted? "
                            +"Forging on...")
            self.setCompIDs = []
            self.runSetID   = None
            self.lastConfig = None

    def getEventCount(self):
        for cid in self.setCompIDs:
            if self.shortNameOf[cid] == "eventBuilder" and self.daqIDof[cid] == 0:
                return int(self.moni.getSingleBeanField(cid, "backEnd", "NumEventsSent"))
        raise Exception("Could not find eventBuilder component 0!!!!")
    
    def getEBDiskUsage(self):
        for cid in self.setCompIDs:
            if self.shortNameOf[cid] == "eventBuilder" and self.daqIDof[cid] == 0:
                return [int(self.moni.getSingleBeanField(cid, "backEnd", "DiskAvailable")),
                        int(self.moni.getSingleBeanField(cid, "backEnd", "DiskSize"))]
        raise Exception("Could not find eventBuilder component 0!!!!")

    unHealthyCount      = 0
    MAX_UNHEALTHY_COUNT = 10
    
    def check_all(self):
        try:
            if self.moni and self.moni.timeToMoni():
                self.moni.doMoni()
                self.numEvents = self.getEventCount() # Updated in rpc_daq_summary_xml
                                                      # as well
                self.logmsg("\t%s events" % self.numEvents)
                    
        except Exception, e:
            self.logmsg("Exception in monitoring: %s" % exc_string())
            return False

        try:
            if self.watchdog and self.watchdog.timeToWatch():
                healthy = self.watchdog.doWatch()
                if healthy:
                    DAQRun.unHealthyCount = 0
                else:
                    DAQRun.unHealthyCount += 1
                    if DAQRun.unHealthyCount >= DAQRun.MAX_UNHEALTHY_COUNT:
                        DAQRun.unHealthyCount = 0
                        return False
                    
        except Exception, e:
            self.logmsg("Exception in run watchdog: %s" % exc_string())
            return False
        return True
    
    def run_thread(self):
        """
        Handle state transitions.
        """

        self.catchAllLogger = SocketLogger(DAQRun.CATCHALL_PORT, "Catchall",
                                           self.logDir + "/catchall.log")
        self.catchAllLogger.startServing()

        self.cnc = RPCClient("localhost", DAQRun.CNC_PORT)

        logDirCreated = False
        
        while 1:
            if self.runState == "STARTING":
                self.numEvents = 0
                logDirCreated = False
                try:
                    self.runStartTime = None
                    # once per config/runset
                    if self.forceConfig or (self.configName != self.lastConfig):
                        self.break_existing_runset(self.cnc)
                        self.build_run_set(self.cnc, self.configName, self.configDir)
                                                                                        
                    self.fill_component_dictionaries(self.cnc)
                    # once per run
                    self.setup_run_logging(self.cnc, self.logDir, self.runNum,
                                           self.configName)
                    logDirCreated = True
                    self.setup_component_loggers(self.cnc, self.ip, self.runSetID)
                    self.setup_monitoring()
                    self.setup_watchdog()

                    if self.forceConfig or (self.configName != self.lastConfig):
                        self.runset_configure(self.cnc, self.runSetID, self.configName)

                    self.lastConfig = self.configName
                    self.runStartTime = datetime.datetime.now()
                    self.start_run(self.cnc)
                    self.runState = "RUNNING"
                except Exception, e:
                    self.logmsg("Failed to start run: %s" % exc_string())
                    self.runState = "ERROR"
                    
            elif self.runState == "STOPPING" or self.runState == "RECOVERING":
                hadError = False
                if self.runState == "RECOVERING":
                    self.logmsg("Recovering from failed run %d..." % self.runNum)
                    # "Forget" configuration so new run set will be made next time:
                    self.lastConfig = None 
                    hadError = True
                else:
                    try:
                        # Points all loggers back to catchall
                        self.stop_run(self.cnc)
                    except:
                        self.logmsg(exc_string())
                        # Wait for exp. control to signal for recovery:
                        self.runState = "ERROR" 
                        continue

                nev      = 0
                duration = 0
                if self.runStartTime != None:
                    durDelta = datetime.datetime.now()-self.runStartTime
                    duration = durDelta.days*86400 + durDelta.seconds
                    try:
                        self.numEvents = self.getEventCount()
                        self.logmsg("%d events collected in %d seconds" % (self.numEvents,
                                                                           duration))
                    except:
                        self.logmsg("Could not get event count: %s" % exc_string())
                        hadError = True;
                        
                self.moni = None
                self.watchdog = None

                try:      self.stopAllComponentLoggers()
                except:   hadError = True; self.logmsg(exc_string())

                try:      self.stopCnCLogging(self.cnc)
                except:   hadError = True; self.logmsg(exc_string())

                self.logmsg("RPC Call stats:\n%s" % self.cnc.showStats())

                if hadError:
                    self.logmsg("Run terminated WITH ERROR.")
                else:
                    self.logmsg("Run terminated SUCCESSFULLY.")

                try:
                    self.prevRunInfo = RunInfo(self.runNum, self.runStartTime,
                                               self.numEvents, 0, 0, 0)
                except:
                    self.logmsg("Couldn't save run info: %s" % exc_string())
                    self.prevRunInfo = None

                if logDirCreated:
                    self.catchAllLogger.stopServing() 
                    self.queue_for_spade(self.spadeDir, self.logDir, self.runNum,
                                         datetime.datetime.now(), duration)
                    self.catchAllLogger.startServing()

                if hadError and self.doViolentRestart:
                    try:
                        self.logmsg("Doing complete rip-down and restart of pDAQ "+
                                    "(everything but DAQRun)")
                        cyclePDAQ(self.dashDir, self.clusterConfig, self.configDir,
                                  self.logDir, self.spadeDir,
                                  DAQRun.CATCHALL_PORT, DAQRun.CNC_PORT)
                    except:
                        self.logmsg("Couldn't cycle pDAQ components ('%s')!!!"
                                    % exc_string())
                    
                if self.log is not None:
                    self.log.close()
                self.runState = "STOPPED"

            elif self.runState == "RUNNING":
                if not self.check_all():
                    self.logmsg("Caught error in system, going to ERROR state...")
                    self.runState = "ERROR"                    
                else:
                    sleep(0.25)
            else:
                sleep(0.25)
        
    def rpc_run_state(self):
        r'Returns DAQ State, one of "STARTING", "RUNNING", "STOPPED",'
        r'"STOPPING", "ERROR", "RECOVERING"'
        return self.runState
            
    def rpc_ping(self):
        "Returns 1 - use to see if object is reachable"
        return 1

    def rpc_start_run(self, runNumber, subRunNumber, configName):
        """
        Start a run
        runNumber, subRunNumber - integers
        configName              - ASCII configuration name
        """
        self.runNum     = runNumber
        self.configName = configName
        if self.runState != "STOPPED": return 0
        self.runState   = "STARTING"
        return 1
 
    def rpc_stop_run(self):
        "Stop a run"
        if self.runState != "RUNNING":
            self.logmsg("Warning: invalid state (%s), won't stop run." % self.runState)
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
    
    def rpc_daq_reboot(self):
        "Signal DAQ to restart all components"
        self.logmsg("YIKES!!! GOT REBOOT SIGNAL FROM EXPCONT!")
        self.server_close() 
        self.do_reboot()
        raise Exception("REBOOT_FAULT")

    def rpc_release_runsets(self):
        "Tell DAQ in STOPPED state to release any runsets it may be holding"
        if self.runState != "STOPPED":
            raise IncorrectDAQState("DAQ State is %s, need to be %s"
                                    % (self.runState, "STOPPED"))
        self.break_existing_runset(self.cnc)
        return 1

    def rpc_daq_summary_xml(self):
        "Return DAQ status overview XML for Experiment Control"

        # Get summary for current run, if available
        currentRun = ""
        prevRun    = ""
        if self.prevRunInfo:
                prevRun = """
   <run ordering="previous">
      <number>%s</number>
      <start-time>%s</start-time>
      <events>
         <stream>physics</stream>
         <count>%s</count>
      </events>
      <events>
         <stream>monitor</stream>
         <count>%s</count>
      </events>
      <events>
         <stream>sn</stream>
         <count>%s</count>
      </events>
      <events>
         <stream>tcal</stream>
         <count>%s</count>
      </events>
   </run>\
""" % (self.prevRunInfo.runNum, str(self.prevRunInfo.startTime),
       self.prevRunInfo.physicsEvents, self.prevRunInfo.moniEvents,
       self.prevRunInfo.snEvents,      self.prevRunInfo.tcalEvents)
            
        if self.runState == "RUNNING":
            try:
                self.numEvents       = self.getEventCount() # Updated in check_all as well
                self.EBDiskAvailable, self.EBDiskSize = self.getEBDiskUsage()
                currentRun = """
   <run ordering="current">
      <number>%s</number>
      <start-time>%s</start-time>
      <events>
         <stream>physics</stream>
         <count>%s</count>
      </events>
      <events>
         <stream>monitor</stream>
         <count>%s</count>
      </events>
      <events>
         <stream>sn</stream>
         <count>%s</count>
      </events>
      <events>
         <stream>tcal</stream>
         <count>%s</count>
      </events>
   </run>
   <resource warning="10">
      <available>%s</available>
      <capacity>%s</capacity>
      <units>MB</units>
      <name>EventBuilder dispatch cache</name>
   </resource>\
""" % (self.runNum, str(self.runStartTime), self.numEvents, 0, 0, 0,
       self.EBDiskAvailable, self.EBDiskSize)
      
            except:
                self.logmsg("Failed to update event builder quantities "+
                            "for summary XML (%s)!" % exc_string())

        # Global summary
        ret = """\
<daq>%s%s
</daq>\
""" % (prevRun, currentRun)

        return ret


    
if __name__ == "__main__":
    p = optparse.OptionParser()
    
    p.add_option("-c", "--config-dir",
                 action="store",      type="string",
                 dest="configDir",    help="Directory where run configurations are stored")
    
    p.add_option("-f", "--force-reconfig",
                 action="store_true",
                 dest="forceConfig",  help="Force 'configure' opration between runs")
    
    p.add_option("-k", "--kill",
                 action="store_true",
                 dest="kill",         help="Kill existing instance(s) of DAQRun")
    
    p.add_option("-l", "--log-dir",
                 action="store",      type="string",
                 dest="logDir",
                 help="Directory where pDAQ logs/monitoring should be stored")
    
    p.add_option("-n", "--no-daemon",
                 action="store_true",
                 dest="nodaemon",     help="Do not daemonize process")
    
    p.add_option("-p", "--port",
                 action="store",      type="int",
                 dest="port",         help="Listening port for Exp. Control RPC commands")
    
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
                   clusterConfigName = None,
                   nodaemon          = False,
                   forceConfig       = False,
                   doRelaunch        = False,
                   configDir         = "/usr/local/icecube/config",
                   spadeDir          = "/mnt/data/pdaq/runs",
                   logDir            = "/tmp",
                   port              = 9000)
    opt, args = p.parse_args()

    pids = list(findProcess("DAQRun.py", processList()))

    if opt.kill:
        pid = int(os.getpid())
        for p in pids:
            if pid != p:
                # print "Killing %d..." % p
                import signal
                os.kill(p, signal.SIGKILL)
                
        raise SystemExit
    
    if len(pids) > 1:
        print "ERROR: More than one instance of DAQRun.py is already running!"
        raise SystemExit

    dashDir          = join(metaDir, 'dash')
    clusterConfigDir = join(metaDir, 'cluster-config')
    opt.configDir    = abspath(opt.configDir)
    opt.logDir       = abspath(opt.logDir)
    opt.spadeDir     = abspath(opt.spadeDir)

    readClusterConfig = getDeployedClusterConfig(join(clusterConfigDir, '.config'))

    # Choose configuration
    clusterConfigName = "sim-localhost"
    if readClusterConfig:
        clusterConfigName = readClusterConfig
    if opt.clusterConfigName:
        clusterConfigName = opt.clusterConfigName

    clusterConfig = deployConfig(join(clusterConfigDir, 'src', 'main', 'xml'),
                                 clusterConfigName)
            
    if not exists(opt.configDir):
        print "Configuration directory '%s' doesn't exist!  "+\
              "Use the -c option, or -h for help." % opt.configDir
        raise SystemExit

    if not exists(opt.logDir):
        print "Log directory '%s' doesn't exist!  Use the -l option, "+\
              " or -h for help." % opt.logDir
        raise SystemExit

    if not exists(opt.spadeDir):
        print "Spade directory '%s' doesn't exist!  Use the -s option, "+\
              " or -h for help." % opt.spadeDir
        raise SystemExit
    
    if not opt.nodaemon: Daemon.Daemon().Daemonize()
        
    while 1:
        try:
            cl = DAQRun(opt.port, dashDir, clusterConfig,
                        opt.configDir, opt.logDir, opt.spadeDir,
                        opt.forceConfig, opt.doRelaunch)
            try:
                cl.serve_forever()
            finally:
                cl.server_close()
        except KeyboardInterrupt, k:
            cl.server_close()
            raise SystemExit
        except socket.error, e:
            sleep(3)
        except Exception, e:
            print e
            raise SystemExit
