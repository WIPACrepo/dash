#!/usr/bin/env python

import datetime
import os
import threading
import time
import sys

import SpadeQueue

from CnCThread import CnCThread
from CompOp import ComponentOperation, ComponentOperationGroup, Result
from ComponentManager import ComponentManager, listComponentRanges
from DAQClient import DAQClientState
from DAQConfig import DOMNotInConfigException
from DAQConst import DAQPort
from DAQLog import DAQLog, FileAppender, LiveSocketAppender, LogSocketServer
from DAQRPC import RPCClient
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT, MoniClient, MoniPort, Prio
from RunOption import RunOption
from RunSetState import RunSetState
from TaskManager import TaskManager
from UniqueID import UniqueID
from leapseconds import leapseconds, LeapsecondException, MJD
from scmversion import get_scmversion_str
from utils import ip
from utils.DashXMLLog import DashXMLLog, DashXMLLogException

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class RunSetException(Exception):
    pass


class ConnectionException(RunSetException):
    pass


class InvalidSubrunData(RunSetException):
    pass


class Connection(object):
    """
    Component connection data to be passed to a component
    conn - connection description
    comp - component
    """

    def __init__(self, conn, comp):
        """
        Connection constructor
        conn - connection description
        comp - component
        """
        self.conn = conn
        self.comp = comp

    def __str__(self):
        "String description"
        front = '%s:%s#%d@%s' % \
            (self.conn.name, self.comp.name, self.comp.num, self.comp.host)
        if not self.conn.isInput:
            return front
        return '%s:%d' % (front, self.conn.port)

    def map(self):
        conn_dict = {}
        conn_dict['type'] = self.conn.name
        conn_dict['compName'] = self.comp.name
        conn_dict['compNum'] = self.comp.num
        conn_dict['host'] = self.comp.host
        conn_dict['port'] = self.conn.port
        return conn_dict


class ConnTypeEntry(object):
    """
    Temporary class used to build the connection map for a runset
    type - connection type
    in_list - list of [input connection, component] entries
    out_list - list of output connections
    """
    def __init__(self, conn_type):
        """
        ConnTypeEntry constructor
        type - connection type
        """
        self.__type = conn_type
        self.__in_list = []
        self.__opt_in_list = []
        self.__out_list = []
        self.__opt_out_list = []

    def __str__(self):
        return '%s in#%d out#%d' % (self.__type, len(self.__in_list),
                                    len(self.__out_list))

    def add(self, conn, comp):
        "Add a connection and component to the appropriate list"
        if conn.isInput:
            if conn.isOptional:
                self.__opt_in_list.append([conn, comp])
            else:
                self.__in_list.append([conn, comp])
        else:
            if conn.isOptional:
                self.__opt_out_list.append(comp)
            else:
                self.__out_list.append(comp)

    def build_connection_map(self, conn_map):
        "Validate and fill the map of connections for each component"

        in_len = len(self.__in_list) + len(self.__opt_in_list)
        out_len = len(self.__out_list) + len(self.__opt_out_list)

        # if there are no inputs and no required outputs (or no required
        # inputs and no outputs), we're done
        if (out_len == 0 and len(self.__in_list) == 0) or \
           (in_len == 0 and len(self.__out_list) == 0):
            return

        # if there are no inputs, throw an error
        if in_len == 0:
            out_str = None
            for out_comp in self.__out_list + self.__opt_out_list:
                if out_str is None:
                    out_str = ''
                else:
                    out_str += ', '
                out_str += str(out_comp)
            raise ConnectionException('No inputs found for %s outputs (%s)' %
                                      (self.__type, out_str))

        # if there are no outputs, throw an error
        if out_len == 0:
            in_str = None
            for pair in self.__in_list + self.__opt_in_list:
                if in_str is None:
                    in_str = ''
                else:
                    in_str += ', '
                in_str += str(pair[1])
            raise ConnectionException('No outputs found for %s inputs (%s)' %
                                      (self.__type, in_str))

        # if there are multiple inputs and outputs, throw an error
        if in_len > 1 and out_len > 1:
            raise ConnectionException('Found %d %s inputs for %d outputs' %
                                      (in_len, self.__type, out_len))

        # at this point there is either a single input or a single output

        if in_len == 1:
            if len(self.__in_list) == 1:
                in_obj = self.__in_list[0]
            else:
                in_obj = self.__opt_in_list[0]
            in_conn = in_obj[0]
            in_comp = in_obj[1]

            for out_comp in self.__out_list + self.__opt_out_list:
                entry = Connection(in_conn, in_comp)

                if out_comp not in conn_map:
                    conn_map[out_comp] = []
                conn_map[out_comp].append(entry)
        else:
            if len(self.__out_list) == 1:
                out_comp = self.__out_list[0]
            else:
                out_comp = self.__opt_out_list[0]

            for in_conn, in_comp in self.__in_list + self.__opt_in_list:
                entry = Connection(in_conn, in_comp)

                if out_comp not in conn_map:
                    conn_map[out_comp] = []
                conn_map[out_comp].append(entry)


class GoodTimeThread(CnCThread):
    """
    A thread which queries all hubs for either the latest first hit time
    or the earliest last hit time
    """

    # bean field name holding the number of non-zombie hubs
    NONZOMBIE_FIELD = "NumberOfNonZombies"
    # maximum number of attempts to get the time from all hubs
    MAX_ATTEMPTS = 5

    def __init__(self, src_set, other_set, runset, data, log, quick_set=False,
                 thread_name=None):
        """
        Create the thread

        src_set - list of sources (stringHubs) in the runset
        other_set - list of non-sources in the runset
        runset - collection of components in the run
        data - RunData for the run
        log - log file for the runset
        quick_set - True if time should be passed on as quickly as possible
        thread_name - thread name
        """
        self.__src_set = src_set
        self.__other_set = other_set
        self.__runset = runset
        self.__data = data
        self.__log = log
        self.__quick_set = quick_set

        self.__time_dict = {}
        self.__bad_comps = {}

        self.__good_time = None
        self.__final_time = None

        self.__stopped = False

        super(GoodTimeThread, self).__init__(thread_name, log)

    def __fetch_time(self):
        """
        Query all hubs which haven't yet reported a time
        """
        tgroup = ComponentOperationGroup(ComponentOperation.GET_GOOD_TIME)
        for comp in self.__src_set:
            if comp not in self.__time_dict:
                tgroup.start(comp, self.__log,
                             (self.NONZOMBIE_FIELD, self.beanfield()))

        if self.wait_for_all():
            # if we don't need results as soon as possible,
            # wait for all threads to finish
            tgroup.wait()
            tgroup.reportErrors(self.__log, "getGoodTimes")

        complete = True
        updated = False

        # wait for up to two seconds for a result
        sleep_secs = 0.1
        sleep_reps = 20

        for _ in xrange(sleep_reps):
            hanging = False
            complete = True

            rlist = tgroup.results()
            for comp in self.__src_set:
                if self.__stopped:
                    # run has been stopped, don't bother checking anymore
                    break

                if comp in self.__time_dict:
                    # already have a time for this hub
                    continue

                result = rlist[comp]
                if result is None or \
                   result == ComponentOperation.RESULT_HANGING:
                    # still waiting for results
                    complete = False
                    hanging = True
                    continue

                if result == ComponentOperation.RESULT_ERROR:
                    # component operation failed
                    self.__bad_comps[comp] = 1
                    continue

                if not isinstance(result, dict):
                    self.__log.error("Expected dictionary, not %s for %s"
                                     " (result=%s)" %
                                     (type(result), result, comp.fullname))
                    continue

                if comp in self.__bad_comps:
                    # got a result from a component which previously failed
                    del self.__bad_comps[comp]

                num_doms = result[self.NONZOMBIE_FIELD]
                if num_doms == 0:
                    # this string has no usable DOMs, record illegal time
                    self.__log.error("No usable DOMs on %s for %s" %
                                     (comp.fullname, self.moniname()))
                    self.__time_dict[comp] = -1L
                    continue

                if self.beanfield() in result:
                    val = result[self.beanfield()]
                else:
                    val = None
                if val is None or val <= 0L:
                    # No results yet, need to poll again
                    complete = False
                    continue

                self.__time_dict[comp] = val
                if self.__good_time is None or \
                   self.is_better(self.__good_time, val):
                    # got new good time, tell the builders
                    self.__good_time = val
                    updated = True

            if complete:
                # quit if we've got all the results
                break

            if not hanging and not self.wait_for_all():
                # quit if all threads are done or if we don't need to wait
                break

            # wait a bit more for the threads to finish
            time.sleep(sleep_secs)

        if updated:
            try:
                for comp in self.__other_set:
                    if comp.isBuilder or comp.isComponent("globalTrigger"):
                        self.notify_component(comp, self.__good_time)
            except:
                self.__log.error("Cannot send %s to builders: %s" %
                                 (self.moniname(), exc_string()))

        return complete

    def _run(self):
        "Gather good hit time data from all hubs"
        try:
            complete = False
            for num in range(self.MAX_ATTEMPTS):
                complete = self.__fetch_time()
                loud = False
                if loud and (complete or self.__stopped):
                    if complete:
                        status = "complete"
                    elif self.__stopped:
                        status = "stopped"
                    else:
                        status = "unknown"
                    self.__log.error("GetGoodTime %s after %d attempts" %
                                     (status, num))
                    # we're done, break out of the loop
                    break
                time.sleep(0.1)
        except:
            self.__log.error("Couldn't find %s: %s" %
                             (self.moniname(), exc_string()))

        self.__final_time = self.__good_time

        if len(self.__bad_comps) > 0:
            self.__log.error("Couldn't find %s for %s" %
                             (self.moniname(),
                              listComponentRanges(self.__bad_comps.keys())))

        if self.__good_time is None:
            good_val = "unknown"
        else:
            good_val = self.__good_time
        self.__runset.report_good_time(self.__data, self.moniname(), good_val)

    def beanfield(self):
        "Return the name of the 'stringhub' MBean field"
        raise NotImplementedError("Unimplemented")

    @property
    def finished(self):
        "Return True if the thread has finished"
        return self.__final_time is not None

    def is_better(self, oldval, newval):
        "Return True if 'newval' is better than 'oldval'"
        raise NotImplementedError("Unimplemented")

    def logError(self, msg):
        self.__log.error(msg)

    def moniname(self):
        "Return the name of the value sent to I3Live"
        raise NotImplementedError("Unimplemented")

    def notify_component(self, comp, good_time):
        "Notify the builder of the good time"
        raise NotImplementedError("Unimplemented")

    def stop(self):
        self.__stopped = True

    def time(self):
        "Return the time marking the start or end of good data taking"
        return self.__final_time

    def wait_for_all(self):
        "Wait for all threads to finish before checking results?"
        raise NotImplementedError("Unimplemented")


