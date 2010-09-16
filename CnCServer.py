#!/usr/bin/env python

import Daemon, datetime, errno, optparse, os, signal, socket, sys, threading, \
    time

from CnCLogger import CnCLogger
from CompOp import ComponentOperation, ComponentOperationGroup
from DAQClient import ComponentName, DAQClient
from DAQConfig import DAQConfigParser, XMLFileNotFound
from DAQConst import DAQPort
from DAQLive import DAQLive
from DAQLog import DAQLog, LogSocketServer
from DAQRPC import RPCServer
from Process import processList, findProcess
from RunSet import RunSet
from RunSetState import RunSetState
from SocketServer import ThreadingMixIn

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID  = "$Id: CnCServer.py 5227 2010-09-16 23:11:47Z dglo $"

class CnCServerException(Exception): pass

class DAQPool(object):
    "Pool of DAQClients and RunSets"

    def __init__(self, defaultDebugBits=None):
        "Create an empty pool"
        self.__pool = {}
        self.__poolLock = threading.RLock()

        self.__sets = []
        self.__setsLock = threading.RLock()

        self.__defaultDebugBits = defaultDebugBits

        super(DAQPool, self).__init__()

    def __addInternal(self, comp):
        "This method assumes that self.__poolLock has already been acquired"
        if not self.__pool.has_key(comp.name()):
            self.__pool[comp.name()] = []
        self.__pool[comp.name()].append(comp)

    def __addRunset(self, runSet):
        self.__setsLock.acquire()
        try:
            self.__sets.append(runSet)
        finally:
            self.__setsLock.release()

    def __collectComponents(self, requiredList, compList, logger, timeout):
        """
        Take all components in requiredList from pool and add them to compList.
        Return the list of any missing components if we time out.
        """
        needed = []
        for r in requiredList:
            pound = r.rfind("#")
            if pound > 0:
                name = r[0:pound]
                num = int(r[pound+1:])
            else:
                dash = r.rfind("-")
                if dash > 0:
                    name = r[0:dash]
                    num = int(r[dash+1:])
                else:
                    name = r
                    num = 0
            needed.append(ComponentName(name, num))

        tstart = datetime.datetime.now()
        while len(needed) > 0:
            waitList = []

            self.__poolLock.acquire()
            try:
                for cn in needed:
                    found = False
                    if self.__pool.has_key(cn.name()) and \
                            len(self.__pool[cn.name()]) > 0:
                        for comp in self.__pool[cn.name()]:
                            if comp.num() == cn.num():
                                self.__pool[cn.name()].remove(comp)
                                if len(self.__pool[cn.name()]) == 0:
                                    del self.__pool[cn.name()]
                                compList.append(comp)
                                found = True
                                break

                    if not found:
                        waitList.append(cn)
            finally:
                self.__poolLock.release()

            needed = waitList

            if len(needed) > 0:
                if datetime.datetime.now()-tstart >= \
                        datetime.timedelta(seconds=timeout):
                    break

                logger.info("Waiting for " + str(needed))
                time.sleep(5)

        if len(waitList) == 0:
            waitList = None
        return waitList

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

    def __returnComponents(self, compList, logger):
        tGroup = ComponentOperationGroup(ComponentOperation.RESET_COMP)
        for c in compList:
            tGroup.start(c, logger, ())
        tGroup.wait()
        tGroup.reportErrors(logger, "reset")

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
            self.__addInternal(comp)
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

    def findRunset(self, id):
        "Find the runset with the specified ID"
        runset = None

        self.__setsLock.acquire()
        try:
            for s in self.__sets:
                if s.id() == id:
                    runset = s
                    break
        finally:
            self.__setsLock.release()

        return runset

    def getRunsetsInErrorState(self):
        problems = []
        for rs in self.__sets:
            if rs.state() == RunSetState.ERROR:
                problems.append(rs)
        return problems

    def listRunsetIDs(self):
        "List active runset IDs"
        ids = []

        self.__setsLock.acquire()
        try:
            for s in self.__sets:
                ids.append(s.id())
        finally:
            self.__setsLock.release()

        return ids

    def makeRunset(self, runConfigDir, runConfigName, timeout, logger,
                   forceRestart=True, strict=True):
        "Build a runset from the specified run configuration"
        logger.info("Loading run configuration \"%s\"" % runConfigName)
        runConfig = DAQConfigParser.load(runConfigName, runConfigDir, strict)
        logger.info("Loaded run configuration \"%s\"" % runConfigName)

        nameList = []
        for c in runConfig.components():
            nameList.append(c.fullName())

        if nameList is None or len(nameList) == 0:
            raise CnCServerException("No components found in" +
                                     " run configuration \"%s\"" % runConfig)

        compList = []
        try:
            waitList = self.__collectComponents(nameList, compList, logger,
                                                timeout)
            if waitList is not None:
                raise CnCServerException("Still waiting for " + str(waitList))
        except:
            self.__returnComponents(compList, logger)
            raise

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
            if self.__defaultDebugBits is not None:
                runSet.setDebugBits(self.__defaultDebugBits)

            try:
                connMap = runSet.buildConnectionMap()
                runSet.connect(connMap, logger)
                runSet.setOrder(connMap, logger)
                runSet.configure()
            except:
                self.__removeRunset(runSet)
                self.__returnComponents(runSet.components(), logger)
                raise

            setComps = []
            for c in runSet.components():
                setComps.append(c.fullName())
            logger.info("Built runset #%d: %s" % (runSet.id(), setComps))

        return runSet

    def monitorClients(self):
        "check that all components in the pool are still alive"
        count = 0

        for k in self.__pool.keys():
            try:
                bin = self.__pool[k]
            except KeyError:
                # bin may have been removed by daemon
                continue

            for c in bin:
                state = c.monitor()
                if state == DAQClient.STATE_DEAD:
                    self.remove(c)
                elif state != DAQClient.STATE_MISSING:
                    count += 1

        return count

    def numActiveSets(self):
        num = 0
        self.__setsLock.acquire()
        try:
            for s in self.__sets:
                if s.isRunning():
                    num += 1
                    break
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
            if self.__pool.has_key(comp.name()):
                self.__pool[comp.name()].remove(comp)
                if len(self.__pool[comp.name()]) == 0:
                    del self.__pool[comp.name()]
        finally:
            self.__poolLock.release()

        return comp

    def restartRunset(self, s, clusterConfig, runConfigDir, dashDir, logger,
                      verbose=False, killWith9=False, eventCheck=False):
        # save the list of components
        #
        compList = s.components()

        try:
            self.__removeRunset(s)
        except ValueError:
            logger.error("Cannot remove %s (#%d available - %s)" %
                         (s, len(self.__sets), self.__sets))

        try:
            s.restartComponents(compList, clusterConfig, runConfigDir, dashDir,
                                logger.logPort(), logger.livePort(),
                                verbose=verbose, killWith9=killWith9,
                                eventCheck=eventCheck)
        except:
            logger.error("Cannot restart %s (#%d available - %s)" %
                         (s, len(self.__sets), self.__sets))

        self.returnRunsetComponents(s)
        s.destroy()

    def returnAll(self, killRunning=True):
        """
        Return all runset components to the pool
        NOTE: This DESTROYS all runsets, even those which are active
        """
        removed = None
        self.__setsLock.acquire()
        try:
            for rs in self.__sets:
                if rs.isRunning():
                    return False
            removed = self.__sets[:]
            del self.__sets[:]
        finally:
            self.__setsLock.release()

        savedEx = None
        for s in removed:
            try:
                self.returnRunsetComponents(s)
                s.destroy()
            except Exception, ex:
                savedEx = ex

        if savedEx is not None:
            raise savedEx

        return True

    def returnRunset(self, s):
        "Return runset components to the pool"
        self.__removeRunset(s)
        savedEx = None
        try:
            self.returnRunsetComponents(s)
        except Exception, ex:
            savedEx = ex
        s.destroy()
        if savedEx is not None:
            raise savedEx

    def returnRunsetComponents(self, rs, verbose=False, killWith9=True,
                               eventCheck=False):
        "Placeholder for subclass method"
        raise CnCServerException("Unimplemented")

    def runset(self, num):
        return self.__sets[num]

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
        if type(descrChar) == bool:
            raise Exception("Convert to new format")
        self.__descrChar = descrChar
        if self.isInput():
            self.__port = port
        else:
            self.__port = None

    def __str__(self):
        "String description"
        if self.isOptional():
            connCh = "~"
        else:
            connCh = "="
        if self.isInput():
            return '%d%s>%s' % (self.__port, connCh, self.__name)
        return self.__name + connCh + '>'

    def connectorTuple(self):
        "Return connector tuple (used when registering components)"
        if self.__port is not None:
            port = self.__port
        elif not self.isInput():
            port = 0
        else:
            raise Error("Connector %s port was set to None" % str(self))

        return (self.__name, self.__descrChar, port)

    def isInput(self):
        "Return True if this is an input connector"
        return self.__descrChar == self.INPUT or \
               self.__descrChar == self.OPT_INPUT

    def isOptional(self):
        "Return True if this is an optional connector"
        return self.__descrChar == self.OPT_INPUT or \
               self.__descrChar == self.OPT_OUTPUT

    def name(self):
        "Return the connector name"
        return self.__name
    
    def port(self):
        "Return connector port number"
        return self.__port

