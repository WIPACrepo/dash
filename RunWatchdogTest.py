#!/usr/bin/env python

import unittest
from DAQLogClient import DAQLog
from RunWatchdog import RunWatchdog, ThresholdWatcher, ValueWatcher, WatchData

from DAQMocks import MockAppender, MockRunComponent

class BeanData(object):
    TYPE_INPUT = 'i'
    TYPE_OUTPUT = 'o'
    TYPE_STATIC = 's'
    TYPE_THRESHOLD = 't'

    def __init__(self, remoteComp, bean, field, watchType, val=0,
                 increasing=True):
        self.__remoteComp = remoteComp
        self.__bean = bean
        self.__field = field
        self.__watchType = watchType
        self.__value = val
        self.__increasing = increasing

    def append(self, val):
        if type(self.__value) == list:
            self.__value.append(val)
        else:
            prev = self.__value
            self.__value = [prev, val]

    def getValue(self):
        return self.__value

    def setStatic(self):
        self.__watchType = BeanData.TYPE_STATIC

    def setValue(self, val):
        self.__value = val

    def update(self):
        if self.__watchType != BeanData.TYPE_STATIC:
            if type(self.__value) == int:
                if self.__increasing:
                    self.__value += 1
                else:
                    self.__value -= 1
            elif type(self.__value) == list:
                for i in range(len(self.__value)):
                    if self.__increasing:
                        self.__value[i] += 1
                    else:
                        self.__value[i] -= 1
            else:
                print 'Not updating %s:%s:%s type %s' % \
                    (self.__remoteComp, self.__bean, self.__field,
                     str(type(self.__value)))

class MockMBeanClient(object):
    def __init__(self, mbeanDict):
        self.__mbeanDict = mbeanDict

    def get(self, bean, fld):
        return self.__mbeanDict[bean][fld].getValue()

    def getAttributes(self, bean, fldList):
        attrs = {}
        for f in fldList:
            attrs[f] = self.__mbeanDict[bean][f].getValue()
        return attrs

    def listGetters(self, bean):
        k = self.__mbeanDict[bean].keys()
        k.sort()
        return k

    def listMBeans(self):
        k = self.__mbeanDict.keys()
        k.sort()
        return k

    def updateMBeanData(self, comp):
        for b in self.__mbeanDict:
            for f in self.__mbeanDict[b]:
                self.__mbeanDict[b][f].update()

class MockRPCClient(object):
    def __init__(self, mbeans):
        self.mbean = MockMBeanClient(mbeans)

class MockData(WatchData):
    def __init__(self, id, name, daqID, addr, port, rpcClient):
        self.__client = rpcClient
        self.__comp = '%s#%d' % (name, daqID)

        super(MockData, self).__init__(id, name, daqID, addr, port)

    def getRPCClient(self, addr, port):
        return self.__client

    def updateMBeanData(self):
        self.__client.mbean.updateMBeanData(self.__comp)

class MockWatchdog(RunWatchdog):
    def __init__(self, daqLog, interval, comps, dataDict):
        self.__dataDict = dataDict

        super(MockWatchdog, self).__init__(daqLog, interval, comps, True)

    def createData(self, id, name, daqID, rpcAddr, mbeanPort):
        return self.__dataDict[id]

