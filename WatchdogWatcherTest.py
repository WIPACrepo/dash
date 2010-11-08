#!/usr/bin/env python

import unittest

from CnCTask import TaskException
from WatchdogTask import ThresholdWatcher, ValueWatcher

class MockComponent(object):
    def __init__(self, name, num, order, source=False, builder=False):
        self.__name = name
        self.__num = num
        self.__order = order
        self.__source = source
        self.__builder = builder

    def __str__(self):
        return self.fullName()

    def fullName(self):
        if self.__num == 0:
            return self.__name
        return self.__name + "#%d" % self.__num

    def isBuilder(self):
        return self.__builder

    def isSource(self):
        return self.__source

    def order(self):
        return self.__order

class WatchdogWatcherTest(unittest.TestCase):
    def __buildValueComps(self, fname, fnum, forder, tname, tnum, torder, bits):
        fbldr = False
        fsrc = False
        tbldr = False
        tsrc = False

        high = bits & 4 == 4
        low = bits & 3
        if low == 1:
            fbldr = high
            tsrc = not high
        elif low == 2:
            fsrc = high
            tbldr = not high
        elif low == 3:
            fsrc = high
            fbldr = not high
            tsrc = not high
            tbldr = high

        fcomp = MockComponent(fname, fnum, forder, source=fsrc, builder=fbldr)

        tcomp = MockComponent(tname, tnum, torder, source=tsrc, builder=tbldr)

        vorder = (fbldr and tsrc) and forder + 1 or \
                     ((fsrc and tbldr) and torder + 2 or forder)

        return (fcomp, tcomp, vorder)

    def testThresholdStrings(self):
        compOrder = 1
        comp = MockComponent("foo", 1, compOrder)

        beanName = "bean"
        fldName = "fld"
        for lt in False, True:
            for tv in -10, 15, 100000000000:
                tw = ThresholdWatcher(comp, beanName, fldName, tv, lt)

                nm = "%s %s.%s %s %s" % (comp.fullName(), beanName, fldName,
                                         lt and "below" or "above", tv)
                if str(tw) != nm:
                    self.fail("Expected \"%s\", not \"%s\"" % (str(tw), nm))

                uval = 16
                urec =  tw.unhealthyRecord(uval)

                self.assertEqual(urec.order(), compOrder,
                                 "Expected order %d, not %d" %
                                 (compOrder, urec.order()))

                umsg = "%s (value=%s)" % (nm, uval)
                self.assertEqual(urec.message(), umsg,
                                 "Expected message %s, not %s" %
                                 (umsg, urec.message()))

    def testThresholdBadType(self):
        comp = MockComponent("foo", 1, 1)

        beanName = "bean"
        fldName = "fld"
        threshVal = 15

        tw = ThresholdWatcher(comp, beanName, fldName, threshVal, True)

        badVal = "foo"
        try:
            tw.check(badVal)
        except TaskException, te:
            expMsg = " is %s, new value is %s" % (type(threshVal), type(badVal))
            if str(te).find(expMsg) < 0:
                raise te

    def testThresholdUnsupported(self):
        comp = MockComponent("foo", 1, 1)

        beanName = "bean"
        fldName = "fld"

        for threshVal in ["q", "r"], { "x":1, "y":2}:
            tw = ThresholdWatcher(comp, beanName, fldName, threshVal, True)
            try:
                tw.check(threshVal)
            except TaskException, te:
                expMsg = "ThresholdWatcher does not support %s" % type(threshVal)
                if str(te).find(expMsg) < 0:
                    raise te

    def testThresholdCheck(self):
        comp = MockComponent("foo", 1, 1)

        beanName = "bean"
        fldName = "fld"
        threshVal = 15

        for lt in False, True:
            tw = ThresholdWatcher(comp, beanName, fldName, threshVal, lt)

            for val in threshVal - 5, threshVal - 1, threshVal, threshVal + 1, \
                    threshVal + 5:

                if lt:
                    cmpVal = val >= threshVal
                else:
                    cmpVal = val <= threshVal

                if tw.check(val) != cmpVal:
                    self.fail("ThresholdWatcher(%d) returned %s for value %d" %
                              (threshVal, not cmpVal, val))

    def testValueStrings(self):
        for bits in range(1, 8):
            (fcomp, tcomp, uorder) = \
                    self.__buildValueComps("foo", 1, 1, "bar", 0, 10, bits)

            beanName = "bean"
            fldName = "fld"

            vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

            nm = "%s->%s %s.%s" % (fcomp.fullName(), tcomp.fullName(), beanName,
                                   fldName)
            if str(vw) != nm:
                self.fail("Expected \"%s\", not \"%s\"" % (str(vw), nm))

            uval = 16
            urec =  vw.unhealthyRecord(uval)

            self.assertEqual(urec.order(), uorder,
                             "Expected order %d, not %d" %
                             (uorder, urec.order()))

            umsg = "%s not changing from %s" % (nm, None)
            self.assertEqual(urec.message(), umsg,
                             "Expected message %s, not %s" %
                             (umsg, urec.message()))

    def testValueBadType(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        prevVal = 5
        vw.check(prevVal)

        badVal = "foo"
        try:
            vw.check(badVal)
        except TaskException, te:
            expMsg = " was %s (%s), new type is %s (%s)" % \
                     (type(prevVal), prevVal, type(badVal), badVal)
            if str(te).find(expMsg) < 0:
                raise te

    def testValueCheckListSize(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        lst = [1, 15, 7, 3]
        rtnval = vw.check(lst)

        l2 = lst[:-1]
        try:
            rtnval = vw.check(l2)
        except TaskException, te:
            expMsg = "Previous %s list had %d entries, new list has %d" % \
                     (vw, len(lst), len(l2))
            if str(te).find(expMsg) < 0:
                raise te

    def testValueCheckDecreased(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        val = 15
        rtnval = vw.check(val)

        try:
            rtnval = vw.check(val - 2)
        except TaskException, te:
            expMsg = "%s DECREASED (%s->%s)" % (vw, val, val - 2)
            if str(te).find(expMsg) < 0:
                raise te

    def testValueCheckDecreasedList(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        lst = [1, 15, 7, 3]
        rtnval = vw.check(lst)

        l2 = lst[:]
        for i in range(len(l2)):
            l2[i] -= 2

        try:
            rtnval = vw.check(l2)
        except TaskException, te:
            expMsg = "%s DECREASED (%s->%s)" % (vw, lst[0], l2[0])
            if str(te).find(expMsg) < 0:
                raise te

    def testValueCheckUnchanged(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        val = 5

        sawUnchanged = False
        for i in range(4):
            try:
                rtnval = vw.check(val)
            except TaskException, te:
                expMsg = "%s.%s is not changing" % (beanName, fldName)
                if str(te).find(expMsg) < 0:
                    raise te
                sawUnchanged = True

        if not sawUnchanged:
            self.fail("Never saw \"unchanged\" exception")


    def testValueCheckUnchangedList(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        lst = [1, 15, 7, 3]

        sawUnchanged = False
        for i in range(4):
            try:
                rtnval = vw.check(lst)
            except TaskException, te:
                expMsg = "At least one %s value is not changing" % vw
                if str(te).find(expMsg) < 0:
                    raise te
                sawUnchanged = True

        if not sawUnchanged:
            self.fail("Never saw \"unchanged\" exception")

    def testValueUnsupported(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        prevVal = { "a":1, "b":2 }
        vw.check(prevVal)

        badVal = { "a":1, "b":2 }
        try:
            vw.check(badVal)
        except TaskException, te:
            expMsg = "ValueWatcher does not support %s" % type(badVal)
            if str(te).find(expMsg) < 0:
                raise te

    def testValueCheck(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        for val in range(4):
            rtnval = vw.check(val)

    def testValueCheckList(self):
        (fcomp, tcomp, uorder) = \
                self.__buildValueComps("foo", 1, 1, "bar", 0, 10, 0)

        beanName = "bean"
        fldName = "fld"

        vw = ValueWatcher(fcomp, tcomp, beanName, fldName)

        lst = [1, 15, 7, 3]

        for i in range(4):
            l2 = lst[:]
            for n in range(len(lst)):
                l2[n] += i
            rtnval = vw.check(l2)

if __name__ == '__main__':
    unittest.main()
