#!/usr/bin/env python

from DAQRPC import RPCClient, RPCServer
from DAQLogClient import DAQLogger
from exc_string import *
from time import sleep
import socket
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
        """String description"""
        if self.isInput:
            return '%d=>%s' % (self.port, self.type)
        return self.type + '=>'

class Connection:
    """
    Component connection data to be passed to a component
    type - connection type
    compName - component name
    compNum - component instance number
    host - component host name
    port - component port number for this connection
    """

    def __init__(self, type, compName, compNum, host, port):
        """
        Connection constructor
        type - connection type
        compName - component name
        compNum - component instance number
        host - component host name
        port - component port number for this connection
        """
        self.type = type
        self.compName = compName
        self.compNum = compNum
        self.host = host
        self.port = port

    def __str__(self):
        """String description"""
        return '%s:%s#%d@%s:%d' % \
            (self.type, self.compName, self.compNum, self.host, self.port)

class ConnTypeEntry:
    """Temporary class used to build the connection map for a runset
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
        """Add a connection and component to the appropriate list"""
        if conn.isInput:
            self.inList.append([conn, comp])
        else:
            self.outList.append(comp)

    def buildConnectionMap(self, map):
        """Validate and fill the map of connections for each component"""
        if len(self.inList) == 0:
            raise ValueError, 'No inputs found for %d %s outputs' % \
                (len(self.outList), self.type)
        elif len(self.inList) > 1:
            raise ValueError, 'Found %d %s inputs for %d outputs' % \
                (len(self.inList), self.type, len(self.outList))
        if len(self.outList) == 0:
            raise ValueError, 'No outputs found for %d %s inputs' % \
                (len(self.inList), self.type)

        inConn = self.inList[0][0]
        inComp = self.inList[0][1]

        for outComp in self.outList:
            entry = Connection(inConn.type, inComp.name, inComp.num,
                               inComp.host, inConn.port)

            if not map.has_key(outComp):
                map[outComp] = []
            map[outComp].append(entry)

class ConnectionManager:
    """Manage the connections for a runset"""

    def __init__(self):
        """ConnectionManager constructor"""
        self.connDict = {}

    def add(self, comp):
        """Add a component's connections"""
        for n in comp.connectors:
            if not self.connDict.has_key(n.type):
                self.connDict[n.type] = ConnTypeEntry(n.type)
            self.connDict[n.type].add(n, comp)

    def buildConnectionMap(self):
        """Validate and fill the map of connections for each component"""
        map = {}

        for k in self.connDict:
            self.connDict[k].buildConnectionMap(map)

        return map

class RunSet:
    """A set of components to be used in a set of runs"""

    ID = 1

    def __init__(self, set):
        """
        RunSet constructor
        set - list of components
        id - unique runset ID
        runNumber - run number (if assigned)
        """
        self.set = set

        self.id = RunSet.ID
        RunSet.ID += 1

        self.configured = False
        self.runNumber = None

    def __str__(self):
        """String description"""
        setStr = 'RunSet #' + str(self.id)
        if self.runNumber is not None:
            setStr += ' run#' + str(self.runNumber)
        return setStr

    def componentListStr(self):
        """Return string of all components, one per line"""
        setStr = ""
        for c in self.set:
            setStr += str(c) + "\n"
        return setStr

    def configure(self):
        """Configure all components in the runset"""
        for c in self.set:
            c.configure()
        self.configured = True

    def reset(self):
        """Reset all components in the runset back to the idle state"""
        for c in self.set:
            c.reset()

        self.configured = False
        self.runNumber = None

    def startRun(self, runNum):
        """Start all components in the runset"""
        if not self.configured:
            raise ValueError, "RunSet #" + str(self.id) + " is not configured"

        self.runNumber = runNum
        for c in self.set:
            c.startRun(runNum)

    def stopRun(self):
        """Stop all components in the runset"""
        if self.runNumber is None:
            raise ValueError, "RunSet #" + str(self.id) + " is not running"

        for c in self.set:
            c.stopRun()

        self.runNumber = None

    def status(self):
        """Print the current state of components in the runset"""
        for c in self.set:
            print str(c) + ' ' + c.getState()

