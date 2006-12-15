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
    LOGDIR = "/tmp" # Should change eventually to something more sensible
    CFGDIR = "/usr/local/icecube/config"
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
        self.CnCLogReceiver  = None
        self.runState        = "STOPPED"
        self.configDir       = configDir
        self.logDir          = logDir
        self.runComponents   = ["zero", "eventBuilder", "ebHarness"]
        self.compNames       = []
        self.compLogReceiver = []
        self.catchAllLogger  = SocketLogger(9001, "Catchall", logDir + "/catchall.log")
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

    def parseComponentName(self, c, field):
        "Find component name in string returned by CnCServer"
        match = search(r'ID#(\d+) (\S+?)#(\d+) at (\S+?):(\d+) ', c)
        if not match: return ''
        compID = match.group(1)
        name   = match.group(2)
        addr   = match.group(4)
        port   = match.group(5)
        self.compPorts[name] = (compID, addr, port)
        return name
    
    def parseNames(self, l):
        "Build list of parsed names from CnCServer"
        for x in l: yield self.parseComponentName(x, 2)

    def listContains(self, target, reference):
        "See if list 'target' contained in list 'reference' (Would be much easier w/ Python 2.4!)"
        for t in target:
            found = False
            for r in reference:
                if t == r: found = True; break
            if not found: return False
        return True

    def waitForRequiredComponents(self, RPCObj, requiredList, timeOutSecs):
        "Verify that all components in requiredList are present on remote server"
        tstart = datetime.datetime.now()
        while(datetime.datetime.now()-tstart < datetime.timedelta(seconds=timeOutSecs)):
            self.remoteComponents = RPCObj.rpc_show_components()
            if self.listContains(requiredList, list(self.parseNames(self.remoteComponents))): return
            sleep(5)

        # Do some debug logging to show what actually showed up:
        self.logmsg("Got the following %d remote components:" % len(remoteComponents))
        for x in self.remoteComponents:
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
        self.stringlist    = self.configuration.strings()
        self.kindlist      = self.configuration.kinds()
        self.logmsg("Loaded global configuration \"%s\"" % self.configName)
        for string in self.stringlist:
            self.logmsg("Configuration includes string %d" % string)
        for kind in self.kindlist:
            self.logmsg("Configuration includes detector %s" % kind)

    def setUpOneComponentLogging(self, compName, logPort):
        logFile  = "%s/%s.log" % (self.log.logPath, compName)
        self.logmsg("Creating logger for %s at %s on port %d" % (compName, logFile, logPort))
        compLogReceiver = SocketLogger(logPort, compName, logFile)
        compLogReceiver.startServing()
        self.compNames.append(compName)
        ID, addr, port = self.compPorts[compName] # Set of 3 - ID, addr, port
        # self.logmsg("%s(%d) -> %s:%d" % (compName, int(ID), addr, int(port)))
        remote = RPCClient(addr, int(port))
        remote.xmlrpc.logTo(int(ID), self.ip, logPort)
        return compLogReceiver

    def setUpAllComponentLogging(self):
        # Set up logging for other components
        self.logmsg("Setting up logging for %d components" % len(self.runComponents))
        for ic in range(0, len(self.runComponents)):
            self.compLogReceiver.append(self.setUpOneComponentLogging(self.runComponents[ic], 9002 + ic))

    def stopAllComponentLogging(self):
        self.logmsg("Stopping all external component logging")
        for ic in range(0, len(self.runComponents)):
            self.compLogReceiver[ic].stopServing()
                            
    def start_run(self):
        "Includes configuration, etc. -- can take some time"
        # Log file is already defined since STARTING state does not get invoked otherwise
        # Set up logger for CnCServer and required components
        try:
            self.CnCRPC = RPCClient("localhost", 8080)
            self.configureCnCLogging()
            self.getComponentsFromGlobalConfig()
            
            # Wait for required components
            self.logmsg("Starting run %d (waiting for required %d components to register w/ CnCServer)"
                        % (self.runNum, len(self.runComponents)))
            self.waitForRequiredComponents(self.CnCRPC, self.runComponents, 60)
            # Throws RequiredComponentsNotAvailableException

            self.setUpAllComponentLogging()

            # build CnC run set
            self.runSetID = self.CnCRPC.rpc_set_make(self.ip, self.compNames)
            self.logmsg("Created Run Set #%d" % self.runSetID)
                            
            # Configure the run set
            self.logmsg("Configuring run set...")
            self.CnCRPC.rpc_set_configure(self.runSetID)

            # Start run.  Eventually, starting/stopping runs will be done
            # without reconfiguration, if configuration hasn't changed
            self.CnCRPC.rpc_set_start_run(self.runSetID, self.runNum)
            self.logmsg("Started run %d on run set %d" % (self.runNum, self.runSetID))
            self.runState = "RUNNING"
            return

        except Exception, e:
            self.logmsg(exc_string())
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
            self.logmsg("Stopping component logging")
            self.stopAllComponentLogging()
            
            if self.runSetID:
                self.logmsg("Stopping run...")
                try: self.CnCRPC.rpc_set_stop_run(self.runSetID)
                except: self.logmsg(exc_string())

                self.logmsg("Breaking run set:")
                try:    self.CnCRPC.rpc_set_break(self.runSetID)
                except: self.logmsg(exc_string())

            self.logmsg("Telling CNC Server to close log")
            try:    self.stopCnCLogging()
            except: self.logmsg(exc_string())

            try:
                self.logmsg("Closing down log receivers")
                if self.CnCLogReceiver: self.CnCLogReceiver.stopServing()
            except:
                self.logmsg(exc_string())
        except:
            self.logmsg(exc_string())

        self.runSetID       = None
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
        if self.runState == "RUNNING" and random() < 0.02:
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
