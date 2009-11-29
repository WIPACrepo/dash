#!/usr/bin/env python

from DAQConst import DAQPort
from DAQLogClient \
    import BothSocketAppender, DAQLog, LiveSocketAppender, LogSocketAppender
from DAQRPC import RPCClient, RPCServer
from Process import processList, findProcess
from time import time, sleep
from SocketServer import ThreadingMixIn

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

import Daemon
import optparse
import os
import socket
import sys
import threading

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID  = "$Id: CnCServer.py 4746 2009-11-29 13:20:15Z dglo $"

class Connector(object):
    """
    Component connector description
    type - connection type
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
        if isInput:
            self.port = port
        else:
            self.port = None

    def __str__(self):
        "String description"
        if self.port is not None:
            return '%d=>%s' % (self.port, self.type)
        return self.type + '=>'

    def isInput(self):
        return self.port is not None

class Connection(object):
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
        frontStr = '%s:%s#%d@%s' % \
            (self.conn.type, self.comp.name(), self.comp.num(),
             self.comp.host())
        if not self.conn.isInput():
            return frontStr
        return '%s:%d' % (frontStr, self.conn.port)

    def map(self):
        connDict = {}
        connDict['type'] = self.conn.type
        connDict['compName'] = self.comp.name()
        connDict['compNum'] = self.comp.num()
        connDict['host'] = self.comp.host()
        connDict['port'] = self.conn.port
        return connDict

class ConnTypeEntry(object):
    """
    Temporary class used to build the connection map for a runset
    type - connection type
    inList - list of [input connection, component] entries
    outList - list of output connections
    """
    def __init__(self, type):
        """
        ConnTypeEntry constructor
        type - connection type
        """
        self.__type = type
        self.__inList = []
        self.__outList = []

    def __str__(self):
        return '%s in#%d out#%d' % (self.__type, len(self.__inList),
                                    len(self.__outList))

    def add(self, conn, comp):
        "Add a connection and component to the appropriate list"
        if conn.isInput():
            self.__inList.append([conn, comp])
        else:
            self.__outList.append(comp)

    def buildConnectionMap(self, connMap):
        "Validate and fill the map of connections for each component"
        if len(self.__inList) == 0:
            raise ValueError('No inputs found for %d %s outputs' %
                             (len(self.__outList), self.__type))
        if len(self.__outList) == 0:
            inStr = ''
            for inPair in self.__inList:
                if len(inStr) == 0:
                    inStr = str(inPair[1])
                else:
                    inStr += ', ' + str(inPair[1])
            raise ValueError('No outputs found for %d %s inputs (%s)' %
                             (len(self.__inList), self.__type, inStr))
        if len(self.__inList) > 1 and len(self.__outList)  > 1:
            inStr = ''
            for inPair in self.__inList:
                if len(inStr) == 0:
                    inStr = str(inPair[1])
                else:
                    inStr += ', ' + str(inPair[1])
            raise ValueError('Found %d %s outputs for %d inputs (%s)' %
                             (len(self.__outList), self.__type,
                              len(self.__inList), inStr))

        if len(self.__inList) == 1:
            inConn = self.__inList[0][0]
            inComp = self.__inList[0][1]

            for outComp in self.__outList:
                entry = Connection(inConn, inComp)

                if not connMap.has_key(outComp):
                    connMap[outComp] = []
                connMap[outComp].append(entry)
        else:
            outComp = self.__outList[0]

            for inConn, inComp in self.__inList:
                entry = Connection(inConn, inComp)

                if not connMap.has_key(outComp):
                    connMap[outComp] = []
                connMap[outComp].append(entry)

class SubrunThread(threading.Thread):
    "A thread which starts the subrun in an individual stringHub"

    def __init__(self, comp, data):
        self.__comp = comp
        self.__data = data
        self.__time = None
        self.__done = False

        threading.Thread.__init__(self)

        self.setName(str(comp) + ":subrun")

    def done(self):
        return self.__done

    def finished(self):
        return self.__time is not None

    def run(self):
        tStr = self.__comp.startSubrun(self.__data)
        if tStr is not None:
            self.__time = long(tStr)
        self.__done = True

    def time(self):
        return self.__time

class RunSetThreadGroup(object):
    def __init__(self):
        "Create a runset thread group"
        self.__list = []

    def reportErrors(self, logger, method):
        numAlive = 0
        numErrors = 0
        for t in self.__list:
            if t.isAlive():
                numAlive += 1
            if t.isError():
                numErrors += 1
        if numAlive > 0:
            if numAlive == 1:
                plural = ""
            else:
                plural = "s"
            logger.error(("Thread group contains %d running thread%s" +
                          " after %s") % (numAlive, plural, method))
        if numErrors > 0:
            if numErrors == 1:
                plural = ""
            else:
                plural = "s"
            logger.error("Thread group encountered %d error%s during %s" %
                         (numErrors, plural, method))

    def start(self, thread):
        "Start a thread after adding it to the group"
        self.__list.append(thread)
        thread.start()

    def wait(self, reps=4, waitSecs=0.5):
        """
        Wait for all the threads to finish
        reps - number of times to loop before deciding threads are hung
        waitSecs - number of seconds to wait (as a float)
        NOTE:
        if all threads are hung, max wait time is (#threads * waitSecs * reps)
        """
        alive = True
        for i in range(reps):
            alive = False
            for t in self.__list:
                if t.isAlive():
                    t.join(waitSecs)
                    alive |= t.isAlive()
            if not alive:
                break

class RunSetThread(threading.Thread):
    "Thread used to communicate with a component in a run set"

    "thread will configure the component"
    CONFIG_COMP = "CONFIG_COMP"
    "thread will configure the component's logging"
    CONFIG_LOGGING = "CONFIG_LOGGING"
    "thread will force the running component to stop"
    FORCED_STOP = "FORCED_STOP"
    "thread will reset the component"
    RESET_COMP = "RESET_COMP"
    "thread will reset the component's logging"
    RESET_LOGGING = "RESET_LOGGING"
    "thread will start the component running"
    START_RUN = "START_RUN"
    "thread will stop the running component"
    STOP_RUN = "STOP_RUN"

    def __init__(self, comp, log, operation, data):
        """
        Initialize a run set thread
        comp - component
        log - object used to log errors
        operation - RunSetThread operation
        data - tuple holding all data needed for the operation
        """
        self.__comp = comp
        self.__log = log
        self.__operation = operation
        self.__data = data

        self.__error = False

        threading.Thread.__init__(self)

        self.setName("CnCServer:RunSet*%s" % str(self.__comp))

    def __configComponent(self):
        "Configure the component"
        self.__comp.configure(self.__data[0])

    def __configLogging(self):
        "Configure logging for the component"
        self.__comp.logTo(self.__data[0], self.__data[1], self.__data[2],
                          self.__data[3])

    def __forcedStop(self):
        "Force the running component to stop"
        self.__comp.forcedStop()

    def __resetComponent(self):
        "Reset the component"
        self.__comp.reset()

    def __resetLogging(self):
        "Reset logging for the component"
        self.__comp.resetLogging()

    def __startRun(self):
        "Start the component running"
        self.__comp.startRun(self.__data[0])

    def __stopRun(self):
        "Stop the running component"
        self.__comp.stopRun()

    def __runOperation(self):
        "Execute the requested operation"
        if self.__operation == RunSetThread.CONFIG_COMP:
            self.__configComponent()
        elif self.__operation == RunSetThread.CONFIG_LOGGING:
            self.__configLogging()
        elif self.__operation == RunSetThread.FORCED_STOP:
            self.__forcedStop()
        elif self.__operation == RunSetThread.RESET_COMP:
            self.__resetComponent()
        elif self.__operation == RunSetThread.RESET_LOGGING:
            self.__resetLogging()
        elif self.__operation == RunSetThread.START_RUN:
            self.__startRun()
        elif self.__operation == RunSetThread.STOP_RUN:
            self.__stopRun()
        else:
            raise Exception("Unknown operation %s" % str(self.__operation))

    def isError(self): return self.__error

    def run(self):
        "Main method for thread"
        try:
            self.__runOperation()
        except:
            self.__log.error("%s(%s): %s" % (str(self.__operation),
                                             str(self.__comp),
                                             exc_string()))
            self.__error = True

class RunSet(object):
    "A set of components to be used in one or more runs"

    ID = 1

    # number of seconds to wait after stopping components seem to be
    # hung before forcing remaining components to stop
    #
    TIMEOUT_SECS = RPCClient.TIMEOUT_SECS - 5

    def __init__(self, set, logger):
        """
        RunSet constructor
        set - list of components
        logger - logging object
        id - unique runset ID
        configured - true if this runset has been configured
        runNumber - run number (if assigned)
        state - current state of this set of components
        """
        self.__set = set
        self.__logger = logger

        self.__id = RunSet.ID
        RunSet.ID += 1

        self.__configured = False
        self.__runNumber = None
        self.__state = 'unknown'

    def __str__(self):
        "String description"
        setStr = 'RunSet #%d' % self.__id
        if self.__runNumber is not None:
            setStr += ' run#%d' % self.__runNumber
        return setStr

    def componentListStr(self):
        "Return string of all components, one per line"
        setStr = ""
        for c in self.__set:
            setStr += str(c) + "\n"
        return setStr

    def components(self):
        return self.__set[:]

    def configure(self, globalConfigName):
        "Configure all components in the runset"
        self.__state = 'configuring'

        tGroup = RunSetThreadGroup()
        for c in self.__set:
            tGroup.start(RunSetThread(c, self.__logger,
                                      RunSetThread.CONFIG_COMP,
                                      (globalConfigName, )))
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "configure")

        waitLoop = 0
        while True:
            waitList = []
            for c in self.__set:
                stateStr = c.state()
                if stateStr != 'configuring' and stateStr != 'ready':
                    waitList.append(c)

            if len(waitList) == 0:
                break
            self.__logger.info('%s: Waiting for %s: %s' %
                               (str(self), self.__state,
                                self.listComponentsCommaSep(waitList)))

            sleep(1)
            waitLoop += 1
            if waitLoop > 60:
                break

        self.waitForStateChange(30)

        self.__state = 'ready'
        badList = self.listBadState()
        if len(badList) > 0:
            raise ValueError('Could not configure %s' % str(badList))

        self.__configured = True

    def configureBothLogging(self, liveIP, livePort, pdaqIP, pdaqList):
        "Configure I3Live and pDAQ logging for all components in the runset"
        tGroup = RunSetThreadGroup()
        for c in self.__set:
            for i in range(0, len(pdaqList)):
                logData = pdaqList[i]
                if c.isComponent(logData[0], logData[1]):
                    tGroup.start(RunSetThread(c, self.__logger,
                                              RunSetThread.CONFIG_LOGGING,
                                              (pdaqIP, logData[2],
                                               liveIP, livePort)))
                    del pdaqList[i]
                    break

        tGroup.wait()
        tGroup.reportErrors(self.__logger, "configureBothLogging")

        return pdaqList

    def configureLiveLogging(self, logIP, logPort):
        "Configure I3Live logging for all components in the runset"
        tGroup = RunSetThreadGroup()
        for c in self.__set:
            tGroup.start(RunSetThread(c, self.__logger,
                                      RunSetThread.CONFIG_LOGGING,
                                      (None, None, logIP, logPort)))

        tGroup.wait()
        tGroup.reportErrors(self.__logger, "configureLiveLogging")

    def configureLogging(self, logIP, logList):
        "Configure logging for specified components in the runset"
        tGroup = RunSetThreadGroup()
        for c in self.__set:
            for i in range(0, len(logList)):
                logData = logList[i]
                if c.isComponent(logData[0], logData[1]):
                    tGroup.start(RunSetThread(c, self.__logger,
                                              RunSetThread.CONFIG_LOGGING,
                                              (logIP, logData[2], None, None)))
                    del logList[i]
                    break

        tGroup.wait()
        tGroup.reportErrors(self.__logger, "configureLogging")

        return logList

    def configured(self):
        return self.__configured

    def destroy(self):
        if len(self.__set) > 0:
            raise ValueError('RunSet #%d is not empty' % self.__id)

        self.__id = None
        self.__configured = False
        self.__runNumber = None
        self.__state = 'destroyed'

    def events(self, subrunNumber):
        "Get the number of events in the specified subrun"
        for c in self.__set:
            if c.isBuilder():
                return c.events(subrunNumber)

        raise ValueError('RunSet #%d does not contain an event builder' %
                         self.__id)

    def id(self):
        return self.__id

    def isRunning(self):
        return self.__state is not None and self.__state == 'running'

    def list(self):
        slst = []
        for c in self.__set:
            slst.append(c.list())

        return slst

    def listBadState(self):
        slst = []

        for c in self.__set:
            stateStr = c.state()
            if stateStr != self.__state:
                slst.append(c.fullName() + ':' + stateStr)

        return slst

    def listComponentsCommaSep(compList):
        """
        Concatenate a list of components into a string showing names and IDs,
        similar to componentListStr but more compact
        """
        compStr = None
        for c in compList:
            if compStr == None:
                compStr = ''
            else:
                compStr += ', '
            compStr += c.fullName()
        return compStr
    listComponentsCommaSep = staticmethod(listComponentsCommaSep)

    def reset(self):
        "Reset all components in the runset back to the idle state"
        self.__state = 'resetting'

        tGroup = RunSetThreadGroup()
        for c in self.__set:
            tGroup.start(RunSetThread(c, self.__logger,
                                      RunSetThread.RESET_COMP, ()))
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "reset")

        try:
            self.waitForStateChange(60)
        except:
            # give up after 60 seconds
            pass

        self.__state = 'idle'

        badList = self.listBadState()

        self.__configured = False
        self.__runNumber = None

        return badList

    def resetLogging(self):
        "Reset logging for all components in the runset"
        tGroup = RunSetThreadGroup()
        for c in self.__set:
            tGroup.start(RunSetThread(c, self.__logger,
                                      RunSetThread.RESET_LOGGING, ()))
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "resetLogging")

    def returnComponents(self, pool):
        badList = self.reset()

        # transfer components back to pool
        #
        while len(self.__set) > 0:
            comp = self.__set[0]
            del self.__set[0]
            pool.add(comp)

        # raise exception if one or more components could not be reset
        #
        if len(badList) > 0:
            raise ValueError('Could not reset %s' % str(badList))

    def runNumber(self):
        return self.__runNumber

    def size(self):
        return len(self.__set)

    def sortCmp(self, x, y):
        if y.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(y))
            return -1
        elif x.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(x))
            return 1
        else:
            return y.order()-x.order()

    def startRun(self, runNum):
        "Start all components in the runset"
        if not self.__configured:
            raise ValueError("RunSet #%d is not configured" % self.__id)

        srcSet = []
        otherSet = []

        failStr = None
        for c in self.__set:
            if c.order() is not None:
                if c.isSource():
                    srcSet.append(c)
                else:
                    otherSet.append(c)
            else:
                if not failStr:
                    failStr = 'No order set for ' + str(c)
                else:
                    failStr += ', ' + str(c)
        if failStr:
            raise ValueError(failStr)

        self.__state = 'starting'
        self.__runNumber = runNum

        # start non-sources in order (back to front)
        #
        otherSet.sort(self.sortCmp)
        for c in otherSet:
            c.startRun(runNum)

        # start sources in parallel
        #
        tGroup = RunSetThreadGroup()
        for c in srcSet:
            tGroup.start(RunSetThread(c, self.__logger,
                                      RunSetThread.START_RUN, (runNum, )))
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "startRun")
        
        self.waitForStateChange(30)

        self.__state = 'running'

        badList = self.listBadState()
        if len(badList) > 0:
            raise ValueError('Could not start runset#%d run#%d components: %s' %
                             (self.__id, runNum, str(badList)))

    def status(self):
        """
        Return a dictionary of components in the runset
        and their current state
        """
        setStat = {}
        for c in self.__set:
            setStat[c] = c.state()

        return setStat

    def stopRun(self):
        "Stop all components in the runset"
        if self.__runNumber is None:
            raise ValueError("RunSet #%d is not running" % self.__id)

        srcSet = []
        otherSet = []

        for c in self.__set:
            if c.isSource():
                srcSet.append(c)
            else:
                otherSet.append(c)

        # stop from front to back
        #
        otherSet.sort(lambda x, y: self.sortCmp(y, x))

        for i in range(0, 2):
            if i == 0:
                self.__state = 'stopping'
                srcOp = RunSetThread.STOP_RUN
                timeoutSecs = int(RunSet.TIMEOUT_SECS * .75)
            else:
                self.__state = 'forcingStop'
                srcOp = RunSetThread.FORCED_STOP
                timeoutSecs = int(RunSet.TIMEOUT_SECS * .25)

            if i == 1:
                self.__logger.error('%s: Forcing %d components to stop: %s' %
                                    (str(self), len(waitList),
                                     self.listComponentsCommaSep(waitList)))

            # stop sources in parallel
            #
            tGroup = RunSetThreadGroup()
            for c in srcSet:
                tGroup.start(RunSetThread(c, self.__logger, srcOp, ()))
            tGroup.wait()
            tGroup.reportErrors(self.__logger, self.__state)

            # stop non-sources in order
            #
            for c in otherSet:
                if i == 0:
                    c.stopRun()
                else:
                    c.forcedStop()

            connDict = {}

            waitList = srcSet + otherSet

            endSecs = time() + timeoutSecs
            while len(waitList) > 0 and time() < endSecs:
                newList = waitList[:]
                for c in waitList:
                    stateStr = c.state()
                    if stateStr != self.__state:
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
                            waitStr += c.fullName() + connDict[c]

                        self.__logger.info('%s: Waiting for %s %s' %
                                           (str(self), self.__state, waitStr))

            # if the components all stopped normally, don't force-stop them
            #
            if len(waitList) == 0:
                break

        self.__runNumber = None

        if len(waitList) > 0:
            waitStr = None
            for c in waitList:
                if waitStr is None:
                    waitStr = ''
                else:
                    waitStr += ', '
                waitStr += c.fullName() + connDict[c]

            errStr = '%s: Could not stop %s' % (str(self), waitStr)
            self.__logger.error(errStr)
            raise ValueError(errStr)

    def subrun(self, id, data):
        "Start a subrun with all components in the runset"
        if self.__runNumber is None:
            raise ValueError("RunSet #%d is not running" % self.__id)

        for c in self.__set:
            if c.isBuilder():
                c.prepareSubrun(id)

        shThreads = []
        for c in self.__set:
            if c.isSource():
                thread = SubrunThread(c, data)
                thread.start()
                shThreads.append(thread)

        badComps = []

        latestTime = None
        while len(shThreads) > 0:
            sleep(0.1)
            for thread in shThreads:
                if thread.done():
                    if not thread.finished():
                        badComps.append(thread.comp)
                    elif latestTime is None or thread.time() > latestTime:
                        latestTime = thread.time()
                    shThreads.remove(thread)

        if latestTime is None:
            raise ValueError("Couldn't start subrun on any string hubs")

        if len(badComps) > 0:
            raise ValueError("Couldn't start subrun on %s" %
                             self.listComponentsCommaSep(badComps))

        for c in self.__set:
            if c.isBuilder():
                c.commitSubrun(id, repr(latestTime))

    def waitForStateChange(self, timeoutSecs=TIMEOUT_SECS):
        """
        Wait for state change, with a timeout of timeoutSecs (renewed each time
        any component changes state).  Raise a ValueError if the state change
        fails.
        """
        waitList = self.__set[:]

        endSecs = time() + timeoutSecs
        while len(waitList) > 0 and time() < endSecs:
            newList = waitList[:]
            for c in waitList:
                stateStr = c.state()
                if stateStr != self.__state:
                    newList.remove(c)

            # if one or more components changed state...
            #
            if len(waitList) == len(newList):
                sleep(1)
            else:
                waitList = newList
                if len(waitList) > 0:
                    waitStr = RunSet.listComponentsCommaSep(waitList)
                    self.__logger.info('%s: Waiting for %s %s' %
                                       (str(self), self.__state, waitStr))

                # reset timeout
                #
                endSecs = time() + timeoutSecs

        if len(waitList) > 0:
            waitStr = RunSet.listComponentsCommaSep(waitList)
            raise ValueError(('Still waiting for %d components to leave %s' +
                              ' (%s)') % (len(waitList), self.__state, waitStr))

class LogInfo(object):
    def __init__(self, logHost, logPort, liveHost, livePort):
        self.__logHost = logHost
        self.__logPort = logPort
        self.__liveHost = liveHost
        self.__livePort = livePort

    def __cmp__(self, other):
        val = cmp(self.__logHost, other.__logHost)
        if val == 0:
            val = cmp(self.__logPort, other.__logPort)
            if val == 0:
                val = cmp(self.__liveHost, other.__liveHost)
                if val == 0:
                    val = cmp(self.__livePort, other.__livePort)
        return val

    def __str__(self):
        outStr = ''
        if self.__logHost is not None and self.__logPort is not None:
            outStr += ' log(%s:%d)' % (self.__logHost, self.__logPort)
        if self.__liveHost is not None and self.__livePort is not None:
            outStr += ' live(%s:%d)' % (self.__liveHost, self.__livePort)
        if len(outStr) == 0:
            return 'NoInfo'
        return outStr[1:]
            
    def logHost(self): return self.__logHost
    def logPort(self): return self.__logPort
    def liveHost(self): return self.__liveHost
    def livePort(self): return self.__livePort

class CnCLogger(DAQLog):
    "CnC logging client"

    def __init__(self, appender=None, quiet=False):
        "create a logging client"
        self.__quiet = quiet

        self.__prevInfo = None
        self.__logInfo = None

        super(CnCLogger, self).__init__(appender)

    def __getName(self):
        if self.__logInfo is not None:
            return 'LOG=%s' % str(self.__logInfo)
        if self.__prevInfo is not None:
            return 'PREV=%s' % str(self.__prevInfo)
        return '?LOG?'

    def __str__(self):
        return self.__getName()

    def _logmsg(self, level, s):
        """
        Log a string to stdout and, if available, to the socket logger
        stdout of course will not appear if daemonized.
        """
        if not self.__quiet: print s
        try:
            super(CnCLogger, self)._logmsg(level, s)
        except Exception, ex:
            if str(ex).find('Connection refused') < 0:
                raise
            print 'Lost logging connection to %s' % str(self.__logInfo)
            self.resetLog()
            self._logmsg(level, s)

    def closeLog(self):
        "Close the log socket"
        self.info("End of log")
        self.resetLog()

    def closeFinal(self):
        self.close()
        self.__logInfo = None
        self.__prevInfo = None

    def createAppender(self, logHost, logPort, liveHost, livePort):
        "create a socket logger (overrideable method used for testing)"
        if logHost is not None and logPort is not None:
            if liveHost is not None and livePort is not None:
                return BothSocketAppender(logHost, logPort, liveHost, livePort)
            return LogSocketAppender(logHost, logPort)
        elif liveHost is not None and livePort is not None:
            return LiveSocketAppender(liveHost, livePort)
        raise Exception('Could not create appender: log(%s:%s) live(%s:%s)' %
                        (str(logHost), str(logPort), str(liveHost),
                         str(livePort)))

    def liveHost(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.liveHost()

    def livePort(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.livePort()

    def logHost(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.logHost()

    def logPort(self):
        if self.__logInfo is None:
            return None
        return self.__logInfo.logPort()

    def isQuiet(self):
        return self.__quiet

    def openLog(self, logHost, logPort, liveHost, livePort):
        "initialize socket logger"
        if self.__prevInfo is None:
            self.__prevInfo = self.__logInfo

        self.__logInfo = LogInfo(logHost, logPort, liveHost, livePort)
        logAppender = self.createAppender(logHost, logPort, liveHost, livePort)

        self.setAppender(logAppender)
        self.debug('Start of log at %s' % str(logAppender))

    def resetLog(self):
        "close current log and reset to initial state"
        if self.__prevInfo is not None and self.__logInfo != self.__prevInfo:
            self.__logInfo = self.__prevInfo
            logAppender = self.createAppender(self.__logInfo.logHost(),
                                              self.__logInfo.logPort(),
                                              self.__logInfo.liveHost(),
                                              self.__logInfo.livePort())
        else:
            logAppender = None
            self.__logInfo = None

        self.__prevInfo = None

        self.setAppender(logAppender)
        if logAppender is not None:
            self.info('Reset log to %s' % str(logAppender))

class DAQClient(object):
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

    def __init__(self, name, num, host, port, mbeanPort, connectors,
                 quiet=False):
        """
        DAQClient constructor
        name - component name
        num - component instance number
        host - component host name
        port - component port number
        mbeanPort - component MBean port number
        connectors - list of Connectors
        """
        self.__name = name
        self.__num = num
        self.__host = host
        self.__port = port
        self.__mbeanPort = mbeanPort
        self.__connectors = connectors

        self.__id = DAQClient.ID
        DAQClient.ID += 1

        self.__log = self.createCnCLogger(quiet=quiet)

        self.__client = self.createClient(host, port)

        self.__deadCount = 0
        self.__cmdOrder = None

    def __str__(self):
        "String description"
        if self.__port <= 0:
            hpStr = ''
        else:
            hpStr = ' at %s:%d' % (self.__host, self.__port)

        if self.__mbeanPort <= 0:
            mbeanStr = ''
        else:
            mbeanStr = ' M#%d' % self.__mbeanPort

        extraStr = ''
        if self.__connectors and len(self.__connectors) > 0:
            first = True
            for c in self.__connectors:
                if first:
                    extraStr += ' [' + str(c)
                    first = False
                else:
                    extraStr += ' ' + str(c)
            extraStr += ']'

        return "ID#%d %s#%d%s%s%s" % \
            (self.__id, self.__name, self.__num, hpStr, mbeanStr, extraStr)

    def close(self):
        self.__log.close()

    def commitSubrun(self, subrunNum, latestTime):
        "Start marking events with the subrun number"
        try:
            return self.__client.xmlrpc.commitSubrun(subrunNum, latestTime)
        except Exception:
            self.__log.error(exc_string())
            return None

    def configure(self, configName=None):
        "Configure this component"
        try:
            if not configName:
                return self.__client.xmlrpc.configure()
            else:
                return self.__client.xmlrpc.configure(configName)
        except Exception:
            self.__log.error(exc_string())
            return None

    def connect(self, connList=None):
        "Connect this component with other components in a runset"

        if not connList:
            return self.__client.xmlrpc.connect()

        cl = []
        for conn in connList:
            cl.append(conn.map())

        return self.__client.xmlrpc.connect(cl)

    def connectors(self):
        return self.__connectors[:]

    def createClient(self, host, port):
        return RPCClient(host, port)

    def createCnCLogger(self, quiet):
        return CnCLogger(quiet=quiet)

    def events(self, subrunNumber):
        "Get the number of events in the specified subrun"
        try:
            evts = self.__client.xmlrpc.getEvents(subrunNumber)
            if type(evts) == str:
                evts = long(evts[:-1])
            return evts
        except Exception:
            self.__log.error(exc_string())
            return None

    def forcedStop(self):
        "Force component to stop running"
        try:
            return self.__client.xmlrpc.forcedStop()
        except Exception:
            self.__log.error(exc_string())
            return None

    def fullName(self):
        if self.__num == 0 and self.__name[-3:].lower() != 'hub':
            return self.__name
        return '%s#%d' % (self.__name, self.__num)

    def getNonstoppedConnectorsString(self):
        """
        Return string describing states of all connectors
        which have not yet stopped
        """
        try:
            connStates = self.__client.xmlrpc.listConnectorStates()
        except Exception:
            self.__log.error(exc_string())
            return None

        csStr = None
        for cs in connStates:
            if cs[1] == 'idle':
                continue
            if not csStr:
                csStr = '['
            else:
                csStr += ', '
            csStr += '%s:%s' % (cs[0], cs[1])

        if not csStr:
            csStr = ''
        else:
            csStr += ']'

        return csStr

    def host(self):
        return self.__host

    def id(self):
        return self.__id

    def isBuilder(self):
        "Is this an eventBuilder (or debugging fooBuilder)?"
        return self.__name.endswith("Builder")

    def isComponent(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__name == name and (num < 0 or self.__num == num)

    def isSource(self):
        "Is this component a source of data?"

        # XXX This is a hack
        if self.__name.endswith('Hub'):
            return True

        for conn in self.__connectors:
            if conn.isInput():
                return False

        return True

    def list(self):
        return [ self.__id, self.__name, self.__num, self.__host, self.__port,
                 self.__mbeanPort, self.state() ]

    def logTo(self, logIP, logPort, liveIP, livePort):
        "Send log messages to the specified host and port"
        self.__log.openLog(logIP, logPort, liveIP, livePort)

        if logIP is None:
            logIP = ''
        if logPort is None:
            logPort = 0
        if liveIP is None:
            liveIP = ''
        if livePort is None:
            livePort = 0
        self.__client.xmlrpc.logTo(logIP, logPort, liveIP, livePort)

        infoStr = self.__client.xmlrpc.getVersionInfo()
        self.__log.debug(("Version info: %(filename)s %(revision)s" +
                          " %(date)s %(time)s %(author)s %(release)s" +
                          " %(repo_rev)s") % get_version_info(infoStr))

    def monitor(self):
        "Return the monitoring value"
        return self.state()

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def order(self):
        return self.__cmdOrder

    def port(self):
        return self.__port

    def prepareSubrun(self, subrunNum):
        "Start marking events as bogus in preparation for subrun"
        try:
            return self.__client.xmlrpc.prepareSubrun(subrunNum)
        except Exception:
            self.__log.error(exc_string())
            return None

    def reset(self):
        "Reset component back to the idle state"
        self.__log.closeLog()
        return self.__client.xmlrpc.reset()

    def resetLogging(self):
        "Reset component back to the idle state"
        self.__log.resetLog()
        return self.__client.xmlrpc.resetLogging()

    def setOrder(self, orderNum):
        self.__cmdOrder = orderNum

    def startRun(self, runNum):
        "Start component processing DAQ data"
        try:
            return self.__client.xmlrpc.startRun(runNum)
        except Exception:
            self.__log.error(exc_string())
            return None

    def startSubrun(self, data):
        "Send subrun data to stringHubs"
        try:
            return self.__client.xmlrpc.startSubrun(data)
        except Exception:
            self.__log.error(exc_string())
            return None

    def state(self):
        "Get current state"
        try:
            state = self.__client.xmlrpc.getState()
        except socket.error:
            state = None
        except Exception:
            self.__log.error(exc_string())
            state = None

        if not state:
            self.__deadCount += 1
            if self.__deadCount < 3:
                state = DAQClient.STATE_MISSING
            else:
                state = DAQClient.STATE_DEAD

        return state

    def stopRun(self):
        "Stop component processing DAQ data"
        try:
            return self.__client.xmlrpc.stopRun()
        except Exception:
            self.__log.error(exc_string())
            return None

class DAQPool(object):
    "Pool of DAQClients and RunSets"

    def __init__(self):
        "Create an empty pool"
        self.__pool = {}
        self.__sets = []

        super(DAQPool, self).__init__()

    def __buildRunset(self, nameList, compList, logger):
        """
        Internal method to build a runset from the specified list of
        component names, using the supplied 'compList' as a workspace
        for storing components removed from the pool
        """
        if len(compList) > 0:
            raise ValueError('Temporary component list must be empty')

        for name in nameList:
            # separate name and number
            #
            pound = name.rfind('#')
            if pound < 0:
                num = -1
            else:
                num = int(name[pound+1:])
                name = name[0:pound]

            if not self.__pool.has_key(name) or len(self.__pool[name]) == 0:
                raise ValueError('No "%s" components are available' % name)

            # find component in pool
            #
            comp = None
            for c in self.__pool[name]:
                if num < 0 or c.num() == num:
                    self.remove(c)
                    comp = c
                    break
            if not comp:
                raise ValueError('Component "%s#%d" is not available' %
                                 (name, num))

            # add component to temporary list
            #
            compList.append(comp)

        # make sure I/O channels match up
        #
        connMap = DAQPool.buildConnectionMap(compList)

        # connect all components
        #
        errMsg = None
        for c in compList:
            if not connMap.has_key(c):
                rtnVal = c.connect()
            else:
                rtnVal = c.connect(connMap[c])

        chkList = compList[:]
        while len(chkList) > 0:
            for c in chkList:
                state = c.state()
                if state == 'connected':
                    chkList.remove(c)
                elif state != 'connecting':
                    if not errMsg:
                        errMsg = 'Connect failed for %s (%s)' % \
                            (c.fullName(), rtnVal)
                    else:
                        errMsg += ', %s (%s)' % (c.fullName(), rtnVal)
            sleep(1)

        if errMsg:
            raise ValueError(errMsg)

        self.setOrder(compList, connMap, logger)

        return None

    def add(self, comp):
        "Add the component to the config server's pool"
        if not self.__pool.has_key(comp.name()):
            self.__pool[comp.name()] = []
        self.__pool[comp.name()].append(comp)

    def buildConnectionMap(cls, compList):
        "Validate and fill the map of connections for each component"
        connDict = {}

        for comp in compList:
            for n in comp.connectors():
                if not connDict.has_key(n.type):
                    connDict[n.type] = ConnTypeEntry(n.type)
                connDict[n.type].add(n, comp)

        connMap = {}

        for k in connDict:
            connDict[k].buildConnectionMap(connMap)

        return connMap

    buildConnectionMap = classmethod(buildConnectionMap)

    def components(self):
        compList = []
        for k in self.__pool:
            for c in self.__pool[k]:
                compList.append(c)

        for c in compList:
            yield c

    def findRunset(self, id):
        "Find the runset with the specified ID"
        runset = None
        for s in self.__sets:
            if s.id() == id:
                runset = s
                break
        return runset

    def listRunsetIDs(self):
        "List active runset IDs"
        ids = []
        for s in self.__sets:
            ids.append(s.id())
        return ids

    def makeRunset(self, nameList, logger):
        "Build a runset from the specified list of component names"
        compList = []
        setAdded = False
        try:
            try:
                # __buildRunset fills 'compList' with the specified components
                #
                self.__buildRunset(nameList, compList, logger)
                runSet = RunSet(compList, logger)
                self.__sets.append(runSet)
                setAdded = True
            except Exception:
                runSet = None
                raise
        finally:
            if not setAdded:
                for c in compList:
                    c.reset()
                    self.add(c)
                runSet = None

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

    def numComponents(self):
        tot = 0
        for binName in self.__pool:
            tot += len(self.__pool[binName])
        return tot

    def numSets(self):
        return len(self.__sets)

    def numUnused(self):
        return len(self.__pool)

    def remove(self, comp):
        "Remove a component from the pool"
        if self.__pool.has_key(comp.name()):
            self.__pool[comp.name()].remove(comp)
            if len(self.__pool[comp.name()]) == 0:
                del self.__pool[comp.name()]

        return comp

    def returnRunset(self, s):
        "Return runset components to the pool"
        self.__sets.remove(s)
        s.returnComponents(self)
        s.destroy()

    def runset(self, num):
        return self.__sets[num]

    def setOrder(self, compList, connMap, logger):
        "set the order in which components are started/stopped"

        # build initial lists of source components
        #
        allComps = {}
        curLevel = []
        for c in compList:
            # complain if component has already been added
            #
            if allComps.has_key(c):
                print >>sys.stderr, 'Found multiple instances of %s' % str(c)
                continue

            # clear order
            #
            c.setOrder(None)

            # add component to the list
            #
            allComps[c] = 1

            # if component is a source, save it to the initial list
            #
            if c.isSource():
                curLevel.append(c)

        if len(curLevel) == 0:
            raise Exception("No sources found")

        # walk through detector, setting order number for each component
        #
        level = 1
        while len(allComps) > 0 and len(curLevel) > 0:
            tmp = {}
            for c in curLevel:

                # if we've already ordered this component, skip it
                #
                if not allComps.has_key(c):
                    continue

                del allComps[c]

                c.setOrder(level)

                if not connMap.has_key(c):
                    if c.isSource():
                        print >>sys.stderr, 'No connection map entry for %s' % \
                            str(c)
                else:
                    for m in connMap[c]:
                        # XXX hack -- ignore source->eventBuilder links
                        if not c.isSource() or not m.comp.isBuilder():
                            tmp[m.comp] = 1

            curLevel = tmp.keys()
            level += 1

        if len(allComps) > 0:
            errStr = 'Unordered:'
            for c in allComps:
                errStr += ' ' + str(c)
            logger.error(errStr)

        for c in compList:
            failStr = None
            if not c.order():
                if not failStr:
                    failStr = 'No order set for ' + str(c)
                else:
                    failStr += ', ' + str(c)
            if failStr:
                raise ValueError(failStr)

class ThreadedRPCServer(ThreadingMixIn, RPCServer):
    pass

class CnCServer(DAQPool):
    "Command and Control Server"

    DEFAULT_LOG_LEVEL = 'info'

    def __init__(self, name="GenericServer", logIP=None, logPort=None,
                 liveIP=None, livePort=None, testOnly=False, quiet=False):
        "Create a DAQ command and configuration server"
        self.__name = name
        self.__versionInfo = get_version_info(SVN_ID)

        self.__id = int(time())

        super(CnCServer, self).__init__()

        self.__log = self.createCnCLogger(quiet=(testOnly or quiet))

        if (logIP is not None and logPort is not None) or \
                (liveIP is not None and livePort is not None):
            self.__log.openLog(logIP, logPort, liveIP, livePort)

        if testOnly:
            self.__server = None
        else:
            while True:
                try:
                    # CnCServer needs to be made thread-safe
                    # before we can thread the XML-RPC server
                    #
                    #self.__server = ThreadedRPCServer(DAQPort.CNCSERVER)
                    self.__server = RPCServer(DAQPort.CNCSERVER)
                    break
                except socket.error, e:
                    self.__log.error("Couldn't create server socket: %s" % e)
                    raise SystemExit

        if self.__server:
            self.__server.register_function(self.rpc_close_log)
            self.__server.register_function(self.rpc_get_num_components)
            self.__server.register_function(self.rpc_list_components)
            self.__server.register_function(self.rpc_log_to)
            self.__server.register_function(self.rpc_num_sets)
            self.__server.register_function(self.rpc_ping)
            self.__server.register_function(self.rpc_register_component)
            self.__server.register_function(self.rpc_runset_bothlog_to)
            self.__server.register_function(self.rpc_runset_break)
            self.__server.register_function(self.rpc_runset_configure)
            self.__server.register_function(self.rpc_runset_events)
            self.__server.register_function(self.rpc_runset_list)
            self.__server.register_function(self.rpc_runset_listIDs)
            self.__server.register_function(self.rpc_runset_livelog_to)
            self.__server.register_function(self.rpc_runset_log_to)
            self.__server.register_function(self.rpc_runset_log_to_default)
            self.__server.register_function(self.rpc_runset_make)
            self.__server.register_function(self.rpc_runset_start_run)
            self.__server.register_function(self.rpc_runset_status)
            self.__server.register_function(self.rpc_runset_stop_run)
            self.__server.register_function(self.rpc_runset_subrun)
            self.__server.register_function(self.rpc_show_components)

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

    def closeServer(self):
        self.__server.server_close()
        self.__log.closeFinal()
        for c in self.components():
            c.close()

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        "overrideable method used for testing"
        return DAQClient(name, num, host, port, mbeanPort, connectors,
                         self.__log.isQuiet())

    def createCnCLogger(self, quiet):
        return CnCLogger(None, quiet)

    def monitorLoop(self):
        "Monitor components to ensure they're still alive"
        new = True
        lastCount = 0
        while True:
            try:
                count = self.monitorClients()
            except Exception:
                self.__log.error(exc_string())
                count = lastCount

            new = (lastCount != count)
            if new:
                print "%d bins, %d comps" % (self.numUnused(), count)

            lastCount = count
            sleep(1)

    def name(self):
        return self.__name

    def rpc_close_log(self):
        "close log file (and possibly roll back to previous log file)"
        self.__log.closeLog()
        return 1

    def rpc_get_num_components(self):
        "return number of components currently registered"
        return self.numComponents()

    def rpc_list_components(self):
        "list unused components"
        s = []
        for c in self.components():
            try:
                state = c.state()
            except Exception:
                state = DAQClient.STATE_DEAD

            s.append(c.list())

        return s

    def rpc_log_to(self, logHost, logPort, liveHost, livePort):
        "called by DAQLog object to tell us what UDP port to log to"
        if logHost is not None and len(logHost) == 0:
            logHost = None
        if logPort is not None and logPort == 0:
            logPort = None
        if liveHost is not None and len(liveHost) == 0:
            liveHost = None
        if livePort is not None and livePort == 0:
            livePort = None
        self.__log.openLog(logHost, logPort, liveHost, livePort)
        return 1

    def rpc_num_sets(self):
        "show existing run sets"
        return self.numSets()

    def rpc_ping(self):
        "remote method for far end to confirm that server is still alive"
        return self.__id

    def rpc_register_component(self, name, num, host, port, mbeanPort,
                               connArray):
        "register a component with the server"
        connectors = []
        for d in connArray:
            connectors.append(Connector(d[0], d[1], d[2]))

        client = self.createClient(name, num, host, port, mbeanPort,
                                   connectors)
        self.__log.info("Got registration for %s" % str(client))

        self.add(client)

        logIP = self.__getHostAddress(self.__log.logHost())

        logPort = self.__log.logPort()
        if logPort is None:
            logPort = 0

        liveIP = self.__getHostAddress(self.__log.liveHost())

        livePort = self.__log.livePort()
        if livePort is None:
            livePort = 0

        return [client.id(), logIP, logPort, liveIP, livePort, self.__id]

    def rpc_runset_bothlog_to(self, id, liveIP, livePort, pdaqIP, pdaqList):
        "configure I3Live logging for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#%d' % id

        leftOver = runSet.configureBothLogging(liveIP, livePort,
                                               pdaqIP, pdaqList)

        if len(leftOver) > 0:
            errMsg = 'Could not configure logging for %d components:' % \
                len(leftOver)
            for l in leftOver:
                errMsg += ' %s#%d' % (l[0], l[1])

            self.__log.error(errMsg)

        return "OK"

    def rpc_runset_break(self, id):
        "break up the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        self.returnRunset(runSet)

        return "OK"

    def rpc_runset_configure(self, id, globalConfigName=None):
        "configure the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        runSet.configure(globalConfigName)

        return "OK"

    def rpc_runset_events(self, id, subrunNumber):
        """
        get the number of events for the specified subrun
        from the specified runset
        """
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        return runSet.events(subrunNumber)

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
            raise ValueError('Could not find runset#%d' % id)

        return runSet.list()

    def rpc_runset_livelog_to(self, id, logIP, logPort):
        "configure I3Live logging for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError, 'Could not find runset#%d' % id

        runSet.configureLiveLogging(logIP, logPort)

        return "OK"

    def rpc_runset_log_to(self, id, logIP, logList):
        "configure logging for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        leftOver = runSet.configureLogging(logIP, logList)

        if len(leftOver) > 0:
            errMsg = 'Could not configure logging for %d components:' % \
                len(leftOver)
            for l in leftOver:
                errMsg += ' %s#%d' % (l[0], l[1])

            self.__log.error(errMsg)

        return "OK"

    def rpc_runset_log_to_default(self, id):
        "reset logging for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        self.__log.resetLog()

        runSet.resetLogging()

        return "OK"

    def rpc_runset_make(self, nameList):
        "build a runset using the specified components"
        try:
            runSet = self.makeRunset(nameList, self.__log)
        except:
            self.__log.error(exc_string())
            runSet = None

        if not runSet:
            return -1

        self.__log.info("Built runset with the following components:\n" +
                        runSet.componentListStr())
        return runSet.id()

    def rpc_runset_start_run(self, id, runNum):
        "start a run with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        runSet.startRun(runNum)

        return "OK"

    def rpc_runset_status(self, id):
        "get run status for the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        setStat = runSet.status()
        for c in setStat.keys():
            self.__log.info(str(c) + ' ' + str(c.state()))

        return "OK"

    def rpc_runset_stop_run(self, id):
        "stop a run with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        runSet.stopRun()

        self.__log.resetLog()
        runSet.resetLogging()

        return "OK"

    def rpc_runset_subrun(self, id, subrunId, subrunData):
        "start a subrun with the specified runset"
        runSet = self.findRunset(id)

        if not runSet:
            raise ValueError('Could not find runset#%d' % id)

        runSet.subrun(subrunId, subrunData)

        return "OK"

    def rpc_show_components(self):
        "show unused components and their current states"
        s = []
        for c in self.components():
            try:
                state = c.state()
            except Exception:
                state = DAQClient.STATE_DEAD

            s.append(str(c) + ' ' + str(state))
        return s

    def run(self):
        "Server loop"
        self.serve(self.monitorLoop)

    def serve(self, handler):
        "Start a server"
        self.__log.info("I'm server %s running on port %d" %
                        (self.__name, DAQPort.CNCSERVER))
        self.__log.info(("%(filename)s %(revision)s %(date)s %(time)s" +
                         " %(author)s %(release)s %(repo_rev)s") %
                        self.__versionInfo)
        threading.Thread(target=handler, args=()).start()
        self.__server.serve_forever()

if __name__ == "__main__":
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)
    p.add_option("-d", "--daemon",  action="store_true", dest="daemon")
    p.add_option("-k", "--kill",    action="store_true", dest="kill")
    p.add_option("-l", "--log",     action="store",      dest="log",
                 type="string")
    p.add_option("-L", "--liveLog", action="store",      dest="liveLog",
                 type="string")
    p.set_defaults(kill     = False,
                   liveLog  = None,
                   log      = None,
                   nodaemon = False)
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

    if opt.log is None:
        logIP = None
        logPort = None
    else:
        colon = opt.log.find(':')
        if colon < 0:
            print "ERROR: Bad log argument '" + opt.log + "'"
            raise SystemExit

        logIP = opt.log[:colon]
        logPort = int(opt.log[colon+1:])

    if opt.liveLog is None:
        liveIP = None
        livePort = None
    else:
        colon = opt.liveLog.find(':')
        if colon < 0:
            print "ERROR: Bad liveLog argument '" + opt.liveLog + "'"
            raise SystemExit

        liveIP = opt.liveLog[:colon]
        livePort = int(opt.liveLog[colon+1:])

    if opt.daemon: Daemon.Daemon().Daemonize()

    cnc = CnCServer("CnCServer", logIP=logIP, logPort=logPort, liveIP=liveIP,
                    livePort=livePort, testOnly=False)
    try:
        cnc.run()
    except KeyboardInterrupt:
        print "Interrupted."
        raise SystemExit
