#!/usr/bin/env python

#!/usr/bin/env python

#
# DAQ Monitoring object for high level DAQRun scrupt
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started December, 2006

from DAQLog import *
from DAQRPC import RPCClient
import datetime
from exc_string import *

class ValueWatcher(object):
    NUM_UNCHANGED = 3

    def __init__(self, fromComp, toComp, beanName, fieldName):
        self.fromComp = fromComp
        self.toComp = toComp
        self.beanName = beanName
        self.fieldName = fieldName
        self.prevValue = None
        self.unchanged = 0

    def __str__(self):
        return self.fromComp + '->' + self.toComp + ' ' + self.beanName + \
            '.' + self.fieldName

    def check(self, newValue):
        if self.prevValue is None:
            self.prevValue = newValue
        elif type(newValue) != type(self.prevValue):
            raise Exception, 'Previous value for ' + str(self) + ' was ' + \
                str(type(self.prevValue)) + ', new value is ' + \
                str(type(newValue))
        elif type(newValue) != list:
            if self.compare(self.prevValue, newValue):
                self.unchanged += 1
                if self.unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise Exception, str(self) + ' is not changing'
            else:
                self.unchanged = 0
                self.prevValue = newValue
        elif len(newValue) != len(self.prevValue):
            raise Exception, 'Previous ' + str(self) + ' list had ' + \
                str(len(self.prevValue)) + ' entries, new list has ' + \
                str(len(newValue))
        else:
            tmpStag = False
            for i in range(0,len(newValue)):
                if self.compare(self.prevValue[i], newValue[i]):
                    tmpStag = True
                else:
                    self.prevValue[i] = newValue[i]
            if tmpStag:
                self.unchanged += 1
                if self.unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise Exception, 'At least one ' + str(self) + \
                        ' value is not changing'

        return self.unchanged == 0

    def compare(self, oldValue, newValue):
        if newValue < oldValue:
            raise Exception, str(self) + ' DECREASED (' + str(oldValue) + \
                '->' + str(newValue) + ')'

        return newValue == oldValue

class WatchData(object):
    def __init__(self, id, compType, compNum, addr, port):
        self.id = id

        if compNum == 0:
            numStr = ''
        else:
            numStr = '#' + str(compNum)
        self.name = compType + numStr

        self.client = RPCClient(addr, port)
        self.beanFields = {}
        self.beanList = self.client.mbean.listMBeans()
        for bean in self.beanList:
            self.beanFields[bean] = self.client.mbean.listGetters(bean)
        self.inputFields = {}
        self.outputFields = {}

    def __str__(self):
        return '#' + str(self.id) + ': ' + self.name

    def addInputValue(self, otherType, beanName, fieldName):
        if beanName not in self.beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.name)

        if fieldName not in self.beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.name)

        if beanName not in self.inputFields:
            self.inputFields[beanName] = []

        vw = ValueWatcher(otherType, self.name, beanName, fieldName)
        self.inputFields[beanName].append(vw)

    def addOutputValue(self, otherType, beanName, fieldName):
        if beanName not in self.beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.name)

        if fieldName not in self.beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.name)

        if beanName not in self.outputFields:
            self.outputFields[beanName] = []

        vw = ValueWatcher(self.name, otherType, beanName, fieldName)
        self.outputFields[beanName].append(vw)

    def checkValues(self, watchList):
        unhealthy = []
        if len(watchList) == 1:
            val = self.client.mbean.get(watchList[0].beanName,
                                        watchList[0].fieldName)
            prevVal = watchList[0].prevValue
            if not watchList[0].check(val):
                unhealthy.append(str(watchList[0]) + ' (' + str(prevVal) +
                                 '->' + str(val) + ')')
        else:
            fldList = []
            for f in watchList:
                fldList.append(f.fieldName)

            valList = self.client.mbean.getList(watchList[0].beanName, fldList)
            for i in range(0,len(fldList)):
                prevVal = watchList[i].prevValue
                if not watchList[i].check(valList[i]):
                    unhealthy.append(str(watchList[i]) + ' (' + str(prevVal) +
                                     '->' + str(valList[i]) + ')')

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def checkInputs(self, now):
        unhealthy = []
        for b in self.inputFields:
            badList = self.checkValues(self.inputFields[b])
            if badList is not None:
                unhealthy += badList

        if len(unhealthy) == 0:
            return None

        return unhealthy


    def checkOutputs(self, now):
        unhealthy = []
        for b in self.outputFields:
            badList = self.checkValues(self.outputFields[b])
            if badList is not None:
                unhealthy += badList

        if len(unhealthy) == 0:
            return None

        return unhealthy

class BeanFieldNotFoundException(Exception): pass

