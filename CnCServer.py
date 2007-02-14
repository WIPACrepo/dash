#!/usr/bin/env python

from DAQRPC import RPCClient, RPCServer
from DAQLogClient import DAQLogger
from Process import processList, findProcess
from exc_string import *
from time import time, sleep

import Daemon
import optparse
import os
import socket
import sys
import thread

set_exc_string_encoding("ascii")

class Connector:
    """
    Component connector description
    type - connection type
    isInput - True if this is an input connector
    port - IP port number (for input connections)
    """

    def __init__(self, type, isInput, port):
        """
        Connector constructor
        type - connection type
        isInput - True if this is an input connector
        port - IP port number (for input connections)
        """
        self.type = type
        self.isInput = isInput
        self.port = port

    def __str__(self):
        "String description"
        if self.isInput:
            return '%d=>%s' % (self.port, self.type)
        return self.type + '=>'

class Connection:
    """
    Component connection data to be passed to a component
    conn - connection description
    comp - component
    """

    def __init__(self, conn, comp):
        """
        Connection constructor
        conn - connection description
        comp - component
        """
        self.conn = conn
        self.comp = comp

    def __str__(self):
        "String description"
        return '%s:%s#%d@%s:%d' % \
            (self.conn.type, self.comp.name, self.comp.num, self.comp.host,
             self.conn.port)

    def getMap(self):
        map = {}
        map['type'] = self.conn.type
        map['compName'] = self.comp.name
        map['compNum'] = self.comp.num
        map['host'] = self.comp.host
        map['port'] = self.conn.port
        return map

class ConnTypeEntry:
    """
    Temporary class used to build the connection map for a runset
    type - connection type
    inList - list of [input connection, component] entries
    inList - list of output connections
    """
    def __init__(self, type):
        """
        ConnTypeEntry constructor
        type - connection type
        """
        self.type = type
        self.inList = []
        self.outList = []

    def add(self, conn, comp):
        "Add a connection and component to the appropriate list"
        if conn.isInput:
            self.inList.append([conn, comp])
        else:
            self.outList.append(comp)

    def buildConnectionMap(self, map):
        "Validate and fill the map of connections for each component"
        if len(self.inList) == 0:
            raise ValueError, 'No inputs found for %d %s outputs' % \
                (len(self.outList), self.type)
        if len(self.outList) == 0:
            raise ValueError, 'No outputs found for %d %s inputs' % \
                (len(self.inList), self.type)
        if len(self.inList) > 1 and len(self.outList)  > 1:
            raise ValueError, 'Found %d %s outputs for %d inputs' % \
                (len(self.outList), len(self.inList), self.type)

        if len(self.inList) == 1:
            inConn = self.inList[0][0]
            inComp = self.inList[0][1]

            for outComp in self.outList:
                entry = Connection(inConn, inComp)

                if not map.has_key(outComp):
                    map[outComp] = []
                map[outComp].append(entry)
        else:
            outComp = self.outList[0]

            for inConn, inComp in self.inList:
                entry = Connection(inConn, inComp)


                if not map.has_key(outComp):
                    map[outComp] = []
                map[outComp].append(entry)

