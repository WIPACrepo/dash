#!/usr/bin/env python

import sys

from CnCTask import CnCTask, TaskException
from CnCThread import CnCThread
from Component import Component
from ComponentManager import ComponentManager
from decorators import classproperty
from i3helper import Comparable, reraise_excinfo

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class UnhealthyRecord(Comparable):
    "Record of a problem, including the order so problems can be prioritized"

    def __init__(self, msg, order):
        "Create an unhealthy record"
        self.__msg = msg
        self.__order = order

    def __repr__(self):
        "Return the string representation of this object"
        return str(self)

    def __str__(self):
        """
        Return a string containing the order and the description of the problem
        """
        return "#%d: %s" % (self.__order, self.__msg)

    def __cmp__(self, other):
        "Compare this record with others"
        if not isinstance(other, UnhealthyRecord):
            return -1

        val = cmp(self.__order, other.order)
        if val == 0:
            val = cmp(self.__msg, other.message)
        return val

    @property
    def compare_tuple(self):
        return (self.__order, self.__msg)

    @property
    def message(self):
        "Return the description of this problem"
        return self.__msg

    @property
    def order(self):
        "Return the order of this problem"
        return self.__order


class Watcher(object):
    "Watch an MBean value"

    def __init__(self, full_name, bean_name, field_name):
        "Create a watcher"
        self.__full_name = full_name
        self.__bean_name = bean_name
        self.__field_name = field_name

    def __repr__(self):
        "Return the name of this watcher"
        return self.__full_name

    def __str__(self):
        "Return the name of this watcher"
        return self.__full_name

    def bean_name(self):
        "Return the name of the MBean to be watched"
        return self.__bean_name

    def field_name(self):
        "Return the name of the MBean field to be watched"
        return self.__field_name

    @classmethod
    def type_category(cls, val):
        "Return the type of this value, coercing 'tuple' to 'list'"
        vtype = type(val)
        if vtype == tuple:
            return list
        return vtype


class ThresholdWatcher(Watcher):
    "Watch a value, making sure that it is below or above a threshold value"

    def __init__(self, comp, bean_name, field_name, threshold, less_than):
        "Create a threshold watcher"
        self.__comp = comp
        self.__threshold = threshold
        self.__less_than = less_than

        if self.__less_than:
            updown = "below"
        else:
            updown = "above"

        full_name = "%s %s.%s %s %s" % \
            (comp.fullname, bean_name, field_name, updown, self.__threshold)
        super(ThresholdWatcher, self).__init__(full_name, bean_name, field_name)

    def __compare(self, threshold, value):
        "Check the value against the threshold value"
        if self.__less_than:
            return value < threshold
        return value > threshold

    def check(self, new_value):
        "Check the current value against the threshold value"
        new_type = self.type_category(new_value)
        thresh_type = self.type_category(self.__threshold)

        if new_type != thresh_type:
            raise TaskException(("Threshold value for %s is %s, new value" +
                                 " is %s") %
                                (str(self), str(type(self.__threshold)),
                                 str(type(new_value))))
        elif new_type == list or new_type == dict:
            raise TaskException("ThresholdWatcher does not support %s" %
                                new_type)
        elif self.__compare(self.__threshold, new_value):
            return False

        return True

    def unhealthy_record(self, value):
        "Create an UnhealthyRecord for this threshold"
        if isinstance(value, Exception) and \
                not isinstance(value, TaskException):
            msg = "%s: %s" % (str(self), exc_string())
        else:
            msg = "%s (value=%s)" % (str(self), str(value))
        return UnhealthyRecord(msg, self.__comp.order)


