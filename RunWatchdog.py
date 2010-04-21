#!/usr/bin/env python

#!/usr/bin/env python

#
# DAQ Monitoring object for high level DAQRun scrupt
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started December, 2006

import datetime, threading
from DAQRPC import RPCClient
from IntervalTimer import IntervalTimer
from DAQMoni import unFixValue

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class ThresholdWatcher(object):
    def __init__(self, comp, beanName, fieldName, threshold, lessThan):
        self.__comp = comp
        self.beanName = beanName
        self.fieldName = fieldName
        self.__threshold = threshold
        self.__lessThan = lessThan

        if self.__lessThan:
            self.opDescription = 'below'
        else:
            self.opDescription = 'above'

    def __str__(self):
        return '%s %s.%s %s %s' % \
            (self.__comp, self.beanName, self.fieldName,
             self.opDescription, str(self.__threshold))

    def __compare(self, threshold, value):
        if self.__lessThan:
            return value < threshold
        else:
            return value > threshold

    def check(self, newValue):
        if type(newValue) != type(self.__threshold):
            raise Exception('Threshold value for %s is %s, new value is %s' %
                            (str(self), str(type(self.__threshold)),
                             str(type(newValue))))
        elif type(newValue) == list:
            raise Exception('ThresholdValue does not support lists')
        elif self.__compare(self.__threshold, newValue):
            return False

        return True

    def unhealthyString(self, value):
        return '%s (value=%s)' % (str(self), str(value))

class ValueWatcher(object):
    NUM_UNCHANGED = 3

    def __init__(self, fromComp, toComp, beanName, fieldName):
        self.__fromComp = fromComp
        self.__toComp = toComp
        self.beanName = beanName
        self.fieldName = fieldName
        self.__prevValue = None
        self.__unchanged = 0

    def __str__(self):
        return '%s->%s %s.%s' % \
            (self.__fromComp, self.__toComp, self.beanName, self.fieldName)

    def __compare(self, oldValue, newValue):
        if newValue < oldValue:
            raise Exception('%s DECREASED (%s->%s)' %
                            (str(self), str(oldValue), str(newValue)))

        return newValue == oldValue

    def check(self, newValue):
        if self.__prevValue is None:
            if type(newValue) == list:
                self.__prevValue = newValue[:]
            else:
                self.__prevValue = newValue
        elif type(newValue) != type(self.__prevValue):
            if type(self.__prevValue) != list or \
                    type(newValue) != tuple or \
                    len(newValue) != 0:
                raise Exception(("Previous type for %s was %s (%s)," +
                                 " new type is %s (%s)") %
                                (str(self), str(type(self.__prevValue)),
                                str(self.__prevValue),
                                str(type(newValue)), str(newValue)))
        elif type(newValue) != list:
            if self.__compare(self.__prevValue, newValue):
                self.__unchanged += 1
                if self.__unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise Exception(str(self) + ' is not changing')
            else:
                self.__unchanged = 0
                self.__prevValue = newValue
        elif len(newValue) != len(self.__prevValue):
            raise Exception('Previous %s list had %d entries, new list has %d' %
                            (str(self), len(self.__prevValue), len(newValue)))
        else:
            tmpStag = False
            for i in range(0, len(newValue)):
                if self.__compare(self.__prevValue[i], newValue[i]):
                    tmpStag = True
                else:
                    self.__prevValue[i] = newValue[i]
            if not tmpStag:
                self.__unchanged = 0
            else:
                self.__unchanged += 1
                if self.__unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise Exception('At least one %s value is not changing' %
                                    str(self))

        return self.__unchanged == 0

    def unhealthyString(self, value):
        return '%s not changing from %s' % (str(self), str(self.__prevValue))