class RunWatchdog(object):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof, rpcAddrOf, mbeanPortOf):
        self.log         = daqLog
        self.path        = daqLog.logPath
        self.interval    = interval
        self.tstart      = datetime.datetime.now()
        self.tlast       = None
        self.IDs         = IDs
        self.stringHubs  = []
        self.soloComps   = []

        iniceTrigger  = None
        icetopTrigger  = None
        amandaTrigger  = None
        globalTrigger   = None
        eventBuilder   = None
        secondaryBuilders   = None
        for c in self.IDs:
            if mbeanPortOf[c] > 0:
                try:
                    cw = WatchData(c, shortNameOf[c], daqIDof[c],
                                   rpcAddrOf[c], mbeanPortOf[c])
                    if shortNameOf[c] == 'stringHub':
                        cw.addInputValue('dom', 'sender', 'NumHitsReceived')
                        cw.addInputValue('eventBuilder', 'sender',
                                         'NumReadoutRequestsReceived')
                        cw.addOutputValue('eventBuilder', 'sender',
                                          'NumReadoutsSent')
                        self.stringHubs.append(cw)
                    elif shortNameOf[c] == 'inIceTrigger':
                        cw.addInputValue('stringHub', 'stringHit',
                                         'RecordsReceived')
                        cw.addOutputValue('globalTrigger', 'trigger',
                                          'RecordsSent')
                        iniceTrigger = cw
                    elif shortNameOf[c] == 'iceTopTrigger':
                        cw.addInputValue('stringHub', 'stringHit',
                                         'RecordsReceived')
                        cw.addOutputValue('globalTrigger', 'trigger',
                                          'RecordsSent')
                        icetopTrigger = cw
                    elif shortNameOf[c] == 'amandaTrigger':
                        cw.addOutputValue('globalTrigger', 'trigger',
                                          'RecordsSent')
                        amandaTrigger = cw
                    elif shortNameOf[c] == 'globalTrigger':
                        cw.addInputValue('triggers', 'trigger',
                                         'RecordsReceived')
                        cw.addOutputValue('eventBuilder', 'glblTrig',
                                          'RecordsSent')
                        globalTrigger = cw
                    elif shortNameOf[c] == 'eventBuilder':
                        cw.addInputValue('globalTrigger', 'backEnd',
                                         'NumTriggerRequestsReceived');
                        cw.addInputValue('stringHub', 'backEnd',
                                         'NumReadoutsReceived');
                        cw.addOutputValue('dispatch', 'backEnd',
                                          'NumEventsSent');
                        eventBuilder = cw
                    elif shortNameOf[c] == 'secondaryBuilders':
                        secondaryBuilders = cw
                    else:
                        raise Exception, 'Unknown component type ' + \
                            shortNameOf[c]
                except Exception, e:
                    self.logmsg(('Couldn''t create watcher (%s#%d)' +
                                 ' for component %d: %s') %
                                (shortNameOf[c], daqIDof[c], c, exc_string()))

        # soloComps is filled here so we can determine the order
        # of components in the list
        #
        if iniceTrigger: self.soloComps.append(iniceTrigger)
        if icetopTrigger: self.soloComps.append(icetopTrigger)
        if amandaTrigger: self.soloComps.append(amandaTrigger)
        if globalTrigger: self.soloComps.append(globalTrigger)
        if eventBuilder: self.soloComps.append(eventBuilder)
        if secondaryBuilders: self.soloComps.append(secondaryBuilders)

    def timeToWatch(self):
        if not self.tlast: return True
        now = datetime.datetime.now()
        dt  = now - self.tlast
        if dt.seconds+dt.microseconds*1.E-6 > self.interval: return True
        return False
    
    def joinAll(self, comps):
        compStr = None
        for c in comps:
            if compStr is None:
                compStr = '    ' + str(c)
            else:
                compStr += "\n    " + str(c)
        return compStr

    def doWatch(self):
        now = datetime.datetime.now()
        self.tlast = now
        healthy = True
        starved = []
        stagnant = []

        # checkInputs/checkOutputs can raise exception if far end is dead
        for comp in self.stringHubs:
            isStarved = False
            try:
                badList = comp.checkInputs(now)
                if badList is not None:
                    starved += badList
                    isStarved = True
            except Exception, e:
                self.logmsg(str(comp) + ' inputs: ' + exc_string())

            if not isStarved:
                try:
                    badList = comp.checkOutputs(now)
                    if badList is not None:
                        stagnant += badList
                except Exception, e:
                    self.logmsg(str(comp) + ' outinputs: ' + exc_string())

        for comp in self.soloComps:
            isStarved = False
            try:
                badList = comp.checkInputs(now)
                if badList is not None:
                    starved += badList
                    isStarved = True
            except Exception, e:
                self.logmsg(str(comp) + ': ' + exc_string())
            if not isStarved:
                try:
                    badList = comp.checkOutputs(now)
                    if badList is not None:
                        stagnant += badList
                except Exception, e:
                    self.logmsg(str(comp) + ': ' + exc_string())

        noOutStr = None
        if len(stagnant) > 0:
            noOutStr = self.joinAll(stagnant)

        noInStr = None
        if len(starved) > 0:
            noInStr = self.joinAll(starved)

        if noOutStr:
            if noInStr:
                self.logmsg("** Run watchdog reports stagnant components:\n" +
                            noOutStr + "\nand starved components:\n" + noInStr)
                healthy = False
            else:
                self.logmsg("** Run watchdog reports stagnant components:\n" +
                            noOutStr)
                healthy = False
        elif noInStr:
            self.logmsg("** Run watchdog reports starving components:\n" +
                        noInStr)
            healthy = False
        #else:
            # self.logmsg('** Run watchdog reports all components are healthy')

        return healthy

    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log: self.log.dashLog(m)
     