class ValueWatcher(Watcher):
    "Watch a value, making sure that it always increases"

    # number of checks which can be unchanged before we think there's a problem
    NUM_UNCHANGED = 3

    def __init__(self, from_comp, to_comp, bean_name, field_name):
        "Create a value watcher"
        self.__from_comp = from_comp
        self.__to_comp = to_comp
        self.__order = self.__compute_order(bean_name, field_name)
        self.__prev_value = None
        self.__unchanged = 0

        full_name = "%s->%s %s.%s" % (from_comp.fullname, to_comp.fullname,
                                      bean_name, field_name)
        super(ValueWatcher, self).__init__(full_name, bean_name, field_name)

    def __compare(self, old_value, new_value):
        "Compare the current value against the previous value"
        if new_value < old_value:
            raise TaskException("%s DECREASED (%s->%s)" %
                                (str(self), str(old_value), str(new_value)))

        return new_value == old_value

    def __compute_order(self, bean_name, field_name):
        "Compute the order of this component in the DAQ data flow"
        if self.__from_comp.is_builder and self.__to_comp.is_source:
            return self.__from_comp.order + 1

        if self.__from_comp.is_source and self.__to_comp.is_builder:
            return self.__to_comp.order + 2

        return self.__from_comp.order

    def check(self, new_value):
        "Check the current value against the previous value"
        if self.__prev_value is None:
            if isinstance(new_value, list):
                self.__prev_value = new_value[:]
            else:
                self.__prev_value = new_value
            return True

        new_type = self.type_category(new_value)
        prev_type = self.type_category(self.__prev_value)

        if new_type != prev_type:
            raise TaskException(("Previous type for %s was %s (%s)," +
                                 " new type is %s (%s)") %
                                (str(self), str(type(self.__prev_value)),
                                 str(self.__prev_value),
                                 str(type(new_value)), str(new_value)))

        if new_type == dict:
            raise TaskException("ValueWatcher does not support %s" % new_type)

        if new_type != list:
            try:
                cmp_eq = self.__compare(self.__prev_value, new_value)
            except TaskException:
                self.__unchanged = 0
                raise

            if cmp_eq:
                self.__unchanged += 1
                if self.__unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise TaskException(str(self) + " is not changing")
            else:
                self.__unchanged = 0
                self.__prev_value = new_value
        elif len(new_value) != len(self.__prev_value):
            raise TaskException(("Previous %s list had %d entries, new list" +
                                 " has %d") %
                                (str(self), len(self.__prev_value),
                                 len(new_value)))
        else:
            tmp_stag = False
            tmp_exc = None
            for idx, value in enumerate(new_value):
                try:
                    cmp_eq = self.__compare(self.__prev_value[idx],
                                            value)
                except TaskException:
                    if not tmp_exc:
                        tmp_exc = sys.exc_info()
                    cmp_eq = False

                if cmp_eq:
                    tmp_stag = True
                else:
                    self.__prev_value[idx] = value

            if not tmp_stag:
                self.__unchanged = 0
            else:
                self.__unchanged += 1
                if self.__unchanged == ValueWatcher.NUM_UNCHANGED:
                    raise TaskException(("At least one %s value is not" +
                                         " changing") % str(self))

            if tmp_exc:
                reraise_excinfo(tmp_exc)

        return self.__unchanged == 0

    def unhealthy_record(self, value):
        "Create an UnhealthyRecord for this value"
        if isinstance(value, Exception) and \
               not isinstance(value, TaskException):
            msg = "%s: %s" % (str(self), exc_string())
        else:
            msg = "%s not changing from %s" % (str(self),
                                               str(self.__prev_value))
        return UnhealthyRecord(msg, self.__order)