class WatchData(object):
    def __init__(self, id, compType, compNum, addr, port):
        self.__id = id

        if compNum == 0 and not compType.lower().endswith('hub'):
            self.__name = compType
        else:
            self.__name = '%s#%d' % (compType, compNum)

        self.__client = self.getRPCClient(addr, port)
        self.__beanFields = {}
        self.__beanList = self.__client.mbean.listMBeans()
        for bean in self.__beanList:
            self.__beanFields[bean] = self.__client.mbean.listGetters(bean)
        self.inputFields = {}
        self.outputFields = {}
        self.thresholdFields = {}

    def __str__(self):
        return '#%d: %s' % (self.__id, self.__name)

    def __checkValues(self, watchList):
        unhealthy = []
        if len(watchList) == 1:
            val = unFixValue(self.__client.mbean.get(watchList[0].beanName,
                                                     watchList[0].fieldName))
            if not watchList[0].check(val):
                unhealthy.append(watchList[0].unhealthyString(val))
        else:
            fldList = []
            for f in watchList:
                fldList.append(f.fieldName)

            valMap = self.__client.mbean.getAttributes(watchList[0].beanName,
                                                       fldList)
            for i in range(0, len(fldList)):
                val = unFixValue(valMap[fldList[i]])
                if not watchList[i].check(val):
                    unhealthy.append(watchList[i].unhealthyString(val))

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def addInputValue(self, otherType, beanName, fieldName):
        if beanName not in self.__beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.__name)

        if fieldName not in self.__beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.__name)

        if beanName not in self.inputFields:
            self.inputFields[beanName] = []

        vw = ValueWatcher(otherType, self.__name, beanName, fieldName)
        self.inputFields[beanName].append(vw)

    def addOutputValue(self, otherType, beanName, fieldName):
        if beanName not in self.__beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.__name)

        if fieldName not in self.__beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.__name)

        if beanName not in self.outputFields:
            self.outputFields[beanName] = []

        vw = ValueWatcher(self.__name, otherType, beanName, fieldName)
        self.outputFields[beanName].append(vw)

    def addThresholdValue(self, beanName, fieldName, threshold, lessThan=True):
        """
        Watchdog triggers if field value drops below the threshold value
        (or, when lessThan==False, if value rises above the threshold
        """

        if beanName not in self.__beanList:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' for ' + self.__name)

        if fieldName not in self.__beanFields[beanName]:
            raise BeanFieldNotFoundException('Unknown MBean ' + beanName +
                                             ' field ' + fieldName +
                                             ' for ' + self.__name)

        if beanName not in self.thresholdFields:
            self.thresholdFields[beanName] = []

        tw = ThresholdWatcher(self.__name, beanName, fieldName, threshold,
                              lessThan)
        self.thresholdFields[beanName].append(tw)

    def checkList(self, inList):
        unhealthy = []
        for b in inList:
            badList = self.__checkValues(inList[b])
            if badList is not None:
                unhealthy += badList

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def getRPCClient(self, addr, port):
        return RPCClient(addr, port)

class BeanFieldNotFoundException(Exception): pass

class WatchThread(threading.Thread):
    def __init__(self, watchdog, log):
        self.__watchdog = watchdog
        self.__log = log

        self.done = False
        self.error = False
        self.healthy = False

        threading.Thread.__init__(self)

        self.setName('RunWatchdog')

    def run(self):
        try:
            self.healthy = self.__watchdog.realWatch()
            self.done = True
        except Exception:
            self.__log.error("Exception in run watchdog: %s" % exc_string())
            self.error = True

