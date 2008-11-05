#!/usr/bin/env python

#!/usr/bin/env python

#
# DAQ Monitoring object for high level DAQRun scrupt
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started December, 2006

from DAQRPC import RPCClient
import datetime, threading

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
            self.__prevValue = newValue
        elif type(newValue) != type(self.__prevValue):
            raise Exception('Previous value for %s was %s, new value is %s' %
                            (str(self), str(type(self.__prevValue)),
                             str(type(newValue))))
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

        if compNum == 0 and not not compType.lower().endswith('hub'):
            self.__name = compType
        else:
            self.__name = '%s#%d' % (compType, compNum)

        self.__client = RPCClient(addr, port)
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
            val = self.__client.mbean.get(watchList[0].beanName,
                                          watchList[0].fieldName)
            if not watchList[0].check(val):
                unhealthy.append(watchList[0].unhealthyString(val))
        else:
            fldList = []
            for f in watchList:
                fldList.append(f.fieldName)

            valMap = self.__client.mbean.getAttributes(watchList[0].beanName,
                                                       fldList)
            for i in range(0, len(fldList)):
                val = valMap[fldList[i]]
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
            self.__log.logmsg("Exception in run watchdog: %s" % exc_string())
            self.error = True

class RunWatchdog(object):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof, rpcAddrOf, mbeanPortOf):
        self.__log            = daqLog
        self.__interval       = interval
        self.__tlast          = None
        self.__stringHubs     = []
        self.__soloComps      = []
        self.__thread         = None

        iniceTrigger  = None
        simpleTrigger  = None
        icetopTrigger  = None
        amandaTrigger  = None
        globalTrigger   = None
        eventBuilder   = None
        secondaryBuilders   = None
        for c in IDs:
            if mbeanPortOf[c] > 0:
                try:
                    cw = WatchData(c, shortNameOf[c], daqIDof[c],
                                   rpcAddrOf[c], mbeanPortOf[c])
                    if shortNameOf[c] == 'stringHub' or \
                            shortNameOf[c] == 'replayHub':
                        cw.addInputValue('dom', 'sender', 'NumHitsReceived')
                        if self.__contains(shortNameOf, 'eventBuilder'):
                            cw.addInputValue('eventBuilder', 'sender',
                                             'NumReadoutRequestsReceived')
                            cw.addOutputValue('eventBuilder', 'sender',
                                              'NumReadoutsSent')
                        self.__stringHubs.append(cw)
                    elif shortNameOf[c] == 'inIceTrigger':
                        hubName = self.__findHub(shortNameOf)
                        if hubName is not None:
                            cw.addInputValue(hubName, 'stringHit',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        iniceTrigger = cw
                    elif shortNameOf[c] == 'simpleTrigger':
                        hubName = self.__findHub(shortNameOf)
                        if hubName is not None:
                            cw.addInputValue(hubName, 'stringHit',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        iniceTrigger = cw
                    elif shortNameOf[c] == 'iceTopTrigger':
                        hubName = self.__findHub(shortNameOf)
                        if hubName is not None:
                            cw.addInputValue(hubName, 'stringHit',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        icetopTrigger = cw
                    elif shortNameOf[c] == 'amandaTrigger':
                        if self.__contains(shortNameOf, 'globalTrigger'):
                            cw.addOutputValue('globalTrigger', 'trigger',
                                              'RecordsSent')
                        amandaTrigger = cw
                    elif shortNameOf[c] == 'globalTrigger':
                        if self.__contains(shortNameOf, 'inIceTrigger'):
                            cw.addInputValue('inIceTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'simpleTrigger'):
                            cw.addInputValue('simpleTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'iceTopTrigger'):
                            cw.addInputValue('iceTopTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'amandaTrigger'):
                            cw.addInputValue('amandaTrigger', 'trigger',
                                             'RecordsReceived')
                        if self.__contains(shortNameOf, 'eventBuilder'):
                            cw.addOutputValue('eventBuilder', 'glblTrig',
                                              'RecordsSent')
                        globalTrigger = cw
                    elif shortNameOf[c] == 'eventBuilder':
                        hubName = self.__findHub(shortNameOf)
                        if hubName is not None:
                            cw.addInputValue(hubName, 'backEnd',
                                             'NumReadoutsReceived');
                        if self.__contains(shortNameOf, 'globalTrigger'):
                            cw.addInputValue('globalTrigger', 'backEnd',
                                             'NumTriggerRequestsReceived');
                        cw.addOutputValue('dispatch', 'backEnd',
                                          'NumEventsSent');
                        cw.addThresholdValue('backEnd', 'DiskAvailable', 1024)
                        cw.addThresholdValue('backEnd', 'NumBadEvents', 0,
                                             False)
                        eventBuilder = cw
                    elif shortNameOf[c] == 'secondaryBuilders':
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
                        raise Exception('Unknown component type ' +
                                        shortNameOf[c])
                except Exception:
                    self.logmsg(('Couldn''t create watcher (%s#%d)' +
                                 ' for component %d: %s') %
                                (shortNameOf[c], daqIDof[c], c, exc_string()))

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
        isProblem = False
        try:
            badList = comp.checkList(comp.inputFields)
            if badList is not None:
                starved += badList
                isProblem = True
        except Exception:
            self.logmsg(str(comp) + ' inputs: ' + exc_string())

        if not isProblem:
            try:
                badList = comp.checkList(comp.outputFields)
                if badList is not None:
                    stagnant += badList
                    isProblem = True
            except Exception:
                self.logmsg(str(comp) + ' outputs: ' + exc_string())

            if not isProblem:
                try:
                    badList = comp.checkList(comp.thresholdFields)
                    if badList is not None:
                        threshold += badList
                        isProblem = True
                except Exception:
                    self.logmsg(str(comp) + ' thresholds: ' + exc_string())

    def __contains(self, nameDict, compName):
        for n in nameDict.values():
            if n == compName:
                return True

        return False

    def __findHub(self, nameDict):
        for n in nameDict.values():
            if n == 'stringHub' or n == 'replayHub':
                return n

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

    def clearThread(self):
        self.__thread = None

    def inProgress(self):
        return self.__thread is not None

    def isDone(self):
        return self.__thread is not None and self.__thread.done

    def isHealthy(self):
        return self.__thread is not None and self.__thread.healthy

    def logmsg(self, m):
        "Log message to logger, but only if logger exists"
        print m
        if self.__log: self.__log.dashLog(m)

    def realWatch(self):
        starved = []
        stagnant = []
        threshold = []

        # checks can raise exception if far end is dead
        for comp in self.__stringHubs:
            self.__checkComp(comp, starved, stagnant, threshold)

        for comp in self.__soloComps:
            self.__checkComp(comp, starved, stagnant, threshold)

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

        healthy = True
        if errMsg is not None:
            self.logmsg(errMsg)
            healthy = False
        #else:
        #    self.logmsg('** Run watchdog reports all components are healthy')

        return healthy

    def startWatch(self):
        self.__tlast = datetime.datetime.now()
        self.__thread = WatchThread(self, self.__log)
        self.__thread.start()

    def timeToWatch(self):
        if self.inProgress(): return False
        if not self.__tlast: return True
        now = datetime.datetime.now()
        dt  = now - self.__tlast
        if dt.seconds+dt.microseconds*1.E-6 > self.__interval: return True
        return False