class WatchData(object):
    "Object which holds all the watched MBean fields for a component"

    def __init__(self, comp, mbean_client, dashlog):
        "Create a data-watching object"
        self.__comp = comp
        self.__mbean_client = mbean_client
        self.__dashlog = dashlog

        self.__input_fields = {}
        self.__output_fields = {}
        self.__threshold_fields = {}

        self.__closed = False

    def __str__(self):
        "Return the name of the component associated with this data"
        return self.__comp.fullname

    def __check_beans(self, bean_list):
        "Check values for all MBeans in 'bean_list'"
        unhealthy = []
        for bean in bean_list:
            if self.__closed:
                # break out of the loop if this thread has been closed
                break
            bad_list = self.__check_values(bean_list[bean])
            if bad_list is not None:
                unhealthy += bad_list

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def __check_values(self, watch_list):
        "Check all values in 'watch_list'"
        unhealthy = []
        if len(watch_list) == 1:
            try:
                bean_name = watch_list[0].bean_name()
                fld_name = watch_list[0].field_name()
                val = self.__mbean_client.get(bean_name, fld_name)

                chk_val = watch_list[0].check(val)
            except Exception as exc:
                unhealthy.append(watch_list[0].unhealthy_record(exc))
                chk_val = True
            if not chk_val:
                unhealthy.append(watch_list[0].unhealthy_record(val))
        else:
            bean_name = None
            fld_list = []
            for fld in watch_list:
                if bean_name is None:
                    bean_name = fld.bean_name()
                elif bean_name != fld.bean_name():
                    self.__dashlog.error("NOT requesting fields from multiple"
                                         " beans (%s != %s)" %
                                         (bean_name, fld.bean_name()))
                    continue
                fld_list.append(fld.field_name())

            try:
                val_map = self.__mbean_client.get_attributes(bean_name,
                                                             fld_list)
            except Exception as exc:
                fld_list = []
                unhealthy.append(watch_list[0].unhealthy_record(exc))

            for index, fld_val in enumerate(fld_list):
                try:
                    val = val_map[fld_val]
                except KeyError:
                    self.__dashlog.error("No value found for %s field#%d %s" %
                                         (self.__comp.fullname, index,
                                          fld_val))
                    continue

                try:
                    chk_val = watch_list[index].check(val)
                except Exception as exc:
                    unhealthy.append(watch_list[index].unhealthy_record(exc))
                    chk_val = True
                if not chk_val:
                    unhealthy.append(watch_list[index].unhealthy_record(val))

        if len(unhealthy) == 0:
            return None

        return unhealthy

    def add_input_value(self, other_comp, bean_name, field_name):
        "Add a rule which triggers when an input field value stops increasing"
        if bean_name not in self.__input_fields:
            self.__input_fields[bean_name] = []

        watch = ValueWatcher(other_comp, self.__comp, bean_name, field_name)
        self.__input_fields[bean_name].append(watch)

    def add_output_value(self, other_comp, bean_name, field_name):
        "Add a rule which triggers when an output field value stops increasing"
        if bean_name not in self.__output_fields:
            self.__output_fields[bean_name] = []

        watch = ValueWatcher(self.__comp, other_comp, bean_name, field_name)
        self.__output_fields[bean_name].append(watch)

    def add_threshold_value(self, bean_name, field_name, threshold,
                            less_than=True):
        """
        Add a rule which triggers when a field value drops below the threshold
        value (or, if less_than==False, the value rises above the threshold)
        """

        if bean_name not in self.__threshold_fields:
            self.__threshold_fields[bean_name] = []

        watch = ThresholdWatcher(self.__comp, bean_name, field_name, threshold,
                                 less_than)
        self.__threshold_fields[bean_name].append(watch)

    def check(self, starved, stagnant, threshold):
        """
        Check for problems with this component's data flow.
        Input problems are added to the 'starved' list.
        Output problems are added to the 'stagnant' list.
        Quantities which are too large/small are added to the 'threshold' list.
        """
        is_ok = True

        # look for input problems
        if not self.__closed:
            try:
                bad_list = self.__check_beans(self.__input_fields)
                if bad_list is not None:
                    # add any input problems to the 'starved' list
                    starved += bad_list
                    is_ok = False
            except:
                self.__dashlog.error(self.__comp.fullname + " inputs: " +
                                     exc_string())
                is_ok = False

        # only look for output problems if there are no input problems
        if not self.__closed and is_ok:
            try:
                bad_list = self.__check_beans(self.__output_fields)
                if bad_list is not None:
                    # add any output problems to the 'stagnant' list
                    stagnant += bad_list
                    is_ok = False
            except:
                self.__dashlog.error(self.__comp.fullname + " outputs: " +
                                     exc_string())
                is_ok = False

        # look for threshold problems
        if not self.__closed:
            try:
                bad_list = self.__check_beans(self.__threshold_fields)
                if bad_list is not None:
                    # add any threshold problems (value too big or too small)
                    #  to the 'threshold' list
                    threshold += bad_list
                    is_ok = False
            except:
                self.__dashlog.error(self.__comp.fullname + " thresholds: " +
                                     exc_string())
                is_ok = False

        return is_ok

    def close(self):
        "Mark this data object as 'closed'"
        self.__closed = True

    @property
    def order(self):
        "Return the order of the component associated with this data"
        return self.__comp.order


