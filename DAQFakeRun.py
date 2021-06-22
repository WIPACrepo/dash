#!/usr/bin/env python
"""
Manage a 'fake' run (which can include 'real' Java components)

To test CnCServer, start it with:
    python CnCServer.py -c "/tmp/pdaq/config" -j "/tmp/pdaq/jade" \
        -o "/tmp/pdaq/log" -q "/tmp/pdaq/pdaqlocal" -v

then run this program to simulate a pDAQ run:
    PYTHONPATH=~/prj/livecore python DAQFakeRun.py
"""

from __future__ import print_function

import datetime
import os
import random
import select
import shutil
import socket
import sys
import threading
import time
import traceback

from CnCServer import Connector
from DAQConfig import ConfigNotSpecifiedException, DAQConfig, DAQConfigParser
from DAQConst import DAQPort
from DAQMocks import MockLeapsecondFile
from DAQRPC import RPCClient
from DefaultDomGeometry import DefaultDomGeometry, DefaultDomGeometryReader
from FakeClient import FakeClient, FakeClientException, PortNumber
from FakeComponent import StringHub
from RunOption import RunOption
from locate_pdaq import find_pdaq_config
from utils import ip
from xmlparser import XMLBadFileError

LOUD = False


class DAQFakeRunException(Exception):
    "Base exception"


class HubType(object):
    "Hub type definitions"
    ALL = 0
    PHYSICS_ONLY = 1
    SECONDARY_ONLY = 2


class LogThread(threading.Thread):
    "Log message reader socket"

    TIMEOUT = 100

    def __init__(self, comp_name, port):
        """
        Create a log socket reader

        comp_name - component name
        port - log port number
        """

        self.__comp_name = comp_name
        self.__port = port

        self.__sock = None
        self.__serving = False

        log_name = "%s:log#%d" % (self.__comp_name, self.__port)
        super(LogThread, self).__init__(name=log_name)
        self.setDaemon(True)

    def stop(self):
        "Stop reading from the socket"
        self.__serving = False
        self.__sock.close()

    def run(self):
        "Create socket and read until closed"
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.setblocking(0)
        self.__sock.settimeout(2)
        self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if LOUD:
            print("Create log server localhost#%d" % self.__port,
                  file=sys.stderr)
        try:
            self.__sock.bind(("", self.__port))
        except socket.error:
            raise FakeClientException('Cannot bind log thread to port %d' %
                                      self.__port)

        self.__serving = True

        prd = [self.__sock]
        pwr = []
        per = [self.__sock]
        while self.__serving:
            try:
                rdsock, _, ersock = select.select(prd, pwr, per, self.TIMEOUT)
            except select.error as selerr:
                if selerr[0] == socket.EBADF:
                    break
                raise
            except socket.error as sockerr:
                if sockerr.errno == socket.EBADF:
                    break
                raise

            if len(ersock) != 0:  # pylint: disable=len-as-condition
                print("Error on select", file=sys.stderr)

            if len(rdsock) == 0:  # pylint: disable=len-as-condition
                continue

            while True:
                try:
                    data = self.__sock.recv(8192, socket.MSG_DONTWAIT)
                    if LOUD:
                        print("%s: %s" % (self.__comp_name, data),
                              file=sys.stderr)
                except:  # pylint: disable=bare-except
                    break  # Go back to select so we don't busy-wait


