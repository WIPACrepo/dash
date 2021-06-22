#!/usr/bin/env python

import unittest

from WatchdogTask import UnhealthyRecord, WatchData


class MockBean(object):
    def __init__(self, val):
        self.__val = val

    def _set_value(self, new_val):
        self.__val = new_val

    def _value(self):
        return self.__val


class MockBeanDecreasing(MockBean):
    def __init__(self, val, dec=1):
        self.__dec = dec
        super(MockBeanDecreasing, self).__init__(val)

    @property
    def next_value(self):
        new_val = self._value() - self.__dec
        self._set_value(new_val)
        return new_val


class MockBeanIncreasing(MockBean):
    def __init__(self, val, inc=1):
        self.__inc = inc
        super(MockBeanIncreasing, self).__init__(val)

    @property
    def next_value(self):
        new_val = self._value() + self.__inc
        self._set_value(new_val)
        return new_val


class MockBeanStagnant(MockBean):
    def __init__(self, val, count_down):
        self.__count_down = count_down
        super(MockBeanStagnant, self).__init__(val)

    @property
    def next_value(self):
        val = self._value()
        if self.__count_down == 0:
            return val
        self.__count_down -= 1
        val += 1
        self._set_value(val)
        return val


class MockBeanTimeBomb(MockBeanIncreasing):
    def __init__(self, val, inc, bomb_ticks):
        self.__bomb_ticks = bomb_ticks
        super(MockBeanTimeBomb, self).__init__(val, inc)

    @property
    def next_value(self):
        if self.__bomb_ticks == 0:
            raise Exception("TimeBomb")
        self.__bomb_ticks -= 1
        return super(MockBeanTimeBomb, self).next_value


class MockMBeanClient(object):
    def __init__(self):
        self.__bean_data = {}

    def __check_add_bean(self, name, fld_name):
        if name not in self.__bean_data:
            self.__bean_data[name] = {}
        if fld_name in self.__bean_data[name]:
            raise Exception("Cannot add duplicate bean %s.%s to %s" %
                            (name, fld_name, self.fullname))

    def add_decreasing(self, name, fld_name, val, dec):
        self.__check_add_bean(name, fld_name)
        self.__bean_data[name][fld_name] = MockBeanDecreasing(val, dec)

    def add_increasing(self, name, fld_name, val, inc):
        self.__check_add_bean(name, fld_name)
        self.__bean_data[name][fld_name] = MockBeanIncreasing(val, inc)

    def add_stagnant(self, name, fld_name, val, count_down):
        self.__check_add_bean(name, fld_name)
        self.__bean_data[name][fld_name] = MockBeanStagnant(val, count_down)

    def add_time_bomb(self, name, fld_name, val, inc, bomb_ticks):
        self.__check_add_bean(name, fld_name)
        self.__bean_data[name][fld_name] = MockBeanTimeBomb(val, inc,
                                                            bomb_ticks)

    def check(self, name, fld_name):
        if name not in self.__bean_data or \
           fld_name not in self.__bean_data[name]:
            raise Exception("Unknown %s bean %s.%s" %
                            (self.fullname, name, fld_name))

    @property
    def fullname(self):
        return "MockMBeanClient"

    def get(self, bean_name, fld_name):
        self.check(bean_name, fld_name)
        return self.__bean_data[bean_name][fld_name].next_value

    def get_attributes(self, bean_name, fld_list):
        rtn_map = {}
        for fld in fld_list:
            rtn_map[fld] = self.get(bean_name, fld)
        return rtn_map


class MockComponent(object):
    def __init__(self, name, num, order, mbean_client, source=False,
                 builder=False):
        self.__name = name
        self.__num = num
        self.__order = order
        self.__mbean_client = mbean_client
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