class RunSet:
    "A set of components to be used in one or more runs"

    ID = 1

    # number of seconds to wait after stopping components seem to be
    # hung before forcing remaining components to stop
    #
    TIMEOUT_SECS = 10

    def __init__(self, set, logger):
        """
        RunSet constructor
        set - list of components
        id - unique runset ID
        runNumber - run number (if assigned)
        """
        self.set = set
        self.logger = logger

        self.id = RunSet.ID
        RunSet.ID += 1

        self.configured = False
        self.runNumber = None
        self.state = 'unknown'

    def __str__(self):
        "String description"
        setStr = 'RunSet #' + str(self.id)
        if self.runNumber is not None:
            setStr += ' run#' + str(self.runNumber)
        return setStr

    def componentListStr(self):
        "Return string of all components, one per line"
        setStr = ""
        for c in self.set:
            setStr += str(c) + "\n"
        return setStr

    def configure(self, globalConfigName):
        "Configure all components in the runset"
        self.state = 'configuring'

        for c in self.set:
            c.configure(globalConfigName)

        self.waitForStateChange(20)

        self.state = 'ready'

        badList = self.listBadState()
        if len(badList) > 0:
            raise ValueError, 'Could not configure ' + str(badList)

        self.configured = True

    def configureLogging(self, logIP, logList):
        "Configure logging for specified components in the runset"
        for c in self.set:
            for i in range(0, len(logList)):
                logData = logList[i]
                if c.isComponent(logData[0], logData[1]):
                    c.logTo(logIP, logData[2])
                    del logList[i]
                    break

        return logList

    def destroy(self):
        if len(self.set) > 0:
            raise ValueError, 'RunSet #' + str(self.id) + ' is not empty'

        self.id = None
        self.configured = False
        self.runNumber = None
        self.state = 'destroyed'

    def isRunning(self):
        return self.state is not None and self.state == 'running'

    def list(self):
        list = []
        for c in self.set:
            list.append(c.list())

        return list

    def listBadState(self):
        list = []

        for c in self.set:
            stateStr = c.getState()
            if stateStr != self.state:
                list.append(c.name + '#' + str(c.num) + ':' + stateStr)

        return list

    def logmsg(self, msg):
        if self.logger:
            self.logger.logmsg(msg)
        else:
            print msg

    def reset(self):
        "Reset all components in the runset back to the idle state"
        self.state = 'resetting'

        for c in self.set:
            c.reset()

        self.waitForStateChange()

        self.state = 'idle'

        badList = self.listBadState()

        self.configured = False
        self.runNumber = None

        return badList

    def resetLogging(self):
        "Reset logging for all components in the runset"
        for c in self.set:
            c.resetLogging()

    def returnComponents(self, pool):
        badList = self.reset()

        # transfer components back to pool
        #
        while len(self.set) > 0:
            comp = self.set[0]
            del self.set[0]
            pool.add(comp)

        # raise exception if one or more components could not be reset
        #
        if len(badList) > 0:
            raise ValueError, 'Could not reset ' + str(badList)

    def sortCmp(self, x, y):
        if y.cmdOrder is None:
            self.logmsg('Comp ' + str(y) + ' is none')
            return -1
        elif x.cmdOrder is None:
            self.logmsg('Comp ' + str(x) + ' is none')
            return 1
        else:
            return y.cmdOrder-x.cmdOrder

    def startRun(self, runNum):
        "Start all components in the runset"
        if not self.configured:
            raise ValueError, "RunSet #" + str(self.id) + " is not configured"

        failStr = None
        for c in self.set:
            if c.cmdOrder is None:
                if not failStr:
                    'No order set for ' + str(c)
                else:
                    failStr += ', ' + str(c)
        if failStr:
            raise ValueError, failStr

        # start back to front
        #
        self.set.sort(lambda x, y: self.sortCmp(x, y))

        self.state = 'starting'

        self.runNumber = runNum
        for c in self.set:
            c.startRun(runNum)

        self.waitForStateChange()

        self.state = 'running'

        badList = self.listBadState()
        if len(badList) > 0:
            raise ValueError, 'Could not start runset#%d run#%d components: %s' \
                % (self.id, runNum, str(badList))

    def status(self):
        """
        Return a dictionary of components in the runset
        and their current state
        """
        setStat = {}
        for c in self.set:
            setStat[c] = c.getState()

        return setStat

    def stopRun(self):
        "Stop all components in the runset"
        if self.runNumber is None:
            raise ValueError, "RunSet #" + str(self.id) + " is not running"

        # stop from front to back
        #
        self.set.sort(lambda x, y: x.cmdOrder-y.cmdOrder)

        waitList = self.set[:]

        for i in range(0,2):
            if i == 0:
                self.state = 'stopping'
            else:
                self.state = 'forcingStop'

            if i == 1:
                warnStr = str(self) + ': Forcing ' + str(len(waitList)) + \
                    ' components to stop:'
                for c in waitList:
                    warnStr += ' ' + c.name + '#' + str(c.num)
                self.logmsg(warnStr)

            for c in waitList:
                if i == 0:
                    c.stopRun()
                else:
                    c.forcedStop()

            connDict = {}

            endSecs = time() + RunSet.TIMEOUT_SECS
            while len(waitList) > 0 and time() < endSecs:
                newList = waitList[:]
                for c in waitList:
                    stateStr = c.getState()
                    if stateStr != self.state:
                        newList.remove(c)
                        if c in connDict:
                            del connDict[c]

                changed = False

                # if any components have changed state...
                #
                if len(waitList) != len(newList):
                    waitList = newList
                    changed = True

                # ...or if any component's engines have changed state...
                #
                for c in waitList:
                    csStr = c.getNonstoppedConnectorsString()
                    if not c in connDict:
                        connDict[c] = csStr
                    elif connDict[c] != csStr:
                        connDict[c] = csStr
                        changed = True

                if not changed:
                    #
                    # hmmm ... we may be hanging
                    #
                    sleep(1)
                else:
                    #
                    # one or more components must have stopped
                    #
                    if len(waitList) > 0:
                        waitStr = None
                        for c in waitList:
                            if waitStr is None:
                                waitStr = ''
                            else:
                                waitStr += ', '
                            waitStr += c.name + '#' + str(c.num) + \
                                connDict[c]

                        if waitStr:
                            self.logmsg(str(self) + ': Waiting for ' +
                                        self.state + ' ' + waitStr)

                        # reset timeout
                        #
                        endSecs = time() + RunSet.TIMEOUT_SECS

            # if the components all stopped normally, don't force-stop them
            #
            if len(waitList) == 0:
                break

        self.runNumber = None

    def waitForStateChange(self, timeoutSecs=TIMEOUT_SECS):
        waitList = self.set[:]

        endSecs = time() + timeoutSecs
        while len(waitList) > 0 and time() < endSecs:
            newList = waitList[:]
            for c in waitList:
                stateStr = c.getState()
                if stateStr != self.state:
                    newList.remove(c)

            # if one or more components changed state...
            #
            if len(waitList) == len(newList):
                sleep(1)
            else:

                waitList = newList

                waitStr = None
                for c in waitList:
                    if waitStr is None:
                        waitStr = ''
                    else:
                        waitStr += ', '
                    waitStr += c.name + '#' + str(c.num)
                if waitStr:
                    self.logmsg(str(self) + ': Waiting for ' + self.state +
                                ' ' + waitStr)

                # reset timeout
                #
                endSecs = time() + timeoutSecs

        if len(waitList) > 0:
            raise ValueError, 'Still waiting for %d components to leave %s' % \
                (len(waitList), self.state)