class ComponentData(object):
    "Component data used to create simulated components"

    def __init__(self, comp_name, comp_num, numeric_prefix=False):
        """
        Create a component

        comp_name - component name
        comp_num - component number
        bean_dict - dictionary of 'MBean' name/value pairs
        numeric_prefix - if True, add a number to the component name
        """
        self.__name = comp_name
        self.__num = comp_num
        self.__is_fake = True
        self.__numeric_prefix = numeric_prefix

        self.__conn_list = None

    def __str__(self):
        return self.fullname

    @property
    def connections(self):
        "Return list of connections"
        return self.__conn_list

    @connections.setter
    def connections(self, connlist):
        "Set the connections for this component"
        self.__conn_list = connlist

    @classmethod
    def create_all_data(cls, num_hubs, numeric_prefix=False,
                        include_icetop=False):
        "Create initial component data list"
        comps = cls.create_hubs(num_hubs, 1, numeric_prefix=numeric_prefix,
                                is_icetop=False)
        if include_icetop:
            it_hubs = num_hubs / 8
            if it_hubs == 0:
                it_hubs = 1
            comps += cls.create_hubs(it_hubs, 201,
                                     numeric_prefix=numeric_prefix,
                                     is_icetop=True)

        # create additional components
        comps.append(TriggerDescription("inIceTrigger", 0,
                                        numeric_prefix=numeric_prefix))
        if include_icetop:
            comps.append(TriggerDescription("icetopTrigger", 0,
                                            numeric_prefix=numeric_prefix))

        comps.append(TriggerDescription("globalTrigger", 0,
                                        numeric_prefix=numeric_prefix))
        comps.append(BuilderDescription("eventBuilder", 0,
                                        numeric_prefix=numeric_prefix))
        comps.append(BuilderDescription("secondaryBuilders", 0,
                                        numeric_prefix=numeric_prefix))

        return comps

    @staticmethod
    def create_hubs(num_hubs, starting_number, numeric_prefix=False,
                    is_icetop=False, hub_type=HubType.ALL):
        "create all stringHubs"
        comps = []
        for num in range(num_hubs):
            hub = HubDescription(num + starting_number,
                                 numeric_prefix=numeric_prefix,
                                 is_icetop=is_icetop, hub_type=hub_type)
            comps.append(hub)

        return comps

    @staticmethod
    def create_small_data():
        "Create 3-element component data list"
        comps = []
        for idx in range(3):
            if idx == 0:
                name = "foo"
                connlist = [("hit", Connector.OUTPUT)]
            elif idx == 1:
                name = "bar"
                connlist = [
                    ("hit", Connector.INPUT),
                    ("event", Connector.OUTPUT),
                ]
            elif idx == 2:
                name = "builder"
                connlist = [("event", Connector.INPUT)]
            else:
                break

            comp = ComponentData(name, 0)
            comp.connections = connlist
            comps.append(comp)

        return comps

    @staticmethod
    def create_tiny_data():
        "Create 2-element component data list"
        comps = []
        for idx in range(2):
            if idx == 0:
                name = "foo"
                connlist = [("hit", Connector.OUTPUT)]
            elif idx == 1:
                name = "bar"
                connlist = [("hit", Connector.INPUT)]
            else:
                break

            comp = ComponentData(name, 0)
            comp.connections = connlist
            comps.append(comp)

        return comps

    @property
    def fullname(self):
        "Full component name, omitting the instance number if it's zero"
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def get_fake_client(self, _, quiet=False):
        "Create a FakeClient object using this component data"
        if not self.__is_fake:
            return None

        return FakeClient(self.__name, self.__num, self.connections,
                          numeric_prefix=self.__numeric_prefix, quiet=quiet)

    def is_component(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def is_fake(self):
        "Return True if this is a FakeClient"
        return self.__is_fake

    @property
    def name(self):
        "Return the component name"
        return self.__name

    @property
    def num(self):
        "Return the component instance number"
        return self.__num

    @property
    def use_numeric_prefix(self):
        "Return True if this component should prepend a numeric value"
        return self.__numeric_prefix

    def use_real_component(self):
        "This component should not register itself so the Java version is used"
        self.__is_fake = False


class HubDescription(ComponentData):
    "StringHub data"

    def __init__(self, num, numeric_prefix=False, is_icetop=False,
                 hub_type=HubType.ALL):
        super(HubDescription, self).__init__("stringHub", num,
                                             numeric_prefix=numeric_prefix)

        connlist = []
        if hub_type in (HubType.ALL, HubType.PHYSICS_ONLY):
            connlist += [
                ("rdoutReq", Connector.INPUT),
                ("rdoutData", Connector.OUTPUT),
            ]
            if is_icetop:
                connlist.append(("icetopHit", Connector.OUTPUT))
            else:
                connlist.append(("stringHit", Connector.OUTPUT))
        if hub_type in (HubType.ALL, HubType.SECONDARY_ONLY):
            connlist += [
                ("moniData", Connector.OUTPUT),
                ("snData", Connector.OUTPUT),
                ("tcalData", Connector.OUTPUT),
            ]
        self.connections = connlist

    def get_fake_client(self, def_dom_geom, quiet=False):
        "Create a FakeClient object using this component data"
        if not self.is_fake:
            return None

        return StringHub(self.name, self.num, def_dom_geom, self.connections,
                         quiet=quiet)


class TriggerDescription(ComponentData):
    "Trigger data"

    def __init__(self, name, num, numeric_prefix=False):
        super(TriggerDescription, self).__init__(name, num,
                                                 numeric_prefix=numeric_prefix)

        if name == "inIceTrigger":
            connlist = [
                ("stringHit", Connector.INPUT),
                ("trigger", Connector.OUTPUT),
            ]
        elif name == "iceTopTrigger":
            connlist = [
                ("icetopHit", Connector.INPUT),
                ("trigger", Connector.OUTPUT),
            ]
        elif name == "globalTrigger":
            connlist = [
                ("trigger", Connector.INPUT),
                ("glblTrig", Connector.OUTPUT),
            ]
        else:
            raise FakeClientException("Unknown trigger handler \"%s\"" %
                                      (name, ))

        self.connections = connlist


class BuilderDescription(ComponentData):
    "EventBuilder/SecondaryBuilders data"

    def __init__(self, name, num, numeric_prefix=False):
        super(BuilderDescription, self).__init__(name, num,
                                                 numeric_prefix=numeric_prefix)

        if name == "eventBuilder":
            connlist = [
                ("glblTrig", Connector.INPUT),
                ("rdoutReq", Connector.OUTPUT),
                ("rdoutData", Connector.INPUT),
            ]
        elif name == "secondaryBuilders":
            connlist = [
                ("moniData", Connector.INPUT),
                ("snData", Connector.INPUT),
                ("tcalData", Connector.INPUT),
            ]
        else:
            raise FakeClientException("Unknown builder \"%s\"" % (name, ))

        self.connections = connlist


class DAQFakeRun(object):
    "Fake DAQRun"

    LOCAL_ADDR = ip.get_local_address()
    CNCSERVER_HOST = LOCAL_ADDR

    def __init__(self, cnc_host=CNCSERVER_HOST, cnc_port=DAQPort.CNCSERVER):
        """
        Create a fake DAQRun

        cnc_host - CnCServer host name/address
        cnc_port - CnCServer port number
        """

        self.__log_threads = []

        self.__client = RPCClient(cnc_host, cnc_port)

    def __check_finished_run(self, run_num):
        summary = self.__client.rpc_run_summary(run_num)
        if "result" not in summary:
            raise FakeException("No result field found in run #%d summary" %
                                (run_num, ))
        print("Run #%d: %s" % (run_num, summary["result"]))

    @staticmethod
    def __create_cluster_desc_file(run_cfg_dir):
        path = os.path.join(run_cfg_dir, "sps-cluster.cfg")
        if not os.path.exists(path):
            with open(path, 'w') as fin:
                print("""<cluster name="localhost">
  <logDirForSpade>spade</logDirForSpade>
 <default>
   <jvm>java</jvm>
    <jvmArgs>-server</jvmArgs>
    <logLevel>INFO</logLevel>
 </default>
  <host name="localhost">
    <component name="SecondaryBuilders" required="true"/>
    <component name="eventBuilder" required="true"/>
    <component name="globalTrigger" required="true"/>
    <component name="inIceTrigger"/>
    <component name="iceTopTrigger"/>
    <component name="amandaTrigger"/>
    <simulatedHub number="100" priority="1"/>
  </host>
</cluster>""", file=fin)

    @staticmethod
    def __get_run_time(start_time):
        diff = datetime.datetime.now() - start_time
        return float(diff.seconds) + (float(diff.microseconds) / 1000000.0)

    def __monitor_run(self, runset_id, run_num, start_time, duration,
                      num_checks):
        wait_secs = duration / float(num_checks)

        reps = 0
        run_secs = 0
        while run_secs <= duration and reps < num_checks:
            time.sleep(wait_secs)

            try:
                num_evts = self.__client.rpc_runset_events(runset_id, -1)
            except:  # pylint: disable=bare-except
                num_evts = None

            run_secs = self.__get_run_time(start_time)
            if num_evts is not None:
                print("RunSet %d had %d event%s after %.2f secs" %
                      (runset_id, num_evts, "s" if num_evts != 1 else "",
                       run_secs))
            else:
                print("RunSet %d could not get event count after %.2f secs" %
                      (runset_id, run_secs))

            reps += 1

    def __run_internal(self, runset_id, run_num, duration, subrun_doms=None,
                       verbose=False):
        """
        Take all components through a simulated run

        runset_id - ID of runset being used
        run_num - run number
        duration - length of run in seconds
        verbose - if True, print progress messages
        """
        run_comps = self.__client.rpc_runset_list(runset_id)
        if verbose:
            print("Found %d components" % (len(run_comps), ))

        log_list = []
        for comp in run_comps:
            log_port = PortNumber.next_number()

            log_thread = LogThread("%s#%d" %
                                   (comp["compName"], comp["compNum"]),
                                   log_port)
            log_thread.start()

            self.__log_threads.append(log_thread)
            log_list.append([comp["compName"], comp["compNum"], log_port])

        run_options = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        stopped = False
        try:
            self.__client.rpc_runset_start_run(runset_id, run_num, run_options)

            start_time = datetime.datetime.now()

            time.sleep(1)

            self.__client.rpc_runset_list(runset_id)

            time.sleep(1)

            if subrun_doms is not None:
                data = []
                for mbid in subrun_doms:
                    data.append((mbid, 0, 1, 2, 3, 4))

                print("Subrun data %s" % str(data), file=sys.stderr)
                self.__client.rpc_runset_subrun(runset_id, -1, data)
                self.__client.rpc_runset_subrun(runset_id, 1, data)
                self.__client.rpc_runset_subrun(runset_id, -2, data)
                self.__client.rpc_runset_subrun(runset_id, 2, data)

            self.__monitor_run(runset_id, run_num, start_time, duration, 6)

            self.__client.rpc_runset_switch_run(runset_id, run_num + 1)
            switch_time = datetime.datetime.now()
            self.__check_finished_run(run_num)

            self.__monitor_run(runset_id, run_num + 1, switch_time, duration,
                               3)

            self.__client.rpc_runset_stop_run(runset_id)
            stopped = True
            self.__check_finished_run(run_num + 1)

        finally:
            if not stopped:
                try:
                    self.__client.rpc_runset_stop_run(runset_id)
                except:  # pylint: disable=bare-except
                    print("Cannot stop run for runset #%d\n%s" %
                          (runset_id, traceback.format_exc()), file=sys.stderr)

    def __run_one(self, comp_list, run_cfg, run_num, duration, verbose=False,
                  subrun_doms=None):
        """
        Simulate a run

        comp_list - list of components
        run_cfg - run configuration object
        run_num - run number
        duration - length of run in seconds
        """

        num_sets = self.__client.rpc_runset_count()
        if LOUD:
            print("%d active runsets" % num_sets, file=sys.stderr)
            for cdict in self.__client.rpc_component_list_dicts():
                print(str(cdict), file=sys.stderr)
            print("---", file=sys.stderr)

        runset_id = self.make_runset(comp_list, run_cfg.basename, run_num)

        if num_sets != self.__client.rpc_runset_count() - 1:
            print("Expected %d run sets" % (num_sets + 1), file=sys.stderr)

        try:
            self.__run_internal(runset_id, run_num, duration, verbose=verbose,
                                subrun_doms=subrun_doms)
        except:
            print("Run #%s FAILED:\n%s" % (run_num, traceback.format_exc()))
        finally:
            self.close_all(runset_id)

    def __wait_for_components(self, num_comps):
        """
        Wait for our components to be removed from CnCServer

        num_comps - initial number of components
        """
        for _ in range(10):
            num = self.__client.rpc_component_count()
            if num == num_comps:
                break
            time.sleep(1)

        num = self.__client.rpc_component_count()
        if num > num_comps:
            print("CnCServer still has %d components (expect %d)" %
                  (num, num_comps), file=sys.stderr)

    def close_all(self, runset_id):
        "Kill the runset and stop any threads"
        try:
            self.__client.rpc_runset_break(runset_id)
        except:  # pylint: disable=bare-except
            pass

        for thrd in self.__log_threads:
            thrd.stop()
        del self.__log_threads[:]

    @staticmethod
    def create_comps(comp_data, def_dom_geom, fork_clients=False,
                     quiet=False):
        "Create and start components"
        comps = []
        for cdt in comp_data:
            client = cdt.get_fake_client(def_dom_geom, quiet=quiet)
            if client is None:
                continue

            if cdt.is_fake:
                if fork_clients:
                    if client.fork() == 0:
                        return None

                client.start()
                client.register()

            comps.append(client)
        return comps

    @staticmethod
    def hack_active_config(cluster_cfg):
        "Update pDAQ's active configuration file"
        path = os.path.join(os.environ["HOME"], ".active")
        if not os.path.exists(path):
            print("Setting ~/.active to \"%s\"" % cluster_cfg, file=sys.stderr)
            cur_cfg = None
        else:
            with open(path, 'r') as fin:
                cur_cfg = fin.read().split("\n")[0]

        if cur_cfg != cluster_cfg:
            print("Changing ~/.active from \"%s\" to \"%s\"" %
                  (cur_cfg, cluster_cfg), file=sys.stderr)
            with open(path, 'w') as fin:
                print(cluster_cfg, file=fin)

    @classmethod
    def make_mock_cluster_config(cls, run_cfg_dir, comps, num_hubs):
        "Write the cluster configuration to an XML file"
        mock_name = "localhost-cluster.cfg"
        path = os.path.join(run_cfg_dir, mock_name)
        if not os.path.exists(path):
            with open(path, 'w') as out:
                print("<cluster name=\"localhost\">", file=out)
                print("  <host name=\"localhost\">", file=out)

                for comp in comps:
                    if comp.name == "stringHub":
                        continue

                    if comp.name == "globalTrigger" or \
                      comp.name == "eventBuilder" or \
                      comp.name == "secondaryBuilders":
                        req = " required=\"true\""
                    else:
                        req = ""

                    print("    <component name=\"%s\"%s/>" % (comp.name, req),
                          file=out)

                print("    <simulatedHub number=\"%d\" priority=\"1\"/>" %
                      (num_hubs, ), file=out)
                print("  </host>", file=out)
                print("</cluster>", file=out)

        return path

    @classmethod
    def make_mock_run_config(cls, run_cfg_dir, comp_data, moni_period=None):
        "Write the run configuration to an XML file"
        mock_name = "fake-localhost"
        trig_cfg_name = "spts-IT-stdtest-01"

        path = os.path.join(run_cfg_dir, mock_name + ".xml")
        with open(path, 'w') as out:
            print("<runConfig>", file=out)
            if moni_period is not None:
                print("  <monitor period=\"%d\"/>" % moni_period, file=out)
            print("  <randomConfig>", file=out)
            print("   <noiseRate>17.0</noiseRate>", file=out)
            for comp in comp_data:
                if comp.name != "stringHub":
                    continue

                print("  <string id=\"%d\"/>" % comp.num, file=out)
            print("  </randomConfig>", file=out)

            print("  <triggerConfig>%s</triggerConfig>" % trig_cfg_name,
                  file=out)
            for comp in comp_data:
                if comp.name == "stringHub":
                    continue

                print("  <runComponent name=\"%s\"/>" % (comp.name, ),
                      file=out)

            print("</runConfig>", file=out)

        cls.make_mock_trigger_config(run_cfg_dir, trig_cfg_name)

        return (mock_name, trig_cfg_name)

    @classmethod
    def write_tag_and_value(cls, out, indent, name, value):
        "Write a single XML name/value pair"
        print("%s<%s>%s</%s>" % (indent, name, value, name), file=out)

    @classmethod
    def write_trigger_config(cls, out, indent, trig_type, trig_cfg_id, src_id,
                             name, parameter_dict, readout_dict):
        "Write the trigger configuration to an XML file"
        indent2 = indent + "  "
        indent3 = indent2 + "  "
        readout_defaults = {
            "type": ("readoutType", 0),
            "offset": ("timeOffset", 0),
            "minus": ("timeMinus", 10000),
            "plus": ("timePlus", 10000),
        }

        print(file=out)
        print("%s<triggerConfig>" % indent, file=out)
        cls.write_tag_and_value(out, indent2, "triggerType", str(trig_type))
        cls.write_tag_and_value(out, indent2, "triggerConfigId",
                                str(trig_cfg_id))
        cls.write_tag_and_value(out, indent2, "sourceId", str(src_id))
        cls.write_tag_and_value(out, indent2, "triggerName", name)
        if parameter_dict is not None:
            for pname, value in parameter_dict.items():
                print("%s<parameterConfig>" % indent2, file=out)
                cls.write_tag_and_value(out, indent3, "parameterName",
                                        str(pname))
                cls.write_tag_and_value(out, indent3, "parameterValueName",
                                        str(value))
                print("%s</parameterConfig>" % indent2, file=out)

        print("%s<readoutConfig>" % indent2, file=out)
        for key in ("type", "offset", "minus", "plus"):
            name, def_value = readout_defaults[key]
            if readout_dict is not None and key in readout_dict:
                value = readout_dict[key]
            else:
                value = def_value
            cls.write_tag_and_value(out, indent3, name, str(value))
        print("%s</readoutConfig>" % indent2, file=out)
        print("%s</triggerConfig>" % indent, file=out)

    @classmethod
    def make_mock_trigger_config(cls, run_cfg_dir, trig_cfg_name):
        "Create a mock trigger configuration"
        inice_id = 4000
        icetop_id = 5000
        global_id = 6000

        path = os.path.join(run_cfg_dir, "trigger", trig_cfg_name + ".xml")
        if not os.path.exists(path):
            with open(path, 'w') as out:
                indent = "  "
                print("<activeTriggers>", file=out)
                # add global trigger
                cls.write_trigger_config(out, indent, 3, -1, global_id,
                                         "ThroughputTrigger", None, None)

                # add in-ice fixed rate trigger
                cls.write_trigger_config(out, indent, 23, 23050, inice_id,
                                         "FixedRateTrigger",
                                         {"interval": 30000000000},
                                         {"minus": 5000000, "plus": 5000000})

                # add in-ice min bias trigger
                cls.write_trigger_config(out, indent, 2, 0, inice_id,
                                         "MinBiasTrigger",
                                         {"prescale": 23},
                                         {"minus": 25000, "plus": 25000})

                # add icetop simple majority trigger
                cls.write_trigger_config(out, indent, 0, 102, icetop_id,
                                         "SimpleMajorityTrigger",
                                         {"threshold": 6}, None)

                # add icetop calibration trigger
                cls.write_trigger_config(out, indent, 1, 1009, icetop_id,
                                         "CalibrationTrigger",
                                         {"hitType": 4},
                                         {"minus": 1000, "plus": 1000})

                # add icetop min bias trigger
                cls.write_trigger_config(out, indent, 2, 101, icetop_id,
                                         "MinBiasTrigger",
                                         {"prescale": 10000}, None)

                # add final tag
                print("</activeTriggers>", file=out)

    def make_runset(self, comp_list, run_cfg, run_num):
        "Build a runset"
        name_list = []
        for comp in comp_list:
            name_list.append(comp.fullname)

        runset_id = self.__client.rpc_runset_make(run_cfg, run_num, False)
        if runset_id < 0:
            raise DAQFakeRunException(("Cannot make runset from %s" +
                                       " (runset ID=%d)") %
                                      (name_list, runset_id))

        return runset_id

    def run_all(self, comps, start_num, num_runs, duration, run_cfg,
                verbose=False, test_subrun=False):
        "Shepherd a set of components through the specified runs"
        run_num = start_num

        # grab the number of components before we add ours
        #
        num_comps = self.__client.rpc_component_count()

        if not test_subrun:
            subrun_doms = None
        else:
            # build a list of all DOMs in the run configuration
            doms = []
            for dom_cfg in run_cfg.dom_cfgs:
                for entry in dom_cfg.rundoms:
                    doms.append(entry)

            # randomly choose a couple of DOMs to be used in the subrun
            subrun_doms = []
            for idx in range(2):
                entry = random.choice(doms)
                if isinstance(entry.mbid, int):
                    mbid = "%x" % entry.mbid
                else:
                    mbid = entry.mbid
                subrun_doms.append(mbid)

        # set the active configuration to our run configuration name
        self.hack_active_config(run_cfg.basename)

        # do all the runs
        #
        for _ in range(num_runs):
            # wait for all components to be registered
            #
            num_new = num_comps + len(comps)
            for _ in range(10):
                if self.__client.rpc_component_count() == num_new:
                    break
                time.sleep(0.1)

            # simulate a run
            #
            try:
                self.__run_one(comps, run_cfg, run_num, duration,
                               verbose=verbose, subrun_doms=subrun_doms)
            except:  # pylint: disable=bare-except
                traceback.print_exc()
            run_num += 1

            # close all created components
            #
            self.__client.rpc_end_all()

            # wait for closed components to be removed from server
            #
            print("Waiting for components")
            self.__wait_for_components(num_new)


def clear_directory(subdir, dirname):
    if not subdir.startswith("/tmp"):
        print("Not destroying %s directory \"%s\"" % (dirname, subdir, ))
    elif os.path.exists(subdir):
        # destroy old data
        if not os.path.isdir(subdir):
            os.unlink(subdir)
        else:
            for entry in os.listdir(subdir):
                path = os.path.join(subdir, entry)
                if os.path.isdir(path):
                    shutil.rmtree(path)


def copy_default_dom_geometry_file(target):
    "Copy the standard default DOM geometry file to another location"
    cfg_path = find_pdaq_config()
    ddg_path = os.path.join(cfg_path, DefaultDomGeometry.FILENAME)
    if not os.path.exists(ddg_path):
        raise DAQFakeRunException("Cannot copy nonexistent \"%s\" to \"%s\"" %
                                  (ddg_path, cfg_path))

    new_path = os.path.join(target, DefaultDomGeometry.FILENAME)
    shutil.copyfile(ddg_path, new_path)


def main():
    "Main program"

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--config", dest="run_cfg_dir",
                        default="/tmp/pdaq/config",
                        help="Run configuration directory")
    parser.add_argument("-d", "--duration", type=int, dest="duration",
                        default="5",
                        help="Number of seconds for run")
    parser.add_argument("-e", "--event-builder", dest="evt_bldr",
                        action="store_true", default=False,
                        help="Use existing event builder")
    parser.add_argument("-F", "--fake-names", dest="fake_names",
                        action="store_true", default=False,
                        help="Add a numeric prefix to component names")
    parser.add_argument("-f", "--fork-clients", dest="fork_clients",
                        action="store_true", default=False,
                        help="Run clients in subprocesses")
    parser.add_argument("-g", "--global-trigger", dest="glbl_trig",
                        action="store_true", default=False,
                        help="Use existing global trigger")
    parser.add_argument("-H", "--number-of-hubs", type=int, dest="num_hubs",
                        default=2,
                        help="Number of fake hubs")
    parser.add_argument("-i", "--inice-trigger", dest="inice_trig",
                        action="store_true", default=False,
                        help="Use existing in-ice trigger")
    parser.add_argument("-j", "--jade-dir", dest="jade_dir",
                        default="/tmp/pdaq/spade",
                        help="Directory holding files queued for JADE/SPADE")
    parser.add_argument("-K", "--keep-old-files", dest="keep_old_files",
                        action="store_true", default=False,
                        help=("Keep old runs from /tmp/pdaq/log and"
                              " /tmp/pdaq/pdaqlocal"))
    parser.add_argument("-n", "--num-of-runs", type=int, dest="num_runs",
                        default=1,
                        help="Number of runs")
    parser.add_argument("-M", "--moni-period", type=int, dest="moni_period",
                        default=None,
                        help="Number of seconds between monitoring requests")
    parser.add_argument("-o", "--log-dir", dest="log_dir",
                        default="/tmp/pdaq/log",
                        help=("Directory holding pDAQ log/monitoring"
                              " subdirectories"))
    parser.add_argument("-p", "--first-port-number", type=int,
                        dest="first_port", default=None,
                        help="First port number used for fake components")
    parser.add_argument("-Q", "--data-dir", dest="daq_data_dir",
                        default="/tmp/pdaq/pdaqlocal",
                        help="Directory holding physics/tcal/moni/sn files")
    parser.add_argument("-q", "--quiet", dest="quiet",
                        action="store_true", default=False,
                        help=("Fake components don't announce what they're"
                              " doing"))
    parser.add_argument("-r", "--run-number", type=int, dest="run_num",
                        default=1234,
                        help="Run number")
    parser.add_argument("-S", "--small", dest="use_small",
                        action="store_true", default=False,
                        help="Use canned 3-element configuration")
    parser.add_argument("-s", "--secondary-builders", dest="sec_bldrs",
                        action="store_true", default=False,
                        help="Use existing secondary builders")
    parser.add_argument("-T", "--tiny", dest="use_tiny",
                        action="store_true", default=False,
                        help="Use canned 2-element configuration")
    parser.add_argument("-t", "--icetop-trigger", dest="icetop_trig",
                        action="store_true", default=False,
                        help="Use existing icetop trigger")
    parser.add_argument("-u", "--test-subrun", dest="test_subrun",
                        action="store_true", default=False,
                        help="Test subrun")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print progress messages during run")
    parser.add_argument("-X", "--extra-hubs", type=int, dest="extra_hubs",
                        default=0,
                        help="Number of extra hubs to create")

    args = parser.parse_args()

    if sys.version_info > (2, 3):
        from DumpThreads import DumpThreadsOnSignal
        DumpThreadsOnSignal(file_handle=sys.stderr)

    if args.first_port is not None:
        PortNumber.set_next_number(args.first_port)

    log_path = args.log_dir
    data_path = args.daq_data_dir
    cfg_path = args.run_cfg_dir
    jade_path = args.jade_dir

    for subdir, dirname in ((log_path, "log"), (data_path, "data"),
                            (cfg_path, "run configuration"),
                            (jade_path, "JADE")):
        if not args.keep_old_files:
            clear_directory(subdir, dirname)

        if not os.path.exists(subdir):
            os.makedirs(subdir)

    # get string/dom info
    try:
        def_dom_geom = DefaultDomGeometryReader.parse(config_dir=cfg_path)
    except XMLBadFileError:
        # copy from the default location and try again
        copy_default_dom_geometry_file(cfg_path)
        def_dom_geom = DefaultDomGeometryReader.parse(config_dir=cfg_path)

    # get list of components
    #
    if args.use_tiny:
        comp_data = ComponentData.create_tiny_data()
    elif args.use_small:
        comp_data = ComponentData.create_small_data()
    else:
        comp_data = ComponentData.create_all_data(args.num_hubs,
                                                  args.fake_names)
        for cdt in comp_data:
            if args.evt_bldr and cdt.is_component("eventBuilder"):
                cdt.use_real_component()
            elif args.glbl_trig and cdt.is_component("globalTrigger"):
                cdt.use_real_component()
            elif args.inice_trig and cdt.is_component("iniceTrigger"):
                cdt.use_real_component()
            elif args.icetop_trig and cdt.is_component("icetopTrigger"):
                cdt.use_real_component()
            elif args.sec_bldrs and cdt.is_component("secondaryBuilders"):
                cdt.use_real_component()

    run_cfg_dir = os.path.abspath(args.run_cfg_dir)
    if not os.path.exists(run_cfg_dir):
        os.makedirs(run_cfg_dir)
    trig_subdir = os.path.join(run_cfg_dir, "trigger")
    if not os.path.exists(trig_subdir):
        os.makedirs(trig_subdir)

    cc_path = DAQFakeRun.make_mock_cluster_config(run_cfg_dir, comp_data,
                                                  args.num_hubs)
    if args.verbose:
        print("Created cluster configuration \"%s\"" % (cc_path, ))

    run_cfg_name, _ = DAQFakeRun.make_mock_run_config(run_cfg_dir,
                                                      comp_data,
                                                      args.moni_period)

    # load the (newly created?) run configuration
    run_cfg = DAQConfig(run_cfg_dir, run_cfg_name)

    if args.verbose:
        rc_path = os.path.join(run_cfg_dir, run_cfg_name + ".xml")
        print("Created run configuration \"%s\"" % (rc_path, ))

    if args.extra_hubs <= 0:
        extra_data = None
    else:
        extra_data = ComponentData.create_hubs(args.extra_hubs,
                                               args.num_hubs + 1,
                                               args.fake_names, False)

    # create a fake leapseconds file
    leapfile = MockLeapsecondFile(run_cfg_dir)
    leapfile.create()

    # create components
    #
    try:
        comps = DAQFakeRun.create_comps(comp_data, def_dom_geom,
                                        fork_clients=args.fork_clients,
                                        quiet=args.quiet)
    except socket.error as serr:
        if serr.errno != 111:
            raise
        errmsg = "Please start CnCServer before faking a run\n\n" \
          "python CnCServer.py -c \"%s\" -o \"%s\" -q \"%s\" -s \"%s\" -v" % \
          (args.run_cfg_dir, args.log_dir, args.daq_data_dir, args.jade_dir)
        raise SystemExit(errmsg)

    if extra_data is not None:
        _ = DAQFakeRun.create_comps(extra_data, def_dom_geom,
                                    fork_clients=args.fork_clients,
                                    quiet=args.quiet)

    try:
        DAQConfigParser.get_cluster_configuration(None, use_active_config=True,
                                                  config_dir=run_cfg_dir,
                                                  validate=False)
    except ConfigNotSpecifiedException:
        DAQFakeRun.hack_active_config("sim-localhost")

    # create run object and initial run number
    #
    runner = DAQFakeRun()

    runner.run_all(comps, args.run_num, args.num_runs, args.duration,
                   run_cfg, verbose=args.verbose, test_subrun=args.test_subrun)


if __name__ == "__main__":
    import argparse

    main()