class RunWatchdog(IntervalTimer):
    IN_PROGRESS = 1
    NOT_RUNNING = 0
    CAUGHT_ERROR = -1
    UNHEALTHY = -2

    MAX_UNHEALTHY_COUNT = 3

    def __init__(self, daqLog, interval, components, quiet=False):
        self.__log            = daqLog
        self.__stringHubs     = []
        self.__soloComps      = []
        self.__thread         = None
        self.__quiet          = quiet
        self.__unHealthyCount = 0

        super(RunWatchdog, self).__init__(interval)

        iniceTrigger  = None
        simpleTrigger  = None
        icetopTrigger  = None
        amandaTrigger  = None
        globalTrigger   = None
        eventBuilder   = None
        secondaryBuilders   = None
        for c, comp in components.iteritems():
            if comp.mbeanPort() > 0:
                try:
                    cw = self.createData(c, comp.name(), comp.id(),
                                         comp.inetAddress(), comp.mbeanPort())
                    if comp.name() == 'stringHub' or \
                            comp.name() == 'replayHub':
                        cw.addInputValue('dom', 'sender', 'NumHitsReceived')
                        if self.__contains(components, 'eventBuilder'):
                            cw.addInputValue('eventBuilder', 'sender',
                                             'NumReadoutRequestsReceived')
                            cw.addOutputValue('eventBuilder', 'sender',
                                              'NumReadoutsSent')
                        self.__stringHubs.append(cw)
                    elif comp.name() == 'inIceTrigger':
                        hub = self.__findAnyHub(components)
                        if hub is not None:
                            cw.addInputValue(hub.name(), 'stringHit',
                                             'RecordsReceived')
                        if self.__contains(components, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        iniceTrigger = cw
                    elif comp.name() == 'simpleTrigger':
                        hub = self.__findAnyHub(components)
                        if hub is not None:
                            cw.addInputValue(hub.name(), 'stringHit',
                                             'RecordsReceived')
                        if self.__contains(components, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        iniceTrigger = cw
                    elif comp.name() == 'iceTopTrigger':
                        hub = self.__findAnyHub(components)
                        if hub is not None:
                            cw.addInputValue(hub.name(), 'icetopHit',
                                             'RecordsReceived')
                        if self.__contains(components, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        icetopTrigger = cw
                    elif comp.name() == 'amandaTrigger':
                        if self.__contains(components, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        amandaTrigger = cw
                    elif comp.name() == 'globalTrigger':
                        if self.__contains(components, 'inIceTrigger'):
                            cw.addInputValue('inIceTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(components, 'simpleTrigger'):
                            cw.addInputValue('simpleTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(components, 'iceTopTrigger'):
                            cw.addInputValue('iceTopTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(components, 'amandaTrigger'):
                            cw.addInputValue('amandaTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(components, 'eventBuilder'):
                            cw.addOutputValue('eventBuilder', 'glblTrig',
                                              'RecordsSent')
                        globalTrigger = cw
                    elif comp.name() == 'eventBuilder':
                        hub = self.__findAnyHub(components)
                        if hub is not None:
                            cw.addInputValue(hub.name(), 'backEnd',
                                             'NumReadoutsReceived')
                        if self.__contains(components, 'globalTrigger'):
                            cw.addInputValue('globalTrigger', 'backEnd',
                                             'NumTriggerRequestsReceived')
                        cw.addOutputValue('dispatch', 'backEnd',
                                          'NumEventsSent')
                        cw.addThresholdValue('backEnd', 'DiskAvailable', 1024)
                        cw.addThresholdValue('backEnd', 'NumBadEvents', 0,
                                             False)
                        eventBuilder = cw
                    elif comp.name() == 'secondaryBuilders':
                        cw.addThresholdValue('snBuilder', 'DiskAvailable', 1024)
                        cw.addOutputValue('dispatch', 'moniBuilder',
                                          'TotalDispatchedData')
                        cw.addOutputValue('dispatch', 'snBuilder',
                                          'TotalDispatchedData')
                        # XXX - Disabled until there's a simulated tcal stream
                        #cw.addOutputValue('dispatch', 'tcalBuilder',
                        #                  'TotalDispatchedData')
                        secondaryBuilders = cw
                    else:
                        self.__log.error("Couldn't create watcher for" +
                                         ' unknown component #%d type %s#%d' %
                                         (c, comp.name(), comp.id()))
                except Exception:
                    self.__log.error("Couldn't create watcher for component" +
                                     ' #%d type %s#%d: %s' %
                                     (c, comp.name(), comp.id(),
                                      exc_string()))

        # soloComps is filled here so we can determine the order
        # of components in the list
        #
        if iniceTrigger: self.__soloComps.append(iniceTrigger)
        if simpleTrigger: self.__soloComps.append(simpleTrigger)
        if icetopTrigger: self.__soloComps.append(icetopTrigger)
        if amandaTrigger: self.__soloComps.append(amandaTrigger)
        if globalTrigger: self.__soloComps.append(globalTrigger)
        if eventBuilder: self.__soloComps.append(eventBuilder)
        if secondaryBuilders: self.__soloComps.append(secondaryBuilders)

    def __appendError(errMsg, compType, compErr):
        if errMsg is None:
            errMsg = "** Run watchdog reports"
        else:
            errMsg += "\nand"
        errMsg += " " + compType + " components:\n" + compErr

        return errMsg

    __appendError = staticmethod(__appendError)

    def __checkComp(self, comp, starved, stagnant, threshold):
        isOK = True
        try:
            badList = comp.checkList(comp.inputFields)
            if badList is not None:
                starved += badList
                isOK = False
        except Exception:
            self.__log.error(str(comp) + ' inputs: ' + exc_string())
            isOK = False

        if isOK:
            try:
                badList = comp.checkList(comp.outputFields)
                if badList is not None:
                    stagnant += badList
                    isOK = False
            except Exception:
                self.__log.error(str(comp) + ' outputs: ' + exc_string())
                isOK = False

            if isOK:
                try:
                    badList = comp.checkList(comp.thresholdFields)
                    if badList is not None:
                        threshold += badList
                        isOK = False
                except Exception:
                    self.__log.error(str(comp) + ' thresholds: ' + exc_string())
                    isOK = False

        return isOK

    def __contains(self, comps, compName):
        for c in comps.values():
            if c.name() == compName:
                return True

        return False

    def __findAnyHub(self, comps):
        for comp in comps.values():
            if comp.isHub():
                return comp

        return None

    def __joinAll(self, comps):
        compStr = None
        for c in comps:
            if compStr is None:
                compStr = '    ' + str(c)
            else:
                compStr += "\n    " + str(c)
        return compStr

    def caughtError(self):
        return self.__thread is not None and self.__thread.error

    def checkProgress(self):
        if self.inProgress():
            if self.caughtError():
                self.clearThread()
                return RunWatchdog.CAUGHT_ERROR

            if self.isDone():
                healthy = self.isHealthy()
                self.clearThread()
                if healthy:
                    self.__unHealthyCount = 0
                else:
                    self.__unHealthyCount += 1
                    if self.__unHealthyCount >= RunWatchdog.MAX_UNHEALTHY_COUNT:
                        self.__unHealthyCount = 0
                        return RunWatchdog.UNHEALTHY

            return RunWatchdog.IN_PROGRESS
        elif self.timeToWatch():
            self.startWatch()
            return RunWatchdog.IN_PROGRESS

        return RunWatchdog.NOT_RUNNING

    def clearThread(self):
        self.__thread = None

    def createData(self, id, name, daqID, inetAddr, mbeanPort):
        return WatchData(id, name, daqID, inetAddr, mbeanPort)

    def inProgress(self):
        return self.__thread is not None

    def isDone(self):
        return self.__thread is not None and self.__thread.done

    def isHealthy(self):
        return self.__thread is not None and self.__thread.healthy

    def realWatch(self):
        starved = []
        stagnant = []
        threshold = []

        healthy = True

        # checks can raise exception if far end is dead
        for comp in self.__stringHubs:
            if not self.__checkComp(comp, starved, stagnant, threshold):
                healthy = False

        for comp in self.__soloComps:
            if not self.__checkComp(comp, starved, stagnant, threshold):
                healthy = False

        errMsg = None

        if len(stagnant) > 0:
            errMsg = RunWatchdog.__appendError(errMsg, 'stagnant',
                                               self.__joinAll(stagnant))

        if len(starved) > 0:
            errMsg = RunWatchdog.__appendError(errMsg, 'starving',
                                               self.__joinAll(starved))

        if len(threshold) > 0:
            errMsg = RunWatchdog.__appendError(errMsg, 'threshold',
                                               self.__joinAll(threshold))

        if errMsg is not None:
            self.__log.error(errMsg)
            healthy = False

        return healthy

    def startWatch(self):
        self.reset()
        self.__thread = WatchThread(self, self.__log)
        self.__thread.start()

    def timeToWatch(self):
        if self.inProgress(): return False
        return self.isTime()
