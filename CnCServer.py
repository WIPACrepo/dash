#!/usr/bin/env python

from __future__ import print_function

import Daemon
import datetime
import numbers
import os
import signal
import socket
import sys
import threading
import time

from CnCExceptions import CnCServerException, MissingComponentException, \
    StartInterruptedException
from CnCLogger import CnCLogger
from CompOp import ComponentGroup, OpClose, OpGetConnectionInfo, OpGetState, \
    OpResetComponent
from ComponentManager import ComponentManager
from DAQClient import ComponentName, DAQClient, DAQClientState
from DAQConfig import DAQConfigException, DAQConfigParser
from DAQConst import DAQPort
from DAQLive import DAQLive
from DAQLog import LogSocketServer
from DAQRPC import RPCClient, RPCServer
from ListOpenFiles import ListOpenFiles
from Process import find_python_process
from RunSet import RunSet, SummaryNotReady
from RunSetState import RunSetState
from SocketServer import ThreadingMixIn
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from scmversion import get_scmversion, get_scmversion_str
from xmlparser import XMLBadFileError
from utils import ip

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


# get location of pDAQ trunk
PDAQ_HOME = find_pdaq_trunk()


class DAQPool(object):
    "Pool of DAQClients and RunSets"

    def __init__(self):
        "Create an empty pool"
        self.__pool = {}
        self.__poolLock = threading.RLock()

        self.__sets = []
        self.__setsLock = threading.RLock()

        self.__starting = False

        super(DAQPool, self).__init__()

    def __addInternal(self, comp):
        "This method assumes that self.__poolLock has already been acquired"
        if comp.name not in self.__pool:
            self.__pool[comp.name] = []
        for oldcomp in self.__pool[comp.name]:
            if comp.matches(oldcomp):
                return False

        self.__pool[comp.name].append(comp)
        return True

    def __addRunset(self, runSet):
        self.__setsLock.acquire()
        try:
            self.__sets.append(runSet)
        finally:
            self.__setsLock.release()

    def __buildCompNameList(self, namelist):
        """Build a list of ComponentNames from a list of name strings"""
        compnames = []
        for r in namelist:
            pound = r.rfind("#")
            if pound > 0:
                name = r[0:pound]
                num = int(r[pound + 1:])
            else:
                dash = r.rfind("-")
                if dash > 0:
                    name = r[0:dash]
                    num = int(r[dash + 1:])
                else:
                    name = r
                    num = 0
            compnames.append(ComponentName(name, num))
        return compnames

    def __collectComponents(self, requiredList, compList, logger, timeout):
        """
        Take all components in requiredList from pool and add them to compList.
        Stop collecting if self.__starting is set to False.
        Return the list of any missing components if we time out.
        """
        needed = self.__buildCompNameList(requiredList)
        waitList = []

        dt_timeout = datetime.timedelta(seconds=timeout)

        tstart = datetime.datetime.now()
        while self.__starting and len(needed) > 0:

            self.__poolLock.acquire()
            try:
                for cobj in needed:
                    found = False
                    if cobj.name in self.__pool and \
                            len(self.__pool[cobj.name]) > 0:
                        for comp in self.__pool[cobj.name]:
                            if comp.num == cobj.num and not comp.is_dying:
                                self.__pool[cobj.name].remove(comp)
                                if len(self.__pool[cobj.name]) == 0:
                                    del self.__pool[cobj.name]
                                compList.append(comp)
                                found = True
                                break

                    if not found:
                        waitList.append(cobj)
            finally:
                self.__poolLock.release()

            needed = waitList
            waitList = []

            if len(needed) > 0:
                if datetime.datetime.now() - tstart >= dt_timeout:
                    break

                logger.info("Waiting for %s" %
                            (ComponentManager.format_component_list(needed)), )
                time.sleep(5)

        if not self.__starting:
            raise StartInterruptedException("Collect interrupted")

        if len(needed) == 0:
            return None
        return needed

    def __makeRunsetInternal(self, runConfigDir, runConfigName, runNum,
                             timeout, logger, daqDataDir, forceRestart=True,
                             strict=False):
        """
        Build a runset from the specified run configuration.
        If self.__starting is False, revert everything and raise an exception.
        If successful, return the runset.
        """
        logger.info("Loading run configuration \"%s\"" % runConfigName)
        try:
            runConfig = DAQConfigParser.parse(runConfigDir, runConfigName,
                                              strict)
        except DAQConfigException as ex:
            raise CnCServerException("Cannot load %s from %s" %
                                     (runConfigName, runConfigDir), ex)
        logger.info("Loaded run configuration \"%s\"" % runConfigName)

        nameList = []
        for comp in runConfig.components():
            nameList.append(comp.fullname)

        if nameList is None or len(nameList) == 0:
            raise CnCServerException("No components found in" +
                                     " run configuration \"%s\"" % runConfig)

        compList = []
        try:
            waitList = self.__collectComponents(nameList, compList, logger,
                                                timeout)
        except:
            self.__returnComponents(compList, logger)
            raise

        if waitList is not None:
            self.__returnComponents(compList, logger)
            self.__restartMissingComponents(waitList, runConfig, logger,
                                            daqDataDir)
            raise MissingComponentException(waitList)

        setAdded = False
        try:
            try:
                runSet = self.createRunset(runConfig, compList, logger)
            except:
                runSet = None
                raise

            self.__addRunset(runSet)
            setAdded = True
        finally:
            if not setAdded:
                self.__returnComponents(compList, logger)
                runSet = None

        if runSet is not None:
            (release, revision) = self.getRelease()
            try:
                if self.__starting:
                    # figure out how components should be connected
                    connMap = runSet.build_connection_map()
                if self.__starting:
                    # connect components to each other
                    runSet.connect(connMap, logger)
                if self.__starting:
                    # set the order in which components should be configured
                    runSet.set_order(connMap, logger)
                if self.__starting:
                    # configure components
                    runSet.configure()
                if self.__starting:
                    # if this is a replay run, compute the offset for hit times
                    if runConfig.updateHitSpoolTimes:
                        runSet.init_replay_hubs()
                if not self.__starting:
                    # if the process was interrupted at any point,
                    #  throw an exception
                    raise StartInterruptedException("Start interrupted")
            except:
                runSet.report_run_start_failure(runNum, release, revision)
                if not forceRestart:
                    self.returnRunset(runSet, logger)
                else:
                    self.restartRunset(runSet, logger)
                raise

            cstr = ComponentManager.format_component_list(runSet.components())
            logger.info("Built runset #%d: %s" % (runSet.id, cstr))

        return runSet

    def __removeRunset(self, runSet):
        """
        Remove the runset and return all the components to the pool.

        This method can throw ValueError if the runset is not found
        """
        self.__setsLock.acquire()
        try:
            self.__sets.remove(runSet)
        finally:
            self.__setsLock.release()

    def __restartMissingComponents(self, waitList, runConfig, logger,
                                   daqDataDir):
        cluCfg = self.getClusterConfig(runConfig=runConfig)
        if cluCfg is None:
            logger.error("Cannot restart missing components:"
                         " No cluster config")
        else:
            (deadList, missingList) = cluCfg.extractComponents(waitList)
            if len(missingList) > 0:
                cstr = ComponentManager.format_component_list(missingList)
                logger.error(("Cannot restart missing %s: Not found in"
                              " cluster config \"%s\"") %
                             (cstr, cluCfg.config_name))

            if len(deadList) > 0:
                self.cycle_components(deadList, runConfig.configdir,
                                      daqDataDir, logger, logger.log_port,
                                      logger.live_port)

    def __returnComponents(self, compList, logger):
        ComponentGroup.run_simple(OpResetComponent, compList, (), logger,
                                  report_errors=True)

        self.__poolLock.acquire()
        try:
            for c in compList:
                self.__addInternal(c)
        finally:
            self.__poolLock.release()

    def add(self, comp):
        "Add the component to the config server's pool"
        self.__poolLock.acquire()
        try:
            return self.__addInternal(comp)
        finally:
            self.__poolLock.release()

    def components(self):
        compList = []
        self.__poolLock.acquire()
        try:
            for k in self.__pool:
                for c in self.__pool[k]:
                    compList.append(c)
        finally:
            self.__poolLock.release()

        return compList

    def createRunset(self, runConfig, compList, logger):
        return RunSet(self, runConfig, compList, logger)

    def cycle_components(self, compList, runConfigDir, daqDataDir, logger,
                         logPort, livePort, verbose=False, kill_with_9=False,
                         event_check=False):
        RunSet.cycle_components(compList, runConfigDir, daqDataDir, logger,
                                logPort, livePort, verbose=verbose,
                                kill_with_9=kill_with_9,
                                event_check=event_check)

    def findRunset(self, id):
        "Find the runset with the specified ID"
        runset = None

        self.__setsLock.acquire()
        try:
            for rs in self.__sets:
                if rs.id == id:
                    runset = rs
                    break
        finally:
            self.__setsLock.release()

        return runset

    def getClusterConfig(self, runConfig=None):
        raise NotImplementedError("Unimplemented")

    def getRelease(self):
        return (None, None)

    def getRunsetsInErrorState(self):
        problems = []
        for rs in self.__sets:
            if rs.state == RunSetState.ERROR:
                problems.append(rs)
        return problems

    def listRunsetIDs(self):
        "List active runset IDs"
        ids = []

        self.__setsLock.acquire()
        try:
            for rs in self.__sets:
                ids.append(rs.id)
        finally:
            self.__setsLock.release()

        return ids

    def makeRunset(self, runConfigDir, runConfigName, runNum, timeout, logger,
                   daqDataDir, forceRestart=True, strict=False):
        "Build a runset from the specified run configuration"
        try:
            self.__starting = True
            return self.__makeRunsetInternal(runConfigDir, runConfigName,
                                             runNum, timeout, logger,
                                             daqDataDir,
                                             forceRestart=forceRestart,
                                             strict=strict)
        finally:
            self.__starting = False

    def monitorClients(self, logger=None):
        "check that all components in the pool are still alive"
        count = 0

        clients = []
        for bin in list(self.__pool.values()):
            for c in bin:
                clients.append(c)

        states = ComponentGroup.run_simple(OpGetState, clients, (), logger)
        for c in clients:
            if c in states:
                stateStr = str(states[c])
            else:
                stateStr = DAQClientState.MISSING

            if stateStr == DAQClientState.DEAD or \
               (stateStr == DAQClientState.HANGING and c.is_dead):
                self.remove(c)
                try:
                    c.close()
                except:
                    if logger is not None:
                        logger.error("Could not close %s: %s" %
                                     (c.fullname, exc_string()))
            elif stateStr == DAQClientState.MISSING or \
                 stateStr == DAQClientState.HANGING:
                c.addDeadCount()
            else:
                count += 1

        return count

    def numActiveSets(self):
        num = 0
        self.__setsLock.acquire()
        try:
            for rs in self.__sets:
                if rs.isRunning:
                    num += 1
        finally:
            self.__setsLock.release()

        return num

    def numComponents(self):
        tot = 0

        self.__poolLock.acquire()
        try:
            for binName in self.__pool:
                tot += len(self.__pool[binName])
        finally:
            self.__poolLock.release()

        return tot

    def numSets(self):
        return len(self.__sets)

    def numUnused(self):
        return len(self.__pool)

    def remove(self, comp):
        "Remove a component from the pool"
        self.__poolLock.acquire()
        try:
            if comp.name in self.__pool:
                self.__pool[comp.name].remove(comp)
                if len(self.__pool[comp.name]) == 0:
                    del self.__pool[comp.name]
        finally:
            self.__poolLock.release()

        return comp

    def restartRunset(self, rs, logger, verbose=False, kill_with_9=False,
                      event_check=False):
        try:
            self.__removeRunset(rs)
        except ValueError:
            logger.error("Cannot remove %s (#%d available - %s)" %
                         (rs, len(self.__sets), self.__sets))

        try:
            self.restartRunsetComponents(rs, verbose=verbose,
                                         kill_with_9=kill_with_9,
                                         event_check=event_check)
        except:
            logger.error("Cannot restart %s (#%d available - %s): %s" %
                         (rs, len(self.__sets), self.__sets, exc_string()))

        rs.destroy(ignore_components=True)

    def restartRunsetComponents(self, rs, verbose=False, kill_with_9=True,
                                event_check=False):
        "Placeholder for subclass method"
        raise CnCServerException("Unimplemented for %s" % type(self))

    def returnAll(self, killRunning=True):
        """
        Return all runset components to the pool
        NOTE: This DESTROYS all runsets, unless there is an active run
        """
        removed = None
        self.__setsLock.acquire()
        try:
            for rs in self.__sets:
                if rs.isRunning and not killRunning:
                    return False
            removed = self.__sets[:]
            del self.__sets[:]
        finally:
            self.__setsLock.release()

        savedEx = None
        for rs in removed:
            try:
                self.returnRunsetComponents(rs)
            except:
                if not savedEx:
                    savedEx = sys.exc_info()

            try:
                rs.destroy()
            except:
                if not savedEx:
                    savedEx = sys.exc_info()

        if savedEx:
            raise savedEx[0], savedEx[1], savedEx[2]

        return True

    def returnRunset(self, rs, logger):
        "Return runset components to the pool"
        try:
            self.__removeRunset(rs)
        except ValueError:
            logger.error("Cannot remove %s (#%d available - %s)" %
                         (rs, len(self.__sets), self.__sets))

        savedEx = None
        try:
            self.returnRunsetComponents(rs)
        finally:
            try:
                rs.destroy()
            except:
                savedEx = sys.exc_info()

        if savedEx:
            raise savedEx[0], savedEx[1], savedEx[2]

    def returnRunsetComponents(self, rs, verbose=False, kill_with_9=True,
                               event_check=False):
        "Placeholder for subclass method"
        raise CnCServerException("Unimplemented for %s" % type(self))

    def runset(self, num):
        return self.__sets[num]

    def stopCollecting(self):
        if self.__starting:
            self.__starting = False