class WatchdogThread(CnCThread):
    "Thread which checks a rule for a component"

    def __init__(self, runset, comp, rule, dashlog, data=None, init_fail=0,
                 mbean_client=None):
        "Create a watchdog thread"
        self.__runset = runset
        self.__comp = comp
        if mbean_client is not None:
            self.__mbean_client = mbean_client
        else:
            self.__mbean_client = comp.create_mbean_client()
        self.__rule = rule
        self.__dashlog = dashlog

        self.__data = data
        self.__init_fail = init_fail

        self.__starved = []
        self.__stagnant = []
        self.__threshold = []

        super(WatchdogThread, self).__init__(self.__comp.fullname + ":" +
                                             str(self.__rule), self.__dashlog)

    def __str__(self):
        "Return the name of the component associated with this rule"
        return self.__comp.fullname

    def _run(self):
        "Run this task"
        if self.isClosed:
            return

        if self.__data is None:
            try:
                self.__data = self.__rule.create_data(
                    self.__comp,
                    self.__mbean_client,
                    self.__runset.components(),
                    self.__dashlog)
            except:
                self.__init_fail += 1
                self.__dashlog.error(("Initialization failure #%d" +
                                      " for %s %s: %s") %
                                     (self.__init_fail, self.__comp.fullname,
                                      self.__rule, exc_string()))
                return

        self.__data.check(self.__starved, self.__stagnant, self.__threshold)

    def close(self):
        "Close this thread"
        super(WatchdogThread, self).close()

        if self.__data is not None:
            self.__data.close()
            self.__data = None

    def get_new_thread(self):
        "Create a new copy of this thread"
        thrd = WatchdogThread(self.__runset, self.__comp, self.__rule,
                              self.__dashlog, data=self.__data,
                              init_fail=self.__init_fail,
                              mbean_client=self.__mbean_client)
        return thrd

    def stagnant(self):
        "Return the list of components which have stopped sending data"
        return self.__stagnant[:]

    def starved(self):
        "Return the list of components which have stopped receiving data"
        return self.__starved[:]

    def threshold(self):
        """
        Return the list of components with a quantity above/below a threshold
        value
        """
        return self.__threshold[:]


class WatchdogRule(object):
    "Base class for all watchdog rules"

    DOM_COMP = Component("dom", -9)
    DISPATCH_COMP = Component("dispatch", -10)

    def __str__(self):
        "Return the name of this rule"
        return type(self).__name__

    @classmethod
    def find_component(cls, comps, comp_name):
        "Find the component matching `comp_name`, returning None if not found"
        for comp in comps:
            if comp.name == comp_name:
                return comp

        return None

    def init_data(self, data, this_comp, components):
        "Initialize the monitoring parameters"
        raise NotImplementedError("you were supposed to implement init_data")

    def create_data(self, this_comp, this_client, components, dashlog):
        "This is a base method for classes that define init_data"
        data = WatchData(this_comp, this_client, dashlog)
        self.init_data(data, this_comp, components)
        return data

    @classmethod
    def initialize(cls, runset):
        "Initialize the order to use with this runset"
        min_order = None
        max_order = None

        for comp in runset.components():
            order = comp.order
            if not isinstance(order, int):
                raise TaskException("Expected integer order for %s, not %s" %
                                    (comp.fullname, type(comp.order)))

            if min_order is None or order < min_order:
                min_order = order
            if max_order is None or order > max_order:
                max_order = order

        cls.DOM_COMP.order = min_order - 1
        cls.DISPATCH_COMP.order = max_order + 1


class StringHubRule(WatchdogRule):
    "Rules for stringHub components"

    def init_data(self, data, this_comp, components):
        "Initialize the monitoring parameters"
        data.add_input_value(self.DOM_COMP, "sender", "NumHitsReceived")
        comp = self.find_component(components, "eventBuilder")
        if comp is not None:
            data.add_input_value(comp, "sender", "NumReadoutRequestsReceived")
            data.add_output_value(comp, "sender", "NumReadoutsSent")

    def matches(self, comp):
        "Return True if this rule applies to the component"
        return comp.name == "stringHub" or comp.name == "replayHub"