class DAQClient:
    """DAQ component"""

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

    def __init__(self, name, num, host, port, connectors):
        """
        DAQClient constructor
        name - component name
        num - component instance number
        host - component host name
        port - component port number
        connectors - list of Connectors
        """
        self.name = name
        self.num = num
        self.host = host
        self.port = port
        self.connectors = connectors

        self.id = DAQClient.ID
        DAQClient.ID += 1

        self.client = RPCClient(host, port)

        self.deadCount = 0

    def __str__(self):
        """String description"""
        if not self.connectors or len(self.connectors) == 0:
            connStr = ''
        else:
            connStr = None
            for c in self.connectors:
                if not connStr:
                    connStr = ' [' + str(c)
                else:
                    connStr += ' ' + str(c)
            connStr += ']'

        return "ID#%d %s#%d at %s:%d%s" % \
            (self.id, self.name, self.num, self.host, self.port, connStr)

    def configure(self, xml=None):
        """Configure this component"""
        try:
            if not xml:
                return self.client.xmlrpc.configure(self.id)
            else:
                return self.client.xmlrpc.configure(self.id, list)
        except Exception, e:
            print exc_string()
            return None

    def connect(self, list=None):
        """Connect this component with other components in a runset"""
        try:
            if not list:
                return self.client.xmlrpc.connect(self.id)
            else:
                return self.client.xmlrpc.connect(self.id, list)
        except Exception, e:
            print exc_string()
            return None

    def getState(self):
        """Get current state"""
        try:
            return self.client.xmlrpc.getState(self.id)
        except Exception, e:
            print exc_string()
            return None

    def logTo(self, logIP, port):
        self.client.xmlrpc.logTo(self.id, logIP, port)

    def monitor(self):
        state = self.getState()
        if not state:
            self.deadCount += 1
            if self.deadCount < 3:
                state = DAQClient.STATE_MISSING
            else:
                state = DAQClient.STATE_DEAD

        return state

    def reset(self):
        """Reset component back to the idle state"""
        return self.client.xmlrpc.reset(self.id)

    def startRun(self, runNum):
        """Start component processing DAQ data"""
        try:
            return self.client.xmlrpc.startRun(self.id, runNum)
        except Exception, e:
            print exc_string()
            return None

    def stopRun(self):
        """Stop component processing DAQ data"""
        try:
            print "XMLRPC stop run for ", self.id
            return self.client.xmlrpc.stopRun(self.id)
        except Exception, e:
            print exc_string()
            return None