class WatchdogDataTest(unittest.TestCase):
    def test_create(self):
        comp = MockComponent("foo", 1, 1, MockMBeanClient())

        wdata = WatchData(comp, None, None)
        self.assertEqual(comp.order, wdata.order,
                         "Expected WatchData order %d, not %d" %
                         (comp.order, wdata.order))

    def test_check_values_good(self):
        bean_name = "bean"
        in_name = "inFld"
        out_name = "outFld"
        lt_name = "ltFld"
        gt_name = "gtFld"

        thresh_val = 15

        mbean_client = MockMBeanClient()
        mbean_client.add_increasing(bean_name, in_name, 12, 1)
        mbean_client.add_increasing(bean_name, out_name, 5, 1)
        mbean_client.add_increasing(bean_name, lt_name, thresh_val, 1)
        mbean_client.add_decreasing(bean_name, gt_name, thresh_val, 1)

        comp = MockComponent("foo", 1, 1, mbean_client)
        other = MockComponent("other", 0, 17, MockMBeanClient())

        wdata = WatchData(comp, mbean_client, None)

        wdata.add_input_value(other, bean_name, in_name)
        wdata.add_output_value(other, bean_name, out_name)
        wdata.add_threshold_value(bean_name, lt_name, thresh_val, True)
        wdata.add_threshold_value(bean_name, gt_name, thresh_val, False)

        starved = []
        stagnant = []
        threshold = []
        for i in range(4):
            if not wdata.check(starved, stagnant, threshold):
                self.fail("Check #%d failed" % i)
            self.assertEqual(0, len(starved),
                             "Check #%d returned %d starved (%s)" %
                             (i, len(starved), starved))
            self.assertEqual(0, len(stagnant),
                             "Check #%d returned %d stagnant (%s)" %
                             (i, len(stagnant), stagnant))
            self.assertEqual(0, len(threshold),
                             "Check #%d returned %d threshold (%s)" %
                             (i, len(threshold), threshold))

    def test_check_values_fail_one(self):
        bean_name = "bean"
        in_name = "inFld"
        out_name = "outFld"
        gt_name = "gtFld"

        starve_val = 12
        stagnant_val = 5
        thresh_val = 15
        fail_num = 2

        for fidx in range(2):
            mbean_client = MockMBeanClient()

            comp = MockComponent("foo", 1, 1, mbean_client)
            other = MockComponent("other", 0, 17, MockMBeanClient())

            wdata = WatchData(comp, mbean_client, None)

            if fidx == 0:
                mbean_client.add_stagnant(bean_name, in_name, starve_val,
                                          fail_num)
                wdata.add_input_value(other, bean_name, in_name)
            elif fidx == 1:
                mbean_client.add_stagnant(bean_name, out_name, stagnant_val,
                                          fail_num)
                wdata.add_output_value(other, bean_name, out_name)

            mbean_client.add_increasing(bean_name, gt_name,
                                        thresh_val - fail_num, 1)
            wdata.add_threshold_value(bean_name, gt_name, thresh_val, False)

            for idx in range(5):
                starved = []
                stagnant = []
                threshold = []
                rtnval = wdata.check(starved, stagnant, threshold)

                n_starved = 0
                n_stagnant = 0
                n_threshold = 0

                if idx < fail_num:
                    self.assertTrue(rtnval, "Check #%d failed" % idx)
                else:
                    self.assertTrue(not rtnval, "Check #%d succeeded" % idx)
                    if fidx == 0:
                        n_starved = 1
                        n_stagnant = 0
                    else:
                        n_starved = 0
                        n_stagnant = 1
                    n_threshold = 1

                self.assertEqual(n_starved, len(starved),
                                 "Check #%d returned %d starved (%s)" %
                                 (idx, len(starved), starved))
                self.assertEqual(n_stagnant, len(stagnant),
                                 "Check #%d returned %d stagnant (%s)" %
                                 (idx, len(stagnant), stagnant))
                self.assertEqual(n_threshold, len(threshold),
                                 "Check #%d returned %d threshold (%s)" %
                                 (idx, len(threshold), threshold))

                if n_starved > 0:
                    msg = UnhealthyRecord(
                        ("%s->%s %s.%s not changing from %d") %
                        (other, comp, bean_name, in_name,
                         starve_val + fail_num), other.order)
                    self.assertEqual(msg, starved[0],
                                     ("Check #%d starved#1 should be" +
                                      " \"%s\" not \"%s\"") %
                                     (idx, msg, starved[0]))

                if n_stagnant > 0:
                    msg = UnhealthyRecord(("%s->%s %s.%s not changing" +
                                           " from %d") %
                                          (comp, other, bean_name, out_name,
                                           stagnant_val + fail_num),
                                          comp.order)
                    self.assertEqual(msg, stagnant[0],
                                     ("Check #%d stagnant#1 should be" +
                                      " \"%s\" not \"%s\"") %
                                     (idx, msg, stagnant[0]))

                if n_threshold > 0:
                    msg = UnhealthyRecord("%s %s.%s above %d (value=%d)" %
                                          (comp, bean_name, gt_name,
                                           thresh_val,
                                           thresh_val + idx - (fail_num - 1)),
                                          comp.order)
                    self.assertEqual(msg, threshold[0],
                                     ("Check #%d threshold#1 should be" +
                                      " \"%s\" not \"%s\"") %
                                     (idx, msg, threshold[0]))

    def test_check_values_time_bomb(self):
        bean_name = "bean"
        in_name = "inFld"
        out_name = "outFld"
        gt_name = "gtFld"

        t_val = 10
        lt_thresh = True
        bomb_ticks = 2

        for fidx in range(3):
            mbean_client = MockMBeanClient()

            comp = MockComponent("foo", 1, 1, mbean_client)
            other = MockComponent("other", 0, 17, MockMBeanClient())

            wdata = WatchData(comp, mbean_client, None)

            if fidx == 0:
                mbean_client.add_time_bomb(bean_name, in_name, t_val, 1,
                                           bomb_ticks)
                wdata.add_input_value(other, bean_name, in_name)
            elif fidx == 1:
                mbean_client.add_time_bomb(bean_name, out_name, t_val, 1,
                                           bomb_ticks)
                wdata.add_output_value(other, bean_name, out_name)
            elif fidx == 2:
                mbean_client.add_time_bomb(bean_name, gt_name, t_val, 1,
                                           bomb_ticks)
                wdata.add_threshold_value(bean_name, gt_name, t_val, lt_thresh)

            for idx in range(bomb_ticks + 1):
                starved = []
                stagnant = []
                threshold = []
                rtnval = wdata.check(starved, stagnant, threshold)

                n_starved = 0
                n_stagnant = 0
                n_threshold = 0

                if idx < bomb_ticks:
                    self.assertTrue(rtnval, "Check #%d failed" % idx)
                else:
                    self.assertTrue(not rtnval, "Check #%d succeeded" % idx)
                    if fidx == 0:
                        n_starved = 1
                    elif fidx == 1:
                        n_stagnant = 1
                    elif fidx == 2:
                        n_threshold = 1

                self.assertEqual(n_starved, len(starved),
                                 "Check #%d returned %d starved (%s)" %
                                 (idx, len(starved), starved))
                self.assertEqual(n_stagnant, len(stagnant),
                                 "Check #%d returned %d stagnant (%s)" %
                                 (idx, len(stagnant), stagnant))
                self.assertEqual(n_threshold, len(threshold),
                                 "Check #%d returned %d threshold (%s)" %
                                 (idx, len(threshold), threshold))

                front = None
                bad_rec = None

                if n_starved > 0:
                    front = "%s->%s %s.%s" % (other, comp, bean_name, in_name)
                    bad_rec = starved[0]
                elif n_stagnant > 0:
                    front = "%s->%s %s.%s" % (comp, other, bean_name, out_name)
                    bad_rec = stagnant[0]
                elif n_threshold > 0:
                    front = "%s %s.%s %s %s" % \
                            (comp, bean_name, gt_name,
                             lt_thresh and "below" or "above", t_val)
                    bad_rec = threshold[0]

                if front is not None:
                    self.assertTrue(bad_rec is not None,
                                    "No UnhealthyRecord found for " + front)

                    front += ': Exception("TimeBomb")'
                    if bad_rec.message.find(front) != 0:
                        self.fail(("Expected UnhealthyRecord %s to start" +
                                   " with \"%s\"") % (bad_rec, front))


if __name__ == '__main__':
    unittest.main()