class CnCLogger(object):
    "CnC logging client"

    def __init__(self):
        "create a logging client"
        self.socketlog = None
        self.logIP = None
        self.logPort = None

        self.prevIP = None
        self.prevPort = None

    def closeLog(self):
        "Close the log socket"
        try:
            self.logmsg("End of log")
        except:
            pass
        self.resetLog()

    def createLogger(self, host, port):
        "create a socket logger (overrideable method used for testing)"
        return DAQLogger(host, port)

    def logmsg(self, s):
        """
        Log a string to stdout and, if available, to the socket logger
        stdout of course will not appear if daemonized.
        """
        print s
        if self.socketlog:
            try:
                self.socketlog.write_ts(s)
            except Exception, ex:
                if str(ex).find('Connection refused') < 0:
                    raise
                self.resetLog()
                print 'Lost logging connection'

    def openLog(self, host, port):
        "initialize socket logger"
        self.socketlog = self.createLogger(host, port)
        self.logIP = host
        self.logPort = port
        self.logmsg('Start of log at ' + host + ':' + str(port))

        if self.prevIP is None and self.prevPort is None:
            self.prevIP = host
            self.prevPort = port

    def resetLog(self):
        "close current log and reset to initial state"
        if self.socketlog is not None:
            try:
                self.socketlog.close
            except:
                pass

        if self.prevIP is not None and self.prevPort is not None and \
                (self.logIP != self.prevIP or self.logPort != self.prevPort):
            self.openLog(self.prevIP, self.prevPort)
        else:
            self.socketlog = None
            self.logIP = None
            self.logPort = None

