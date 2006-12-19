#!/usr/bin/env python

#
# DAQ Run Server
#  Top level DAQ control object - used by Experiment Control to start/stop/monitor runs
# 
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006

from sys import argv
from time import sleep
from DAQLog import *
from DAQElement import *
from random import random
from os.path import exists
from DAQRPC import RPCClient
from Process import processList, findProcess
from exc_string import *
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

class RequiredComponentsNotAvailableException(Exception): pass

class DAQRun(RPCServer, Rebootable.Rebootable):
    "Serve requests to start/stop DAQ runs (exp control iface)"
    LOGDIR         = "/tmp" # Should change eventually to something more sensible
    CFGDIR         = "/usr/local/icecube/config"
    CATCHALL_PORT  = 9001
    CNC_PORT       = 8080
    
    def __init__(self, portnum, configDir=CFGDIR, logDir=LOGDIR):
        RPCServer.__init__(self, portnum,
                           "localhost", "DAQ Run Server - object for starting and stopping DAQ runs")
        Rebootable.Rebootable.__init__(self) # Can change reboot thread delay here if desired
        self.register_function(self.rpc_ping)
        self.register_function(self.rpc_start_run)
        self.register_function(self.rpc_stop_run)
        self.register_function(self.rpc_run_state)
        self.register_function(self.rpc_daq_status)
        self.register_function(self.rpc_recover)
        self.register_function(self.rpc_daq_reboot)
        self.runThread = thread.start_new_thread(self.run_thread, ())
        self.log             = None
        self.CnCRPC          = None
        self.runSetID        = None
        self.runSetRunning   = False
        self.runSetCreated   = False
        self.CnCLogReceiver  = None
        self.runState        = "STOPPED"
        self.configDir       = configDir
        self.logDir          = logDir
        self.requiredComps   = []

        # setCompID is the ID returned by CnCServer
        # daqID is e.g. 21 for string 21
        self.setCompIDs      = []
        self.shortNameOf     = {} # indexed by setCompID
        self.daqIDof         = {} # "                  "
        self.addrOf          = {} # "                  "
        self.rpcPortOf       = {} # "                  "
        self.loggerOf        = {} # "                  "
        self.logPortOf       = {} # "                  "
        
        self.catchAllLogger  = SocketLogger(DAQRun.CATCHALL_PORT, "Catchall", logDir + "/catchall.log")
        self.ip              = self.getIP()
        self.catchAllLogger.startServing()
        self.compPorts       = {} # Indexed by name

    def getIP(self):
        """
        Found this gem of a kludge at
        http://mail.python.org/pipermail/python-list/2005-January/300454.html
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('1.2.3.4', 56))
        return s.getsockname()[0]
        
    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log: self.log.dashLog(m)

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
        "See if list 'target' contained in list 'reference' (Would be much easier w/ Python 2.4!)"
        for t in target:
            if not DAQRun.isInList(t, reference): return False
        return True
    listContains = staticmethod(listContains)

    def waitForRequiredComponents(self, RPCObj, requiredList, timeOutSecs):
        "Verify that all components in requiredList are present on remote server"
        tstart = datetime.datetime.now()
        while(datetime.datetime.now()-tstart < datetime.timedelta(seconds=timeOutSecs)):
            remoteList = RPCObj.rpc_show_components()
            if DAQRun.listContains(requiredList,
                                   list(DAQRun.getNameList(remoteList))):
                return remoteList
            sleep(5)

        # Do some debug logging to show what actually showed up:
        self.logmsg("Got the following %d remote components:" % len(remoteList))
        for x in remoteList:
            self.logmsg(x)
        raise RequiredComponentsNotAvailableException()

    def configureCnCLogging(self):
        "Tell CnCServer where to log to"
        self.CnCLogReceiver = SocketLogger(6667, "CnCServer", self.log.logPath + "/cncserver.log")
        self.CnCLogReceiver.startServing()
        self.CnCRPC.rpc_log_to(self.ip, 6667)
        self.logmsg("Created logger for CnCServer")

    def stopCnCLogging(self):
        "Turn off CnC server logging"
        self.CnCRPC.rpc_close_log()
        self.CnCLogReceiver.stopServing()
        self.CnCLogReceiver = None

    def getComponentsFromGlobalConfig(self):
        # Get and set global configuration
        self.configuration = DAQConfig.DAQConfig(self.configName, self.configDir)
        stringlist = self.configuration.strings()
        kindlist   = self.configuration.kinds()
        self.logmsg("Loaded global configuration \"%s\"" % self.configName)
        requiredComps = []
        for string in stringlist:
            self.logmsg("Configuration includes string %d" % string)
            requiredComps.append("stringHub#%d" % string)
        for kind in kindlist:
            self.logmsg("Configuration includes detector %s" % kind)
        requiredComps.append("eventBuilder#0")
        requiredComps.append("globalTrigger#0")
        requiredComps.append("inIceTrigger#0")
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
            self.loggerOf[compID]  = DAQRun.setUpOneComponentLogger(self.log.logPath,
                                                                    self.shortNameOf[compID],
                                                                    self.daqIDof[compID],
                                                                    self.logPortOf[compID])
            self.logmsg("%s(%d %s:%d) -> %s:%d" % (self.shortNameOf[compID], compID,
                                                   self.addrOf[compID], self.rpcPortOf[compID],
                                                   self.ip, self.logPortOf[compID]))
            
    def stopAllComponentLoggers(self):
        "Stops loggers for remote components"
        for compID in self.setCompIDs:
            self.loggerOf[compID].stopServing()
            self.loggerOf[compID] = None
            
    def createRunsetRequestNameList(self):
        "Create a list of names in the form of e.g. 'stringHub#21'"
        for r in self.setCompIDs:
            yield "%s#%d" % (self.shortNameOf[r], self.daqIDof[r])

    def createRunsetLoggerNameList(self, logLevel):
        "Create a list of arguments in the form of (shortname, daqID, logport, logLevel)"
        for r in self.setCompIDs:
            yield [self.shortNameOf[r], self.daqIDof[r], self.logPortOf[r], logLevel]
            
    def isRequiredComponent(shortName, daqID, list):
        return DAQRun.isInList("%s#%d" % (shortName, daqID), list)
    isRequiredComponent = staticmethod(isRequiredComponent)
    
    def start_run(self):
        "Includes configuration, etc. -- can take some time"
        # Log file is already defined since STARTING state does not get invoked otherwise
        # Set up logger for CnCServer and required components
        try:
            self.CnCRPC = RPCClient("localhost", DAQRun.CNC_PORT)
            self.configureCnCLogging()
            self.requiredComps = self.getComponentsFromGlobalConfig()
            
            # Wait for required components
            self.logmsg("Starting run %d (waiting for required %d components to register w/ CnCServer)"
                        % (self.runNum, len(self.requiredComps)))
            remoteList = self.waitForRequiredComponents(self.CnCRPC, self.requiredComps, 60)
            # Throws RequiredComponentsNotAvailableException

            # Form up table of discovered components
            for r in remoteList:
                parsed    = DAQRun.parseComponentName(r)
                setCompID = parsed[0]
                shortName = parsed[1]
                daqID     = parsed[2]
                if(DAQRun.isRequiredComponent(shortName, daqID, self.requiredComps)):
                    self.setCompIDs.append(setCompID)
                    self.shortNameOf[ setCompID ] = shortName
                    self.daqIDof    [ setCompID ] = daqID
                    self.addrOf     [ setCompID ] = parsed[3]
                    self.rpcPortOf  [ setCompID ] = parsed[4]

            # Set up log receivers for remote components
            self.setUpAllComponentLoggers()
            
            # build CnC run set
            self.runSetID = self.CnCRPC.rpc_runset_make(list(self.createRunsetRequestNameList()))
            self.runSetCreated = True

            # Tell components where to log to
            l = list(self.createRunsetLoggerNameList(SocketLogger.LOGLEVEL_INFO))
            self.CnCRPC.rpc_runset_log_to(self.runSetID, self.ip, l)
            
            self.logmsg("Created Run Set #%d" % self.runSetID)
                            
            # Configure the run set
            self.logmsg("Configuring run set...")
            self.CnCRPC.rpc_runset_configure(self.runSetID)

            # Start run.  Eventually, starting/stopping runs will be done
            # without reconfiguration, if configuration hasn't changed
            self.CnCRPC.rpc_runset_start_run(self.runSetID, self.runNum)
            self.runSetRunning = True
            self.logmsg("Started run %d on run set %d" % (self.runNum, self.runSetID))
            self.runState = "RUNNING"
            return

        except Exception, e:
            self.logmsg("Failed to initialize run: %s" % exc_string())
            self.runState = "ERROR"
            return
        
    def stop_run(self):
        "Includes collecting logging, etc. -- can take some time"
        self.logmsg("Stopping run %d" % self.runNum)

        # These operations may fail, but if they do there is nothing to be done
        # except continue to try and shut down, so we do NOT move back into ERROR
        # state (yet).
        
        # Paranoid nested try loops to make sure we at least try to do
        # each step
        try:            
            
            if self.runSetID:
                if self.runSetRunning:
                    self.logmsg("Sending set_stop_run...")
                    try: self.CnCRPC.rpc_runset_stop_run(self.runSetID)
                    except: self.logmsg(exc_string())
                self.runSetRunning = False

                if self.runSetCreated:
                    self.logmsg("Breaking run set...")
                    try:    self.CnCRPC.rpc_runset_break(self.runSetID)
                    except: self.logmsg(exc_string())
                self.runSetCreated = False

                self.logmsg("Stopping component logging")
                self.stopAllComponentLoggers()

            self.logmsg("Telling CNC Server to close log")
            try:    self.stopCnCLogging()
            except: self.logmsg(exc_string())

            try:
                self.logmsg("Closing down log receivers")
                if self.CnCLogReceiver: self.CnCLogReceiver.stopServing()
            except:
                self.logmsg(exc_string())

            self.setCompIDs = []
            
        except:
            self.logmsg(exc_string())

        self.runSetID = None
        self.logmsg("Run terminated.")
        self.log.close()
        self.runState = "STOPPED"
        
    def recover(self):
        "Recover from failed run"
        self.logmsg("Recovering from failed run %d..." % self.runNum)
        self.stop_run()
        
    def run_thread(self):
        "Handle state transitions"
        while 1:
            if   self.runState == "STARTING":   self.start_run()
            elif self.runState == "STOPPING":   self.stop_run()
            elif self.runState == "RECOVERING": self.recover()
            else: sleep(0.25)
        
    def rpc_run_state(self):
        r'Returns DAQ State, one of "STARTING", "RUNNING", "STOPPED", "STOPPING", "ERROR", "RECOVERING"'
        if self.runState == "RUNNING" and random() < 0.01:
            self.logmsg("Generating fake error state.")
            self.runState = "ERROR"
        
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
        if self.runState != "STOPPED": return 0
        self.runNum     = runNumber
        self.configName = configName
        self.log        = logCollector(self.runNum, self.logDir)
        self.logmsg("Starting run with run number %d, config name %s"
                    % (self.runNum, self.configName))
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

def fully_qualified(x):
    "True if 'x' begins with '/'"
    if search(r'^/', x): return True
    else: return False

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-k", "--kill",       action="store_true", dest="kill")
    p.add_option("-p", "--port",       action="store",      type="int", dest="port")
    p.add_option("-n", "--no-daemon",  action="store_true", dest="nodaemon")
    p.add_option("-c", "--config-dir", action="store",      type="string", dest="configDir")
    p.add_option("-l", "--log-dir",    action="store",      type="string", dest="logDir")
    p.set_defaults(kill      = False,
                   nodaemon  = False,
                   configDir = "/usr/local/icecube/config",
                   logDir    = "/tmp",
                   port      = 9000)
    opt, args = p.parse_args()

    pids = list(findProcess("DAQRun.py", processList()))

    if opt.kill:
        pid = int(os.getpid())
        for p in pids:
            if pid != p:
                print "Killing %d..." % p
                import signal
                os.kill(p, signal.SIGKILL)
                
        raise SystemExit
    
    if len(pids) > 1:
        print "ERROR: More than one instance of DAQRun.py is already running!"
        raise SystemExit

    if not exists(opt.configDir) or not fully_qualified(opt.configDir):
        print """\
Configuration directory '%s' doesn't exist or is not fully-qualified.
Use the -d option, or -h for help.\
        """ % opt.configDir
        raise SystemExit

    if not exists(opt.logDir) or not fully_qualified(opt.logDir):
        print """\
Log directory '%s' doesn't exist or is not fully-qualified.
Use the -l option, or -h for help.\
        """ % opt.logDir
        raise SystemExit
    
    if not opt.nodaemon: Daemon.Daemon().Daemonize()
        
    while 1:
        try:
            cl = DAQRun(opt.port, opt.configDir, opt.logDir)
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