class LocalTriggerRule(WatchdogRule):
    "Rules for local trigger components (in-ice, icetop, etc.)"

    def init_data(self, data, this_comp, components):
        "Initialize the monitoring parameters"
        if this_comp.name == "iceTopTrigger":
            hit_name = "icetopHit"
            want_icetop = True
        else:
            hit_name = "stringHit"
            want_icetop = False

        hub = None
        for comp in components:
            if comp.name.lower().endswith("hub"):
                if want_icetop:
                    found = comp.num >= 200
                else:
                    found = comp.num < 200
                if found:
                    hub = comp
                    break

        if hub is not None:
            data.add_input_value(hub, hit_name, "RecordsReceived")
        comp = self.find_component(components, "globalTrigger")
        if comp is not None:
            data.add_output_value(comp, "trigger", "RecordsSent")

    def matches(self, comp):
        "Return True if this rule applies to the component"
        return comp.name == "inIceTrigger" or \
                   comp.name == "simpleTrigger" or \
                   comp.name == "iceTopTrigger"


class GlobalTriggerRule(WatchdogRule):
    "Rules for global trigger component"

    def init_data(self, data, this_comp, components):
        "Initialize the monitoring parameters"
        for trig in ("inIce", "iceTop", "simple"):
            comp = self.find_component(components, trig + "Trigger")
            if comp is not None:
                data.add_input_value(comp, "trigger", "RecordsReceived")
        comp = self.find_component(components, "eventBuilder")
        if comp is not None:
            data.add_output_value(comp, "glblTrig", "RecordsSent")

    def matches(self, comp):
        "Return True if this rule applies to the component"
        return comp.name == "globalTrigger"


class EventBuilderRule(WatchdogRule):
    "Rules for eventBuilder"

    def init_data(self, data, this_comp, components):
        "Initialize the monitoring parameters"
        hub = None
        for comp in components:
            if comp.name.lower().endswith("hub"):
                hub = comp
                break
        if hub is not None:
            data.add_input_value(hub, "backEnd", "NumReadoutsReceived")
        comp = self.find_component(components, "globalTrigger")
        if comp is not None:
            data.add_input_value(comp, "backEnd", "NumTriggerRequestsReceived")
        data.add_output_value(self.DISPATCH_COMP, "backEnd", "NumEventsSent")
        data.add_output_value(self.DISPATCH_COMP,
                              "backEnd", "NumEventsDispatched")
        data.add_threshold_value("backEnd", "DiskAvailable", 1024)
        data.add_threshold_value("backEnd", "NumBadEvents", 0, False)

    def matches(self, comp):
        "Return True if this rule applies to the component"
        return comp.name == "eventBuilder"


class SecondaryBuildersRule(WatchdogRule):
    "Rules for secondaryBuilders component"

    def init_data(self, data, this_comp, components):
        "Initialize the monitoring parameters"
        data.add_threshold_value("snBuilder", "DiskAvailable", 1024)
        data.add_output_value(self.DISPATCH_COMP, "moniBuilder",
                              "NumDispatchedData")
        data.add_output_value(self.DISPATCH_COMP, "snBuilder",
                              "NumDispatchedData")
        # XXX - Disabled until there"s a simulated tcal stream
        # data.add_output_value(self.DISPATCH_COMP, "tcalBuilder",
        #                       "NumDispatchedData")

    def matches(self, comp):
        "Return True if this rule applies to the component"
        return comp.name == "secondaryBuilders"


