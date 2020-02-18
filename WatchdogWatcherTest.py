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
        return self.fullname

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return self.__name + "#%d" % self.__num

    @property
    def is_builder(self):
        return self.__builder

    @property
    def is_source(self):
        return self.__source

    @property
    def order(self):
        return self.__order


class WatchdogWatcherTest(unittest.TestCase):
    def __build_value_comps(self, fname, fnum, forder, tname, tnum, torder,
                            bits):
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

    def test_threshold_strings(self):
        comp_order = 1
        comp = MockComponent("foo", 1, comp_order)

        bean_name = "bean"
        fld_name = "fld"
        for less_than in False, True:
            for thresh_val in -10, 15, 100000000000:
                watcher = ThresholdWatcher(comp, bean_name, fld_name,
                                           thresh_val, less_than)

                name = "%s %s.%s %s %s" % (comp.fullname, bean_name, fld_name,
                                           less_than and "below" or "above",
                                           thresh_val)
                if str(watcher) != name:
                    self.fail("Expected \"%s\", not \"%s\"" %
                              (str(watcher), name))

                uval = 16
                urec = watcher.unhealthy_record(uval)

                self.assertEqual(urec.order, comp_order,
                                 "Expected order %d, not %d" %
                                 (comp_order, urec.order))

                umsg = "%s (value=%s)" % (name, uval)
                self.assertEqual(urec.message, umsg,
                                 "Expected message %s, not %s" %
                                 (umsg, urec.message))

    def test_threshold_bad_type(self):
        comp = MockComponent("foo", 1, 1)

        bean_name = "bean"
        fld_name = "fld"
        thresh_val = 15

        watcher = ThresholdWatcher(comp, bean_name, fld_name, thresh_val, True)

        bad_val = "foo"
        try:
            watcher.check(bad_val)
        except TaskException as tex:
            exp_msg = " is %s, new value is %s" % \
                (type(thresh_val), type(bad_val))
            if str(tex).find(exp_msg) < 0:
                raise

    def test_threshold_unsupported(self):
        comp = MockComponent("foo", 1, 1)

        bean_name = "bean"
        fld_name = "fld"

        for thresh_val in ["q", "r"], {"x": 1, "y": 2}:
            watcher = ThresholdWatcher(comp, bean_name, fld_name, thresh_val,
                                       True)
            try:
                watcher.check(thresh_val)
            except TaskException as tex:
                exp_msg = "ThresholdWatcher does not support %s" % \
                    type(thresh_val)
                if str(tex).find(exp_msg) < 0:
                    raise

    def test_threshold_check(self):
        comp = MockComponent("foo", 1, 1)

        bean_name = "bean"
        fld_name = "fld"
        thresh_val = 15

        for less_than in False, True:
            watcher = ThresholdWatcher(comp, bean_name, fld_name, thresh_val,
                                       less_than)

            for val in thresh_val - 5, thresh_val - 1, thresh_val, \
                    thresh_val + 1, thresh_val + 5:

                if less_than:
                    cmp_val = val >= thresh_val
                else:
                    cmp_val = val <= thresh_val

                if watcher.check(val) != cmp_val:
                    self.fail("ThresholdWatcher(%d) returned %s for value %d" %
                              (thresh_val, not cmp_val, val))

    def test_value_strings(self):
        for bits in range(1, 8):
            (fcomp, tcomp, uorder) = \
                    self.__build_value_comps("foo", 1, 1, "bar", 0, 10, bits)

            bean_name = "bean"
            fld_name = "fld"

            watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

            name = "%s->%s %s.%s" % (fcomp.fullname, tcomp.fullname,
                                     bean_name, fld_name)
            if str(watcher) != name:
                self.fail("Expected \"%s\", not \"%s\"" % (str(watcher), name))

            uval = 16
            urec = watcher.unhealthy_record(uval)

            self.assertEqual(urec.order, uorder,
                             "Expected order %d, not %d" %
                             (uorder, urec.order))

            umsg = "%s not changing from %s" % (name, None)
            self.assertEqual(urec.message, umsg,
                             "Expected message %s, not %s" %
                             (umsg, urec.message))

    def test_value_bad_type(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        prev_val = 5
        watcher.check(prev_val)

        bad_val = "foo"
        try:
            watcher.check(bad_val)
        except TaskException as tex:
            exp_msg = " was %s (%s), new type is %s (%s)" % \
                     (type(prev_val), prev_val, type(bad_val), bad_val)
            if str(tex).find(exp_msg) < 0:
                raise

    def test_value_check_list_size(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        lst = [1, 15, 7, 3]
        watcher.check(lst)

        ls2 = lst[:-1]
        try:
            watcher.check(ls2)
        except TaskException as tex:
            exp_msg = "Previous %s list had %d entries, new list has %d" % \
                     (watcher, len(lst), len(ls2))
            if str(tex).find(exp_msg) < 0:
                raise

    def test_value_check_decreased(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        val = 15
        watcher.check(val)

        try:
            watcher.check(val - 2)
        except TaskException as tex:
            exp_msg = "%s DECREASED (%s->%s)" % (watcher, val, val - 2)
            if str(tex).find(exp_msg) < 0:
                raise

    def test_value_check_decreased_list(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        lst = [1, 15, 7, 3]
        watcher.check(lst)

        ls2 = lst[:]
        for idx in range(len(ls2)):
            ls2[idx] -= 2

        try:
            watcher.check(ls2)
        except TaskException as tex:
            exp_msg = "%s DECREASED (%s->%s)" % (watcher, lst[0], ls2[0])
            if str(tex).find(exp_msg) < 0:
                raise

    def test_value_check_unchanged(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        val = 5

        saw_unchanged = False
        for _ in range(4):
            try:
                watcher.check(val)
            except TaskException as tex:
                exp_msg = "%s.%s is not changing" % (bean_name, fld_name)
                if str(tex).find(exp_msg) < 0:
                    raise
                saw_unchanged = True

        if not saw_unchanged:
            self.fail("Never saw \"unchanged\" exception")

    def test_value_check_unchanged_list(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        lst = [1, 15, 7, 3]

        saw_unchanged = False
        for _ in range(4):
            try:
                watcher.check(lst)
            except TaskException as tex:
                exp_msg = "At least one %s value is not changing" % watcher
                if str(tex).find(exp_msg) < 0:
                    raise
                saw_unchanged = True

        if not saw_unchanged:
            self.fail("Never saw \"unchanged\" exception")

    def test_value_unsupported(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        prev_val = {"a": 1, "b": 2}
        watcher.check(prev_val)

        bad_val = {"a": 1, "b": 2}
        try:
            watcher.check(bad_val)
        except TaskException as tex:
            exp_msg = "ValueWatcher does not support %s" % type(bad_val)
            if str(tex).find(exp_msg) < 0:
                raise

    def test_value_check(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        for val in range(4):
            watcher.check(val)

    def test_value_check_list(self):
        (fcomp, tcomp, _) = \
                self.__build_value_comps("foo", 1, 1, "bar", 0, 10, 0)

        bean_name = "bean"
        fld_name = "fld"

        watcher = ValueWatcher(fcomp, tcomp, bean_name, fld_name)

        lst = [1, 15, 7, 3]

        for idx in range(4):
            ls2 = lst[:]
            for idx2 in range(len(lst)):
                ls2[idx2] += idx
            watcher.check(ls2)


if __name__ == '__main__':
    unittest.main()
