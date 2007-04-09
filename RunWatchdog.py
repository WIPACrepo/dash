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

class ThresholdWatcher(object):
    def __init__(self, comp, beanName, fieldName, threshold, lessThan):
        self.comp = comp
        self.beanName = beanName
        self.fieldName = fieldName
        self.threshold = threshold
        self.lessThan = lessThan

        if self.lessThan:
            self.opDescription = 'below'
        else:
            self.opDescription = 'above'

    def __str__(self):
        return self.comp + ' ' + self.beanName + '.' + self.fieldName + ' ' + \
            self.opDescription + ' ' + str(self.threshold)

    def check(self, newValue):
        if type(newValue) != type(self.threshold):
            raise Exception, 'Threshold value for ' + str(self) + ' is ' + \
                str(type(self.threshold)) + ', new value is ' + \
                str(type(newValue))
        elif type(newValue) == list:
            raise Exception, 'ThresholdValue does not support lists'
        elif self.compare(self.threshold, newValue):
            return False

        return True

    def compare(self, threshold, value):
        if self.lessThan:
            return value < threshold
        else:
            return value > threshold

    def unhealthyString(self, value):
        return str(self) + ' (value=' + str(value) + ')'

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

    def unhealthyString(self, value):
        return str(self) + ' not changing from ' + str(self.prevValue)

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
        self.thresholdFields = {}

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

    def addThresholdValue(self, beanName, fieldName, threshold, lessThan=True):
        """
        Watchdog triggers if field value drops below the threshold value
        (or, when lessThan==False, if value rises above the threshold 
        """

        if beanName not in self.beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.name)

        if fieldName not in self.beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.name)

        if beanName not in self.thresholdFields:
            self.thresholdFields[beanName] = []

        tw = ThresholdWatcher(self.name, beanName, fieldName, threshold,
                              lessThan)
        self.thresholdFields[beanName].append(tw)

    def checkList(self, list, now):
        unhealthy = []
        for b in list:
            badList = self.checkValues(list[b])
            if badList is not None:
                unhealthy += badList

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def checkValues(self, watchList):
        unhealthy = []
        if len(watchList) == 1:
            val = self.client.mbean.get(watchList[0].beanName,
                                        watchList[0].fieldName)
            if not watchList[0].check(val):
                unhealthy.append(watchList[0].unhealthyString(val))
        else:
            fldList = []
            for f in watchList:
                fldList.append(f.fieldName)

            valMap = self.client.mbean.getAttributes(watchList[0].beanName,
                                                     fldList)
            for i in range(0,len(fldList)):
                val = valMap[fldList[i]]
                if not watchList[i].check(val):
                    unhealthy.append(watchList[i].unhealthyString(val))

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
                        if self.contains(shortNameOf, 'eventBuilder'):
                            cw.addInputValue('eventBuilder', 'sender',
                                             'NumReadoutRequestsReceived')
                            cw.addOutputValue('eventBuilder', 'sender',
                                              'NumReadoutsSent')
                        self.stringHubs.append(cw)
                    elif shortNameOf[c] == 'inIceTrigger':
                        if self.contains(shortNameOf, 'stringHub'):
                            cw.addInputValue('stringHub', 'stringHit',
                                             'RecordsReceived')
                        if self.contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        iniceTrigger = cw
                    elif shortNameOf[c] == 'iceTopTrigger':
                        if self.contains(shortNameOf, 'stringHub'):
                            cw.addInputValue('stringHub', 'stringHit',
                                             'RecordsReceived')
                        if self.contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        icetopTrigger = cw
                    elif shortNameOf[c] == 'amandaTrigger':
                        if self.contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        amandaTrigger = cw
                    elif shortNameOf[c] == 'globalTrigger':
                        if self.contains(shortNameOf, 'inIceTrigger'):
                            cw.addInputValue('inIceTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.contains(shortNameOf, 'iceTopTrigger'):
                            cw.addInputValue('iceTopTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.contains(shortNameOf, 'amandaTrigger'):
                            cw.addInputValue('amandaTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.contains(shortNameOf, 'eventBuilder'):
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
                        cw.addThresholdValue('backEnd', 'DiskAvailable', 1024)
                        eventBuilder = cw
                    elif shortNameOf[c] == 'secondaryBuilders':
                        cw.addThresholdValue('snBuilder', 'DiskAvailable', 1024)
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

    def appendError(errMsg, compType, compErr):
        if errMsg is None:
            errMsg = "** Run watchdog reports"
        else:
            errMsg += "\nand"
        errMsg += " " + compType + " components:\n" + compErr

        return errMsg

    appendError = staticmethod(appendError)

    def contains(self, nameList, compName):
        for n in nameList:
            if n == compName:
                return True

        return False

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

    def checkComp(self, comp, starved, stagnant, threshold):
        isProblem = False
        try:
            badList = comp.checkList(comp.inputFields, self.tlast)
            if badList is not None:
                starved += badList
                isProblem = True
        except Exception, e:
            self.logmsg(str(comp) + ' inputs: ' + exc_string())

        if not isProblem:
            try:
                badList = comp.checkList(comp.outputFields, self.tlast)
                if badList is not None:
                    stagnant += badList
                    isProblem = True
            except Exception, e:
                self.logmsg(str(comp) + ' outputs: ' + exc_string())

            if not isProblem:
                try:
                    badList = comp.checkList(comp.thresholdFields, self.tlast)
                    if badList is not None:
                        threshold += badList
                        isProblem = True
                except Exception, e:
                    self.logmsg(str(comp) + ' thresholds: ' + exc_string())

    def doWatch(self):
        self.tlast = datetime.datetime.now()
        starved = []
        stagnant = []
        threshold = []

        # checks can raise exception if far end is dead
        for comp in self.stringHubs:
            self.checkComp(comp, starved, stagnant, threshold)

        for comp in self.soloComps:
            self.checkComp(comp, starved, stagnant, threshold)

        errMsg = None

        if len(stagnant) > 0:
            errMsg = RunWatchdog.appendError(errMsg, 'stagnant',
                                             self.joinAll(stagnant))

        if len(starved) > 0:
            errMsg = RunWatchdog.appendError(errMsg, 'starving',
                                             self.joinAll(starved))

        if len(threshold) > 0:
            errMsg = RunWatchdog.appendError(errMsg, 'threshold',
                                             self.joinAll(threshold))

        healthy = True
        if errMsg is not None:
            self.logmsg(errMsg)
            healthy = False
        #else:
        #    self.logmsg('** Run watchdog reports all components are healthy')

        return healthy

    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.log: self.log.dashLog(m)
     