class WatchdogTask(CnCTask):
    "Watch component quantities and kill the run if there is a serious problem"

    __NAME = "Watchdog"
    __PERIOD = 10

    # number of bad checks before the run is killed
    HEALTH_METER_FULL = 9
    # number of complaints printed before run is killed
    NUM_HEALTH_MSGS = 3

    def __init__(self, taskMgr, runset, dashlog, initial_health=None,
                 period=None, rules=None):
        "Create a watchdog task"
        self.__thread_list = {}
        if initial_health is None:
            self.__health_meter = self.HEALTH_METER_FULL
        else:
            self.__health_meter = int(initial_health)
        self.__unhealthy_message = False

        if period is None:
            period = self.period

        super(WatchdogTask, self).__init__(self.name, taskMgr, dashlog,
                                           self.name, period)

        WatchdogRule.initialize(runset)

        if rules is None:
            rules = (
                StringHubRule(),
                LocalTriggerRule(),
                GlobalTriggerRule(),
                EventBuilderRule(),
                SecondaryBuildersRule(),
            )

        self.__thread_list = self.__create_threads(runset, rules, dashlog)

    def __create_threads(self, runset, rules, dashlog):
        thread_list = {}

        components = runset.components()
        for comp in components:
            try:
                found = False
                for rule in rules:
                    if rule.matches(comp):
                        thread_list[comp] = self.create_thread(runset, comp,
                                                               rule, dashlog)
                        found = True
                        break
                if not found:
                    self.log_error("Couldn't create watcher for unknown" +
                                   " component " + comp.fullname)
            except:
                self.log_error("Couldn't create watcher for component %s: %s" %
                               (comp.fullname, exc_string()))
        return thread_list

    def __log_unhealthy(self, err_type, bad_list):
        errstr = None

        bad_list.sort()
        for bad in bad_list:
            if errstr is None:
                errstr = ""
            else:
                errstr += "\n"
            if isinstance(bad, UnhealthyRecord):
                msg = bad.message
            else:
                msg = "%s (%s is not UnhealthyRecord)" % (str(bad), type(bad))
            errstr += "    " + msg

        self.log_error("%s reports %s components:\n%s" %
                       (self.name, err_type, errstr))

    def _check(self):
        hanging = []
        starved = []
        stagnant = []
        threshold = []

        for key, thrd in list(self.__thread_list.items()):
            if thrd.is_alive():
                hanging.append(key)
            else:
                starved += thrd.starved()
                stagnant += thrd.stagnant()
                threshold += thrd.threshold()

            new_thrd = thrd.get_new_thread()
            new_thrd.start()
            self.__thread_list[key] = new_thrd

        # watchdog starts out "extra healthy" to compensate for
        #  laggy components at the start of each run
        extra_healthy = self.__health_meter > self.HEALTH_METER_FULL

        healthy = True
        if len(hanging) > 0:
            if not extra_healthy:
                hang_str = ComponentManager.format_component_list(hanging)
                self.log_error("%s reports hanging components:\n    %s" %
                               (self.name, hang_str))
            healthy = False
        if len(starved) > 0:
            if not extra_healthy:
                self.__log_unhealthy("starved", starved)
            healthy = False
        if len(stagnant) > 0:
            if not extra_healthy:
                self.__log_unhealthy("stagnant", stagnant)
            healthy = False
        if len(threshold) > 0:
            if not extra_healthy:
                self.__log_unhealthy("threshold", threshold)
            healthy = False

        if healthy:
            if self.__unhealthy_message:
                # only log this if we've logged the "unhealthy" message
                self.__unhealthy_message = False
                self.log_error("Run is healthy again")
            if extra_healthy:
                self.__health_meter -= 1
            if self.__health_meter < self.HEALTH_METER_FULL:
                self.__health_meter = self.HEALTH_METER_FULL
        else:
            self.__health_meter -= 1
            if self.__health_meter > 0:
                if not extra_healthy and \
                   self.__health_meter % self.NUM_HEALTH_MSGS == 0:
                    self.__unhealthy_message = True
                    self.log_error("Run is unhealthy (%d checks left)" %
                                   self.__health_meter)
            else:
                self.log_error("Run is not healthy, stopping")
                self.set_error("WatchdogTask")

    @classmethod
    def create_thread(cls, runset, comp, rule, dashlog):
        "Create a watchdog thread"
        return WatchdogThread(runset, comp, rule, dashlog)

    def close(self):
        "Close everything associated with this task"
        saved_exc = None
        for thrd in list(self.__thread_list.values()):
            try:
                thrd.close()
            except:
                if not saved_exc:
                    saved_exc = sys.exc_info()

        if saved_exc:
            reraise_excinfo(saved_exc)

    @classproperty
    def name(cls):
        "Name of this task"
        return cls.__NAME

    @classproperty
    def period(cls):
        "Number of seconds between tasks"
        return cls.__PERIOD

    def wait_until_finished(self):
        "Wait until all threads have finished"
        for thrd in list(self.__thread_list.values()):
            if thrd.is_alive():
                thrd.join()
