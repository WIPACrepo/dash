#!/usr/bin/env python

from CnCTask import CnCTask, TaskException
from CnCThread import CnCThread
from RunSetDebug import RunSetDebug

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class UnhealthyRecord(object):
    def __init__(self, msg, order):
        self.__msg = msg
        self.__order = order

    def __repr__(self): return str(self)

    def __str__(self):
        return "#%d: %s" % (self.__order, self.__msg)

    def __cmp__(self, other):
        val = cmp(self.__order, other.__order)
        if val == 0:
            val = cmp(self.__msg, other.__msg)
        return val

    def message(self): return self.__msg
    def order(self): return self.__order

class Watcher(object):
    def __init__(self, fullName, beanName, fieldName):
        self.__fullName = fullName
        self.__beanName = beanName
        self.__fieldName = fieldName

    def __repr__(self):
        return self.__fullName

    def __str__(self):
        return self.__fullName

    def beanName(self):
        return self.__beanName

    def fieldName(self):
        return self.__fieldName

    def typeCategory(self, val):
        vType = type(val)
        if vType == tuple:
            return list
        if vType == long:
            return int
        return vType

class ThresholdWatcher(Watcher):
    def __init__(self, comp, beanName, fieldName, threshold, lessThan):
        self.__comp = comp
        self.__threshold = threshold
        self.__lessThan = lessThan

        if self.__lessThan:
            dir = "below"
        else:
            dir = "above"

        fullName = "%s %s.%s %s %s" % \
            (comp.fullName(), beanName, fieldName, dir, str(self.__threshold))
        super(ThresholdWatcher, self).__init__(fullName, beanName, fieldName)

    def __compare(self, threshold, value):
        if self.__lessThan:
            return value < threshold
        else:
            return value > threshold

    def check(self, newValue):
        newType = self.typeCategory(newValue)
        threshType = self.typeCategory(self.__threshold)

        if newType != threshType:
            raise TaskException(("Threshold value for %s is %s, new value" +
                                 " is %s") %
                                (str(self), str(type(self.__threshold)),
                             str(type(newValue))))
        elif newType == list or newType == dict:
            raise TaskException("ThresholdWatcher does not support %s" %
                                newType)
        elif self.__compare(self.__threshold, newValue):
            return False

        return True

    def unhealthyRecord(self, value):
        msg = "%s (value=%s)" % (str(self), str(value))
        return UnhealthyRecord(msg, self.__comp.order())

class ValueWatcher(Watcher):
    NUM_UNCHANGED = 3

    def __init__(self, fromComp, toComp, beanName, fieldName):
        self.__fromComp = fromComp
        self.__toComp = toComp
        self.__order = self.__computeOrder(beanName, fieldName)
        self.__prevValue = None
        self.__unchanged = 0

        fullName = "%s->%s %s.%s" % (fromComp.fullName(), toComp.fullName(),
                                     beanName, fieldName)
        super(ValueWatcher, self).__init__(fullName, beanName, fieldName)

    def __compare(self, oldValue, newValue):
        if newValue < oldValue:
            raise TaskException("%s DECREASED (%s->%s)" %
                                (str(self), str(oldValue), str(newValue)))

        return newValue == oldValue

    def __computeOrder(self, beanName, fieldName):
        if self.__fromComp.isBuilder() and self.__toComp.isSource():
            return self.__fromComp.order() + 1

        if self.__fromComp.isSource() and self.__toComp.isBuilder():
            return self.__toComp.order() + 2

        return self.__fromComp.order()

    def check(self, newValue):
        if self.__prevValue is None:
            if type(newValue) == list:
                self.__prevValue = newValue[:]
            else:
                self.__prevValue = newValue
            return True

        newType = self.typeCategory(newValue)
        prevType = self.typeCategory(self.__prevValue)

        if newType != prevType:
            raise TaskException(("Previous type for %s was %s (%s)," +
                                 " new type is %s (%s)") %
                                (str(self), str(type(self.__prevValue)),
                                 str(self.__prevValue),
                                 str(type(newValue)), str(newValue)))

        if newType == dict:
            raise TaskException("ValueWatcher does not support %s" % newType)

        if newType != list:
            if self.__compare(self.__prevValue, newValue):
                self.__unchanged += 1
                if self.__unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise TaskException(str(self) + " is not changing")
            else:
                self.__unchanged = 0
                self.__prevValue = newValue
        elif len(newValue) != len(self.__prevValue):
            raise TaskException(("Previous %s list had %d entries, new list" +
                                 " has %d") %
                                (str(self), len(self.__prevValue),
                                 len(newValue)))
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
                    raise TaskException(("At least one %s value is not" +
                                         " changing") % str(self))

        return self.__unchanged == 0

    def unhealthyRecord(self, value):
        msg = "%s not changing from %s" % (str(self), str(self.__prevValue))
        return UnhealthyRecord(msg, self.__order)