class ThreadedRPCServer(ThreadingMixIn, RPCServer):
    pass


class Connector(object):
    "Component connector"

    INPUT = "i"
    OUTPUT = "o"
    OPT_INPUT = "I"
    OPT_OUTPUT = "O"

    def __init__(self, name, descrChar, port):
        """
        Connector constructor
        name - connection name
        descrChar - connection description character (I, i, O, o)
        port - IP port number (for input connections)
        """
        self.__name = name
        if isinstance(descrChar, bool):
            raise Exception("Convert to new format")
        self.__descrChar = descrChar
        if self.isInput:
            self.__port = port
        else:
            self.__port = None

    def __str__(self):
        "String description"
        if self.isOptional:
            connCh = "~"
        else:
            connCh = "="
        if self.isInput:
            return '%d%s>%s' % (self.__port, connCh, self.__name)
        return self.__name + connCh + '>'

    def connectorTuple(self):
        """Return connector tuple (used when registering components)
        This method can raise a ValueError exception if __port is none."""
        if self.__port is not None:
            port = self.__port
        elif not self.isInput:
            port = 0
        else:
            raise ValueError("Connector %s port was set to None" % str(self))

        return (self.__name, self.__descrChar, port)

    @property
    def isInput(self):
        "Return True if this is an input connector"
        return self.__descrChar == self.INPUT or \
            self.__descrChar == self.OPT_INPUT

    @property
    def isOptional(self):
        "Return True if this is an optional connector"
        return self.__descrChar == self.OPT_INPUT or \
            self.__descrChar == self.OPT_OUTPUT

    @property
    def isOutput(self):
        "Return True if this is an output connector"
        return self.__descrChar == self.OUTPUT or \
            self.__descrChar == self.OPT_OUTPUT

    @property
    def name(self):
        "Return the connector name"
        return self.__name

    @property
    def port(self):
        "Return connector port number"
        return self.__port