class DAQClient(CnCLogger):
    """DAQ component
    id - internal client ID
    name - component name
    num - component instance number
    host - component host name
    port - component port number
    mbeanPort - component's MBean server port number
    connectors - list of Connectors
    client - XML-RPC client
    deadCount - number of sequential failed pings
    cmdOrder - order in which start/stop commands are issued
    """

    # next component ID
    #
    ID = 1

    # internal state indicating that the client hasn't answered
    # some number of pings but has not been declared dead
    #
    STATE_MISSING = 'MIA'

    # internal state indicating that the client is
    # no longer responding to pings
    #
    STATE_DEAD = 'DEAD'

    def __init__(self, name, num, host, port, mbeanPort, connectors):
        """
        DAQClient constructor
        name - component name
        num - component instance number
        host - component host name
        port - component port number
        mbeanPort - component MBean port number
        connectors - list of Connectors
        """
        self.name = name
        self.num = num
        self.host = host
        self.port = port
        self.mbeanPort = mbeanPort
        self.connectors = connectors

        self.id = DAQClient.ID
        DAQClient.ID += 1

        self.client = self.createClient(host, port)

        self.deadCount = 0
        self.cmdOrder = None

        super(DAQClient, self).__init__()

    def __str__(self):
        "String description"
        if self.mbeanPort <= 0:
            extraStr = ''
        else:
            extraStr = ' M#' + str(self.mbeanPort)

        if self.connectors and len(self.connectors) > 0:
            first = True
            for c in self.connectors:
                if first:
                    extraStr += ' [' + str(c)
                    first = False
                else:
                    extraStr += ' ' + str(c)
            extraStr += ']'

        return "ID#%d %s#%d at %s:%d%s" % \
            (self.id, self.name, self.num, self.host, self.port, extraStr)

    def configure(self, configName=None):
        "Configure this component"
        try:
            if not configName:
                return self.client.xmlrpc.configure(self.id)
            else:
                return self.client.xmlrpc.configure(self.id, configName)
        except Exception, e:
            self.logmsg(exc_string())
            return None

    def connect(self, connList=None):
        "Connect this component with other components in a runset"

        if not connList:
            return self.client.xmlrpc.connect(self.id)

        list = []
        for conn in connList:
            list.append(conn.getMap())

        return self.client.xmlrpc.connect(self.id, list)

    def createClient(self, host, port):
        return RPCClient(host, port)

    def forcedStop(self):
        "Force component to stop running"
        try:
            return self.client.xmlrpc.forcedStop(self.id)
        except Exception, e:
            self.logmsg(exc_string())
            return None

    def getOrder(self):
        return self.cmdOrder

    def getState(self):
        "Get current state"
        try:
            state = self.client.xmlrpc.getState(self.id)
        except Exception, e:
            self.logmsg(exc_string())
            state = None

        if not state:
            self.deadCount += 1
            if self.deadCount < 3:
                state = DAQClient.STATE_MISSING
            else:
                state = DAQClient.STATE_DEAD

        return state

    def getNonstoppedConnectorsString(self):
        """
        Return string describing states of all connectors
        which have not yet stopped
        """
        try:
            connStates = self.client.xmlrpc.listConnectorStates(self.id)
        except Exception, e:
            self.logmsg(exc_string())
            return None

        csStr = None
        for cs in connStates:
            if cs[1] == 'idle':
                continue
            if not csStr:
                csStr = '['
            else:
                csStr += ', '
            csStr += str(cs[0]) + ':' + str(cs[1])

        if not csStr:
            csStr = ''
        else:
            csStr += ']'

        return csStr

    def isComponent(self, name, num):
        "Does this component have the specified name and number?"
        return self.name == name and self.num == num

    def isSource(self):
        "TODO: Move responsibility for this to DAQComponent"
        return not self.name.endswith('Trigger') and \
            self.name.find('Builder') < 0

    def list(self):
        state = self.getState()
        return [ self.id, self.name, self.num, self.host, self.port,
                 self.mbeanPort, state ]

    def logTo(self, logIP, port):
        "Send log messages to the specified host and port"
        self.openLog(logIP, port)
        self.client.xmlrpc.logTo(self.id, logIP, port)

    def monitor(self):
        "Return the monitoring value"
        return self.getState()

    def monitorHack(self):
        "Return the monitoring value"
        #self.client.xmlrpc.monitorHack(self.id)
        return 'OK'

    def reset(self):
        "Reset component back to the idle state"
        self.closeLog()
        return self.client.xmlrpc.reset(self.id)

    def resetLogging(self):
        "Reset component back to the idle state"
        self.resetLog()
        return self.client.xmlrpc.resetLogging(self.id)

    def setOrder(self, orderNum):
        self.cmdOrder = orderNum

    def startRun(self, runNum):
        "Start component processing DAQ data"
        try:
            return self.client.xmlrpc.startRun(self.id, runNum)
        except Exception, e:
            self.logmsg(exc_string())
            return None

    def stopRun(self):
        "Stop component processing DAQ data"
        try:
            return self.client.xmlrpc.stopRun(self.id)
        except Exception, e:
            self.logmsg(exc_string())
            return None