class WatchData(object):
    def __init__(self, comp, dashlog):
        self.__comp = comp
        self.__dashlog = dashlog

        self.__inputFields = {}
        self.__outputFields = {}
        self.__thresholdFields = {}

    def __str__(self):
        return self.__comp.fullName()

    def __checkBeans(self, beanList):
        unhealthy = []
        for b in beanList:
            badList = self.__checkValues(beanList[b])
            if badList is not None:
                unhealthy += badList

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def __checkValues(self, watchList):
        unhealthy = []
        if len(watchList) == 1:
            try:
                val = self.__comp.getSingleBeanField(watchList[0].beanName(),
                                                     watchList[0].fieldName())
                chkVal = watchList[0].check(val)
            except:
                val = None
                chkVal = False
            if not chkVal:
                unhealthy.append(watchList[0].unhealthyRecord(val))
        else:
            fldList = []
            for f in watchList:
                fldList.append(f.fieldName())

            try:
                valMap = self.__comp.getMultiBeanFields(watchList[0].beanName(),
                                                        fldList)
            except:
                return [exc_string(), ]

            for i in range(0, len(fldList)):
                val = valMap[fldList[i]]
                try:
                    chkVal = watchList[i].check(val)
                except:
                    chkVal = False
                if not chkVal:
                    unhealthy.append(watchList[i].unhealthyRecord(val))

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def addInputValue(self, otherComp, beanName, fieldName):
        self.__comp.checkBeanField(beanName, fieldName)

        if beanName not in self.__inputFields:
            self.__inputFields[beanName] = []

        vw = ValueWatcher(otherComp, self.__comp, beanName, fieldName)
        self.__inputFields[beanName].append(vw)

    def addOutputValue(self, otherComp, beanName, fieldName):
        self.__comp.checkBeanField(beanName, fieldName)

        if beanName not in self.__outputFields:
            self.__outputFields[beanName] = []

        vw = ValueWatcher(self.__comp, otherComp, beanName, fieldName)
        self.__outputFields[beanName].append(vw)

    def addThresholdValue(self, beanName, fieldName, threshold, lessThan=True):
        """
        Watchdog triggers if field value drops below the threshold value
        (or, when lessThan==False, if value rises above the threshold
        """

        self.__comp.checkBeanField(beanName, fieldName)

        if beanName not in self.__thresholdFields:
            self.__thresholdFields[beanName] = []

        tw = ThresholdWatcher(self.__comp, beanName, fieldName, threshold,
                              lessThan)
        self.__thresholdFields[beanName].append(tw)

    def check(self, starved, stagnant, threshold):
        isOK = True
        try:
            badList = self.__checkBeans(self.__inputFields)
            if badList is not None:
                starved += badList
                isOK = False
        except:
            self.__dashlog.error(self.__comp.fullName() + " inputs: " +
                                 exc_string())
            isOK = False

        if isOK:
            # don't report output problems if there are input problems
            #
            try:
                badList = self.__checkBeans(self.__outputFields)
                if badList is not None:
                    stagnant += badList
                    isOK = False
            except:
                self.__dashlog.error(self.__comp.fullName() + " outputs: " +
                                     exc_string())
                isOK = False

        # report threshold problems even if there are other problems
        #
        try:
            badList = self.__checkBeans(self.__thresholdFields)
            if badList is not None:
                threshold += badList
                isOK = False
        except:
            self.__dashlog.error(self.__comp.fullName() + " thresholds: " +
                                 exc_string())
            isOK = False

        return isOK

    def order(self):
        return self.__comp.order()