class TestRunWatchdog(unittest.TestCase):
    COMP_BEANS = {'stringHub' :
                      (('dom', 'sender', 'NumHitsReceived', 'i', 0),
                       ('eventBuilder', 'sender', 'NumReadoutRequestsReceived',
                        'i', 0),
                       ('eventBuilder', 'sender', 'NumReadoutsSent', 'o', 0),
                       ),
                  'inIceTrigger' :
                      (('stringHub', 'stringHit', 'RecordsReceived', 'i', 0),
                       ('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                       ),
                  'simpleTrigger' :
                      (('stringHub', 'stringHit', 'RecordsReceived', 'i', 0),
                       ('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                       ),
                  'iceTopTrigger' :
                      (('stringHub', 'icetopHit', 'RecordsReceived', 'i', 0),
                       ('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                       ),
                  'amandaTrigger' :
                      (('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                       ),
                  'globalTrigger' :
                      (('inIceTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                       ('simpleTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                       ('iceTopTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                       ('amandaTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                       ('eventBuilder', 'glblTrig', 'RecordsSent', 'o', 0),
                       ),
                  'eventBuilder' :
                      (('stringHub', 'backEnd', 'NumReadoutsReceived', 'i', 0),
                       ('globalTrigger', 'backEnd',
                        'NumTriggerRequestsReceived', 'i', 0),
                       ('dispatch', 'backEnd', 'NumEventsSent', 'o', 0),
                       ('eventBuilder', 'backEnd', 'DiskAvailable',
                        't', 1024, True),
                       ('eventBuilder', 'backEnd', 'NumBadEvents',
                        't', 0, False),
                       ),
                  'secondaryBuilders' :
                      (('secondaryBuilders', 'snBuilder', 'DiskAvailable',
                        't', 1024, True),
                       ('dispatch', 'moniBuilder','TotalDispatchedData',
                        'o', 0),
                       ('dispatch', 'snBuilder', 'TotalDispatchedData', 'o', 0),
                       ('dispatch', 'tcalBuilder', 'TotalDispatchedData',
                        'o', 0),
                       ),
                  }

    def __buildBeans(self, masterList, comp):
        pound = comp.find('#')
        compName = comp[:pound]
        compId = int(comp[pound+1:])

        if not masterList.has_key(compName):
            self.fail('Unknown component %s' % compName)

        mbeans = {}

        beanTuples = masterList[compName]
        for t in beanTuples:
            if not mbeans.has_key(t[1]):
                mbeans[t[1]] = {}

            if mbeans[t[1]].has_key(t[2]):
                mbeans[t[1]][t[2]].append(t[4])
            else:
                if len(t) == 5:
                    data = BeanData(t[0], t[1], t[2], t[3], t[4])
                elif len(t) == 6:
                    data = BeanData(t[0], t[1], t[2], t[3], t[4], t[5])
                else:
                    raise Exception('Bad bean tuple %s' % str(t))

                mbeans[t[1]][t[2]] = data

        return mbeans

    def __runThread(self, wd, appender):
        wd.startWatch()

        result = RunWatchdog.IN_PROGRESS
        while result == RunWatchdog.IN_PROGRESS:
            result = wd.checkProgress()
        self.assertEquals(RunWatchdog.NOT_RUNNING, result,
                          'Expected result %d, not %d' %
                          (RunWatchdog.NOT_RUNNING, result))

        appender.checkStatus(10)

    def __updateBean(self, mbeans, comp, beanName, fldName, val):
        mbeans[beanName][fldName].setValue(val)

    def __setStatic(self, mbeans, comp, beanName, fldName):
        mbeans[beanName][fldName].setStatic()

    # ThresholdWatcher tests

    def testThreshStrings(self):
        comp = 'fooComp'
        bean = 'fooBean'
        fld = 'fooFld'
        lessThan = False
        thresh = 123

        tw = ThresholdWatcher(comp, bean, fld, thresh, lessThan)

        if lessThan:
            descr = 'below'
        else:
            descr = 'above'

        expStr = '%s %s.%s %s %s' % (comp, bean, fld, descr, str(thresh))
        actStr = str(tw)
        self.assertEquals(expStr, actStr,
                          'Expected "%s", not "%s"' % (expStr, actStr))

        badVal = 999

        expHealth = '%s (value=%s)' % (expStr, badVal)
        actHealth = tw.unhealthyString(badVal)
        self.assertEquals(expHealth, actHealth,
                          'Expected "%s", not "%s"' % (expHealth, actHealth))

    def testThreshCheckBadVal(self):
        comp = 'fooComp'
        bean = 'fooBean'
        fld = 'fooFld'
        lessThan = False
        thresh = 123

        tw = ThresholdWatcher(comp, bean, fld, thresh, lessThan)

        val = 'abc'
        try:
            tw.check(val)
            self.fail('Expected check to fail')
        except Exception, e:
            self.assertEquals('Threshold value for %s is %s, new value is %s' %
                              (str(tw), str(type(thresh)), str(type(val))),
                              str(e), 'Unexpected exception: ' + str(e))

    def testThreshCheckList(self):
        comp = 'fooComp'
        bean = 'fooBean'
        fld = 'fooFld'
        lessThan = False
        thresh = [1, 2, 3]

        tw = ThresholdWatcher(comp, bean, fld, thresh, lessThan)

        try:
            tw.check(thresh)
            self.fail('Expected check to fail')
        except Exception, e:
            self.assertEquals('ThresholdValue does not support lists',
                              str(e), 'Unexpected exception: ' + str(e))

    def testThreshCheck(self):
        comp = 'fooComp'
        bean = 'fooBean'
        fld = 'fooFld'
        thresh = 123

        for l in (True, False):
            tw = ThresholdWatcher(comp, bean, fld, thresh, l)

            if l:
                vFalse = thresh - 1
                vTrue = thresh + 1
            else:
                vFalse = thresh + 1
                vTrue = thresh - 1

            if l: dir = 'less than'
            else: dir = 'greater than'
            self.failIf(tw.check(vFalse),
                            'Check(%d) <%s> should be False' % (vFalse, dir))
            self.failUnless(tw.check(thresh),
                            'Check(%d) <%s> should be True' % (thresh, dir))
            self.failUnless(tw.check(vTrue),
                            'Check(%d) <%s> should be True' % (vTrue, dir))

    # ValueWatcher tests

    def testValWatchStrings(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        vw = ValueWatcher(fComp, tComp, bean, fld)

        expStr = '%s->%s %s.%s' % (fComp, tComp, bean, fld)
        actStr = str(vw)
        self.assertEquals(expStr, actStr,
                          'Expected "%s", not "%s"' % (expStr, actStr))

        expHealth = '%s not changing from %s' % (expStr, str(None))
        actHealth = vw.unhealthyString('xxx')
        self.assertEquals(expHealth, actHealth,
                          'Expected "%s", not "%s"' % (expHealth, actHealth))

        val = 111

        vw.check(val)

        expHealth = '%s not changing from %s' % (expStr, str(val))
        actHealth = vw.unhealthyString('xxx')
        self.assertEquals(expHealth, actHealth,
                          'Expected "%s", not "%s"' % (expHealth, actHealth))

    def testValWatchCheckBadVal(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = 123

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        val = 'abc'
        try:
            vw.check(val)
            self.fail('Expected check to fail')
        except Exception, e:
            self.assertEquals('Previous value for %s was %s, new value is %s' %
                              (str(vw), str(type(firstVal)), str(type(val))),
                              str(e), 'Unexpected exception: ' + str(e))

    def testValWatchCheckDecrease(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = 123

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        try:
            vw.check(firstVal - 1)
            self.fail('Expected check to fail')
        except Exception, e:
            self.assertEquals('%s DECREASED (%s->%s)' %
                              (str(vw), str(firstVal), str(firstVal - 1)),
                              str(e), 'Unexpected exception: ' + str(e))

    def testValWatchCheckAlmostStatic(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = 123

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        for i in range(ValueWatcher.NUM_UNCHANGED - 1):
            self.failIf(vw.check(firstVal),
                        'Check #%d should have succeeded' % i)

        self.failUnless(vw.check(firstVal + 1), 'Final change failed')

    def testValWatchCheckStatic(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = 123

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        for i in range(ValueWatcher.NUM_UNCHANGED - 1):
            self.failIf(vw.check(firstVal),
                        'Check #%d should have succeeded' % i)

        try:
            vw.check(firstVal)
            self.fail('Expected check#%d to fail' % ValueWatcher.NUM_UNCHANGED)
        except Exception, e:
            self.assertEquals('%s is not changing' % str(vw),
                              str(e), 'Unexpected exception: ' + str(e))

    def testValWatchCheckListBadLen(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = [1, 2, 3]

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        badList = [1, 2, 3, 4]
        try:
            vw.check(badList)
            self.fail('Expected check to fail')
        except Exception, e:
            self.assertEquals(('Previous %s list had %d entries, new list' +
                               ' has %d') % (str(vw), len(firstVal),
                                             len(badList)),
                              str(e), 'Unexpected exception: ' + str(e))

    def testValWatchCheckListAlmostStatic(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = [1, 2, 3]

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        for i in range(ValueWatcher.NUM_UNCHANGED - 1):
            self.failIf(vw.check(firstVal),
                        'Check #%d should have succeeded' % i)

        self.failUnless(vw.check([2, 3, 4]), 'Final change failed')

    def testValWatchCheckListStatic(self):
        fComp = 'fooComp'
        tComp = 'barComp'
        bean = 'fooBean'
        fld = 'fooFld'

        firstVal = [1, 2, 3]

        vw = ValueWatcher(fComp, tComp, bean, fld)
        vw.check(firstVal)

        for i in range(ValueWatcher.NUM_UNCHANGED - 1):
            self.failIf(vw.check(firstVal),
                        'Check #%d should have succeeded' % i)

        try:
            vw.check(firstVal)
            self.fail('Expected check#%d to fail' % ValueWatcher.NUM_UNCHANGED)
        except Exception, e:
            self.assertEquals('At least one %s value is not changing' % str(vw),
                              str(e), 'Unexpected exception: ' + str(e))

    # WatchData tests

    def testDataString(self):
        id = 5
        compName = 'foo'
        compId = 3

        master = {compName :
                      (('xxx', 'abean', 'a', 'i', 1),
                       ('yyy', 'abean', 'b', 'o', 2),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)

        self.assertEquals('#%d: %s#%d' % (id, compName, compId), str(wd),
                          'Unexpected WatchData string "%s"' % str(wd))

        wd = MockData(id, compName, 0, None, None, client)

        self.assertEquals('#%d: %s' % (id, compName), str(wd),
                          'Unexpected WatchData string "%s"' % str(wd))

    def testAddInput(self):
        id = 5
        compName = 'foo'
        compId = 3

        master = {compName :
                      (('xxx', 'abean', 'a', 'i', 1),
                       ('yyy', 'abean', 'b', 'o', 2),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)

        badBean = 'yyy'
        badFld = 'zzz'

        try:
            wd.addInputValue('xxx', badBean, badFld)
            self.fail('Expected addInput#1 to fail')
        except Exception, e:
            expMsg = 'Unknown MBean %s for %s#%d' % (badBean, compName, compId)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        bean = mbeans.keys()[0]

        try:
            wd.addInputValue('xxx', bean, badFld)
            self.fail('Expected addInput#2 to fail')
        except Exception, e:
            expMsg = 'Unknown MBean %s field %s for %s#%d' % \
                (bean, badFld, compName, compId)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        fld = mbeans[bean].keys()[0]

        wd.addInputValue('xxx', bean, fld)

    def testAddOutput(self):
        id = 5
        compName = 'foo'
        compId = 3

        master = {compName :
                      (('xxx', 'abean', 'a', 'i', 1),
                       ('yyy', 'abean', 'b', 'o', 2),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)

        badBean = 'yyy'
        badFld = 'zzz'

        try:
            wd.addOutputValue('xxx', badBean, badFld)
            self.fail('Expected addOutput#1 to fail')
        except Exception, e:
            expMsg = 'Unknown MBean %s for %s#%d' % (badBean, compName, compId)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        bean = mbeans.keys()[0]

        try:
            wd.addOutputValue('xxx', bean, badFld)
            self.fail('Expected addOutput#2 to fail')
        except Exception, e:
            expMsg = 'Unknown MBean %s field %s for %s#%d' % \
                (bean, badFld, compName, compId)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        fld = mbeans[bean].keys()[0]

        wd.addOutputValue('xxx', bean, fld)

    def testAddThreshold(self):
        id = 5
        compName = 'foo'
        compId = 3

        master = {compName :
                      (('xxx', 'abean', 'a', 'i', 1),
                       ('yyy', 'abean', 'b', 'o', 2),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)

        badBean = 'yyy'
        badFld = 'zzz'

        try:
            wd.addThresholdValue(badBean, badFld, 'val')
            self.fail('Expected addThreshold#1 to fail')
        except Exception, e:
            expMsg = 'Unknown MBean %s for %s#%d' % (badBean, compName, compId)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        bean = mbeans.keys()[0]

        try:
            wd.addThresholdValue(bean, badFld, 'val')
            self.fail('Expected addThreshold#2 to fail')
        except Exception, e:
            expMsg = 'Unknown MBean %s field %s for %s#%d' % \
                (bean, badFld, compName, compId)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        fld = mbeans[bean].keys()[0]

        wd.addThresholdValue(bean, fld, 'val')

    def testCheckListEmpty(self):
        id = 5
        compName = 'foo'
        compId = 3

        master = {compName :
                      (('xxx', 'abean', 'a', 'i', 1),
                       ('yyy', 'abean', 'b', 'o', 2),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)
        self.assertEquals(None, wd.checkList([]),
                          'Expected empty checkValues() to return None')

    def testCheckListOne(self):
        id = 5
        compName = 'foo'
        compId = 3

        inBean = 'abean'
        inFld = 'afld'
        inVal = 1

        master = {compName :
                      (('xxx', inBean, inFld, 'i', inVal),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)
        self.assertEquals(None, wd.checkList([]),
                          'Expected empty checkValues() to return None')

        inName = 'xxx'

        wd.addInputValue(inName, inBean, inFld)

        ul = wd.checkList(wd.inputFields)
        self.failUnless(ul is None,
                        'First check should return None, not %s' % str(ul))

        for i in range(ValueWatcher.NUM_UNCHANGED - 1):
            ul = wd.checkList(wd.inputFields)
            self.failIf(ul is None, 'Check #%d should not return None' % i)
            self.assertEquals(1, len(ul),
                              'Check #%d should return 1-element list, not %s' %
                              (i, str(ul)))
            expMsg = '%s->%s#%d %s.%s not changing from %s' % \
                (inName, compName, compId, inBean, inFld, str(inVal))
            self.assertEquals(expMsg, ul[0],
                              'Check #%d should return "%s", not "%s"' %
                              (i, expMsg, ul[0]))

        try:
            wd.checkList(wd.inputFields)
            self.fail('Expected final check to fail')
        except Exception, e:
            expMsg = '%s->%s#%d %s.%s is not changing' % \
                (inName, compName, compId, inBean, inFld)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        self.failIf(ul is None, 'Final check should not return None')
        self.assertEquals(1, len(ul),
                          'Final check should return 1-element list, not %s' %
                          str(ul))
        expMsg = '%s->%s#%d %s.%s not changing from %s' % \
            (inName, compName, compId, inBean, inFld, str(inVal))
        self.assertEquals(expMsg, ul[0],
                          'Final check should return "%s", not "%s"' %
                          (expMsg, ul[0]))

    def testCheckListMulti(self):
        id = 5
        compName = 'foo'
        compId = 3

        bean = 'xbean'

        aFld = 'afld'
        aVal = 579

        bFld = 'bfld'
        bVal = 'xxx'

        master = {compName :
                      (('xxx', bean, aFld, 'i', aVal),
                       ('yyy', bean, bFld, 'o', bVal),
                       )
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)
        self.assertEquals(None, wd.checkList([]),
                          'Expected empty checkValues() to return None')

        valName = 'xxx'

        for t in master[compName]:
            wd.addInputValue(valName, t[1], t[2])

        ul = wd.checkList(wd.inputFields)
        self.failUnless(ul is None,
                        'First check should return None, not %s' % str(ul))

        for i in range(ValueWatcher.NUM_UNCHANGED - 1):
            ul = wd.checkList(wd.inputFields)
            self.failIf(ul is None, 'Check #%d should not return None' % i)
            self.assertEquals(len(master[compName]), len(ul),
                              ('Check #%d should return %d-element list,' +
                               ' not %s') % (i, len(master[compName]), str(ul)))

            idx = 0
            for t in master[compName]:
                expMsg = '%s->%s#%d %s.%s not changing from %s' % \
                    (valName, compName, compId, t[1], t[2], str(t[4]))
                self.assertEquals(expMsg, ul[idx],
                                  'Check #%d should return "%s", not "%s"' %
                                  (i, expMsg, ul[idx]))
                idx += 1

        try:
            wd.checkList(wd.inputFields)
            self.fail('Expected final check to fail')
        except Exception, e:
            expMsg = '%s->%s#%d %s.%s is not changing' % \
                (valName, compName, compId, bean, aFld)
            self.assertEquals(expMsg, str(e),
                              'Unexpected exception: ' + str(e))

        self.failIf(ul is None, 'Final check should not return None')
        self.assertEquals(len(master[compName]), len(ul),
                          ('Final check should return %d-element list,' +
                           ' not %s') % (len(master[compName]), str(ul)))

        idx = 0
        for t in master[compName]:
            expMsg = '%s->%s#%d %s.%s not changing from %s' % \
                (valName, compName, compId, t[1], t[2], str(t[4]))
            self.assertEquals(expMsg, ul[idx],
                              'Final check should return "%s", not "%s"' %
                              (expMsg, ul[idx]))
            idx += 1

    def testCheckListChangingVal(self):
        id = 5
        compName = 'foo'
        compId = 3

        inBean = 'abean'
        inFld = 'afld'
        inVal = 1

        master = {compName :
                      (('xxx', inBean, inFld, 'i', inVal),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)
        self.assertEquals(None, wd.checkList([]),
                          'Expected empty checkValues() to return None')

        inName = 'xxx'

        wd.addInputValue(inName, inBean, inFld)

        ul = wd.checkList(wd.inputFields)
        self.failUnless(ul is None,
                        'First check should return None, not %s' % str(ul))

        for i in range(ValueWatcher.NUM_UNCHANGED * 2):
            self.__updateBean(mbeans, comp, inBean, inFld, inVal + i + 1)
            ul = wd.checkList(wd.inputFields)
            self.failUnless(ul is None, 'Check #%d should return None' % i)

    def testCheckListChangingList(self):
        id = 5
        compName = 'foo'
        compId = 3

        inBean = 'abean'
        inFld = 'afld'
        inVal = [123, 456]

        master = {compName :
                      (('xxx', inBean, inFld, 'i', inVal),
                       ),
                  }

        comp = '%s#%d' % (compName, compId)
        mbeans = self.__buildBeans(master, comp)

        client = MockRPCClient(mbeans)

        wd = MockData(id, compName, compId, None, None, client)
        self.assertEquals(None, wd.checkList([]),
                          'Expected empty checkValues() to return None')

        inName = 'xxx'

        wd.addInputValue(inName, inBean, inFld)

        ul = wd.checkList(wd.inputFields)
        self.failUnless(ul is None,
                        'First check should return None, not %s' % str(ul))

        for i in range(ValueWatcher.NUM_UNCHANGED * 2):
            newVal = [inVal[0] + (i * 100) + 1, inVal[1] + (i * 10) + 1]
            self.__updateBean(mbeans, comp, inBean, inFld, newVal)
            ul = wd.checkList(wd.inputFields)
            self.failUnless(ul is None, 'Check #%d should return None' % i)

    # RunWatchdog tests

    def testCreateWatchdogBadComp(self):
        id = 43
        name = 'foo'
        compId = 83
        addr = 'xxx'
        port = 543

        compDict = {id:MockRunComponent(name, compId, addr, port, None), }
        dataDict = {id:None}

        appender = MockAppender('log')
        appender.addExpectedExact("Couldn't create watcher for unknown" +
                                  ' component #%d type %s#%d' %
                                  (id, name, compId))

        wd = MockWatchdog(DAQLog(appender), 60.0, compDict, dataDict)

    def testCreateWatchdogBadBean(self):
        id = 43
        name = 'eventBuilder'
        compId = 83
        addr = 'xxx'
        port = 543

        comp = '%s#%d' % (name, compId)
        mbeans = self.__buildBeans({name : []}, comp)

        compDict = {id:MockRunComponent(name, compId, addr, port, None), }
        dataDict = {id:None}

        appender = MockAppender('log')
        appender.addExpectedRegexp(r"Couldn't create watcher for component" +
                                   r' #%d type %s#%d: .*' % (id, name, compId))

        wd = MockWatchdog(DAQLog(appender), 60.0, compDict, dataDict)

    def testCreateWatchdog(self):
        compDict = {}
        dataDict = {}

        nextId = 1
        for comp in ('stringHub#0', 'stringHub#10', 'inIceTrigger#0',
                     'simpleTrigger#0', 'iceTopTrigger#0', 'amandaTrigger#0',
                     'globalTrigger#0', 'eventBuilder#0',
                     'secondaryBuilders#0'):
            pound = comp.find('#')
            compName = comp[:pound]
            compId = int(comp[pound+1:])

            mbeans = self.__buildBeans(TestRunWatchdog.COMP_BEANS, comp)
            if compName == 'eventBuilder':
                self.__setStatic(mbeans, 'dispatch', 'backEnd', 'NumEventsSent')

            client = MockRPCClient(mbeans)

            id = nextId
            nextId += 1

            compDict[id] = \
                MockRunComponent(compName, compId, 'localhost', None, 100 + id)
            dataDict[id] = MockData(id, compName, compId, None, None, client)

        appender = MockAppender('log')

        wd = MockWatchdog(DAQLog(appender), 60.0, compDict, dataDict)

        self.failIf(wd.inProgress(), 'Watchdog should not be in progress')
        self.failIf(wd.isDone(), 'Watchdog should not be done')
        self.failIf(wd.isHealthy(), 'Watchdog should not be healthy')
        self.failIf(wd.caughtError(), 'Watchdog should not have error')
        appender.checkStatus(10)

        self.__runThread(wd, appender)

        for id in dataDict:
            dataDict[id].updateMBeanData()

        appender.addExpectedRegexp(r'\*\* Run watchdog reports stagnant' +
                                   r' components:.*')

        self.__runThread(wd, appender)

    def testCheckWatchdog(self):
        compDict = {}
        dataDict = {}

        nextId = 1
        for comp in ('stringHub#0', 'stringHub#10', 'inIceTrigger#0',
                     'simpleTrigger#0', 'iceTopTrigger#0', 'amandaTrigger#0',
                     'globalTrigger#0', 'eventBuilder#0',
                     'secondaryBuilders#0'):
            pound = comp.find('#')
            compName = comp[:pound]
            compId = int(comp[pound+1:])

            mbeans = self.__buildBeans(TestRunWatchdog.COMP_BEANS, comp)

            client = MockRPCClient(mbeans)

            id = nextId
            nextId += 1

            compDict[id] = \
                MockRunComponent(compName, compId, 'localhost', None, 100 + id)
            dataDict[id] = MockData(id, compName, compId, None, None, client)

        appender = MockAppender('log')

        wd = MockWatchdog(DAQLog(appender), 60.0, compDict, dataDict)

        self.failIf(wd.inProgress(), 'Watchdog should not be in progress')
        self.failIf(wd.isDone(), 'Watchdog should not be done')
        self.failIf(wd.isHealthy(), 'Watchdog should not be healthy')
        self.failIf(wd.caughtError(), 'Watchdog should not have error')
        appender.checkStatus(10)

        for n in range(2):
            for id in dataDict:
                dataDict[id].updateMBeanData()
            self.__runThread(wd, appender)

if __name__ == '__main__':
    unittest.main()