class DAQPool(CnCLogger):
    "Pool of DAQClients and RunSets"

    def __init__(self):
        "Create an empty pool"
        self.pool = {}
        self.sets = []

        super(DAQPool, self).__init__()

    def add(self, comp):
        "Add the component to the config server's pool"
        if not self.pool.has_key(comp.name):
            self.pool[comp.name] = []
        self.pool[comp.name].append(comp)

    def buildConnectionMap(cls, compList):
        "Validate and fill the map of connections for each component"
        connDict = {}

        for comp in compList:
            for n in comp.connectors:
                if not connDict.has_key(n.type):
                    connDict[n.type] = ConnTypeEntry(n.type)
                connDict[n.type].add(n, comp)

        map = {}

        for k in connDict:
            connDict[k].buildConnectionMap(map)

        return map

    buildConnectionMap = classmethod(buildConnectionMap)


    def buildRunset(self, nameList, compList):
        """
        Internal method to build a runset from the specified list of
        component names, using the supplied 'compList' as a workspace
        for storing components removed from the pool
        """
        if len(compList) > 0:
            raise ValueError, 'Temporary component list must be empty'

        for name in nameList:
            # separate name and number
            #
            pound = name.rfind('#')
            if pound < 0:
                num = -1
            else:
                num = int(name[pound+1:])
                name = name[0:pound]

            if not self.pool.has_key(name) or len(self.pool[name]) == 0:
                raise ValueError, 'No "' + name + '" components are available'

            # find component in pool
            #
            comp = None
            for c in self.pool[name]:
                if num < 0 or c.num == num:
                    self.remove(c)
                    comp = c
                    break
            if not comp:
                raise ValueError, 'Component \"' + name + '#' + str(num) + \
                    '" is not available'

            # add component to temporary list
            #
            compList.append(comp)

        # make sure I/O channels match up
        #
        map = DAQPool.buildConnectionMap(compList)

        # connect all components
        #
        errMsg = None
        for c in compList:
            if not map.has_key(c):
                rtnVal = c.connect()
            else:
                rtnVal = c.connect(map[c])

        chkList = compList[:]
        while len(chkList) > 0:
            for c in chkList:
                state = c.getState()
                if state == 'connected':
                    chkList.remove(c)
                elif state != 'connecting':
                    if not errMsg:
                        errMsg = 'Connect failed for ' + c.name + '(' + \
                            rtnVal + ')'
                    else:
                        errMsg += ', ' + c.name + '(' + rtnVal + ')'
            sleep(1)

        if errMsg:
            raise ValueError, errMsg

        self.setOrder(compList, map)

        return None

    def findRunset(self, id):
        "Find the runset with the specified ID"
        set = None
        for s in self.sets:
            if s.id == id:
                set = s
                break

        return set

    def getNumComponents(self):
        tot = 0
        for binName in self.pool:
            tot += len(self.pool[binName])

        return tot

    def listRunsetIDs(self):
        "List active runset IDs"
        ids = []
        for s in self.sets:
            ids.append(s.id)

        return ids

    def makeRunset(self, nameList):
        "Build a runset from the specified list of component names"
        compList = []
        setAdded = False
        try:
            try:
                # buildRunset fills 'compList' with the specified components
                #
                self.buildRunset(nameList, compList)
                runSet = RunSet(compList, self)
                self.sets.append(runSet)
                setAdded = True
            except Exception, ex:
                runSet = None
                self.logmsg(exc_string())
                raise
        finally:
            if not setAdded:
                for c in compList:
                    c.reset()
                    self.add(c)
                runSet = None

        return runSet

    def monitorClients(self, new):
        "check that all components in the pool are still alive"
        count = 0

        for k in self.pool.keys():
            if new: self.logmsg("  %s:" % k)

            try:
                bin = self.pool[k]
            except KeyError:
                # bin may have been removed by daemon
                continue

            for c in bin:
                state = c.monitor()
                if state == DAQClient.STATE_DEAD:
                    self.remove(c)
                elif state != DAQClient.STATE_MISSING:
                    count += 1

                if new:
                    self.logmsg("    %s %s" % (str(c), state))

        return count

    def remove(self, comp):
        "Remove a component from the pool"
        if self.pool.has_key(comp.name):
            self.pool[comp.name].remove(comp)
            if len(self.pool[comp.name]) == 0:
                del self.pool[comp.name]

        return comp

    def returnRunset(self, s):
        "Return runset components to the pool"
        self.sets.remove(s)
        s.returnComponents(self)
        s.destroy()

    def setOrder(self, compList, map):
        "set the order in which components are started/stopped"

        # copy list of components
        #
        allComps = []
        allComps[0:] = compList[0:]

        # build initial list of source components
        #
        curLevel = []
        for c in allComps:
            # clear order
            #
            c.setOrder(None)

            # if component is a source, save it to the initial list
            #
            if c.isSource():
                curLevel.append(c)

        # walk through detector, setting order number for each component
        #
        level = 1
        while len(allComps) > 0 and len(curLevel) > 0:
            tmp = []
            for c in curLevel:
                # remove current component from the temporary component list
                #
                try:
                    i = allComps.index(c)
                    del allComps[i]
                except:
                    # if not found, it must have already been ordered
                    #
                    continue

                c.setOrder(level)

                if map.has_key(c):
                    for m in map[c]:
                        tmp.append(m.comp)

            curLevel = tmp
            level += 1

        if len(allComps) > 0:
            errStr = 'Unordered:'
            for c in allComps:
                errStr += ' ' + str(c)
            self.logmsg(errStr)

        for c in compList:
            failStr = None
            if not c.getOrder():
                if not failStr:
                    'No order set for ' + str(c)
                else:
                    failStr += ', ' + str(c)
            if failStr:
                raise ValueError, failStr