class CnCServer(DAQPool):
    "Command and Control Server"

    # max time to wait for components to register
    REGISTRATION_TIMEOUT = 60

    def __init__(self, name="GenericServer", clusterDesc=None, copyDir=None,
                 dashDir=None, defaultLogDir=None, runConfigDir=None,
                 daqDataDir=None, spadeDir=None, logIP=None, logPort=None,
                 liveIP=None, livePort=None, restartOnError=True,
                 forceRestart=True, testOnly=False, quiet=False):
        "Create a DAQ command and configuration server"
        self.__name = name
        self.__versionInfo = get_scmversion()

        self.__id = int(time.time())

        self.__clusterDesc = clusterDesc
        self.__copyDir = copyDir
        self.__dashDir = os.path.join(PDAQ_HOME, "dash")
        self.__runConfigDir = runConfigDir
        self.__daqDataDir = daqDataDir
        self.__spadeDir = spadeDir
        self.__defaultLogDir = defaultLogDir

        self.__clusterConfig = None

        self.__restartOnError = restartOnError
        self.__forceRestart = forceRestart
        self.__quiet = quiet

        self.__monitoring = False

        self.__live = None

        self.__openFileCount = None

        super(CnCServer, self).__init__()

        # close and exit on ctrl-C
        #
        signal.signal(signal.SIGINT, self.__closeOnSIGINT)

        self.__log = self.createCnCLogger(quiet=(testOnly or quiet))

        self.__logServer = \
            self.openLogServer(DAQPort.CATCHALL, self.__defaultLogDir)
        self.__logServer.start_serving()

        if logIP is None or logPort is None:
            logIP = "localhost"
            logPort = DAQPort.CATCHALL

        self.__log.open_log(logIP, logPort, liveIP, livePort)

        if testOnly:
            self.__server = None
        else:
            while True:
                try:
                    self.__server = ThreadedRPCServer(DAQPort.CNCSERVER)
                    break
                except socket.error as e:
                    self.__log.error("Couldn't create server socket: %s" % e)
                    sys.exit("Couldn't create server socket: %s" % e)

        if self.__server is not None:
            self.__server.register_function(self.rpc_close_files)
            self.__server.register_function(self.rpc_component_connector_info)
            self.__server.register_function(self.rpc_component_count)
            self.__server.register_function(self.rpc_component_get_bean_field)
            self.__server.register_function(self.rpc_component_list)
            self.__server.register_function(self.rpc_component_list_beans)
            self.__server.register_function(
                self.rpc_component_list_bean_fields)
            self.__server.register_function(self.rpc_component_list_dicts)
            self.__server.register_function(self.rpc_component_register)
            self.__server.register_function(self.rpc_cycle_live)
            self.__server.register_function(self.rpc_end_all)
            self.__server.register_function(self.rpc_list_open_files)
            self.__server.register_function(self.rpc_ping)
            self.__server.register_function(self.rpc_register_component)
            self.__server.register_function(self.rpc_run_summary)
            self.__server.register_function(self.rpc_runset_break)
            self.__server.register_function(self.rpc_runset_configname)
            self.__server.register_function(self.rpc_runset_count)
            self.__server.register_function(self.rpc_runset_events)
            self.__server.register_function(self.rpc_runset_list)
            self.__server.register_function(self.rpc_runset_list_ids)
            self.__server.register_function(self.rpc_runset_make)
            self.__server.register_function(self.rpc_runset_monitor_run)
            self.__server.register_function(self.rpc_runset_start_run)
            self.__server.register_function(self.rpc_runset_state)
            self.__server.register_function(self.rpc_runset_stop_run)
            self.__server.register_function(self.rpc_runset_subrun)
            self.__server.register_function(self.rpc_runset_switch_run)
            self.__server.register_function(self.rpc_version)

        if sys.version_info > (2, 3):
            from DumpThreads import DumpThreadsOnSignal
            DumpThreadsOnSignal(fd=sys.stderr, logger=self.__log)

    def __str__(self):
        return "%s<%s>" % (self.__name, self.getClusterConfig().config_name)

    def __closeOnSIGINT(self, signum, frame):
        if self.closeServer(False):
            print("\nExiting", file=sys.stderr)
            sys.exit(0)
        print("Cannot exit with active runset(s)", file=sys.stderr)

    @staticmethod
    def __countFileDescriptors():
        "Count number of open file descriptors for this process"
        if not sys.platform.startswith("linux"):
            return 0

        path = "/proc/%d/fd" % os.getpid()
        if not os.path.exists(path):
            raise CnCServerException("Path \"%s\" does not exist" % path)

        count = len(os.listdir(path))

        return count

    def __findComponentById(self, compId, includeRunsetComponents=False):
        for c in self.components():
            if c.id == compId:
                return c

        if includeRunsetComponents:
            for rsid in self.listRunsetIDs():
                rs = self.findRunset(rsid)
                for c in rs.components():
                    if c.id == compId:
                        return c

        return None

    def __getComponents(self, idList, getAll):
        compList = []

        if idList is None or len(idList) == 0:
            compList += self.components()
        else:
            for c in self.components():
                for i in [j for j, cid in enumerate(idList) if cid == c.id]:
                    compList.append(c)
                    del idList[i]
                    break

        if getAll or (idList is not None and len(idList) > 0):
            for rsid in self.listRunsetIDs():
                rs = self.findRunset(rsid)
                if getAll:
                    compList += rs.components()
                else:
                    for c in rs.components():
                        for i in [j for j, cid in enumerate(idList)
                                  if cid == c.id]:
                            compList.append(c)
                            del idList[i]
                            break
                    if len(idList) == 0:
                        break

        return compList

    def __listComponentDicts(self, compList):
        slst = []

        states = ComponentGroup.run_simple(OpGetState, compList, (),
                                           self.__log)
        for comp in compList:
            if comp in states:
                stateStr = str(states[comp])
            else:
                stateStr = DAQClientState.DEAD

            cdict = comp.map()
            cdict["state"] = stateStr

            slst.append(cdict)

        return slst

    @classmethod
    def __listCnCOpenFiles(cls):
        userList = ListOpenFiles.run(os.getpid())

        if userList is None or len(userList) <= 0:
            raise CnCServerException("No open file list available!")

        if len(userList) > 1:
            raise CnCServerException(("Expected 1 user from ListOpenFiles," +
                                      " not %d") % len(userList))

        ofList = []
        for f in userList[0].files():
            if isinstance(f.fileDesc(), str) or f.fileDesc() < 3:
                continue

            ofList.append(f)

        return ofList

    def __reportOpenFiles(self, runNum):
        try:
            ofList = self.__listCnCOpenFiles()
        except:
            self.__log.error("Cannot list open files: " + exc_string())
            return

        errmsg = "Open File List\n=============="
        for f in ofList:
            if f.protocol() is None:
                extra = ""
            else:
                extra = " (%s)" % f.protocol()
            errmsg += "\n%4.4s %6.6s %s%s" % \
                      (f.fileDesc(), f.fileType(), f.name, extra)

        self.__log.error(errmsg)

    def breakRunset(self, runSet):
        hadError = False
        if not runSet.isReady:
            try:
                hadError = runSet.stop_run("BreakRunset")
            except:
                self.__log.error("While breaking %s: %s" %
                                 (runSet, exc_string()))

        try:
            if self.__forceRestart or (hadError and self.__restartOnError):
                self.restartRunset(runSet, self.__log)
            else:
                self.returnRunset(runSet, self.__log)
        except:
            self.__log.error("Failed to break %s: %s" %
                             (runSet, exc_string()))

    def client_statistics(self):
        return RPCClient.client_statistics()

    def closeServer(self, killRunning=True):
        try:
            if not self.returnAll(killRunning):
                return False
        except:
            pass

        self.__monitoring = False
        if self.__server is not None:
            self.__server.server_close()

        ComponentGroup.run_simple(OpClose, self.components(), (), self.__log,
                                  report_errors=True)

        self.__log.close_final()
        if self.__logServer is not None:
            self.__logServer.stop_serving()
            self.__logServer = None

        return True

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        "overrideable method used for testing"
        return DAQClient(name, num, host, port, mbeanPort, connectors,
                         self.__quiet)

    def createCnCLogger(self, quiet):
        return CnCLogger("CnC", quiet=quiet)

    def getClusterConfig(self, runConfig=None):
        if self.__clusterConfig is None:
            cdesc = self.__clusterDesc
            cfgDir = self.__runConfigDir
            try:
                cc = DAQConfigParser.\
                     getClusterConfiguration(None, useActiveConfig=True,
                                             clusterDesc=cdesc,
                                             config_dir=cfgDir, validate=False)
                self.__clusterConfig = cc
            except XMLBadFileError:
                if cdesc is None:
                    cdescStr = ""
                else:
                    cdescStr = " for cluster \"%s\"" % cdesc
                raise CnCServerException("Cannot find cluster configuration" +
                                         " %s: %s" % (cdescStr, exc_string()))
        else:
            try:
                self.__clusterConfig.loadIfChanged(runConfig)
            except Exception as ex:
                self.__log.error("Cannot reload cluster config \"%s\": %s" %
                                 (self.__clusterConfig.description, ex))

        return self.__clusterConfig

    def getRelease(self):
        return (self.__versionInfo["release"], self.__versionInfo["repo_rev"])

    def makeRunsetFromRunConfig(self, runConfig, runNum,
                                timeout=REGISTRATION_TIMEOUT, strict=False):
        return self.makeRunset(self.__runConfigDir, runConfig, runNum,
                               timeout, self.__log, self.__daqDataDir,
                               forceRestart=self.__forceRestart, strict=strict)

    def monitorLoop(self):
        "Monitor components to ensure they're still alive"
        new = True
        checkClients = 0
        lastCount = 0
        self.__monitoring = True
        while self.__monitoring:
            # check clients every 5 seconds or so
            #
            if checkClients == 5:
                checkClients = 0
                try:
                    count = self.monitorClients(self.__log)
                except:
                    self.__log.error("Monitoring clients: " + exc_string())
                    count = lastCount

                new = (lastCount != count)
                if new and not self.__quiet:
                    print("%d bins, %d comps" % \
                        (self.numUnused(), count), file=sys.stderr)

                lastCount = count

            checkClients += 1

            problems = self.getRunsetsInErrorState()
            for rs in problems:
                self.__log.error("Returning runset#%d (state=%s)" %
                                 (rs.id, rs.state))
                try:
                    if self.__forceRestart:
                        self.restartRunset(rs, self.__log)
                    else:
                        self.returnRunset(rs, self.__log)
                except:
                    self.__log.error("Failed to return %s: %s" %
                                     (rs, exc_string()))

            time.sleep(1)

    @property
    def name(self):
        return self.__name

    def openLogServer(self, port, logDir):
        logName = os.path.join(logDir, "catchall.log")
        return LogSocketServer(port, "CnCServer", logName, quiet=self.__quiet)

    def restartRunsetComponents(self, rs, verbose=False, kill_with_9=True,
                                event_check=False):
        cluCfg = self.getClusterConfig(runConfig=rs.run_config_data)
        rs.restart_all_components(cluCfg, self.__runConfigDir,
                                  self.__daqDataDir, self.__log.log_port,
                                  self.__log.live_port, verbose=verbose,
                                  kill_with_9=kill_with_9,
                                  event_check=event_check)

    def returnRunsetComponents(self, rs, verbose=False, kill_with_9=True,
                               event_check=False):
        cluCfg = self.getClusterConfig(runConfig=rs.run_config_data)
        rs.return_components(self, cluCfg, self.__runConfigDir,
                             self.__daqDataDir, self.__log.log_port,
                             self.__log.live_port, verbose=verbose,
                             kill_with_9=kill_with_9, event_check=event_check)

    def rpc_close_files(self, fdList):
        savedEx = None
        for fd in fdList:
            try:
                os.close(fd)
                self.__log.error("Manually closed file #%s" % fd)
            except:
                if not savedEx:
                    savedEx = (fd, exc_string())

        if savedEx:
            raise CnCServerException("Cannot close file #%s: %s" %
                                     (savedEx[0], savedEx[1]))

        return 1

    def rpc_component_connector_info(self, idList=None, getAll=True):
        "list component connector information"
        compList = self.__getComponents(idList, getAll)

        results = ComponentGroup.run_simple(OpGetConnectionInfo, compList, (),
                                            self.__log)

        slst = []
        for comp in compList:
            if comp in results:
                result = results[comp]
            else:
                result = DAQClientState.DEAD

            cdict = comp.map()

            if not isinstance(result, list):
                cdict["error"] = str(result)
            else:
                cdict["conn"] = result

            slst.append(cdict)

        return slst

    def rpc_component_count(self):
        "return number of components currently registered"
        return self.numComponents()

    def rpc_component_get_bean_field(self, compId, bean, field,
                                     includeRunsetComponents=False):
        c = self.__findComponentById(compId, includeRunsetComponents)
        if c is None:
            raise CnCServerException("Unknown component #%d" % compId)

        return c.mbean.get(bean, field)

    def rpc_component_list(self, includeRunsetComponents=False):
        "return dictionary of component names -> IDs"
        idDict = {}
        for c in self.components():
            idDict[c.fullname] = c.id

        if includeRunsetComponents:
            for rsid in self.listRunsetIDs():
                rs = self.findRunset(rsid)
                for c in rs.components():
                    idDict[c.fullname] = c.id

        return idDict

    def rpc_component_list_beans(self, compId, includeRunsetComponents=False):
        c = self.__findComponentById(compId, includeRunsetComponents)
        if c is not None:
            return c.mbean.getBeanNames()

        raise CnCServerException("Unknown component #%d" % compId)

    def rpc_component_list_bean_fields(self, compId, bean,
                                       includeRunsetComponents=False):
        c = self.__findComponentById(compId, includeRunsetComponents)
        if c is not None:
            return c.mbean.getBeanFields(bean)

        raise CnCServerException("Unknown component #%d" % compId)

    def rpc_component_list_dicts(self, idList=None, getAll=True):
        "list unused components"
        return self.__listComponentDicts(self.__getComponents(idList, getAll))

    def rpc_component_register(self, name, num, host, port, mbeanPort,
                               connArray):
        "register a component with the server"

        if not isinstance(name, str) or len(name) == 0:
            raise CnCServerException("Bad component name (should be a string)")
        if not isinstance(num, int):
            raise CnCServerException("Bad component number" +
                                     " (should be an integer)")

        connectors = []
        for n in range(len(connArray)):
            d = connArray[n]
            if not isinstance(d, tuple) and not isinstance(d, list):
                errMsg = "Bad %s#%d connector#%d \"%s\"%s" % \
                    (name, num, n, str(d), str(type(d)))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if len(d) != 3:
                errMsg = ("Bad %s#%d connector#%d %s (should have 3" +
                          " elements)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if not isinstance(d[0], str) or len(d[0]) == 0:
                errMsg = ("Bad %s#%d connector#%d %s (first element should" +
                          " be name)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if not isinstance(d[1], str) or len(d[1]) != 1:
                errMsg = ("Bad %s#%d connector#%d %s (second element should" +
                          " be descrChar)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)

            if isinstance(d[2], int):
                connPort = d[2]
            elif isinstance(d[2], str):
                connPort = int(d[2])
            else:
                errMsg = ("Bad %s#%d connector#%d %s (third element should" +
                          " be int)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            connectors.append(Connector(d[0], d[1], connPort))

        client = self.createClient(name, num, host, port, mbeanPort,
                                   connectors)

        if self.add(client):
            self.__log.debug("Registered %s" % client.fullname)
        else:
            self.__log.debug("Ignoring previously registered %s" %
                             client.fullname)

        logIP = ip.convertLocalhostToIpAddr(self.__log.log_host)

        logPort = self.__log.log_port
        if logPort is None:
            if self.__logServer is not None:
                logPort = self.__logServer.port
            else:
                logIP = ""
                logPort = 0

        liveIP = ip.convertLocalhostToIpAddr(self.__log.live_host)

        livePort = self.__log.live_port
        if livePort is None:
            liveIP = ""
            livePort = 0

        return {"id": client.id,
                "logIP": logIP,
                "logPort": logPort,
                "liveIP": liveIP,
                "livePort": livePort,
                "serverId": self.__id}

    def rpc_cycle_live(self):
        "Restart DAQLive thread"
        self.__live.close()
        self.__live = self.startLiveThread()

    def rpc_end_all(self):
        "reset all clients"
        ComponentGroup.run_simple(OpResetComponent, self.components(), (),
                                  report_errors=True)
        return 1

    def rpc_list_open_files(self):
        "list open files"
        ofList = self.__listCnCOpenFiles()

        ofVals = []
        for f in ofList:
            if f.protocol() is None:
                extra = ""
            else:
                extra = " (%s)" % f.protocol()
            ofVals.append((f.fileDesc(), f.fileType(), f.name, extra))

        return ofVals

    def rpc_ping(self):
        "remote method for far end to confirm that server is still alive"
        return self.__id

    def rpc_register_component(self, name, num, host, port, mbeanPort,
                               connArray):
        "backward compatibility shim"
        return self.rpc_component_register(name, num, host, port, mbeanPort,
                                           connArray)

    def rpc_run_summary(self, runNum):
        "Return run summary information (if available)"
        return RunSet.get_run_summary(self.__defaultLogDir, runNum)

    def rpc_runset_break(self, id):
        "break up the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        if runSet.isRunning:
            raise CnCServerException("Cannot break up running runset #%d" % id)

        self.breakRunset(runSet)

        return "OK"

    def rpc_runset_configname(self, id):
        "return run configuration name for this runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        clucfg = runSet.cluster_config()
        if clucfg is None:
            return runSet.config_name
        return "%s@%s" % (runSet.config_name, clucfg)

    def rpc_runset_count(self):
        "return number of existing run sets"
        return self.numSets()

    def rpc_runset_events(self, id, subrunNumber):
        """
        get the number of events for the specified subrun
        from the specified runset
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        return runSet.subrun_events(subrunNumber)

    def rpc_runset_list_ids(self):
        """return a list of active runset IDs"""
        return self.listRunsetIDs()

    def rpc_runset_list(self, id):
        """
        return a list of information about all components
        in the specified runset
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        return self.__listComponentDicts(runSet.components())

    def rpc_runset_make(self, runConfig, runNum=None, strict=False,
                        timeout=REGISTRATION_TIMEOUT):
        "build a runset from the specified run configuration"
        if self.__runConfigDir is None:
            raise CnCServerException("Run configuration directory" +
                                     " has not been set")
        if isinstance(runConfig, list):
            raise CnCServerException("Must now specify a run config name," +
                                     " not a list of components")

        try:
            runSet = self.makeRunsetFromRunConfig(runConfig, runNum,
                                                  strict=strict)
        except MissingComponentException as mce:
            self.__log.error("%s while making runset from \"%s\"" %
                             (str(mce), runConfig))
            runSet = None
        except:
            self.__log.error("While making runset from \"%s\": %s" %
                             (runConfig, exc_string()))
            runSet = None

        if runSet is None:
            return -1

        return runSet.id

    def rpc_runset_monitor_run(self, id, run_num):
        "Return monitoring data for the runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        monidict = runSet.get_event_counts(run_num)
        for key, val in list(monidict.items()):
            if not isinstance(val, str) and \
                not isinstance(val, unicode) and \
                not isinstance(val, numbers.Number):
                monidict[key] = str(val)

        return monidict

    def rpc_runset_start_run(self, id, runNum, runOptions, logDir=None):
        """
        start a run with the specified runset

        id - runset ID
        runNum - run number
        runOptions - bitmapped word (described in RunOption.py)
        logDir - directory where log files are written, defaults to the
                 value specified at CnCServer startup time
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        if logDir is None:
            logDir = self.__defaultLogDir

        if not self.startRun(runSet, runNum, runOptions, log_dir=logDir):
            return "FAILED"

        return "OK"

    def rpc_runset_state(self, id):
        "get the state of the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            return RunSetState.UNKNOWN

        return runSet.state

    def rpc_runset_stop_run(self, id):
        "stop a run with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        delayedException = None
        try:
            hadError = runSet.stop_run(RunSet.NORMAL_STOP)
        except ValueError:
            hadError = True
            delayedException = sys.exc_info()

        chk = 50
        while runSet.stopping() and chk > 0:
            chk -= 1
            time.sleep(1)

        if runSet.stopping():
            raise CnCServerException("Runset#%d is still stopping" % id)

        if self.__forceRestart or (hadError and self.__restartOnError):
            self.restartRunset(runSet, self.__log)

        if delayedException:
            raise delayedException[0], delayedException[1], delayedException[2]

        return "OK"

    def rpc_runset_subrun(self, id, subrunId, subrunData):
        "start a subrun with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        runSet.subrun(subrunId, subrunData)

        return "OK"

    def rpc_runset_switch_run(self, id, runNum):
        "switch the specified runset to a new run number"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        runSet.switch_run(runNum)

        return "OK"

    def rpc_version(self):
        "return the CnCServer release/revision info"
        return self.__versionInfo

    def run(self):
        "Start a server"
        self.__log.info("Version info: " +
                        get_scmversion_str(info=self.__versionInfo))

        t = threading.Thread(name="CnCServer", target=self.monitorLoop)
        t.setDaemon(True)
        t.start()

        try:
            self.__live = self.startLiveThread()
        except:
            self.__log.error("Cannot start I3Live thread: " + exc_string())

        self.__server.serve_forever()

    def saveCatchall(self, runDir):
        "save the catchall.log file to the run directory"
        catchallFile = os.path.join(self.__defaultLogDir, "catchall.log")
        if not os.path.exists(catchallFile):
            return

        if self.__logServer is not None:
            self.__logServer.stop_serving()

        os.rename(catchallFile, os.path.join(runDir, "catchall.log"))

        if self.__logServer is not None:
            self.__logServer.start_serving()

    def server_statistics(self):
        return self.__server.server_statistics()

    def startLiveThread(self):
        "Start I3Live interface thread"
        live = DAQLive(self, self.__log)

        t = threading.Thread(name="DAQLive", target=live.run)
        t.setDaemon(True)
        t.start()

        return live

    def startRun(self, runSet, runNum, runOptions, log_dir=None):
        if log_dir is None:
            log_dir = self.__defaultLogDir

        try:
            openCount = self.__countFileDescriptors()
        except:
            self.__log.error("Cannot count open files: %s" % exc_string())
            openCount = 0

        cluCfg = self.getClusterConfig(runConfig=runSet.run_config_data)
        success = False
        try:
            runSet.start_run(runNum, cluCfg, runOptions, self.__versionInfo,
                             self.__spadeDir, copy_dir=self.__copyDir,
                             log_dir=log_dir, quiet=self.__quiet)
            success = True
        except:
            import traceback
            try:
                self.__log.error("Cannot start runset#%s: %s" %
                                 (runSet.id, traceback.format_exc()))
                runSet.reset()
            except:
                self.__log.error("Cannot reset runset#%s: %s" %
                                 (runSet.id, traceback.format_exc()))

        # file leaks are reported after startRun() because dash.log
        # is created in that method
        #
        if self.__openFileCount is None:
            self.__openFileCount = openCount
        elif openCount > self.__openFileCount:
            runSet.log_to_dash("WARNING: Possible file leak; open file count"
                               " increased from %d to %d" %
                               (self.__openFileCount, openCount))
            if openCount - self.__openFileCount > 5:
                self.__reportOpenFiles(runNum)
            self.__openFileCount = openCount

        if not success:
            raise CnCServerException("Cannot start runset %s" % (runSet, ))

        return success

    def updateRates(self, id):
        """
        This is a convenience method to allow unit tests to force rate updates
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        return runSet.update_rates()

    def versionInfo(self):
        return self.__versionInfo


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("-a", "--copy-dir", dest="copyDir",
                   help="Directory for copies of files sent to SPADE")
    p.add_argument("-C", "--cluster-desc", dest="clusterDesc",
                   help="Cluster description name")
    p.add_argument("-c", "--config-dir", dest="config_dir",
                   help="Directory where run configurations are stored")
    p.add_argument("-d", "--daemon", dest="daemon",
                   action="store_true", default=False,
                   help="Run as a daemon process")
    p.add_argument("-D", "--dashDir", dest="dashDir",
                   default=os.path.join(PDAQ_HOME, "dash"),
                   help="Directory holding Python scripts")
    p.add_argument("-f", "--force-restart", dest="forceRestart",
                   action="store_true", default=True,
                   help="Force components to restart after every run")
    p.add_argument("-F", "--no-force-restart", dest="forceRestart",
                   action="store_false", default=True,
                   help="Don't force components to restart after every run")
    p.add_argument("-k", "--kill", dest="kill",
                   action="store_true", default=False,
                   help="Kill running CnCServer instance(s)")
    p.add_argument("-l", "--log", dest="log",
                   help="Hostname:port for log server")
    p.add_argument("-L", "--liveLog", dest="liveLog",
                   help="Hostname:port for IceCube Live")
    p.add_argument("-o", "--default-log-dir",
                   dest="defaultLogDir",
                   default="/mnt/data/pdaq/log",
                   help="Default directory for pDAQ log/monitoring files")
    p.add_argument("-q", "--data-dir", dest="daqDataDir",
                   default="/mnt/data/pdaqlocal",
                   help="Directory holding physics/tcal/moni/sn files")
    p.add_argument("-r", "--restart-on-error", dest="restartOnError",
                   action="store_true", default=True,
                   help="Restart components if the run ends in an error")
    p.add_argument("-R", "--no-restart-on-error", dest="restartOnError",
                   action="store_false", default=True,
                   help="Don't restart components if the run ends in an error")
    p.add_argument("-s", "--spade-dir", dest="spadeDir",
                   help="Directory where SPADE will pick up logs/moni files")
    p.add_argument("-v", "--verbose", dest="quiet",
                   action="store_false", default=True,
                   help="Write catchall messages to console")

    args = p.parse_args()

    pids = list(find_python_process(os.path.basename(sys.argv[0])))

    if args.kill:
        mypid = os.getpid()
        for pid in pids:
            if pid != mypid:
                # print "Killing %d..." % p
                os.kill(pid, signal.SIGKILL)

        sys.exit(0)

    if len(pids) > 1:
        sys.exit("ERROR: More than one instance of CnCServer.py" +
                 " is already running!")

    args.daqDataDir = os.path.abspath(args.daqDataDir)
    if not os.path.exists(args.daqDataDir):
        sys.exit(("DAQ data directory '%s' doesn't exist!" +
                  "  Use the -q option, or -h for help.") % args.daqDataDir)

    if args.spadeDir is not None:
        args.spadeDir = os.path.abspath(args.spadeDir)
        if not os.path.exists(args.spadeDir):
            sys.exit(("Spade directory '%s' doesn't exist!" +
                      "  Use the -s option, or -h for help.") % args.spadeDir)

    if args.copyDir is not None:
        args.copyDir = os.path.abspath(args.copyDir)
        if not os.path.exists(args.copyDir):
            sys.exit("Log copies directory '%s' doesn't exist!" % args.copyDir)

    if args.defaultLogDir is not None:
        args.defaultLogDir = os.path.abspath(args.defaultLogDir)
        if not os.path.exists(args.defaultLogDir):
            sys.exit("Default log directory '%s' doesn't exist!" %
                     args.defaultLogDir)

    if args.log is None:
        logIP = None
        logPort = None
    else:
        colon = args.log.find(':')
        if colon < 0:
            sys.exit("ERROR: Bad log argument '%s'" % args.log)

        logIP = args.log[:colon]
        logPort = int(args.log[colon + 1:])

    if args.liveLog is None:
        liveIP = None
        livePort = None
    else:
        colon = args.liveLog.find(':')
        if colon < 0:
            sys.exit("ERROR: Bad liveLog argument '%s'" % args.liveLog)

        liveIP = args.liveLog[:colon]
        livePort = int(args.liveLog[colon + 1:])

    if args.daemon:
        Daemon.Daemon().Daemonize()

    if args.config_dir is not None:
        config_dir = args.config_dir
    else:
        config_dir = find_pdaq_config()
    cnc = CnCServer(clusterDesc=args.clusterDesc, name="CnCServer",
                    copyDir=args.copyDir, dashDir=args.dashDir,
                    runConfigDir=config_dir, daqDataDir=args.daqDataDir,
                    spadeDir=args.spadeDir, defaultLogDir=args.defaultLogDir,
                    logIP=logIP, logPort=logPort, liveIP=liveIP,
                    livePort=livePort, forceRestart=args.forceRestart,
                    testOnly=False, quiet=args.quiet)
    try:
        cnc.run()
    except KeyboardInterrupt:
        sys.exit("Interrupted.")
