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
    NUM_UNCHANGED = 10

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
        self.compType = compType
        self.compNum = compNum
        self.client = RPCClient(addr, port)
        self.beanFields = {}
        self.beanList = self.client.mbean.listMBeans()
        for bean in self.beanList:
            self.beanFields[bean] = self.client.mbean.listGetters(bean)
        self.inputFields = {}
        self.outputFields = {}

    def __str__(self):
        if self.compNum == 0:
            numStr = ''
        else:
            numStr = '#' + str(self.compNum)

        return '#' + str(self.id) + ': ' + self.compType + numStr

    def addInputValue(self, otherType, beanName, fieldName):
        if beanName not in self.beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.compType)

        if fieldName not in self.beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.compType)

        if beanName not in self.inputFields:
            self.inputFields[beanName] = []

        vw = ValueWatcher(otherType, self.compType, beanName, fieldName)
        self.inputFields[beanName].append(vw)

    def addOutputValue(self, otherType, beanName, fieldName):
        if beanName not in self.beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.compType)

        if fieldName not in self.beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.compType)

        if beanName not in self.outputFields:
            self.outputFields[beanName] = []

        vw = ValueWatcher(self.compType, otherType, beanName, fieldName)
        self.outputFields[beanName].append(vw)

    def checkValues(self, watchList):
        if len(watchList) == 1:
            val = self.client.mbean.get(watchList[0].beanName,
                                        watchList[0].fieldName)
            healthy = watchList[0].check(val)
        else:
            healthy = True

            fldList = []
            for f in watchList:
                fldList.append(f.fieldName)

            valList = self.client.mbean.getList(watchList[0].beanName, fldList)
            for i in range(0,len(fldList)):
                if not watchList[i].check(valList[i]):
                    healthy = False

        return healthy

    def checkInputs(self, now):
        healthy = True
        for b in self.inputFields:
            if not self.checkValues(self.inputFields[b]):
                healthy = False
        return healthy

    def checkOutputs(self, now):
        healthy = True
        for b in self.outputFields:
            if not self.checkValues(self.outputFields[b]):
                healthy = False
        return healthy

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
                    elif shortNameOf[c] == 'icetopTrigger':
                        cw.addInputValue('stringHub', 'stringHit',
                                         'RecordsReceived')
                        cw.addOutputValue('globalTrigger', 'trigger',
                                          'RecordsSent')
                        icetopTrigger = cw
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
                    self.logmsg('Couldn''t create watcher (%s#%d)' +
                                ' for component %d: %s' %
                                (shortNameOf[c], daqIDof[c], c, exc_string()))

        # soloComps is filled here so we can determine the order
        # of components in the list
        #
        if iniceTrigger: self.soloComps.append(iniceTrigger)
        if icetopTrigger: self.soloComps.append(icetopTrigger)
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
        # XXX this should use some sort of 'join' method
        compStr = None
        for c in comps:
            if compStr is None:
                compStr = str(c)
            else:
                compStr += ', ' + str(c)
        return compStr

    def doWatch(self):
        now = datetime.datetime.now()
        self.tlast = now

        starved = []
        stagnant = []

        # checkInputs/checkOutputs can raise exception if far end is dead
        for comp in self.stringHubs:
            isStarved = False
            try:
                if not comp.checkInputs(now):
                    starved.append(comp)
                    isStarved = True
            except Exception, e:
                self.logmsg(str(comp) + ' inputs: ' + exc_string())

            if not isStarved:
                try:
                    if not comp.checkOutputs(now):
                        stagnant.append(comp)
                except Exception, e:
                    self.logmsg(str(comp) + ' outinputs: ' + exc_string())

        for comp in self.soloComps:
            isStarved = False
            try:
                if not comp.checkInputs(now):
                    starved.append(comp)
                    isStarved = True
            except Exception, e:
                self.logmsg(str(comp) + ': ' + exc_string())
            if not isStarved:
                try:
                    if not comp.checkOutputs(now):
                        stagnant.append(comp)
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
                self.logmsg('** Run watchdog reports stagnant components: ' +
                            noOutStr + ' and starved components: ' + noInStr)
            else:
                self.logmsg('** Run watchdog reports stagnant components: ' +
                            noOutStr)
        elif noInStr:
            self.logmsg('** Run watchdog reports starving components: ' +
                        noInStr)
        else:
            self.logmsg('** Run watchdog reports all components are healthy')

    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log: self.log.dashLog(m)
     