class WatchdogThread(CnCThread):
    def __init__(self, data, dashlog):
        self.__data = data
        self.__dashlog = dashlog

        self.__starved = []
        self.__stagnant = []
        self.__threshold = []

        super(WatchdogThread, self).__init__(str(data), dashlog)

    def __str__(self):
        return str(self.__data)

    def _run(self):
        self.__data.check(self.__starved, self.__stagnant, self.__threshold)

    def getNewThread(self):
        thrd = WatchdogThread(self.__data, self.__dashlog)
        return thrd

    def stagnant(self): return self.__stagnant[:]
    def starved(self): return self.__starved[:]
    def threshold(self): return self.__threshold[:]

class DummyComponent(object):
    def __init__(self, name):
        self.__name = name
        self.__order = None

    def __str__(self): return self.__name
    def fullName(self): return self.__name
    def isBuilder(self): return False
    def isSource(self): return False
    def order(self): return self.__order

    def setOrder(self, num):
        self.__order = num

class WatchdogTask(CnCTask):
    NAME = "Watchdog"
    PERIOD = 10
    DEBUG_BIT = RunSetDebug.WATCH_TASK

    HEALTH_METER_FULL = 3

    DOM_COMP = DummyComponent("dom")
    DISPATCH_COMP = DummyComponent("dispatch")

    def __init__(self, taskMgr, runset, dashlog):
        self.__threadList = {}
        self.__healthMeter = self.HEALTH_METER_FULL

        super(WatchdogTask, self).__init__("Watchdog", taskMgr, dashlog,
                                           self.DEBUG_BIT, self.NAME,
                                           self.PERIOD)

        self.__computeDummyOrder(runset)

        watchData = self.__gatherData(runset)
        for data in watchData:
            self.__threadList[data] = WatchdogThread(data, dashlog)

    def __computeDummyOrder(self, runset):
        minOrder = None
        maxOrder = None

        for comp in runset.components():
            order = comp.order()
            if type(order) != int:
                raise TaskException("Expected integer order for %s, not %s" %
                                    comp.fullName(), type(comp.order()))

            if minOrder is None or order < minOrder:
                minOrder = order
            if maxOrder is None or order > maxOrder:
                maxOrder = order

        self.DOM_COMP.setOrder(minOrder - 1)
        self.DISPATCH_COMP.setOrder(maxOrder + 1)

    def __findAnyHub(self, comps):
        for comp in comps:
            if comp.name().lower().endswith("hub"):
                return comp

        return None

    def __findComp(self, comps, compName):
        for c in comps:
            if c.name() == compName:
                return c

        return None

    def __gatherData(self, runset):
        watchData = []

        components = runset.components()
        for comp in components:
            try:
                cw = WatchData(comp, self.logger())
                if comp.name() == "stringHub" or \
                        comp.name() == "replayHub":
                    cw.addInputValue(self.DOM_COMP, "sender", "NumHitsReceived")
                    comp = self.__findComp(components, "eventBuilder")
                    if comp is not None:
                        cw.addInputValue(comp, "sender",
                                         "NumReadoutRequestsReceived")
                        cw.addOutputValue(comp, "sender", "NumReadoutsSent")
                    watchData.append(cw)
                elif comp.name() == "inIceTrigger":
                    hub = self.__findAnyHub(components)
                    if hub is not None:
                        cw.addInputValue(hub, "stringHit", "RecordsReceived")
                    comp = self.__findComp(components, "globalTrigger")
                    if comp is not None:
                        cw.addOutputValue(comp, "trigger", "RecordsSent")
                    watchData.append(cw)
                elif comp.name() == "simpleTrigger":
                    hub = self.__findAnyHub(components)
                    if hub is not None:
                        cw.addInputValue(hub, "stringHit", "RecordsReceived")
                    comp = self.__findComp(components, "globalTrigger")
                    if comp is not None:
                        cw.addOutputValue(comp, "trigger", "RecordsSent")
                    watchData.append(cw)
                elif comp.name() == "iceTopTrigger":
                    hub = self.__findAnyHub(components)
                    if hub is not None:
                        cw.addInputValue(hub, "icetopHit", "RecordsReceived")
                    comp = self.__findComp(components, "globalTrigger")
                    if comp is not None:
                        cw.addOutputValue(comp, "trigger", "RecordsSent")
                    watchData.append(cw)
                elif comp.name() == "globalTrigger":
                    for trig in ("inIce", "iceTop", "simple"):
                        comp = self.__findComp(components, trig + "Trigger")
                        if comp is not None:
                            cw.addInputValue(comp, "trigger", "RecordsReceived")
                    comp = self.__findComp(components, "eventBuilder")
                    if comp is not None:
                        cw.addOutputValue(comp, "glblTrig", "RecordsSent")
                    watchData.append(cw)
                elif comp.name() == "eventBuilder":
                    hub = self.__findAnyHub(components)
                    if hub is not None:
                        cw.addInputValue(hub, "backEnd", "NumReadoutsReceived")
                    comp = self.__findComp(components, "globalTrigger")
                    if comp is not None:
                        cw.addInputValue(comp, "backEnd",
                                         "NumTriggerRequestsReceived")
                    cw.addOutputValue(self.DISPATCH_COMP, "backEnd",
                                      "NumEventsSent")
                    cw.addThresholdValue("backEnd", "DiskAvailable", 1024)
                    cw.addThresholdValue("backEnd", "NumBadEvents", 0,
                                         False)
                    watchData.append(cw)
                elif comp.name() == "secondaryBuilders":
                    cw.addThresholdValue("snBuilder", "DiskAvailable", 1024)
                    cw.addOutputValue(self.DISPATCH_COMP, "moniBuilder",
                                      "TotalDispatchedData")
                    cw.addOutputValue(self.DISPATCH_COMP, "snBuilder",
                                      "TotalDispatchedData")
                    # XXX - Disabled until there"s a simulated tcal stream
                    #cw.addOutputValue(self.DISPATCH_COMP, "tcalBuilder",
                    #                  "TotalDispatchedData")
                    watchData.append(cw)
                else:
                    self.logError("Couldn't create watcher for unknown" +
                                  " component " + comp.fullName())
            except:
                self.logError("Couldn't create watcher for component %s: %s" %
                              (comp.fullName(), exc_string()))

        # sort entries by component order
        #
        watchData.sort(lambda x,y : cmp(x.order(), y.order()))

        return watchData

    def __logUnhealthy(self, errType, badList):
        errStr = None

        badList.sort()
        for bad in badList:
            if errStr is None:
                errStr = ""
            else:
                errStr += "\n"
            errStr += "    " + bad.message()

        self.logError("Watchdog reports %s components:\n%s" % (errType, errStr))

    def _check(self):
        hanging = []
        starved = []
        stagnant = []
        threshold = []

        for c in self.__threadList.keys():
            if self.__threadList[c].isAlive():
                hanging.append(str(self.__threadList[c]))
            else:
                starved += self.__threadList[c].starved()
                stagnant += self.__threadList[c].stagnant()
                threshold += self.__threadList[c].threshold()

                self.__threadList[c] = self.__threadList[c].getNewThread()
                self.__threadList[c].start()

        healthy = True
        if len(hanging) > 0:
            self.__logUnhealthy("hanging", hanging)
            healthy = False
        if len(starved) > 0:
            self.__logUnhealthy("starved", starved)
            healthy = False
        if len(stagnant) > 0:
            self.__logUnhealthy("stagnant", stagnant)
            healthy = False
        if len(threshold) > 0:
            self.__logUnhealthy("threshold", threshold)
            healthy = False

        if healthy:
            if self.__healthMeter < self.HEALTH_METER_FULL:
                self.__healthMeter = self.HEALTH_METER_FULL
                self.logError("Run is healthy again")
        else:
            self.__healthMeter -= 1
            if self.__healthMeter >= 0:
                self.logError("Run is unhealthy (%d checks left)" %
                              self.__healthMeter)
            else:
                self.logError("Run is not healthy, stopping")
                self.setError()

    def waitUntilFinished(self):
        for c in self.__threadList.keys():
            if self.__threadList[c].isAlive():
                self.__threadList[c].join()
