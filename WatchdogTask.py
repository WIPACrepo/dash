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
        if type(other) != UnhealthyRecord:
            return -1

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
        if isinstance(value, Exception) and not isinstance(value, TaskException):
            msg = "%s: %s" % (str(self), exc_string())
        else:
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
            try:
                cmpEq = self.__compare(self.__prevValue, newValue)
            except TaskException, te:
                self.__unchanged = 0
                raise te

            if cmpEq:
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
            tmpEx = None
            for i in range(len(newValue)):
                try:
                    cmpEq = self.__compare(self.__prevValue[i], newValue[i])
                except TaskException, te:
                    if tmpEx is None:
                        tmpEx = te
                    cmpEq = False

                if cmpEq:
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

            if tmpEx:
                raise tmpEx

        return self.__unchanged == 0

    def unhealthyRecord(self, value):
        if isinstance(value, Exception) and \
               not isinstance(value, TaskException):
            msg = "%s: %s" % (str(self), exc_string())
        else:
            msg = "%s not changing from %s" % (str(self), str(self.__prevValue))
        return UnhealthyRecord(msg, self.__order)

class WatchData(object):
    def __init__(self, comp, dashlog):
        self.__comp = comp
        self.__dashlog = dashlog

        self.__inputFields = {}
        self.__outputFields = {}
        self.__thresholdFields = {}

        self.__closed = False

    def __str__(self):
        return self.__comp.fullName()

    def __checkBeans(self, beanList):
        unhealthy = []
        for b in beanList:
            if self.__closed:
                # break out of the loop if this thread has been closed
                break
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
            except Exception, ex:
                unhealthy.append(watchList[0].unhealthyRecord(ex))
                chkVal = True
            if not chkVal:
                unhealthy.append(watchList[0].unhealthyRecord(val))
        else:
            fldList = []
            for f in watchList:
                fldList.append(f.fieldName())

            try:
                valMap = self.__comp.getMultiBeanFields(watchList[0].beanName(),
                                                        fldList)
            except Exception, ex:
                fldList = []
                unhealthy.append(watchList[0].unhealthyRecord(ex))

            for index, fldVal in enumerate(fldList):

                try:
                    val = valMap[fldVal]
                except KeyError, e:
                    self.__dashlog.error("No value found for %s field#%d %s" %
                                         (self.__comp.fullName(), index,
                                          fldVal))
                    continue

                try:
                    chkVal = watchList[index].check(val)
                except Exception, ex:
                    unhealthy.append(watchList[index].unhealthyRecord(ex))
                    chkVal = True
                if not chkVal:
                    unhealthy.append(watchList[index].unhealthyRecord(val))

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
        if not self.__closed:
            try:
                badList = self.__checkBeans(self.__inputFields)
                if badList is not None:
                    starved += badList
                    isOK = False
            except:
                self.__dashlog.error(self.__comp.fullName() + " inputs: " +
                                     exc_string())
                isOK = False

        if not self.__closed and isOK:
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

        if not self.__closed:
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

    def close(self):
        self.__closed = True

    def order(self):
        return self.__comp.order()

class WatchdogThread(CnCThread):
    def __init__(self, runset, comp, rule, dashlog, data=None, initFail=0):
        self.__runset = runset
        self.__comp = comp
        self.__rule = rule
        self.__dashlog = dashlog

        self.__data = data
        self.__initFail = initFail

        self.__starved = []
        self.__stagnant = []
        self.__threshold = []

        super(WatchdogThread, self).__init__(self.__comp.fullName() + ":" +
                                             str(self.__rule), self.__dashlog)

    def __str__(self):
        return self.__comp.fullName()

    def _run(self):
        if self.isClosed():
            return

        if self.__data is None:
            try:
                self.__data = self.__rule.createData(self.__comp,
                                                     self.__runset.components(),
                                                     self.__dashlog)
            except:
                self.__initFail += 1
                self.__dashlog.error("Initialization failure #%d for %s %s" %
                                     (self.__initFail, self.__comp.fullName(),
                                      self.__rule))
                return

        self.__data.check(self.__starved, self.__stagnant, self.__threshold)

    def close(self):
        super(type(self), self).close()

        if self.__data is not None:
            self.__data.close()
            self.__data = None

    def getNewThread(self):
        thrd = WatchdogThread(self.__runset, self.__comp, self.__rule,
                              self.__dashlog, self.__data, self.__initFail)
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

class WatchdogRule(object):
    DOM_COMP = DummyComponent("dom")
    DISPATCH_COMP = DummyComponent("dispatch")

    def __str__(self):
        return type(self).__name__

    @classmethod
    def findComp(cls, comps, compName):
        for c in comps:
            if c.name() == compName:
                return c

        return None

    def createData(self, thisComp, components, dashlog):
        data = WatchData(thisComp, dashlog)
        self.initData(data, thisComp, components)
        return data

    @classmethod
    def initialize(cls, runset):
        minOrder = None
        maxOrder = None

        for comp in runset.components():
            order = comp.order()
            if type(order) != int:
                raise TaskException("Expected integer order for %s, not %s" %
                                    (comp.fullName(), type(comp.order())))

            if minOrder is None or order < minOrder:
                minOrder = order
            if maxOrder is None or order > maxOrder:
                maxOrder = order

        cls.DOM_COMP.setOrder(minOrder - 1)
        cls.DISPATCH_COMP.setOrder(maxOrder + 1)

class StringHubRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        data.addInputValue(self.DOM_COMP, "sender", "NumHitsReceived")
        comp = self.findComp(components, "eventBuilder")
        if comp is not None:
            data.addInputValue(comp, "sender", "NumReadoutRequestsReceived")
            data.addOutputValue(comp, "sender", "NumReadoutsSent")

    def matches(self, comp):
        return comp.name() == "stringHub" or comp.name() == "replayHub"

class LocalTriggerRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        if thisComp.name() == "iceTopTrigger":
            hitName = "icetopHit"
            wantIcetop = True
        else:
            hitName = "stringHit"
            wantIcetop = False

        hub = None
        for comp in components:
            if comp.name().lower().endswith("hub"):
                if wantIcetop:
                    found = comp.num() >= 200
                else:
                    found = comp.num() < 200
                if found:
                    hub = comp
                    break

        if hub is not None:
            data.addInputValue(hub, hitName, "RecordsReceived")
        comp = self.findComp(components, "globalTrigger")
        if comp is not None:
            data.addOutputValue(comp, "trigger", "RecordsSent")

    def matches(self, comp):
        return comp.name() == "inIceTrigger" or \
                   comp.name() == "simpleTrigger" or \
                   comp.name() == "iceTopTrigger"

class GlobalTriggerRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        for trig in ("inIce", "iceTop", "simple"):
            comp = self.findComp(components, trig + "Trigger")
            if comp is not None:
                data.addInputValue(comp, "trigger", "RecordsReceived")
        comp = self.findComp(components, "eventBuilder")
        if comp is not None:
            data.addOutputValue(comp, "glblTrig", "RecordsSent")

    def matches(self, comp):
        return comp.name() == "globalTrigger"

class EventBuilderRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        hub = None
        for comp in components:
            if comp.name().lower().endswith("hub"):
                hub = comp
                break
        if hub is not None:
            data.addInputValue(hub, "backEnd", "NumReadoutsReceived")
        comp = self.findComp(components, "globalTrigger")
        if comp is not None:
            data.addInputValue(comp, "backEnd", "NumTriggerRequestsReceived")
        data.addOutputValue(self.DISPATCH_COMP, "backEnd", "NumEventsSent")
        data.addThresholdValue("backEnd", "DiskAvailable", 1024)
        data.addThresholdValue("backEnd", "NumBadEvents", 0, False)

    def matches(self, comp):
        return comp.name() == "eventBuilder"

class SecondaryBuildersRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        data.addThresholdValue("snBuilder", "DiskAvailable", 1024)
        data.addOutputValue(self.DISPATCH_COMP, "moniBuilder",
                          "TotalDispatchedData")
        data.addOutputValue(self.DISPATCH_COMP, "snBuilder",
                          "TotalDispatchedData")
        # XXX - Disabled until there"s a simulated tcal stream
        #data.addOutputValue(self.DISPATCH_COMP, "tcalBuilder",
        #                  "TotalDispatchedData")

    def matches(self, comp):
        return comp.name() == "secondaryBuilders"

class WatchdogTask(CnCTask):
    NAME = "Watchdog"
    PERIOD = 10
    DEBUG_BIT = RunSetDebug.WATCH_TASK

    # number of bad checks before the run is killed
    HEALTH_METER_FULL = 9
    # number of complaints printed before run is killed
    NUM_HEALTH_MSGS = 3

    def __init__(self, taskMgr, runset, dashlog, period=None, rules=None):
        self.__threadList = {}
        self.__healthMeter = self.HEALTH_METER_FULL

        if period is None: period = self.PERIOD

        super(WatchdogTask, self).__init__("Watchdog", taskMgr, dashlog,
                                           self.DEBUG_BIT, self.NAME,
                                           period)

        WatchdogRule.initialize(runset)

        if rules is None:
            rules = (StringHubRule(),
                     LocalTriggerRule(),
                     GlobalTriggerRule(),
                     EventBuilderRule(),
                     SecondaryBuildersRule(),
                     )

        self.__threadList = self.__createThreads(runset, rules, dashlog)

    def __createThreads(self, runset, rules, dashlog):
        threadList = {}

        components = runset.components()
        for comp in components:
            try:
                found = False
                for rule in rules:
                    if rule.matches(comp):
                        threadList[comp] = self.createThread(runset, comp,
                                                             rule, dashlog)
                        found = True
                        break
                if not found:
                    self.logError("Couldn't create watcher for unknown" +
                                  " component " + comp.fullName())
            except:
                self.logError("Couldn't create watcher for component %s: %s" %
                              (comp.fullName(), exc_string()))
        return threadList

    def __logUnhealthy(self, errType, badList):
        errStr = None

        badList.sort()
        for bad in badList:
            if errStr is None:
                errStr = ""
            else:
                errStr += "\n"
            if type(bad) == UnhealthyRecord:
                msg = bad.message()
            else:
                msg = "%s (%s is not UnhealthyRecord)" % (str(bad), type(bad))
            errStr += "    " + msg

        self.logError("Watchdog reports %s components:\n%s" % (errType, errStr))

    def _check(self):
        hanging = []
        starved = []
        stagnant = []
        threshold = []

        for c in self.__threadList.keys():
            if self.__threadList[c].isAlive():
                hanging.append(UnhealthyRecord(str(self.__threadList[c]),
                                               c.order()))
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
            if self.__healthMeter > 0:
                if self.__healthMeter % self.NUM_HEALTH_MSGS == 0:
                    self.logError("Run is unhealthy (%d checks left)" %
                                  self.__healthMeter)
            else:
                self.logError("Run is not healthy, stopping")
                self.setError()

    def close(self):
        savedEx = None
        for thr in self.__threadList.values():
            try:
                thr.close()
            except Exception, ex:
                if savedEx is None:
                    savedEx = ex

        if savedEx is not None: raise savedEx

    def createThread(self, runset, comp, rule, dashlog):
        return WatchdogThread(runset, comp, rule, dashlog)

    def waitUntilFinished(self):
        for c in self.__threadList.keys():
            if self.__threadList[c].isAlive():
                self.__threadList[c].join()