class CnCServer(DAQPool):
    "Command and Control Server"

    DEFAULT_LOG_LEVEL = 'info'

    # max time to wait for components to register
    REGISTRATION_TIMEOUT = 60

    def __init__(self, name="GenericServer", clusterDesc=None, copyDir=None,
                 dashDir=None, defaultLogDir=None, runConfigDir=None,
                 spadeDir=None, logIP=None, logPort=None, liveIP=None,
                 livePort=None, restartOnError=True, forceRestart=True,
                 testOnly=False, quiet=False, defaultRunsetDebug=None):
        "Create a DAQ command and configuration server"
        self.__name = name
        self.__versionInfo = get_version_info(SVN_ID)

        self.__id = int(time.time())

        self.__clusterDesc = clusterDesc
        self.__copyDir = copyDir
        self.__dashDir = os.path.join(metaDir, "dash")
        self.__runConfigDir = runConfigDir
        self.__spadeDir = spadeDir
        self.__defaultLogDir = defaultLogDir

        self.__restartOnError = restartOnError
        self.__forceRestart = forceRestart
        self.__quiet = quiet

        self.__monitoring = False

        self.__live = None

        super(CnCServer, self).__init__(defaultDebugBits=defaultRunsetDebug)

        # close and exit on ctrl-C
        #
        signal.signal(signal.SIGINT, self.__closeOnSIGINT)

        self.__log = self.createCnCLogger(quiet=(testOnly or quiet))

        self.__logServer = \
            self.openLogServer(DAQPort.CATCHALL, self.__defaultLogDir)
        self.__logServer.startServing()

        if logIP is None or logPort is None:
            logIP = "localhost"
            logPort = DAQPort.CATCHALL

        self.__log.openLog(logIP, logPort, liveIP, livePort)

        if testOnly:
            self.__server = None
        else:
            while True:
                try:
                    # CnCServer needs to be made thread-safe
                    # before we can thread the XML-RPC server
                    #
                    self.__server = ThreadedRPCServer(DAQPort.CNCSERVER)
                    #self.__server = RPCServer(DAQPort.CNCSERVER)
                    break
                except socket.error, e:
                    self.__log.error("Couldn't create server socket: %s" % e)
                    sys.exit("Couldn't create server socket: %s" % e)

        if self.__server:
            self.__server.register_function(self.rpc_component_connector_info)
            self.__server.register_function(self.rpc_component_count)
            self.__server.register_function(self.rpc_component_get_bean_field)
            self.__server.register_function(self.rpc_component_list)
            self.__server.register_function(self.rpc_component_list_beans)
            self.__server.register_function(self.rpc_component_list_bean_fields)
            self.__server.register_function(self.rpc_component_list_dicts)
            self.__server.register_function(self.rpc_component_register)
            self.__server.register_function(self.rpc_cycle_live)
            self.__server.register_function(self.rpc_end_all)
            self.__server.register_function(self.rpc_ping)
            self.__server.register_function(self.rpc_register_component)
            self.__server.register_function(self.rpc_runset_active)
            self.__server.register_function(self.rpc_runset_break)
            self.__server.register_function(self.rpc_runset_configname)
            self.__server.register_function(self.rpc_runset_count)
            self.__server.register_function(self.rpc_runset_debug)
            self.__server.register_function(self.rpc_runset_events)
            self.__server.register_function(self.rpc_runset_list)
            self.__server.register_function(self.rpc_runset_list_ids)
            self.__server.register_function(self.rpc_runset_make)
            self.__server.register_function(self.rpc_runset_monitor_run)
            self.__server.register_function(self.rpc_runset_start_run)
            self.__server.register_function(self.rpc_runset_state)
            self.__server.register_function(self.rpc_runset_stop_run)
            self.__server.register_function(self.rpc_runset_subrun)
            self.__server.register_function(self.rpc_version)

        if sys.version_info > (2, 3):
            from DumpThreads import DumpThreadsOnSignal
            DumpThreadsOnSignal(fd=sys.stderr, logger=self.__log)

    def __str__(self):
        ccfg = self.getClusterConfig()
        return "%s<%s>" % (self.__name, ccfg.configName())

    def __closeOnSIGINT(self, signum, frame):
        if self.closeServer(False):
            print >>sys.stderr, "\nExiting"
            sys.exit(0)
        print >>sys.stderr, "Cannot exit with active runset(s)"

    def __getComponents(self, idList, getAll):
        compList = []

        if getAll and (idList is None or len(idList) == 0):
            compList += self.components()
        else:
            for c in self.components():
                for i in [j for j,cid in enumerate(idList) if cid == c.id()]:
                    compList.append(c)
                    del idList[j]
                    break

        if getAll or (idList is not None and len(idList) > 0):
            for rsid in self.listRunsetIDs():
                rs = self.findRunset(rsid)
                if getAll:
                    compList += rs.components()
                else:
                    for c in rs.components():
                        for i in [j for j,cid in enumerate(idList)
                                  if cid == c.id()]:
                            compList.append(c)
                            del idList[j]
                            break
                    if len(idList) == 0:
                        break

        return compList

    def __getHostAddress(self, name):
        "Only return IPv4 addresses -- IPv6 confuses some stuff"
        if name is None or name == '':
            name = 'localhost'
        if name == 'localhost' or name == '127.0.0.1':
            for addrData in socket.getaddrinfo(socket.gethostname(), None):
                if addrData[0] == socket.AF_INET:
                    name = addrData[4][0]
                    break
        return name

    def __listComponentDicts(self, compList):
        slst = []

        tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
        for c in compList:
            tGroup.start(c, self.__log, ())
        tGroup.wait()
        states = tGroup.results()
        for c in compList:
            if states.has_key(c):
                stateStr = str(states[c])
            else:
                stateStr = self.STATE_DEAD

            cDict = c.map()
            cDict["state"] = stateStr

            slst.append(cDict)

        return slst

    def breakRunset(self, runSet):
        if not runSet.isReady():
            try:
                runSet.stopRun()
            except:
                self.__log.error("While breaking %s: %s" %
                                 (runSet, exc_string()))

        try:
            if self.__forceRestart:
                self.restartRunset(runSet, self.getClusterConfig(),
                                   self.__runConfigDir, self.__dashDir,
                                   self.__log)
            else:
                self.returnRunset(runSet)
        except:
            self.__log.error("Failed to break %s: %s" %
                             (runSet, exc_string()))

    def closeServer(self, killRunning=True):
        try:
            if not self.returnAll(killRunning):
                return False
        except:
            pass

        self.__monitoring = False
        if self.__server is not None:
            self.__server.server_close()

        tGroup = ComponentOperationGroup(ComponentOperation.CLOSE)
        for c in self.components():
            tGroup.start(c, self.__log, ())
        tGroup.wait()
        tGroup.reportErrors(self.__log, "close")

        self.__log.closeFinal()
        if self.__logServer is not None:
            self.__logServer.stopServing()
            self.__logServer = None

        return True

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        "overrideable method used for testing"
        return DAQClient(name, num, host, port, mbeanPort, connectors,
                         self.__quiet)

    def createCnCLogger(self, quiet):
        return CnCLogger(quiet=quiet)

    def getClusterConfig(self):
        cdesc = self.__clusterDesc
        cfgDir = self.__runConfigDir
        try:
            return DAQConfigParser.getClusterConfiguration(None,
                                                           useActiveConfig=True,
                                                           clusterDesc=cdesc,
                                                           configDir=cfgDir)
        except XMLFileNotFound:
            if cdesc is None:
                cdescStr = ""
            else:
                cdescStr = " for cluster \"%s\"" % cdesc
            raise CnCServerException("Cannot find cluster configuration" +
                                     " %s: %s" % (cdescStr, exc_string()))

    def makeRunsetFromRunConfig(self, runConfig, timeout=REGISTRATION_TIMEOUT,
                                strict=True):
        try:
            runSet = self.makeRunset(self.__runConfigDir, runConfig, timeout,
                                     self.__log,
                                     forceRestart=self.__forceRestart,
                                     strict=strict)
        except:
            self.__log.error("While making runset from \"%s\": %s" %
                             (runConfig, exc_string()))
            runSet = None

        return runSet

    def monitorLoop(self):
        "Monitor components to ensure they're still alive"
        new = True
        lastCount = 0
        self.__monitoring = True
        while self.__monitoring:
            try:
                count = self.monitorClients()
            except:
                self.__log.error("Monitoring clients: " + exc_string())
                count = lastCount

            new = (lastCount != count)
            if new and not self.__quiet:
                print >>sys.stderr, "%d bins, %d comps" % \
                    (self.numUnused(), count)

            lastCount = count

            problems = self.getRunsetsInErrorState()
            for rs in problems:
                self.__log.error("Returning runset#%d (state=%s)" %
                                 (rs.id(), rs.state()))
                try:
                    if self.__forceRestart:
                        self.restartRunset(rs, self.getClusterConfig(),
                                           self.__runConfigDir,
                                           self.__dashDir, self.__log)
                    else:
                        self.returnRunset(rs)
                except:
                    self.__log.error("Failed to return %s: %s" %
                                     (rs, exc_string()))

            time.sleep(1)

    def name(self):
        return self.__name

    def openLogServer(self, port, logDir):
        logName = os.path.join(logDir, "catchall.log")
        return LogSocketServer(port, "CnCServer", logName, quiet=self.__quiet)

    def returnRunsetComponents(self, rs, verbose=False, killWith9=True,
                               eventCheck=False):
        rs.returnComponents(self, self.getClusterConfig(), self.__runConfigDir,
                            self.__dashDir, self.__log.logPort(),
                            self.__log.livePort(), verbose=verbose,
                            killWith9=killWith9, eventCheck=eventCheck)

    def rpc_component_connector_info(self, idList=None, getAll=True):
        "list component connector information"
        compList = self.__getComponents(idList, getAll)

        tGroup = ComponentOperationGroup(ComponentOperation.GET_CONN_INFO)
        for c in compList:
            tGroup.start(c, self.__log, ())
        tGroup.wait()
        results = tGroup.results()

        slst = []
        for c in compList:
            if results.has_key(c):
                result = results[c]
            else:
                result = self.STATE_DEAD

            cDict = c.map()

            if type(result) != list:
                cDict["error"] = str(result)
            else:
                cDict["conn"] = result

            slst.append(cDict)

        return slst

    def rpc_component_count(self):
        "return number of components currently registered"
        return self.numComponents()

    def rpc_component_get_bean_field(self, compId, bean, field):
        for c in self.components():
            if c.id() == compId:
                return c.getSingleBeanField(bean, field)
        raise CnCServerException("Unknown component #%d" % compId)

    def rpc_component_list(self, includeRunsetComponents=False):
        "return dictionary of component names -> IDs"
        idDict = {}
        for c in self.components():
            idDict[c.fullName()] = c.id()

        if includeRunsetComponents:
            for rsid in self.listRunsetIDs():
                rs = self.findRunset(rsid)
                for c in rs.components():
                    idDict[c.fullName()] = c.id()

        return idDict

    def rpc_component_list_beans(self, compId):
        for c in self.components():
            if c.id() == compId:
                return c.getBeanNames()
        raise CnCServerException("Unknown component #%d" % compId)

    def rpc_component_list_bean_fields(self, compId, bean):
        for c in self.components():
            if c.id() == compId:
                return c.getBeanFields(bean)
        raise CnCServerException("Unknown component #%d" % compId)

    def rpc_component_list_dicts(self, idList=None, getAll=True):
        "list unused components"
        return self.__listComponentDicts(self.__getComponents(idList, getAll))

    def rpc_component_register(self, name, num, host, port, mbeanPort,
                               connArray):
        "register a component with the server"

        if type(name) != str or len(name) == 0:
            raise CnCServerException("Bad component name (should be a string)")
        if type(num) != int:
            raise CnCServerException("Bad component number" +
                                     " (should be an integer)")

        connectors = []
        for n in range(len(connArray)):
            d = connArray[n]
            if type(d) != tuple and type(d) != list:
                errMsg = "Bad %s#%d connector#%d \"%s\"%s" % \
                    (name, num, n, str(d), str(type(d)))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if len(d) != 3:
                errMsg = ("Bad %s#%d connector#%d %s (should have 3" +
                          " elements)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if type(d[0]) != str or len(d[0]) == 0:
                errMsg = ("Bad %s#%d connector#%d %s (first element should" +
                          " be name)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if type(d[1]) != str or len(d[1]) != 1:
                errMsg = ("Bad %s#%d connector#%d %s (second element should" +
                          " be descrChar)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            if type(d[2]) != int:
                errMsg = ("Bad %s#%d connector#%d %s (third element should" +
                          " be int)") % (name, num, n, str(d))
                self.__log.info(errMsg)
                raise CnCServerException(errMsg)
            connectors.append(Connector(d[0], d[1], d[2]))

        client = self.createClient(name, num, host, port, mbeanPort,
                                   connectors)

        self.__log.debug("Registered %s" % client.fullName())

        self.add(client)

        logIP = self.__getHostAddress(self.__log.logHost())

        logPort = self.__log.logPort()
        if logPort is None:
            if self.__logServer is not None:
                logPort = self.__logServer.port()
            else:
                logIP = ""
                logPort = 0

        liveIP = self.__getHostAddress(self.__log.liveHost())

        livePort = self.__log.livePort()
        if livePort is None:
            liveIP = ""
            livePort = 0

        return { "id" : client.id(),
                 "logIP" : logIP,
                 "logPort" : logPort,
                 "liveIP" : liveIP,
                 "livePort" : livePort,
                 "serverId" : self.__id }

    def rpc_cycle_live(self):
        "Restart DAQLive thread"
        self.__live.close()
        self.__live = self.startLiveThread()

    def rpc_end_all(self):
        "terminate all clients"
        tGroup = ComponentOperationGroup(ComponentOperation.RESET_COMP)
        for c in self.components():
            tGroup.start(c, self.__log, ())
        tGroup.wait()
        tGroup.reportErrors(logger, "terminate")
        return 1

    def rpc_ping(self):
        "remote method for far end to confirm that server is still alive"
        return self.__id

    def rpc_register_component(self, name, num, host, port, mbeanPort,
                               connArray):
        "backward compatibility shim"
        return self.rpc_component_register(name, num, host, port, mbeanPort,
                                           connArray)

        "register a component with the server"
    def rpc_runset_active(self):
        "return number of active (running) run sets"
        return self.numActiveSets()

    def rpc_runset_break(self, id):
        "break up the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        if runSet.isRunning():
            raise CnCServerException("Cannot break up running runset #%d" % id)

        self.breakRunset(runSet)

        return "OK"

    def rpc_runset_configname(self, id):
        "return run configuration name for this runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        return runSet.configName()

    def rpc_runset_count(self):
        "return number of existing run sets"
        return self.numSets()

    def rpc_runset_debug(self, id, bits):
        "set debugging bits at the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        runSet.setDebugBits(bits)

        return runSet.debugBits()

    def rpc_runset_events(self, id, subrunNumber):
        """
        get the number of events for the specified subrun
        from the specified runset
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        return runSet.events(subrunNumber)

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

    def rpc_runset_make(self, runConfig, strict=True,
                        timeout=REGISTRATION_TIMEOUT):
        "build a runset from the specified run configuration"
        if self.__runConfigDir is None:
            raise CnCServerException("Run configuration directory" +
                                     " has not been set")
        if type(runConfig) == list:
            raise CnCServerException("Must now specify a run config name," +
                                     " not a list of components")

        runSet = self.makeRunsetFromRunConfig(runConfig, strict=strict)
        if runSet is None:
            return -1

        return runSet.id()

    def rpc_runset_monitor_run(self, id):
        "Return monitoring data for the runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        return runSet.getEventCounts()

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

        self.startRun(runSet, runNum, runOptions, logDir=logDir)

        return "OK"

    def rpc_runset_state(self, id):
        "get the state of the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            return RunSetState.UNKNOWN

        return runSet.state()

    def rpc_runset_stop_run(self, id):
        "stop a run with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        delayedException = None
        try:
            hadError = runSet.stopRun()
        except ValueError, ve:
            hadError = True
            delayedException = ve

        if self.__forceRestart or (hadError and self.__restartOnError):
            self.restartRunset(runSet, self.getClusterConfig(),
                               self.__runConfigDir, self.__dashDir,
                               self.__log)

        if delayedException is not None:
            raise delayedException

        return "OK"

    def rpc_runset_subrun(self, id, subrunId, subrunData):
        "start a subrun with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise CnCServerException('Could not find runset#%d' % id)

        runSet.subrun(subrunId, subrunData)

        return "OK"

    def rpc_version(self):
        "return the CnCServer release/revision info"
        return self.__versionInfo

    def run(self):
        "Start a server"
        self.__log.info(("%(filename)s %(revision)s %(date)s %(time)s" +
                         " %(author)s %(release)s %(repo_rev)s") %
                        self.__versionInfo)

        t = threading.Thread(name="CnCServer", target=self.monitorLoop)
        t.setDaemon(True)
        t.start()

        self.__live = self.startLiveThread()

        self.__server.serve_forever()

    def saveCatchall(self, runDir):
        "save the catchall.log file to the run directory"
        catchallFile = os.path.join(self.__defaultLogDir, "catchall.log")
        if not os.path.exists(catchallFile):
            return

        if self.__logServer is not None:
            self.__logServer.stopServing()

        os.rename(catchallFile, os.path.join(runDir, "catchall.log"))

        if self.__logServer is not None:
            self.__logServer.startServing()

    def startLiveThread(self):
        "Start I3Live interface thread"
        live = DAQLive(self, self.__log)

        t = threading.Thread(name="DAQLive", target=live.run)
        t.setDaemon(True)
        t.start()

        return live

    def startRun(self, runSet, runNum, runOptions, logDir=None):
        if logDir is None:
            logDir = self.__defaultLogDir

        runSet.startRun(runNum, self.getClusterConfig().configName(),
                        runOptions, get_version_info(SVN_ID), self.__spadeDir,
                        copyDir=self.__copyDir, logDir=logDir,
                        quiet=self.__quiet)

    def versionInfo(self):
        return self.__versionInfo

if __name__ == "__main__":
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)
    p.add_option("-a", "--copy-dir", type="string", dest="copyDir",
                 action="store", default=None,
                 help="Directory for copies of files sent to SPADE")
    p.add_option("-C", "--cluster-desc", type="string", dest="clusterDesc",
                 action="store", default=None,
                 help="Cluster description name")
    p.add_option("-c", "--config-dir", type="string", dest="configDir",
                 action="store", default="/usr/local/icecube/config",
                 help="Directory where run configurations are stored")
    p.add_option("-d", "--daemon", dest="daemon",
                 action="store_true", default=False,
                 help="Run as a daemon process")
    p.add_option("-D", "--dashDir", type="string", dest="dashDir",
                 action="store", default=os.path.join(metaDir, "dash"),
                 help="Directory holding Python scripts")
    p.add_option("-f", "--force-restart", dest="forceRestart",
                 action="store_true", default=True,
                 help="Force components to restart after every run")
    p.add_option("-F", "--no-force-restart", dest="forceRestart",
                 action="store_false", default=True,
                 help="Don't force components to restart after every run")
    p.add_option("-k", "--kill", dest="kill",
                 action="store_true", default=False,
                 help="Kill running CnCServer instance(s)")
    p.add_option("-l", "--log", type="string", dest="log",
                 action="store", default=None,
                 help="Hostname:port for log server")
    p.add_option("-L", "--liveLog", type="string", dest="liveLog",
                 action="store", default=None,
                 help="Hostname:port for IceCube Live")
    p.add_option("-o", "--default-log-dir", type="string", dest="defaultLogDir",
                 action="store", default="/mnt/data/pdaq/log",
                 help="Default directory for pDAQ log/monitoring files")
    p.add_option("-r", "--restart-on-error", dest="restartOnError",
                 action="store_true", default=True,
                 help="Restart components if the run ends in an error")
    p.add_option("-R", "--no-restart-on-error", dest="restartOnError",
                 action="store_false", default=True,
                 help="Don't restart components if the run ends in an error")
    p.add_option("-s", "--spade-dir", type="string", dest="spadeDir",
                 action="store", default="/mnt/data/pdaq/runs",
                 help="Directory where SPADE will pick up logs/moni files")
    p.add_option("-v", "--verbose", dest="quiet",
                 action="store_false", default=True,
                 help="Write catchall messages to console")

    opt, args = p.parse_args()

    pids = list(findProcess("CnCServer.py", processList()))

    if opt.kill:
        pid = int(os.getpid())
        for p in pids:
            if pid != p:
                # print "Killing %d..." % p
                import signal
                os.kill(p, signal.SIGKILL)

        sys.exit(0)

    if len(pids) > 1:
        sys.exit("ERROR: More than one instance of CnCServer.py" +
                 " is already running!")

    opt.spadeDir = os.path.abspath(opt.spadeDir)
    if not os.path.exists(opt.spadeDir):
        sys.exit(("Spade directory '%s' doesn't exist!" +
                  "  Use the -s option,  or -h for help.") % opt.spadeDir)

    if opt.copyDir is not None:
        opt.copyDir = os.path.abspath(opt.copyDir)
        if not os.path.exists(opt.copyDir):
            sys.exit("Log copies directory '%s' doesn't exist!" % opt.copyDir)

    if opt.defaultLogDir is not None:
        opt.defaultLogDir = os.path.abspath(opt.defaultLogDir)
        if not os.path.exists(opt.defaultLogDir):
            sys.exit("Default log directory '%s' doesn't exist!" %
                     opt.defaultLogDir)

    if opt.log is None:
        logIP = None
        logPort = None
    else:
        colon = opt.log.find(':')
        if colon < 0:
            sys.exit("ERROR: Bad log argument '%s'" % opt.log)

        logIP = opt.log[:colon]
        logPort = int(opt.log[colon+1:])

    if opt.liveLog is None:
        liveIP = None
        livePort = None
    else:
        colon = opt.liveLog.find(':')
        if colon < 0:
            sys.exit("ERROR: Bad liveLog argument '%s'" % opt.liveLog)

        liveIP = opt.liveLog[:colon]
        livePort = int(opt.liveLog[colon+1:])

    if opt.daemon: Daemon.Daemon().Daemonize()

    cnc = CnCServer(clusterDesc=opt.clusterDesc, name="CnCServer",
                    copyDir=opt.copyDir, dashDir=opt.dashDir,
                    runConfigDir=opt.configDir, spadeDir=opt.spadeDir,
                    defaultLogDir=opt.defaultLogDir, logIP=logIP,
                    logPort=logPort, liveIP=liveIP, livePort=livePort,
                    forceRestart=opt.forceRestart, testOnly=False,
                    quiet=opt.quiet)
    try:
        cnc.run()
    except KeyboardInterrupt:
        sys.exit("Interrupted.")