class DAQServer(DAQPool):
    "Configuration server"

    DEFAULT_LOG_LEVEL = 'info'

    def __init__(self, name="GenericServer", port=8080,
                 logIP=None, logPort=None, testOnly=False, showSpinner=False):
        "Create a DAQ command and configuration server"
        self.port = port
        self.name = name
        self.showSpinner = showSpinner

        self.id = int(time())

        super(DAQServer, self).__init__()

        if logIP is not None and logPort is not None:
            self.openLog(logIP, logPort)

        if testOnly:
            self.server = None
        else:
            notify = True
            while True:
                try:
                    self.server = RPCServer(self.port)
                    break
                except socket.error, e:
                    if notify:
                        self.logmsg("Couldn't create server socket: %s" % e)
                    notify = False
                    sleep(3)

        if self.server:
            self.server.register_function(self.rpc_close_log)
            self.server.register_function(self.rpc_get_num_components)
            self.server.register_function(self.rpc_log_to)
            self.server.register_function(self.rpc_log_to_default)
            self.server.register_function(self.rpc_num_sets)
            self.server.register_function(self.rpc_ping)
            self.server.register_function(self.rpc_register_component)
            self.server.register_function(self.rpc_runset_break)
            self.server.register_function(self.rpc_runset_configure)
            self.server.register_function(self.rpc_runset_list)
            self.server.register_function(self.rpc_runset_listIDs)
            self.server.register_function(self.rpc_runset_log_to)
            self.server.register_function(self.rpc_runset_log_to_default)
            self.server.register_function(self.rpc_runset_make)
            self.server.register_function(self.rpc_runset_start_run)
            self.server.register_function(self.rpc_runset_status)
            self.server.register_function(self.rpc_runset_stop_run)
            self.server.register_function(self.rpc_show_components)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        "overrideable method used for testing"
        return DAQClient(name, num, host, port, mbeanPort, connectors)

    def rpc_close_log(self):
        "called by DAQLog object to indicate when we should close log file"
        self.closeLog()
        return 1

    def rpc_get_num_components(self):
        "return number of components currently registered"
        return self.getNumComponents()

    def rpc_log_to(self, host, port):
        "called by DAQLog object to tell us what UDP port to log to"
        self.openLog(host, port)
        return 1

    def rpc_log_to_default(self):
        "reset logging to the default logger"
        self.resetLog()
        return 1

    def rpc_num_sets(self):
        "show existing run sets"
        return len(self.sets)

    def rpc_ping(self):
        "remote method for far end to confirm that server is still alive"
        return self.id

    def rpc_register_component(self, name, num, host, port, mbeanPort,
                               connArray):
        "register a component with the server"
        connectors = []
        for d in connArray:
            connectors.append(Connector(d[0], d[1], d[2]))

        client = self.createClient(name, num, host, port, mbeanPort,
                                   connectors)
        self.logmsg("Got registration for %s" % str(client))

        sleep(0.1)

        self.add(client)

        if self.logIP:
            logIP = self.logIP
        else:
            logIP = ''

        if self.logPort:
            logPort = self.logPort
        else:
            logPort = 0

        return [client.id, logIP, logPort, self.id]

    def rpc_runset_break(self, id):
        "break up the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        self.returnRunset(runSet)

        return "OK"

    def rpc_runset_configure(self, id, globalConfigName=None):
        "configure the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        runSet.configure(globalConfigName)

        return "OK"

    def rpc_runset_listIDs(self):
        """return a list of active runset IDs"""
        return self.listRunsetIDs()

    def rpc_runset_list(self, id):
        """
        return a list of information about all components
        in the specified runset
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        return runSet.list()

    def rpc_runset_log_to(self, id, logIP, logList):
        "configure logging for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        leftOver = runSet.configureLogging(logIP, logList)

        if len(leftOver) > 0:
            errMsg = 'Could not configure logging for ' + \
                str(len(leftOver)) + ' components:'
            for l in leftOver:
                errMsg += ' ' + l[0] + '#' + str(l[1])

            self.logmsg(errMsg)

        return "OK"

    def rpc_runset_log_to_default(self, id):
        "reset logging for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        self.resetLog()

        runSet.resetLogging()

        return "OK"

    def rpc_runset_make(self, nameList):
        "build a runset using the specified components"
        runSet = self.makeRunset(nameList)

        if not runSet:
            return -1

        self.logmsg("Built runset with the following components:\n" +
                    runSet.componentListStr())
        return runSet.id

    def rpc_runset_start_run(self, id, runNum):
        "start a run with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        runSet.startRun(runNum)

        return "OK"

    def rpc_runset_status(self, id):
        "get run status for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        setStat = runSet.status()
        for c in setStat.keys():
            self.logmsg(str(c) + ' ' + str(c.getState()))

        return "OK"

    def rpc_runset_stop_run(self, id):
        "stop a run with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#' + str(id)

        runSet.stopRun()

        self.resetLog()
        runSet.resetLogging()

        return "OK"

    def rpc_show_components(self):
        "show unused components and their current states"
        s = []
        for k in self.pool:
            for c in self.pool[k]:
                try:
                    state = c.getState()
                except Exception:
                    state = DAQClient.STATE_DEAD

                s.append(str(c) + ' ' + str(state))

        return s

    def serve(self, handler):
        "Start a server"
        self.logmsg("I'm server %s running on port %d" % (self.name, self.port))
        thread.start_new_thread(handler, ())
        self.server.serve_forever()

class CnCServer(DAQServer):
    "Command and Control Server"

    def monitorLoop(self):
        "Monitor components to ensure they're still alive"
        spinStr = '-\\|/'
        spinner = 0

        new = True
        lastCount = 0
        while True:
            if new:
                print "%d bins" % len(self.pool)
            elif self.showSpinner:
                sys.stderr.write(spinStr[spinner:spinner+1] + "\r")
                spinner = (spinner + 1) % len(spinStr)

            try:
                count = self.monitorClients(new)
            except Exception, ex:
                self.logmsg(exc_string())
                count = lastCount

            new = (lastCount != count)
            lastCount = count
            sleep(1)

    def run(self):
        "Server loop"
        self.serve(self.monitorLoop)

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-S", "--showSpinner", action="store_true", dest="showSpinner")
    p.add_option("-d", "--daemon",      action="store_true", dest="daemon")
    p.add_option("-k", "--kill",        action="store_true", dest="kill")
    p.add_option("-l", "--log",         action="store",      type="string",     dest="log")
    p.add_option("-p", "--port",        action="store",      type="int",        dest="port")
    p.set_defaults(kill     = False,
                   nodaemon = False,
                   port     = 8080)
    opt, args = p.parse_args()

    pids = list(findProcess("CnCServer.py", processList()))

    if opt.kill:
        pid = int(os.getpid())
        for p in pids:
            if pid != p:
                # print "Killing %d..." % p
                import signal
                os.kill(p, signal.SIGKILL)
                
        raise SystemExit

    if len(pids) > 1:
        print "ERROR: More than one instance of CnCServer.py is already running!"
        raise SystemExit

    logIP = None
    logPort = None

    if opt.log:
        colon = opt.log.find(':')
        if colon < 0:
            print "ERROR: Bad log argument '" + opt.log + "'"
            raise SystemExit

        logIP = opt.log[:colon]
        logPort = int(opt.log[colon+1:])

    if opt.daemon: Daemon.Daemon().Daemonize()

    cnc = CnCServer("CnCServer", opt.port, logIP, logPort, False,
                    opt.showSpinner)
    try:
        cnc.run()
    except KeyboardInterrupt, k:
        print "Interrupted."
        raise SystemExit