class DAQServer:
    """Configuration server"""

    def __init__(self, name="GenericServer", port=8080):
        self.port = port
        self.name = name
        self.pool = {}
        self.sets = []
        self.socketlog = None

        notify = True
        while True:
            try:
                self.server = RPCServer(self.port)
                break
            except socket.error, e:
                if notify: print "Couldn't create server socket: %s" % e
                notify = False
                sleep(3)

        self.server.register_function(self.rpc_close_log)
        self.server.register_function(self.rpc_get_num_components)
        self.server.register_function(self.rpc_log_to)
        self.server.register_function(self.rpc_ping)
        self.server.register_function(self.rpc_register_component)
        self.server.register_function(self.rpc_runset_break)
        self.server.register_function(self.rpc_runset_configure)
        self.server.register_function(self.rpc_runset_make)
        self.server.register_function(self.rpc_runset_start_run)
        self.server.register_function(self.rpc_runset_status)
        self.server.register_function(self.rpc_runset_stop_run)
        self.server.register_function(self.rpc_show_components)
        self.server.register_function(self.rpc_num_sets)

    def rpc_close_log(self):
        "called by DAQLog object to indicate when we should close log file"
        self.logmsg("End of log")
        self.socketlog.close
        self.socketlog = None
        return 1

    def rpc_get_num_components(self):
        "return number of components currently registered"
        return len(self.pool)

    def rpc_log_to(self, host, port):
        "called by DAQLog object to tell us what UDP port to log to"
        self.socketlog = DAQLogger(host, port)
        self.logmsg("Start of log")
        return 1

    def rpc_ping(self):
        "remote method for far end to see if we're alive"
        return "OK"

    def rpc_register_component(self, name, num, host, port, connArray):
        "register a component with the server"
        connectors = []
        for d in connArray:
            connectors.append(Connector(d[0], d[1], d[2]))

        client = DAQClient(name, num, host, port, connectors)
        self.logmsg("Got registration for %s" % str(client))

        sleep(1)

        self.addToPool(client)

        return client.id

    def rpc_runset_break(self, id):
        "break up the specified set"
        found = False
        for s in self.sets:
            if s.id == id:
                self.sets.remove(s)
                s.reset()
                for c in s.set:
                    self.addToPool(c)
                found = True
                break

        if not found:
            raise ValueError, 'Could not find run#' + str(id)

        return "OK"

    def rpc_runset_configure(self, id):
        "configure the specified set"
        set = self.findSet(id)

        if not set:
            raise ValueError, 'Could not find runset#' + str(id)

        set.configure()

        return "OK"

    def rpc_runset_make(self, nameList):
        "build a set using the specified components"
        compList = [ ]
        setAdded = False
        try:
            try:
                # buildSet fills 'compList' with the specified components
                #
                self.buildSet(nameList, compList)
                runSet = RunSet(compList)
                self.sets.append(runSet)
                setAdded = True
                self.logmsg("Built set with the following components:\n"+ runSet.componentListStr())
            except Exception, ex:
                runSet = None
                self.logmsg(exc_string())
                raise ex
        finally:
            if not setAdded:
                for c in compList:
                    c.reset()
                    self.addToPool(c)
                runSet = None

        if not runSet:
            return -1

        return runSet.id

    def rpc_runset_start_run(self, id, runNum):
        "start a run with the specified set"
        set = self.findSet(id)

        if not set:
            raise ValueError, 'Could not find runset#' + str(id)

        set.startRun(runNum)

        return "OK"

    def rpc_runset_status(self, id):
        "get run status for the specified set"
        set = self.findSet(id)

        if not set:
            raise ValueError, 'Could not find runset#' + str(id)

        set.status()

        return "OK"

    def rpc_runset_stop_run(self, id):
        "stop a run with the specified set"
        set = self.findSet(id)

        if not set:
            raise ValueError, 'Could not find runset#' + str(id)

        self.logmsg("stopRun+")
        set.stopRun()
        self.logmsg("stopRun-")

        return "OK"

    def rpc_num_sets(self):
        "show existing run sets"
        return len(self.sets)

    def rpc_show_components(self):
        "show unused components and their current states"
        s = []
        for k in self.pool:
            for c in self.pool[k]:
                try:
                    state = c.getState()
                except Exception:
                    state = DAQClient.STATE_DEAD

                s.append(str(c) + ' ' + state)

        return s

    def addToPool(self, comp):
        """Add the component to the config server's pool"""
        if not self.pool.has_key(comp.name):
            self.pool[comp.name] = []
        self.pool[comp.name].append(comp)

    def buildSet(self, nameList, compList):
        """
        Build a runset from the specified list of component names
        """
        connMgr = ConnectionManager()

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
                    self.takeFromPool(c)
                    comp = c
                    break
            if not comp:
                raise ValueError, 'Component \"' + name + '#' + str(num) + \
                    '" is not available'

            # add component to temporary list
            #
            compList.append(comp)

            # add component's connectors to the connection dictionary
            #
            connMgr.add(comp)

        # make sure I/O channels match up
        #
        map = connMgr.buildConnectionMap()

        # connect all components
        #
        for c in compList:
            if not map.has_key(c):
                c.connect()
            else:
                c.connect(map[c])

        return None

    def findSet(self, id):
        """Find the runset with the specified ID"""
        set = None
        for s in self.sets:
            if s.id == id:
                set = s
                break

        return set

    def logmsg(self, s):
        """
        Log a string to stdout and, if available, to the socket logger
        stdout of course will not appear if daemonized.
        """
        print s
        if self.socketlog: self.socketlog.write_ts(s)

    def monitorClients(self, new):
        """check that all components in the pool are still alive"""
        count = 0

        keys = self.pool.keys()
        for k in keys:
            if new: self.logmsg("  %s:" % k)

            try:
                bin = self.pool[k]
            except KeyError:
                # bin may have been removed by daemon
                continue

            for c in bin:
                state = c.monitor()
                if state == DAQClient.STATE_DEAD:
                    self.takeFromPool(c)
                elif state != DAQClient.STATE_MISSING:
                    count += 1

                if new:
                    self.logmsg("    %s %s" % (str(c), state))

        for s in self.sets:
            self.logmsg(str(s))

        return count

    def serve(self, handler):
        """Start a server"""
        self.logmsg("I'm server %s running on port %d" % (self.name, self.port))
        thread.start_new_thread(handler, ())
        self.server.serve_forever()

    def takeFromPool(self, comp):
        """Remove a component from the pool"""
        self.pool[comp.name].remove(comp)
        if len(self.pool[comp.name]) == 0:
            del self.pool[comp.name]
        return comp

if __name__ == "__main__":
    # Unit tests here
    pass