class FirstGoodTimeThread(GoodTimeThread):
    def __init__(self, src_set, other_set, runset, data, log):
        """
        Create the thread

        src_set - list of sources (stringHubs) in the runset
        other_set - list of non-sources in the runset
        runset - collection of components in the run
        data - RunData for the run
        log - log file for the runset
        """
        super(FirstGoodTimeThread, self).__init__(src_set, other_set, runset,
                                                  data, log,
                                                  thread_name="FirstGoodTime")

    def beanfield(self):
        "Return the name of the 'stringhub' MBean field"
        return "LatestFirstChannelHitTime"

    def is_better(self, oldval, newval):
        "Return True if 'newval' is better than 'oldval'"
        return oldval is None or (newval is not None and oldval < newval)

    def moniname(self):
        "Return the name of the value sent to I3Live"
        return "firstGoodTime"

    def notify_component(self, comp, pay_time):
        "Notify the builder of the good time"
        if pay_time is None:
            self.logError("Cannot set first good time to None")
        else:
            comp.setFirstGoodTime(pay_time)

    def wait_for_all(self):
        "Wait for all threads to finish before checking results?"
        return True


class LastGoodTimeThread(GoodTimeThread):
    def __init__(self, src_set, other_set, runset, data, log):
        """
        Create the thread

        src_set - list of sources (stringHubs) in the runset
        other_set - list of non-sources in the runset
        runset - collection of components in the run
        data - RunData for the run
        log - log file for the runset
        """
        super(LastGoodTimeThread, self).__init__(src_set, other_set, runset,
                                                 data, log,
                                                 thread_name="LastGoodTime",
                                                 quick_set=True)

    def beanfield(self):
        "Return the name of the 'stringhub' MBean field"
        return "EarliestLastChannelHitTime"

    def is_better(self, oldval, newval):
        "Return True if 'newval' is better than 'oldval'"
        return oldval is None or (newval is not None and oldval > newval)

    def moniname(self):
        "Return the name of the value sent to I3Live"
        return "lastGoodTime"

    def notify_component(self, comp, pay_time):
        "Notify the builder of the good time"
        if pay_time is None:
            self.logError("Cannot set last good time to None")
        else:
            comp.setLastGoodTime(pay_time)

    def wait_for_all(self):
        "Wait for all threads to finish before checking results?"
        return False


class RateEntry(object):
    def __init__(self, ticks, count):
        self.__ticks = ticks
        self.__count = count

    def __cmp__(self, other):
        val = cmp(self.__ticks, other.__ticks)
        if val == 0:
            val = cmp(self.__count, other.__count)
        return val

    def __repr__(self):
        return "RateEntry(%s, %s)" % (self.__ticks, self.__count)

    def __str__(self):
        return "RateEntry[%s -> %s]" % (self.__ticks, self.__count)

    def diff_ticks(self, other):
        return float(self.__ticks - other.__ticks)

    def diff_count(self, other):
        return float(self.__count - other.__count)


class StreamData(object):
    def __init__(self, count, ticks):
        self.__count = count
        self.__ticks = ticks

    @property
    def count(self):
        return self.__count

    @property
    def ticks(self):
        return self.__ticks

    def update(self, count, ticks):
        self.__count = count
        self.__ticks = ticks


class RunData(object):
    # True if we've printed a warning about the failed IceCube Live code import
    LIVE_WARNING = False
    # rate interval (in 0.1ns)
    RATE_INTERVAL = 300 * 10000000000
    # maximum number of physics count entries
    MAX_PHYSICS_ENTRIES = 1000

    def __init__(self, run_set, run_number, cluster_config, run_config,
                 run_options, version_info, spade_dir, copy_dir, log_dir,
                 testing=False):
        """
        Constructor for object holding run-specific data

        run_set - run set which uses this data
        run_number - current run number
        cluster_config - current cluster configuration
        run_config - current run configuration
        run_options - logging/monitoring options
        version_info - release and revision info
        spade_dir - directory where SPADE files are written
        copy_dir - directory where a copy of the SPADE files is kept
        log_dir - top-level logging directory
        testing - True if this is called from a unit test
        """
        self.__run_number = run_number
        self.__subrun_number = 0
        self.__cluster_config = cluster_config
        self.__run_config = run_config
        self.__run_options = run_options
        self.__version_info = version_info
        self.__spade_dir = spade_dir
        self.__copy_dir = copy_dir
        self.__testing = testing
        self.__finished = False
        self.__task_mgr = None

        if not RunOption.isLogToFile(self.__run_options):
            self.__log_dir = None
            self.__run_dir = None
        else:
            if log_dir is None:
                raise RunSetException("Log directory not specified for" +
                                      " file logging")

            self.__log_dir = log_dir
            self.__run_dir = run_set.create_run_dir(self.__log_dir,
                                                    self.__run_number)

        if self.__spade_dir is not None and \
           not os.path.exists(self.__spade_dir):
            raise RunSetException("SPADE directory %s does not exist" %
                                  (self.__spade_dir, ))

        self.__dashlog = self.create_dash_log()

        self.__dashlog.error("Version info: %s" %
                             (get_scmversion_str(info=version_info), ))
        self.__dashlog.error("Run configuration: %s" % (run_config.basename, ))
        self.__dashlog.error("Cluster: %s" % (cluster_config.description, ))

        self.__live_moni_client = None

        # run stats
        self.__first_pay_time = None
        self.__num_evts = 0
        self.__wall_time = None
        self.__evt_pay_time = None
        self.__num_moni = 0
        self.__moni_time = None
        self.__num_sn = 0
        self.__sn_time = None
        self.__num_tcal = 0
        self.__tcal_time = None

        # Calculates rate over latest 5min interval
        self.__physics_entries = []

        # cache monitoring data for '*_count_update'
        self.__stream_data = {}

    def __str__(self):
        return "Run#%d[e%d m%d s%d t%d]" % \
            (self.__run_number, self.__num_evts, self.__num_moni,
             self.__num_sn, self.__num_tcal)

    def __add_rate(self, pay_time, num_evts):
        while len(self.__physics_entries) >= self.MAX_PHYSICS_ENTRIES:
            self.__physics_entries.pop(0)

        self.__physics_entries.append(RateEntry(pay_time, num_evts))

    @property
    def _physics_entries(self):
        return self.__physics_entries[:]

    @property
    def cached_monitor_data(self):
        return (self.__num_evts, self.__wall_time, self.__evt_pay_time, None,
                self.__num_moni, self.__moni_time,
                self.__num_sn, self.__sn_time,
                self.__num_tcal, self.__tcal_time)

    def clone(self, run_set, new_run):
        return RunData(run_set, new_run, self.__cluster_config,
                       self.__run_config, self.__run_options,
                       self.__version_info, self.__spade_dir, self.__copy_dir,
                       self.__log_dir, testing=self.__testing)

    @property
    def cluster_configuration(self):
        return self.__cluster_config

    def connect_to_live(self):
        if LIVE_IMPORT:
            moni_client = self.create_moni_client(MoniPort)
        else:
            moni_client = None
            if not self.LIVE_WARNING:
                self.LIVE_WARNING = True
                self.__dashlog.error("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        self.__live_moni_client = moni_client

    @property
    def copy_directory(self):
        return self.__copy_dir

    def create_dash_log(self):
        log = DAQLog("dash", level=DAQLog.ERROR)

        if RunOption.isLogToFile(self.__run_options):
            if self.__run_dir is None:
                raise RunSetException("Run directory has not been specified")
            app = FileAppender("dashlog", os.path.join(self.__run_dir,
                                                       "dash.log"))
            log.addAppender(app)

        if RunOption.isLogToLive(self.__run_options):
            app = LiveSocketAppender("localhost", DAQPort.I3LIVE_ZMQ,
                                     priority=Prio.EMAIL)
            log.addAppender(app)

        return log

    def create_moni_client(self, port):
        return MoniClient("pdaq", "localhost", port)

    def destroy(self):
        saved_ex = None
        try:
            self.stop()
        except:
            saved_ex = sys.exc_info()

        if self.has_moni_client:
            try:
                self.__live_moni_client.close()
            except:
                if not saved_ex:
                    saved_ex = sys.exc_info()
            self.__live_moni_client = None

        if self.__dashlog is not None:
            try:
                self.__dashlog.close()
            except:
                if not saved_ex:
                    saved_ex = sys.exc_info()
            self.__dashlog = None

        if saved_ex:
            raise saved_ex[0], saved_ex[1], saved_ex[2]

    def error(self, msg):
        if self.__dashlog is not None:
            self.__dashlog.error(msg)

    @property
    def finished(self):
        return self.__finished

    @property
    def first_physics_time(self):
        return self.__first_pay_time

    @property
    def has_moni_client(self):
        return self.__live_moni_client is not None

    def info(self, msg):
        if self.__dashlog is not None:
            self.__dashlog.info(msg)

    @property
    def isDestroyed(self):
        return self.__dashlog is not None

    @property
    def isErrorEnabled(self):
        return self.__dashlog.isErrorEnabled

    @property
    def isInfoEnabled(self):
        return self.__dashlog.isInfoEnabled

    @property
    def isWarnEnabled(self):
        return self.__dashlog.isWarnEnabled

    @property
    def log_directory(self):
        return self.__log_dir

    @property
    def moni_client(self):
        return self.__live_moni_client

    @property
    def rate(self):
        """
        Get latest physics rate value.
        """
        # Find the desired bin by walking back in time.
        # This is a bit crude but
        # we don't need to worry about performance for the target application
        # (DAQRun rate calculation)
        first = None
        latest = None
        for entry in reversed(self.__physics_entries):
            if first is None:
                first = entry
            else:
                latest = entry
                if first.diff_ticks(entry) > self.RATE_INTERVAL:
                    break

        if first is None or latest is None:
            return 0.0
        return first.diff_count(latest) / (first.diff_ticks(latest) / 1E10)

    @property
    def release(self):
        return self.__version_info["release"]

    @property
    def repo_revision(self):
        return self.__version_info["repo_rev"]

    def reset(self):
        pass

    @property
    def run_configuration(self):
        return self.__run_config

    @property
    def run_directory(self):
        return self.__run_dir

    @property
    def run_number(self):
        return self.__run_number

    @property
    def run_options(self):
        return self.__run_options

    def send_count_updates(self, moni_data, prio):
        for stream in ("event", "moni", "sn", "tcal"):
            if stream == "event":
                prefix = "physics"
                tick_field = "eventPayloadTicks"
            else:
                prefix = stream
                tick_field = prefix + "Time"
            count_field = prefix + "Events"

            if count_field not in moni_data or tick_field not in moni_data:
                self.error("No %s data provided by RunSet"
                               ".get_event_counts()" % (stream, ))
                continue

            if moni_data[count_field] is None or moni_data[tick_field] is None:
                if moni_data[count_field] > 0:
                    self.error("Bad %s data provided by RunSet"
                                   ".get_event_counts() (count %s, ticks %s)" %
                                   (stream, moni_data[count_field],
                                    moni_data[tick_field]))
                continue

            if stream not in self.__stream_data:
                # add initial count/tick values for this stream, don't send yet
                self.__stream_data[stream] \
                    = StreamData(moni_data[count_field],
                                 moni_data[tick_field])
                continue

            # send the monitoring data for this stream
            entry = self.__stream_data[stream]
            try:
                start_str = str(PayloadTime.toDateTime(entry.ticks))
                stop_str = str(PayloadTime.toDateTime(moni_data[tick_field]))
                count_update = {
                    "start_time": start_str,
                    "stop_time": stop_str,
                    "count": moni_data[count_field] - entry.count,
                    "run_number": self.__run_number,
                }

                self.send_moni(stream + "_count_update", count_update,
                                   prio=prio, time=stop_str)
            finally:
                # update the count/tick for this stream
                entry.update(moni_data[count_field], moni_data[tick_field])

    def send_moni(self, name, value, prio=None, time=None, debug=False):
        if debug:
            if prio is None:
                pstr = ""
            else:
                pstr = "(prio %s)" % str(prio)
            if time is None:
                tstr = ""
            else:
                tstr = "[%s]" % str(time)
            self.__dashlog.error("SendMoni %s%s%s: %s" %
                                 (name, tstr, pstr, value))
        try:
            self.__live_moni_client.sendMoni(name, value, prio=prio, time=time)
        except:
            self.__dashlog.error("Failed to send %s=%s: %s" %
                                 (name, value, exc_string()))

    def set_finished(self):
        self.__finished = True

    def set_first_physics_time(self, paytime):
        if len(self.__physics_entries) > 0:
            self.__dashlog.error("Failed to set first payload time since"
                                 " there are existing rate entries")
        else:
            self.__first_pay_time = paytime
            self.__add_rate(self.__first_pay_time, 1)

    def set_subrun_number(self, num):
        self.__subrun_number = num

    @property
    def spade_directory(self):
        return self.__spade_dir

    def create_task_manager(self, runset):
        return TaskManager(runset, self.__dashlog, self.__live_moni_client,
                           self.__run_dir, self.__run_config,
                           self.__run_options)

    def start_tasks(self, runset):
        # start housekeeping threads
        self.__task_mgr = self.create_task_manager(runset)

        self.__task_mgr.start()

    def stop(self):
        pass

    def stop_tasks(self):
        if self.__task_mgr is not None:
            self.__task_mgr.stop()
            for _ in range(5):
                if self.__task_mgr.isStopped:
                    break
                time.sleep(0.25)

    @property
    def subrun_number(self):
        return self.__subrun_number

    def update_event_counts(self, physics_count, wall_time, first_pay_time,
                            evt_pay_time, moni_count, moni_time, sn_count,
                            sn_time, tcal_count, tcal_time, add_rate=False):
        "Gather run statistics"
        if add_rate and self.__first_pay_time is None and first_pay_time > 0:
            self.set_first_physics_time(first_pay_time)

        if physics_count >= 0 and evt_pay_time > 0:
            (self.__num_evts, self.__wall_time, self.__evt_pay_time,
             self.__num_moni, self.__moni_time,
             self.__num_sn, self.__sn_time,
             self.__num_tcal, self.__tcal_time) = \
             (physics_count, wall_time, evt_pay_time,
              moni_count, moni_time,
              sn_count, sn_time,
              tcal_count, tcal_time)

            if add_rate:
                self.__add_rate(self.__evt_pay_time, self.__num_evts)

        return (self.__num_evts, self.__wall_time, self.__first_pay_time,
                self.__evt_pay_time, self.__num_moni, self.__moni_time,
                self.__num_sn, self.__sn_time, self.__num_tcal,
                self.__tcal_time)

    def warn(self, msg):
        self.__dashlog.warn(msg)


class RunSet(object):
    "A set of components to be used in one or more runs"

    # next runset ID
    #
    ID_SOURCE = UniqueID()

    # number of seconds to wait after stopping components seem to be
    # hung before forcing remaining components to stop
    #
    TIMEOUT_SECS = RPCClient.TIMEOUT_SECS - 5

    STATE_DEAD = DAQClientState.DEAD
    STATE_HANGING = DAQClientState.HANGING

    # token passed to stop_run() to indicate a "normal" stop
    NORMAL_STOP = "NormalStop"

    # number of seconds between "Waiting for ..." messages during stop_run()
    #
    WAIT_MSG_PERIOD = 5

    # number of days before file expiration to start sending alerts
    LEAPSECOND_FILE_EXPIRY = 14

    def __init__(self, parent, cfg, runset, logger):
        """
        RunSet constructor:
        parent - main server
        cfg - parsed run configuration file data
        runset - list of components
        logger - logging object

        Class attributes:
        id - unique runset ID
        configured - true if this runset has been configured
        runNumber - run number (if assigned)
        state - current state of this set of components
        """
        self.__parent = parent
        self.__cfg = cfg
        self.__set = runset
        self.__logger = logger

        self.__id = RunSet.ID_SOURCE.next()

        self.__configured = False
        self.__state = RunSetState.IDLE
        self.__run_data = None
        self.__comp_log = {}

        self.__stopping = None
        self.__stop_lock = threading.Lock()

        self.__spade_thread = None

        self.__moni_count = 0

        # make sure components are in a known order
        self.__set.sort()

    def __repr__(self):
        return str(self)

    def __str__(self):
        "String description"
        if self.__id is None:
            set_str = "DESTROYED RUNSET"
        else:
            set_str = 'RunSet #%d' % (self.__id, )
        if self.__run_data is not None:
            set_str += ' run#%d' % (self.__run_data.run_number, )
        set_str += " (%s)" % (self.__state, )
        return set_str

    def __attempt_to_stop(self, src_set, other_set, new_state, src_op,
                          timeout_secs):
        self.__state = new_state

        # self.__run_data is guaranteed to be set here
        if self.__run_data.isErrorEnabled and \
           src_op == ComponentOperation.FORCED_STOP:
            full_set = src_set + other_set
            plural = len(full_set) == 1 and "s" or ""
            if len(full_set) == 1:
                plural = ""
            else:
                plural = "s"
            self.__run_data.error('%s: Forcing %d component%s to stop: %s' %
                                  (str(self), len(full_set), plural,
                                   listComponentRanges(full_set)))

        # stop sources in parallel
        #
        ComponentOperationGroup.runSimple(src_op, src_set, (),
                                          self.__run_data, errorName=src_op)

        # stop non-sources in order
        #
        for comp in other_set:
            ComponentOperationGroup.runSimple(src_op, (comp, ), (),
                                              self.__run_data,
                                              errorName=src_op)

        # make sure we run at least once
        if timeout_secs == 0:
            timeout_secs = 1

        conn_dict = {}

        msg_secs = None
        cur_secs = time.time()
        end_secs = cur_secs + timeout_secs

        while (len(src_set) > 0 or len(other_set) > 0) and cur_secs < end_secs:
            changed = self.__stop_components(src_set, other_set, conn_dict)
            if not changed:
                #
                # hmmm ... we may be hanging
                #
                time.sleep(1)
            elif len(src_set) > 0 or len(other_set) > 0:
                #
                # one or more components must have stopped
                #
                new_secs = time.time()
                if msg_secs is None or \
                   new_secs < (msg_secs + self.WAIT_MSG_PERIOD):
                    wait_str = self.__connection_string(src_set + other_set,
                                                        conn_dict)
                    self.__run_data.info('%s: Waiting for %s %s' %
                                         (str(self), self.__state, wait_str))
                msg_secs = new_secs

            cur_secs = time.time()

        return conn_dict

    @classmethod
    def __bad_state_string(cls, bad_states):
        badlist = []
        for state in bad_states:
            comp_str = listComponentRanges(bad_states[state])
            badlist.append(state + "[" + comp_str + "]")
        return ", ".join(badlist)

    def __build_start_sets(self):
        """
        Return several lists of components.  The first list contains all the
        sources.  The second contains the non-builder components, sorted in
        reverse order.  The final set contains all builders (which are
        endpoints for the DAQ data streams).
        """
        src_set = []
        middle_set = []
        bldr_set = []

        fail_str = None
        for comp in self.__set:
            if comp.order() is not None:
                if comp.isSource:
                    src_set.append(comp)
                elif comp.isBuilder:
                    bldr_set.append(comp)
                else:
                    middle_set.append(comp)
            else:
                if not fail_str:
                    fail_str = 'No order set for ' + str(comp)
                else:
                    fail_str += ', ' + str(comp)
        if fail_str:
            raise RunSetException(fail_str)
        middle_set.sort(self.__sort_cmp)

        return src_set, middle_set, bldr_set

    def __check_leapseconds(self, run_data, config_dir):
        """
        Reload leapseconds file if it's been updated
        Complain if the leapseconds file is due to expire
        """
        try:
            leapsec = leapseconds.instance(config_dir)
        except LeapsecondException:
            if not run_data.has_moni_client:
                run_data.error("NIST leapsecond file not found in %s" %
                               (config_dir, ))
            else:
                # format an alert message
                value = {
                    "condition": "nist leapsecond file is missing",
                    "desc": "Run dash/leapsecond-fetch.py and deploy pdaq",
                    "vars": {
                        "config_dir": config_dir,
                    }
                }
                run_data.send_moni("alert", value, Prio.ITS)
            return

        reloaded = leapsec.reload_check()

        expiry_mjd = leapsec.expiry

        mjd_now = MJD.now()

        expire_delta = expiry_mjd.value - mjd_now.value
        if expire_delta <= self.LEAPSECOND_FILE_EXPIRY and \
           not self.is_leapsecond_silenced():
            # notify humans that the leapsecond file is about to expire
            run_data.error("Leapsecond file has %d days till expiration" %
                           (expire_delta, ))

            if run_data.has_moni_client:
                # format an alert message
                value = {
                    "condition": "nist leapsecond file approaching expiration",
                    "desc": "Run dash/leapsecond-fetch.py and deploy pdaq",
                    "vars": {
                        "days_till_expiration": expire_delta,
                    }
                }
                run_data.send_moni("alert", value, Prio.ITS)
        elif reloaded:
            # notify humans that the leapsecond file was reloaded
            run_data.info("Reloaded leapsecond file; %d days until"
                          " expiration" % (expire_delta, ))

            if run_data.has_moni_client:
                value = {
                    "condition": "nist leapsecond file reloaded",
                    "desc": "Found updated leapsecond file",
                    "vars": {
                        "days_till_expiration": expire_delta,
                    }
                }
                run_data.send_moni("alert", value, Prio.ITS)

    def __check_state(self, new_state, components=None):
        """
        If component states match 'new_state', set state to 'new_state' and
        return an empty list.
        Otherwise, set state to ERROR and return a dictionary of states
        and corresponding lists of components.
        """

        if components is None:
            components = self.__set

        comp_op = ComponentOperation.GET_STATE
        states = ComponentOperationGroup.runSimple(comp_op, components, (),
                                                   self.__logger)

        state_dict = {}
        for comp in components:
            if comp in states:
                state_str = str(states[comp])
            else:
                state_str = self.STATE_DEAD
            if state_str != new_state:
                if state_str not in state_dict:
                    state_dict[state_str] = []
                state_dict[state_str].append(comp)

        if len(state_dict) == 0:
            self.__state = new_state
        else:
            msg = "Failed to transition to %s:" % new_state
            for state_str in state_dict:
                comp_str = listComponentRanges(state_dict[state_str])
                msg += " %s[%s]" % (state_str, comp_str)

            self.__log_error(msg)

            self.__state = RunSetState.ERROR

        return state_dict

    def __check_stopped_components(self, waitlist):
        """
        If one or more components are not stopped and state==READY,
        throw a RunSetException
        """
        if len(waitlist) > 0:
            try:
                wait_str = listComponentRanges(waitlist)
                err_str = '%s: Could not stop %s' % (self, wait_str)
                self.__log_error(err_str)
            except:
                err_str = "%s: Could not stop components (?)" % str(self)
            self.__state = RunSetState.ERROR
            raise RunSetException(err_str)

        bad_states = self.__check_state(RunSetState.READY)
        if len(bad_states) > 0:
            try:
                msg = "%s: Could not stop %s" % \
                    (self, self.__bad_state_string(bad_states))
                self.__log_error(msg)
            except Exception as ex:
                msg = "%s: Components in bad states: %s" % (self, ex)
            self.__state = RunSetState.ERROR
            raise RunSetException(msg)

    @staticmethod
    def __connection_string(comp_list, conn_dict=None):
        """
        Build a string of component names and (if supplied) the states of
        their connections
        """
        comp_str = None
        for comp in comp_list:
            if comp_str is None:
                comp_str = ''
            else:
                comp_str += ', '
            if conn_dict is None or comp not in conn_dict:
                comp_str += comp.fullname
            else:
                comp_str += comp.fullname + conn_dict[comp]
        return comp_str

    @staticmethod
    def __connector_string(conn_states):
        """
        Build a string from a component's list of connector states
        (returned by the remote `listConnectorStates()` method)
        """
        cs_str = None
        for cst in conn_states:
            if "type" not in cst or "state" not in cst:
                continue
            if cst["state"] == 'idle':
                continue
            if cs_str is None:
                cs_str = '['
            else:
                cs_str += ', '
            cs_str += '%s:%s' % (cst["type"], cst["state"])

        if cs_str is None:
            cs_str = ''
        else:
            cs_str += ']'

        return cs_str

    def __finish_stop(self, caller_name, had_error=False):
        # try to finish end-of-run reporting and move catchall.log to run dir
        if self.__run_data is not None:
            try:
                self.final_report(self.__set, self.__run_data,
                                  had_error=had_error)
            except:
                self.__logger.error("Could not finish run for %s (%s): %s" %
                                    (self, caller_name, exc_string()))
            finally:
                self.__parent.saveCatchall(self.__run_data.run_directory)

        # tell components to switch back to default logger (catchall.log)
        try:
            self.reset_logging()
        except:
            self.__logger.error("Could not stop logs for %s (%s): %s" %
                                (self, caller_name, exc_string()))

        # stop log servers for all components
        try:
            self.__stop_log_servers()
        except:
            self.__logger.error("Could not stop log servers for %s (%s): %s" %
                                (self, caller_name, exc_string()))

        # report event counts to Live
        sent_error = None
        if self.__run_data is None:
            sent_error = "No run data"
        else:
            try:
                self.send_event_counts(self.__run_data)
            except:
                if sent_error is None:
                    sent_error = exc_string()

            # NOTE: ALL FILES MUST BE WRITTEN OUT BEFORE THIS POINT
            # THIS IS WHERE EVERYTHING IS PUT IN A TARBALL FOR SPADE
            try:
                self.__queue_for_spade(self.__run_data)
            except:
                if sent_error is None:
                    sent_error = exc_string()

            # note that this run is finished
            self.__run_data.set_finished()

            try:
                self.__run_data.stop_tasks()
            except:
                if sent_error is None:
                    sent_error = exc_string()

        if sent_error is not None:
            self.__logger.error("Could not send event counts for %s (%s): %s" %
                                (self, caller_name, sent_error))

    def __get_replay_hubs(self):
        "Return the list of replay hubs in this runset"
        replay_hubs = []
        for comp in self.__set:
            if comp.isReplayHub:
                replay_hubs.append(comp)
        return replay_hubs

    def __get_run_counts(self, bldrs, run_data):
        """
        Get the counts and times for all output streams
        (physics, moni, sn, tcal)
        """
        physics_count = 0
        first_time = 0
        last_time = 0
        first_good = 0
        last_good = 0
        moni_count = 0
        moni_ticks = None
        sn_count = 0
        sn_ticks = None
        tcal_count = 0
        tcal_ticks = None

        comp_op = ComponentOperation.GET_RUN_DATA
        rslt = ComponentOperationGroup.runSimple(comp_op, bldrs,
                                                 (run_data.run_number, ),
                                                 run_data)

        for comp in bldrs:
            result = rslt[comp]
            if result == ComponentOperation.RESULT_HANGING or \
                result == ComponentOperation.RESULT_ERROR or \
                result is None:
                run_data.error("Cannot get run data for %s: %s" %
                               (comp.fullname, result))
            elif not isinstance(result, list) and \
                 not isinstance(result, tuple):
                run_data.error("Bogus run data for %s: %s" %
                               (comp.fullname, result))
            elif comp.isComponent("eventBuilder"):
                exp_num = 5
                if len(result) == exp_num:
                    (physics_count, first_time, last_time, first_good,
                     last_good) = result
                else:
                    run_data.error(("Expected %d run data values from" +
                                    " %s, got %d (%s)") %
                                   (exp_num, comp.fullname, len(result),
                                    str(result)))
            elif comp.isComponent("secondaryBuilders"):
                if len(result) == 6:
                    (tcal_count, tcal_ticks, sn_count, sn_ticks, moni_count,
                     moni_ticks) = result
                elif len(result) == 3:  # XXX remove after Sprecher release
                    (tcal_count, sn_count, moni_count) = result
                else:
                    run_data.error(("Expected 3 or 6 run data values from" +
                                    " %s, got %d (%s)") %
                                   (exp_num, comp.fullname, len(result),
                                    str(result)))

        return (physics_count, first_time, last_time, first_good, last_good,
                moni_count, moni_ticks, sn_count, sn_ticks, tcal_count,
                tcal_ticks)

    @classmethod
    def __get_run_directory_path(cls, log_dir, run_num):
        return os.path.join(log_dir, "daqrun%05d" % run_num)

    def __get_single_bean_field(self, comp, bean, fld_name):
        tgroup = ComponentOperationGroup(ComponentOperation.GET_SINGLE_BEAN)
        tgroup.start(comp, self.__run_data, (bean, fld_name))
        tgroup.wait(waitSecs=3, reps=10)

        rslt = tgroup.results()
        if comp not in rslt:
            result = ComponentOperation.RESULT_ERROR
        else:
            result = rslt[comp]

        return result

    def __internal_init_replay(self, replay_hubs):
        comp_op = ComponentOperation.GET_REPLAY_TIME
        rslt = ComponentOperationGroup.runSimple(comp_op, replay_hubs, (),
                                                 self.__logger)

        # find earliest first hit
        firsttime = None
        for comp in replay_hubs:
            result = rslt[comp]
            if result == ComponentOperation.RESULT_HANGING or \
               result == ComponentOperation.RESULT_ERROR:
                self.__logger.error("Cannot get first replay time for %s: %s" %
                                    (comp.fullname, result))
                continue
            elif result < 0:
                self.__logger.error("Got bad replay time for %s: %s" %
                                    (comp.fullname, result))
                continue
            elif firsttime is None or result < firsttime:
                firsttime = result

        if firsttime is None:
            raise RunSetException("Couldn't find first replay time")

        # calculate offset
        now = time.gmtime()
        jan1 = time.struct_time((now.tm_year, 1, 1, 0, 0, 0, 0, 0, -1))
        walltime = (time.mktime(now) - time.mktime(jan1)) * 10000000000
        offset = long(walltime - firsttime)

        # set offset on all replay hubs
        ComponentOperationGroup.runSimple(ComponentOperation.SET_REPLAY_OFFSET,
                                          replay_hubs, (offset, ),
                                          self.__logger,
                                          errorName="setReplayOffset")

    def __log_error(self, msg):
        if self.__run_data is not None and not self.__run_data.isDestroyed:
            logger = self.__run_data
        else:
            logger = self.__logger

        logger.error(msg)

    def __log_state(self, text, comps):
        """
        Debugging method which logs state information for all components
        in the runset
        """
        self.__logger.error("================= " + text + " =================")
        comp_op = ComponentOperation.GET_CONN_INFO
        conn_info = ComponentOperationGroup.runSimple(comp_op, comps, (),
                                                      self.__logger)
        for comp in comps:
            if comp not in conn_info:
                connstr = "???"
            else:
                connstr = None
                for info in conn_info[comp]:
                    if info["state"].find("idle") == 0:
                        continue

                    sstr = "%s(%s)#%s" % (info["type"], info["state"],
                                          info["numChan"])
                    if connstr is None:
                        connstr = sstr
                    else:
                        connstr += " " + sstr

            if connstr is not None:
                self.__logger.error("%s :: %s: %s" %
                                    (text, comp.fullname, connstr))

    def __queue_for_spade(self, run_data):
        if run_data.log_directory is None:
            run_data.error("Not logging to file so cannot queue to SPADE")
            return

        if run_data.spade_directory is not None:
            if self.__spade_thread is not None:
                if self.__spade_thread.is_alive():
                    try:
                        self.__spade_thread.join(0.001)
                    except:
                        pass
                if self.__spade_thread.is_alive():
                    run_data.error("Previous SpadeQueue thread is still"
                                   " running!!!")

            args = (run_data, run_data.spade_directory,
                    run_data.copy_directory, run_data.log_directory,
                    run_data.run_number)
            thrd = threading.Thread(target=SpadeQueue.queueForSpade,
                                    args=args)
            thrd.start()

            self.__spade_thread = thrd

    def __remove_component(self, comp):
        try:
            self.__set.remove(comp)
        except ValueError:
            self.__logger.error(("Cannot remove component %s from" +
                                 " RunSet #%d") %
                                (comp.fullname, self.__id))

        # clean up active log thread
        if comp in self.__comp_log:
            try:
                self.__comp_log[comp].stopServing()
            except:
                pass
            del self.__comp_log[comp]

        try:
            comp.close()
        except:
            self.__logger.error("Close failed for %s: %s" %
                                (comp.fullname, exc_string()))

    def __report_first_good_time(self, run_data):
        eb_comp = None
        for comp in self.__set:
            if comp.isComponent("eventBuilder"):
                eb_comp = comp
                break

        if eb_comp is None:
            run_data.error("Cannot find eventBuilder in %s" % str(self))
            return

        first_time = None
        for _ in xrange(5):
            val = self.__get_single_bean_field(eb_comp, "backEnd",
                                               "FirstEventTime")
            if val is not None and not isinstance(val, Result):
                first_time = val
                break
            time.sleep(0.1)
        if first_time is None:
            run_data.error("Couldn't find first good time" +
                           " for switched run %d" % (run_data.run_number, ))
        else:
            self.report_good_time(run_data, "firstGoodTime", first_time)

    def __report_run_start(self, moni_client, run_number, release, revision,
                           started, start_time=None):
        data = {
            "runnum": run_number,
            "release": release,
            "revision": revision,
            "started": started,
        }

        if start_time is None:
            start_time = datetime.datetime.now()

        moni_client.sendMoni("runstart", data, prio=Prio.SCP,
                             time=start_time)

    def __report_run_stop(self, num_evts, first_pay_time, last_pay_time,
                          had_error):
        if self.__run_data.has_moni_client:
            first_dt = PayloadTime.toDateTime(first_pay_time,
                                              high_precision=True)
            last_dt = PayloadTime.toDateTime(last_pay_time,
                                             high_precision=True)

            if had_error is None:
                status = "UNKNOWN"
            elif had_error:
                status = "FAIL"
            else:
                status = "SUCCESS"

            data = {"runnum": self.__run_data.run_number,
                    "runstart": str(first_dt),
                    "runstop": str(last_dt),
                    "events": num_evts,
                    "status": status}

            monitime = PayloadTime.toDateTime(last_pay_time)
            self.__run_data.send_moni("runstop", data, prio=Prio.ITS,
                                      time=monitime)

    def __sort_cmp(self, x, y):
        if y.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(y))
            return -1
        elif x.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(x))
            return 1
        else:
            return y.order() - x.order()

    def __start_components(self, quiet):
        live_host = None
        live_port = None

        self.__stop_log_servers()

        log_host = ip.getLocalIpAddr()
        log_port = DAQPort.RUNCOMP_BASE

        tgroup = ComponentOperationGroup(ComponentOperation.CONFIG_LOGGING)
        for comp in self.__set:
            self.__comp_log[comp] \
                = self.create_component_log(self.__run_data.run_directory,
                                            comp, log_host, log_port,
                                            live_host, live_port, quiet=quiet)
            tgroup.start(comp, self.__run_data, (log_host, log_port, live_host,
                                                 live_port))

            log_port += 1

        tgroup.wait()
        tgroup.reportErrors(self.__run_data, "startLogging")

        self.__run_data.error("Starting run %d..." %
                              (self.__run_data.run_number, ))

        src_set, middle_set, bldr_set = self.__build_start_sets()
        other_set = bldr_set + middle_set

        self.__state = RunSetState.STARTING

        # start non-sources
        #
        self.__start_set("NonHubs", other_set)

        # start sources
        #
        self.__start_set("Hubs", src_set)

        # start thread to find latest first time from hubs
        #
        good_thread = FirstGoodTimeThread(src_set[:], other_set[:], self,
                                          self.__run_data, self.__run_data)
        good_thread.start()

        for _ in xrange(20):
            if not good_thread.isAlive():
                break
            time.sleep(0.5)

        if good_thread.isAlive():
            raise RunSetException("Could not get runset#%d latest first time" %
                                  self.__id)

    def __start_set(self, set_name, components):
        """
        Start a set of components and verify that they are running
        """
        rstart = datetime.datetime.now()

        op_data = (self.__run_data.run_number, )
        ComponentOperationGroup.runSimple(ComponentOperation.START_RUN,
                                          components, op_data, self.__run_data,
                                          errorName="start" + set_name)

        self.__wait_for_state_change(self.__run_data, (RunSetState.RUNNING, ),
                                     timeout_secs=30, components=components)

        bad_states = self.__check_state(RunSetState.RUNNING, components)
        if len(bad_states) > 0:
            raise RunSetException(("Could not start runset#%d run#%d" +
                                   " %s components: %s") %
                                  (self.__id, self.__run_data.run_number,
                                   set_name,
                                   self.__bad_state_string(bad_states)))
        rend = datetime.datetime.now() - rstart
        rsecs = float(rend.seconds) + (float(rend.microseconds) / 1000000.0)
        self.__logger.error("Waited %.3f seconds for %s" % (rsecs, set_name))

    def __stop_components(self, src_set, other_set, conn_dict):
        op_name = ComponentOperation.GET_STATE
        states = ComponentOperationGroup.runSimple(op_name,
                                                   src_set + other_set, (),
                                                   self.__logger)

        changed = False

        # remove stopped components from appropriate dictionary
        #
        badlist = []
        for oneset in (src_set, other_set):
            copy = oneset[:]
            for comp in copy:
                if comp in states:
                    state_str = str(states[comp])
                else:
                    state_str = self.STATE_DEAD
                if state_str != self.__state and \
                   state_str != self.STATE_HANGING:
                    oneset.remove(comp)
                    if comp in conn_dict:
                        del conn_dict[comp]
                    changed = True
                else:
                    badlist.append(comp)

        if len(badlist) > 0:
            comp_op = ComponentOperation.GET_CONN_INFO
            allconn = ComponentOperationGroup.runSimple(comp_op, badlist, (),
                                                        self.__logger)
            for comp in badlist:
                if comp not in allconn:
                    cs_str = self.STATE_DEAD
                else:
                    cs_dict = allconn[comp]
                    if isinstance(cs_dict, dict):
                        cs_str = self.__connector_string(cs_dict)
                    else:
                        cs_str = str(cs_dict)
                if comp not in conn_dict:
                    conn_dict[comp] = cs_str
                elif conn_dict[comp] != cs_str:
                    conn_dict[comp] = cs_str
                    changed = True

        return changed

    def __stop_log_servers(self):
        """
        Stop all log servers
        """
        # build list of components with active log servers
        loglist = []
        for comp in self.__set:
            if comp in self.__comp_log:
                loglist.append(comp)

        # stop listed log servers
        ComponentOperationGroup.runSimple(ComponentOperation.STOP_LOGGING,
                                          loglist, self.__comp_log,
                                          self.__logger,
                                          errorName="stopLogging")

    def __stop_run_internal(self, timeout=20):
        """
        Stop all components in the runset
        Return list of components which did not stop
        """
        self.__run_data.stop()

        src_set = []
        other_set = []

        for comp in self.__set:
            if comp.isSource:
                src_set.append(comp)
            else:
                other_set.append(comp)

        # stop from front to back
        #
        other_set.sort(lambda x, y: self.__sort_cmp(y, x))

        # start thread to find earliest last time from hubs
        #
        good_thread = LastGoodTimeThread(src_set[:], other_set[:], self,
                                         self.__run_data, self.__run_data)
        good_thread.start()

        try:
            for i in range(0, 2):
                if self.__run_data is None:
                    break

                if i == 0:
                    rs_state = RunSetState.STOPPING
                    comp_op = ComponentOperation.STOP_RUN
                    op_timeout = int(timeout * .75)
                else:
                    rs_state = RunSetState.FORCING_STOP
                    comp_op = ComponentOperation.FORCED_STOP
                    op_timeout = int(timeout * .25)

                self.__attempt_to_stop(src_set, other_set, rs_state, comp_op,
                                       op_timeout)

                if len(src_set) == 0 and len(other_set) == 0:
                    break
        finally:
            # detector has stopped, no need to get last good time
            try:
                good_thread.stop()
            except:
                # ignore problems stopping good_thread
                pass

        final_set = src_set + other_set
        if len(final_set) > 0 and self.__run_data is not None:
            self.__run_data.error("%s failed for %s" %
                                  (comp_op, listComponentRanges(final_set)))

        if self.__run_data is not None:
            self.__run_data.reset()

        return final_set

    @property
    def __update_counts_and_rate(self):
        if self.__run_data is None:
            return None

        physics_count = 0
        wall_time = -1
        last_pay_time = -1
        moni_count = 0
        moni_time = -1
        sn_count = 0
        sn_time = -1
        tcal_count = 0
        tcal_time = -1

        for comp in self.__set:
            if comp.isComponent("eventBuilder"):
                evt_data = self.__get_single_bean_field(comp, "backEnd",
                                                        "EventData")
                if evt_data is None or isinstance(evt_data, Result):
                    self.__run_data.error("Cannot get event data (%s)" %
                                          (evt_data, ))
                elif not isinstance(evt_data, list) and \
                     not isinstance(evt_data, tuple):
                    self.__run_data.error("Got bad event data (%s)" %
                                          (evt_data, ))
                else:
                    physics_count = int(evt_data[0])
                    wall_time = datetime.datetime.utcnow()
                    last_pay_time = long(evt_data[1])

                if physics_count > 0 and \
                   self.__run_data.first_physics_time <= 0:
                    val = self.__get_single_bean_field(comp, "backEnd",
                                                       "FirstEventTime")
                    if val is None or isinstance(val, Result):
                        msg = "Cannot get first event time (%s)" % (val, )
                        self.__run_data.error(msg)
                    else:
                        self.__run_data.set_first_physics_time(val)

            if comp.isComponent("secondaryBuilders"):
                for bldr in ("moni", "sn", "tcal"):
                    val = self.__get_single_bean_field\
                          (comp, bldr + "Builder", "EventData")
                    if val is None or isinstance(val, Result):
                        msg = "Cannot get %sBuilder dispatched data (%s)" % \
                            (bldr, val)
                        self.__run_data.error(msg)
                        num = 0
                        now = None
                    else:
                        num = val[0]
                        now = val[1]

                    if bldr == "moni":
                        moni_count = num
                        moni_time = now
                    elif bldr == "sn":
                        sn_count = num
                        sn_time = now
                    else:  # bldr == "tcal"
                        tcal_count = num
                        tcal_time = now

        return self.__run_data.update_event_counts\
            (physics_count, wall_time, self.__run_data.first_physics_time,
             last_pay_time, moni_count, moni_time, sn_count, sn_time,
             tcal_count, tcal_time, add_rate=True)

    def __validate_subrun_doms(self, subrun_data):
        """
        Check that all DOMs in the subrun are valid.
        Convert (string, position) pairs in argument lists to mainboard IDs
        """
        doms = []
        not_found = []
        for args in subrun_data:
            # Look for (dommb, f0, ..., f4) or (name, f0, ..., f4)
            if len(args) == 6:
                domid = args[0]
                if not self.__cfg.hasDOM(domid):
                    # Look by DOM name
                    try:
                        args[0] = self.__cfg.getIDbyName(domid)
                    except DOMNotInConfigException:
                        not_found.append("#" + domid)
                        continue
            # Look for (str, pos, f0, ..., f4)
            elif len(args) == 7:
                try:
                    pos = int(args[1])
                    string = int(args.pop(0))
                except ValueError:
                    msg = "Bad DOM '%s-%s' in %s (need integers)!" % \
                        (string, pos, args)
                    raise InvalidSubrunData(msg)
                try:
                    args[0] = self.__cfg.getIDbyStringPos(string, pos)
                except DOMNotInConfigException:
                    not_found.append("Pos %s-%s" % (string, pos))
                    continue
            else:
                raise InvalidSubrunData("Bad subrun arguments %s" %
                                        str(args))
            doms.append(args)
        return (doms, not_found)

    def __wait_for_state_change(self, logger, valid_states,
                                timeout_secs=TIMEOUT_SECS, components=None):
        """
        Wait for state change, with a timeout of timeout_secs (renewed each
        time any component changes state).  Raise a ValueError if the state
        change fails.
        """
        if components is None:
            waitlist = self.__set[:]
        else:
            waitlist = components[:]

        start_secs = time.time()
        end_secs = start_secs + timeout_secs
        while len(waitlist) > 0 and time.time() < end_secs:
            new_list = waitlist[:]
            comp_op = ComponentOperation.GET_STATE
            states = ComponentOperationGroup.runSimple(comp_op, waitlist, (),
                                                       self.__logger)
            found_error = False
            for comp in waitlist:
                if comp in states:
                    state_str = str(states[comp])
                else:
                    state_str = self.STATE_DEAD
                if state_str in valid_states and \
                   state_str != self.STATE_HANGING:
                    new_list.remove(comp)
                if state_str.upper() == "ERROR":
                    found_error = True
                    break

            # if any component encounters an error, give up
            if found_error:
                break

            # if one or more components changed state...
            #
            if len(waitlist) == len(new_list):
                time.sleep(1)
            else:
                waitlist = new_list
                if len(waitlist) > 0:
                    wait_str = listComponentRanges(waitlist)
                    logger.info('%s: Waiting for %s %s' %
                                (str(self), self.__state, wait_str))

                # reset timeout
                #
                end_secs = time.time() + timeout_secs

        total_secs = time.time() - start_secs
        if len(waitlist) > 0:
            wait_str = listComponentRanges(waitlist)
            raise RunSetException(("Still waiting for %d components to" +
                                   " leave %s after %d seconds (%s)") %
                                  (len(waitlist), self.__state, total_secs,
                                   wait_str))

        return total_secs

    def __write_run_xml(self, run_data, num_evts, num_moni, num_sn, num_tcal,
                        first_time, last_time, first_good, last_good,
                        had_error):

        xml_log = DashXMLLog(dir_name=run_data.run_directory)
        path = xml_log.getPath()
        if os.path.exists(path):
            run_data.error("Run xml log file \"%s\" already exists!" %
                           (path, ))
            return

        xml_log.setVersionInfo(run_data.release, run_data.repo_revision)
        xml_log.setRun(run_data.run_number)
        xml_log.setConfig(run_data.run_configuration.basename)
        xml_log.setCluster(run_data.cluster_configuration.description)
        xml_log.setStartTime(PayloadTime.toDateTime(first_time))
        xml_log.setEndTime(PayloadTime.toDateTime(last_time))
        xml_log.setFirstGoodTime(PayloadTime.toDateTime(first_good))
        xml_log.setLastGoodTime(PayloadTime.toDateTime(last_good))
        xml_log.setEvents(num_evts)
        xml_log.setMoni(num_moni)
        xml_log.setSN(num_sn)
        xml_log.setTcal(num_tcal)
        xml_log.setTermCond(had_error)

        # write the xml log file to disk
        try:
            xml_log.writeLog()
        except DashXMLLogException:
            self.__log_error("Could not write run xml log file \"%s\"" %
                             (xml_log.getPath(), ))

    def build_connection_map(self):
        "Validate and fill the map of connections for each component"
        conn_dict = {}

        for comp in self.__set:
            for conn in comp.connectors():
                if conn.name not in conn_dict:
                    conn_dict[conn.name] = ConnTypeEntry(conn.name)
                conn_dict[conn.name].add(conn, comp)

        conn_map = {}

        for name in conn_dict:
            # XXX - this can raise ConnectionException
            conn_dict[name].build_connection_map(conn_map)

        return conn_map

    def components(self):
        return self.__set[:]

    @property
    def configName(self):
        return self.__cfg.basename

    def configure(self):
        "Configure all components in the runset"
        self.__state = RunSetState.CONFIGURING

        data = (self.configName, )
        ComponentOperationGroup.runSimple(ComponentOperation.CONFIG_COMP,
                                          self.__set, data, self.__logger,
                                          errorName="configure")

        cfg_states = (RunSetState.CONFIGURING, RunSetState.READY, )
        self.__wait_for_state_change(self.__logger, cfg_states,
                                     timeout_secs=60)

        self.__wait_for_state_change(self.__logger, (RunSetState.READY, ),
                                     timeout_secs=60)

        bad_states = self.__check_state(RunSetState.READY)
        if len(bad_states) > 0:
            msg = "Could not configure %s" % \
                  self.__bad_state_string(bad_states)
            self.__logger.error(msg)
            raise RunSetException(msg)

        self.__configured = True

    def configured(self):
        return self.__configured

    def connect(self, conn_map, logger):
        self.__state = RunSetState.CONNECTING

        # connect all components
        #
        ComponentOperationGroup.runSimple(ComponentOperation.CONNECT,
                                          self.__set, conn_map, self.__logger,
                                          errorName="logger")

        try:
            self.__wait_for_state_change(self.__logger,
                                         (RunSetState.CONNECTED, ),
                                         timeout_secs=20)
        except:
            # give up after 20 seconds
            pass

        bad_states = self.__check_state(RunSetState.CONNECTED)
        if len(bad_states) > 0:
            err_msg = "Could not connect %s" % \
                      self.__bad_state_string(bad_states)
            raise RunSetException(err_msg)

    @classmethod
    def create_component_log(cls, run_dir, comp, host, port, live_host,
                             live_port, quiet=True):
        if not os.path.exists(run_dir):
            raise RunSetException("Run directory \"%s\" does not exist" %
                                  run_dir)

        log_name = os.path.join(run_dir, "%s-%d.log" % (comp.name, comp.num))
        sock = LogSocketServer(port, comp.fullname, log_name, quiet=quiet)
        sock.startServing()

        return sock

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir, log_dir,
                        testing=False):
        return RunData(self, run_num, cluster_config, self.__cfg,
                       run_options, version_info, spade_dir, copy_dir, log_dir,
                       testing=testing)

    def create_run_dir(self, log_dir, run_num, backupExisting=True):
        if not os.path.exists(log_dir):
            raise RunSetException("Log directory \"%s\" does not exist" %
                                  log_dir)

        run_dir = self.__get_run_directory_path(log_dir, run_num)
        if not os.path.exists(run_dir):
            os.makedirs(run_dir)
        elif not backupExisting:
            if not os.path.isdir(run_dir):
                raise RunSetException("\"%s\" is not a directory" % run_dir)
        else:
            # back up existing run directory to daqrun#####.1 (or .2, etc.)
            #
            n = 1
            while True:
                bak_dir = "%s.%d" % (run_dir, n)
                if not os.path.exists(bak_dir):
                    os.rename(run_dir, bak_dir)
                    break
                n += 1
            os.mkdir(run_dir, 0755)

        return run_dir

    @classmethod
    def cycle_components(cls, comp_list, config_dir, daq_data_dir, logger,
                         log_port, live_port, verbose, killWith9, eventCheck,
                         checkExists=True):

        # sort list into a predictable order for unit tests
        #
        logger.error("Cycling components %s" %
                     (listComponentRanges(comp_list), ))

        dry_run = False
        ComponentManager.killComponents(comp_list, dry_run, verbose, killWith9)
        ComponentManager.startComponents(comp_list, dry_run, verbose,
                                         config_dir, daq_data_dir,
                                         logger.logPort, logger.livePort,
                                         eventCheck, checkExists=checkExists)

    def destroy(self, ignore_components=False):
        if not ignore_components and len(self.__set) > 0:
            raise RunSetException('RunSet #%d is not empty' % self.__id)

        if self.__run_data is not None:
            self.__run_data.destroy()

        self.__id = None
        self.__configured = False
        self.__state = RunSetState.DESTROYED
        self.__run_data = None

    def final_report(self, comps, run_data, had_error=False, switching=False):
        """
        Gather end-of-run statistics and send them to various places
        (Live, dash.log, run.xml)
        This is "public" so it can be overridden by unit tests
        """

        # build list of endpoints (eventBuilder and secondaryBuilders)
        bldrs = []
        for comp in comps:
            if comp.isBuilder:
                bldrs.append(comp)

        (physics_count, first_time, last_time, first_good, last_good,
         moni_count, moni_ticks, sn_count, sn_ticks, tcal_count, tcal_ticks) \
         = self.__get_run_counts(bldrs, run_data)

        # set end-of-run statistics
        now = datetime.datetime.utcnow()
        run_data.update_event_counts(physics_count, now, first_time,
                                     last_time, moni_count, moni_ticks,
                                     sn_count, sn_ticks, tcal_count,
                                     tcal_ticks)
        if run_data.first_physics_time is not None:
            # starting payload time is more accurate, use it if available
            first_time = run_data.first_physics_time

        if physics_count is None or physics_count <= 0:
            if physics_count is None:
                self.__log_error("Reset numEvts and duration for final report")
                physics_count = 0
            else:
                self.__log_error("Reset duration for final report")
            duration = 0
        else:
            if first_time is None:
                err_msg = "Starting time is not set"
            elif last_time is None:
                err_msg = "Ending time is not set"
            elif last_time < first_time:
                err_msg = "Ending time %s is before starting time %s" % \
                          (last_time, first_time)
            else:
                err_msg = None
                duration = (last_time - first_time) / 10000000000

            if err_msg is not None:
                self.__log_error(err_msg)
                had_error = True
                duration = 0

        self.__write_run_xml(run_data, physics_count, moni_count, sn_count,
                             tcal_count, first_time, last_time, first_good,
                             last_good, had_error)

        self.__report_run_stop(physics_count, first_good, last_good, had_error)

        if switching:
            self.report_good_time(run_data, "lastGoodTime", last_time)

        # report rates
        if duration == 0:
            rate_str = ""
        else:
            rate_str = " (%2.2f Hz)" % (float(physics_count) / float(duration))
        self.__run_data.error("%d physics events collected in %d seconds%s" %
                              (physics_count, duration, rate_str))

        if moni_count is None and sn_count is None and tcal_count is None:
            self.__run_data.error("!! secondary stream data is not"
                                  " available !!")
        else:
            if moni_count is None:
                moni_count = 0
            if sn_count is None:
                sn_count = 0
            if tcal_count is None:
                tcal_count = 0
            self.__run_data.error("%d moni events, %d SN events, %d tcals" %
                                  (moni_count, sn_count, tcal_count))

        # report run status
        if not switching:
            end_type = "terminated"
        else:
            end_type = "switched"
        if had_error:
            err_type = "WITH ERROR"
        else:
            err_type = "SUCCESSFULLY"
        self.__run_data.error("Run %s %s." % (end_type, err_type))

        return duration

    def finish_setup(self, run_data, start_time):
        """
        Tell Live that we're starting a new run, launch run-related threads
        """

        # reload the leapseconds file if it's changed,
        #  complain if it's outdated
        config_dir = run_data.run_configuration.configdir
        self.__check_leapseconds(run_data, config_dir)

        # send start-of-run message to Live
        if run_data.has_moni_client:
            self.__report_run_start(run_data.moni_client,
                                    run_data.run_number,
                                    run_data.release,
                                    run_data.repo_revision,
                                    True, start_time=start_time)

        run_data.start_tasks(self)

    def get_event_counts(self):
        "Return monitoring data for the run"
        if self.isRunning:
            values = self.__update_counts_and_rate
        else:
            values = self.__run_data.cached_monitor_data

        if values is None:
            return {}

        (num_evts, wall_time, pay_time, _, num_moni, moni_time, num_sn,
         sn_time, num_tcal, tcal_time) = values

        mon_dict = {}

        mon_dict["physicsEvents"] = num_evts
        if wall_time is None or num_evts == 0:
            mon_dict["wallTime"] = None
            mon_dict["eventPayloadTicks"] = None
        else:
            mon_dict["wallTime"] = str(wall_time)
            mon_dict["eventPayloadTicks"] = pay_time
        mon_dict["moniEvents"] = num_moni
        if moni_time is None:
            mon_dict["moniTime"] = None
        else:
            mon_dict["moniTime"] = moni_time
        mon_dict["snEvents"] = num_sn
        if sn_time is None:
            mon_dict["snTime"] = None
        else:
            mon_dict["snTime"] = sn_time
        mon_dict["tcalEvents"] = num_tcal
        if tcal_time is None:
            mon_dict["tcalTime"] = None
        else:
            mon_dict["tcalTime"] = tcal_time

        return mon_dict

    @classmethod
    def get_run_summary(cls, log_dir, run_num):
        "Return a dictionary summarizing the requested run"
        run_dir = cls.__get_run_directory_path(log_dir, run_num)
        if not os.path.exists(run_dir):
            raise RunSetException("No run directory found for run %d" %
                                  (run_num, ))

        return DashXMLLog.parse(run_dir).summary()

    @property
    def id(self):
        return self.__id

    def init_replay_hubs(self):
        "Initialize all replay hubs"
        replay_hubs = self.__get_replay_hubs()
        if len(replay_hubs) == 0:
            return

        prev_state = self.__state
        self.__state = RunSetState.INIT_REPLAY

        try:
            self.__internal_init_replay(replay_hubs)
        finally:
            self.__state = prev_state

    @property
    def isDestroyed(self):
        return self.__state == RunSetState.DESTROYED

    @property
    def isReady(self):
        return self.__state == RunSetState.READY

    @property
    def isRunning(self):
        return self.__state == RunSetState.RUNNING

    @classmethod
    def is_leapsecond_silenced(cls, filename=".leapsecond_alertstamp"):
        """
        Check a named file in the users home directory looking for a timestamp
        indicating the last time when leapsecond warnings were NOT silenced.

        Returns True if silenced
        """
        # build the file path
        alert_timestamp_fname = os.path.join(os.environ["HOME"], filename)

        # check to see if the limit file exists
        try:
            with open(alert_timestamp_fname, 'r') as fin:
                tstamp = int(fin.read())
            diff = time.time() - tstamp
        except IOError:
            # could not open the alert timestamp file for reading
            diff = None
        except ValueError:
            # contents of the alert timestamp file is not an int
            diff = None

        # if it's been less than a day since we were last silenced...
        if diff is not None and diff < 24 * 3600:
            # ... we're still silenced
            return True

        with open(alert_timestamp_fname, 'w') as fout:
            fout.write("%d" % time.time())

        return False

    def log_to_dash(self, msg):
        "Used when the runset needs to add a log message to dash.log"
        self.__log_error(msg)

    def report_good_time(self, run_data, name, pay_time):
        if not run_data.has_moni_client:
            return

        try:
            fulltime = PayloadTime.toDateTime(pay_time, high_precision=True)
        except:
            run_data.error("Cannot report %s: Bad value '%s'" %
                           (name, pay_time))
            return

        value = {
            "runnum": run_data.run_number,
            "subrun": run_data.subrun_number,
            "time": str(fulltime),
        }

        monitime = PayloadTime.toDateTime(pay_time)
        run_data.send_moni(name, value, prio=Prio.SCP, time=monitime)

    def report_run_start_failure(self, run_num, release, revision):
        try:
            moni_client = MoniClient("pdaq", "localhost", DAQPort.I3LIVE)
        except:
            self.__logger.error("Cannot create temporary client: " +
                                exc_string())
            return

        try:
            self.__report_run_start(moni_client, run_num, release, revision,
                                    False)
        finally:
            try:
                moni_client.close()
            except:
                self.__logger.error("Could not close temporary client: " +
                                    exc_string())

    def reset(self):
        "Reset all components in the runset back to the idle state"
        self.__state = RunSetState.RESETTING

        ComponentOperationGroup.runSimple(ComponentOperation.RESET_COMP,
                                          self.__set, (), self.__logger,
                                          errorName="reset")

        try:
            self.__wait_for_state_change(self.__logger, (RunSetState.IDLE, ),
                                         timeout_secs=20)
        except:
            # give up after 60 seconds
            pass

        bad_comps = []

        bad_states = self.__check_state(RunSetState.IDLE)
        if len(bad_states) > 0:
            self.__logger.error("Restarting %s after reset" %
                                self.__bad_state_string(bad_states))
            for state in bad_states:
                bad_comps += bad_states[state]

        self.__configured = False
        self.__run_data = None

        return bad_comps

    def reset_logging(self):
        "Reset logging for all components in the runset"
        ComponentOperationGroup.runSimple(ComponentOperation.RESET_LOGGING,
                                          self.__set, (), self.__logger,
                                          errorName="reset_logging")

    def restart_all_components(self, cluster_config, config_dir, daq_data_dir,
                               log_port, live_port, verbose, killWith9,
                               eventCheck):
        # restarted components are removed from self.__set, so we need to
        # pass in a copy of self.__set, because we'll need self.__set intact
        self.restart_components(self.__set[:], cluster_config, config_dir,
                                daq_data_dir, log_port, live_port, verbose,
                                killWith9, eventCheck)

    def restart_components(self, comp_list, cluster_config, config_dir,
                           daq_data_dir, log_port, live_port, verbose,
                           killWith9, eventCheck):
        """
        Remove all components in 'comp_list' (and which are found in
        'cluster_config') from the runset and restart them
        """
        clu_cfg_list, missing_list \
            = cluster_config.extractComponents(comp_list)

        # complain about missing components
        if len(missing_list) > 0:
            self.__logger.error(("Cannot restart %s: Not found in" +
                                 " cluster config %s") %
                                (listComponentRanges(missing_list),
                                 cluster_config))

        # remove remaining components from this runset
        for comp in comp_list:
            for node_comp in clu_cfg_list:
                if comp.name.lower() == node_comp.name.lower() and \
                   comp.num == node_comp.id:
                    self.__remove_component(comp)
                    break

        self.cycle_components(clu_cfg_list, config_dir, daq_data_dir,
                              self.__logger, log_port, live_port, verbose,
                              killWith9, eventCheck)

    def return_components(self, pool, cluster_config, config_dir, daq_data_dir,
                          log_port, live_port, verbose, killWith9, eventCheck):
        bad_comps = self.reset()
        if len(bad_comps) > 0:
            self.restart_components(bad_comps, cluster_config, config_dir,
                                    daq_data_dir, log_port, live_port, verbose,
                                    killWith9, eventCheck)

        # transfer components back to pool
        #
        while len(self.__set) > 0:
            comp = self.__set[0]
            del self.__set[0]
            if comp not in bad_comps:
                pool.add(comp)
            else:
                self.__logger.error("Not returning unexpected component %s" %
                                    comp.fullname)

        # raise exception if one or more components could not be reset
        #
        if len(bad_comps) > 0:
            raise RunSetException('Could not reset %s' % str(bad_comps))

    @property
    def run_config_data(self):
        return self.__cfg

    def run_number(self):
        if self.__run_data is None:
            return None

        return self.__run_data.run_number

    def send_event_counts(self, run_data=None):
        "Report run monitoring quantities"

        if run_data is None:
            run_data = self.__run_data

        if run_data is None or not run_data.has_moni_client:
            # don't bother if we can't report anything
            return

        moni_data = self.get_event_counts()

        # send every 5th set of data over ITS
        if self.__moni_count % 5 == 0:
            prio = Prio.ITS
        else:
            prio = Prio.EMAIL
        self.__moni_count += 1

        if True:  # XXX this should be removed after Sprecher is released
            run_update = {
                "run": run_data.run_number,
                "subrun": run_data.subrun_number,
                "version": 0,
            }

            # fill in counts and times
            run_update["physicsEvents"] = moni_data["physicsEvents"]
            if moni_data["wallTime"] is not None:
                run_update["wallTime"] = moni_data["wallTime"]
            for src in ("moni", "sn", "tcal"):
                event_key = src + "Events"
                time_key = src + "Time"
                if moni_data[time_key] is not None and \
                   moni_data[time_key] >= 0:
                    run_update[event_key] = moni_data[event_key]
                    run_update[time_key] = str(moni_data[time_key])

            # if we don't have a DAQ time, use system time but complain
            if moni_data["eventPayloadTicks"] is not None:
                ptime = PayloadTime.toDateTime(moni_data["eventPayloadTicks"])
            else:
                ptime = datetime.datetime.utcnow()
                run_data.error("Using system time for initial event" +
                               " counts (no event times available)")

            run_data.send_moni("run_update", run_update, prio=prio, time=ptime)

        run_data.send_count_updates(moni_data, prio)

    def set_order(self, conn_map, logger):
        "set the order in which components are started/stopped"

        # build initial lists of source components
        #
        all_comps = {}
        cur_level = []
        for comp in self.__set:
            # complain if component has already been added
            #
            if comp in all_comps:
                logger.error('Found multiple instances of %s' % (comp, ))
                continue

            # clear order
            #
            comp.setOrder(None)

            # add component to the list
            #
            all_comps[comp] = 1

            # if component is a source, save it to the initial list
            #
            if comp.isSource:
                cur_level.append(comp)

        if len(cur_level) == 0:
            raise RunSetException("No sources found")

        # walk through detector, setting order number for each component
        #
        level = 1
        while len(all_comps) > 0 and len(cur_level) > 0 and \
                level < len(self.__set) + 2:
            tmp = {}
            for comp in cur_level:

                # if we've already ordered this component, skip it
                #
                if comp not in all_comps:
                    continue

                del all_comps[comp]

                comp.setOrder(level)

                if comp not in conn_map:
                    if comp.isSource:
                        logger.warn('No connection map entry for %s' %
                                    (comp, ))
                else:
                    for conn in conn_map[comp]:
                        # XXX hack -- ignore source->builder links
                        if not comp.isSource or \
                             conn.comp.name.lower() != "eventBuilder":
                            tmp[conn.comp] = 1

            cur_level = tmp.keys()
            level += 1

        if len(all_comps) > 0:
            err_str = 'Unordered:'
            for comp in all_comps:
                err_str += ' ' + str(comp)
            logger.error(err_str)

        for comp in self.__set:
            fail_str = None
            if not comp.order():
                if not fail_str:
                    fail_str = 'No order set for ' + str(comp)
                else:
                    fail_str += ', ' + str(comp)
            if fail_str:
                raise RunSetException(fail_str)

    def set_run_error(self, caller_name):
        """
        Used by WatchdogTask (via TaskManager) to stop the current run
        """
        if self.__state == RunSetState.RUNNING and self.__stopping is None:
            try:
                self.stop_run(caller_name, had_error=True)
            except:
                pass

    def size(self):
        return len(self.__set)

    def start_run(self, run_num, cluster_config, run_options, version_info,
                  spade_dir, copy_dir=None, log_dir=None, quiet=True):
        "Start all components in the runset"
        self.__logger.error("Starting run #%d on \"%s\"" %
                            (run_num, cluster_config.description))
        if not self.__configured:
            raise RunSetException("RunSet #%d is not configured" % self.__id)
        if self.__state != RunSetState.READY:
            raise RunSetException("Cannot start runset from state \"%s\"" %
                                  self.__state)

        self.__run_data = self.create_run_data(run_num, cluster_config,
                                               run_options, version_info,
                                               spade_dir, copy_dir, log_dir)

        # record the earliest possible start time
        #
        start_time = datetime.datetime.now()

        self.__run_data.connect_to_live()
        self.__start_components(quiet)
        self.finish_setup(self.__run_data, start_time)

    @property
    def state(self):
        return self.__state

    def status(self):
        """
        Return a dictionary of components in the runset
        and their current state
        """
        comp_op = ComponentOperation.GET_STATE
        states = ComponentOperationGroup.runSimple(comp_op, self.__set, (),
                                                   self.__logger)

        set_stats = {}
        for comp in self.__set:
            if comp in states:
                set_stats[comp] = str(states[comp])
            else:
                set_stats[comp] = self.STATE_DEAD

        return set_stats

    def stop_run(self, caller_name, had_error=False, timeout=20):
        """
        Stop all components in the runset
        Return True if an error is encountered while stopping.
        """
        with self.__stop_lock:
            if self.__run_data is None:
                raise RunSetException("RunSet #%d is not running" % self.__id)

            if self.__run_data.finished:
                self.__logger.error("Not double-stopping %s" % self.__run_data)
                return

            if self.__stopping is not None:
                msg = "Ignored %s stop_run() call, stop_run()" \
                      " from %s is active" % (caller_name, self.__stopping)
                self.__run_data.error(msg)
                return False

            if caller_name != self.NORMAL_STOP:
                self.__run_data.error("Stopping the run (%s)" % caller_name)

            self.__stopping = caller_name

        try:
            waitlist = self.__stop_run_internal(timeout=timeout)
        except:
            waitlist = []
            had_error = True
            self.__logger.error("Could not stop run for %s (%s): %s" %
                                (self, caller_name, exc_string()))
            raise
        finally:
            if len(waitlist) > 0:
                had_error = True
            try:
                self.__finish_stop(caller_name, had_error=had_error)
            finally:
                with self.__stop_lock:
                    self.__stopping = None

        # throw an exception if any component state is not READY
        self.__check_stopped_components(waitlist)

        return had_error

    def stopping(self):
        return self.__stopping is not None

    def subrun(self, sub_id, data):
        "Start a subrun with all components in the runset"
        if self.__run_data is None or self.__state != RunSetState.RUNNING:
            raise RunSetException("RunSet #%d is not running" % self.__id)

        if len(data) > 0:
            try:
                (new_data, missing_doms) = self.__validate_subrun_doms(data)
                if len(missing_doms) > 0:
                    if len(missing_doms) > 1:
                        plural = "s"
                    else:
                        plural = ""
                    self.__run_data.warn(("Subrun %d: ignoring missing" +
                                          " DOM%s %s") % (sub_id, plural,
                                                          missing_doms))

                # new_data has any missing DOMs deleted and any string/position
                # pairs converted to mainboard IDs
                data = new_data
            except InvalidSubrunData as inv:
                raise RunSetException("Subrun %d: invalid argument list (%s)" %
                                      (sub_id, inv))

            if len(missing_doms) > 1:
                plural = "s"
            else:
                plural = ""
            self.__run_data.error("Subrun %d: flashing DOM%s (%s)" %
                                  (sub_id, plural, str(data)))
        else:
            self.__run_data.error("Subrun %d: stopping flashers" % sub_id)
        for comp in self.__set:
            if comp.isBuilder:
                comp.prepareSubrun(sub_id)

        self.__run_data.set_subrun_number(-sub_id)

        hubs = []
        for comp in self.__set:
            if comp.isSource:
                hubs.append(comp)

        r = ComponentOperationGroup.runSimple(ComponentOperation.START_SUBRUN,
                                              hubs, (data, ), self.__run_data,
                                              waitSecs=6)

        bad_comps = []

        latest_time = None
        for comp in hubs:
            result = r[comp]
            if result is None or \
                result == ComponentOperation.RESULT_HANGING or \
                result == ComponentOperation.RESULT_ERROR:
                bad_comps.append(comp)
            elif latest_time is None or result > latest_time:
                latest_time = result

        if latest_time is None:
            raise RunSetException("Couldn't start subrun on any string hubs")

        if len(bad_comps) > 0:
            raise RunSetException("Couldn't start subrun on %s" %
                                  listComponentRanges(bad_comps))

        for comp in self.__set:
            if comp.isBuilder:
                comp.commitSubrun(sub_id, latest_time)

        self.__run_data.set_subrun_number(sub_id)

    def subrun_events(self, subrun_number):
        "Get the number of events in the specified subrun"
        for comp in self.__set:
            if comp.isBuilder:
                return comp.subrunEvents(subrun_number)

        raise RunSetException('RunSet #%d does not contain an event builder' %
                              self.__id)

    @staticmethod
    def switch_component_log(sock, run_dir, comp):
        if not os.path.exists(run_dir):
            raise RunSetException("Run directory \"%s\" does not exist" %
                                  run_dir)

        log_name = os.path.join(run_dir, "%s-%d.log" % (comp.name, comp.num))
        sock.setOutput(log_name)

    def switch_run(self, new_num):
        "Switch all components in the runset to a new run"
        if self.__run_data is None:
            raise RunSetException("RunSet #%d is not running" % self.__id)
        if self.__state != RunSetState.RUNNING:
            raise RunSetException("RunSet #%d is %s, not running" %
                                  (self.__id, self.__state))

        # stop monitoring, watchdog, etc.
        #
        self.__run_data.stop()

        # create new run data object
        #
        new_data = self.__run_data.clone(self, new_num)
        new_data.connect_to_live()

        new_data.error("Switching to run %d..." % new_num)

        # switch logs to new daqrun directory before switching components
        #
        for comp in self.__comp_log:
            self.switch_component_log(self.__comp_log[comp],
                                      new_data.run_directory, comp)

        # get lists of sources and of non-sources sorted back to front
        #
        src_set, middle_set, bldr_set = self.__build_start_sets()

        # record the earliest possible start time
        #
        start_time = datetime.datetime.now()

        # switch builders first
        #
        for comp in bldr_set:
            comp.switchToNewRun(new_num)

        # switch non-builders in order
        #
        for comp in middle_set:
            comp.switchToNewRun(new_num)

        # switch sources in parallel
        #
        ComponentOperationGroup.runSimple(ComponentOperation.SWITCH_RUN,
                                          src_set, (new_num, ),
                                          self.__run_data, errorName="switch")

        # wait for builders to finish switching
        #
        bldr_sleep = 0.5
        bldr_max_sleep = 30   # wait up to 30 seconds
        for i in xrange(int(bldr_max_sleep / bldr_sleep)):
            for comp in bldr_set:
                num = comp.getRunNumber()
                if num == new_num:
                    bldr_set.remove(comp)

            if len(bldr_set) == 0:
                break

            if i > 0 and i % 10 == 0:
                self.__run_data.error("Waiting for builders to switch"
                                      " (after %.1f seconds): %s" %
                                      ((i * bldr_sleep), bldr_set))
            time.sleep(bldr_sleep)

        # from this point, cache any failures until the end
        saved_ex = None

        # if there's a problem...
        #
        if len(bldr_set) > 0:
            bad_bldrs = []
            for comp in bldr_set:
                bad_bldrs.append(comp.fullname)
            self.__state = RunSetState.ERROR
            try:
                raise RunSetException("Still waiting for %s to finish"
                                      " switching" % " ".join(bad_bldrs))
            except:
                saved_ex = sys.exc_info()

        # switch to new run data
        #
        old_data = self.__run_data
        self.__run_data = new_data

        # finish new run data setup
        #
        try:
            self.finish_setup(new_data, start_time)
        except:
            if saved_ex is None:
                saved_ex = sys.exc_info()

        try:
            self.final_report(self.__set, old_data, had_error=False,
                              switching=True)
        except:
            if not saved_ex:
                saved_ex = sys.exc_info()
        finally:
            self.__parent.saveCatchall(old_data.run_directory)

        try:
            self.send_event_counts(old_data)
        except:
            if not saved_ex:
                saved_ex = sys.exc_info()

        try:
            # NOTE: ALL FILES MUST BE WRITTEN OUT BEFORE THIS POINT
            # THIS IS WHERE EVERYTHING IS PUT IN A TARBALL FOR SPADE
            self.__queue_for_spade(old_data)
        except:
            if not saved_ex:
                saved_ex = sys.exc_info()

        # note that the old run is finished
        old_data.set_finished()

        try:
            old_data.stop_tasks()
        except:
            if not saved_ex:
                saved_ex = sys.exc_info()

        try:
            self.__report_first_good_time(new_data)
        except:
            if not saved_ex:
                saved_ex = sys.exc_info()

        if saved_ex:
            raise saved_ex[0], saved_ex[1], saved_ex[2]

    def update_rates(self):
        values = self.__update_counts_and_rate
        if values is None:
            return None

        (num_evts, _, _, _, num_moni, _, num_sn, _, num_tcal, _) = values

        return (num_evts, self.__run_data.rate, num_moni, num_sn, num_tcal)


if __name__ == "__main__":
    pass
