#!/usr/bin/env python

import datetime
import numbers
import os
import select
import shutil
import socket
import sys
import threading
import time
import traceback

from CnCServer import Connector
from DAQConfig import DAQConfigParser
from DAQConst import DAQPort
from DAQMocks import MockLeapsecondFile, MockRunConfigFile, MockTriggerConfig
from DAQRPC import RPCClient
from DefaultDomGeometry import DefaultDomGeometryReader
from FakeClient import FakeClient, FakeClientException, PortNumber
from FakeComponent import StringHub
from RunOption import RunOption
from utils import ip

LOUD = False


class DAQFakeRunException(Exception):
    pass


class HubType(object):
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
            print >>sys.stderr, "Create log server localhost#%d" % self.__port
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

            if len(ersock) != 0:
                print >>sys.stderr, "Error on select"

            if len(rdsock) == 0:
                continue

            while True:
                try:
                    data = self.__sock.recv(8192, socket.MSG_DONTWAIT)
                    if LOUD:
                        print >>sys.stderr, "%s: %s" % (self.__comp_name, data)
                except:
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
        return self.__conn_list

    @classmethod
    def create_all_data(cls, num_hubs, def_dom_geom, numeric_prefix=False,
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
            comp.set_connections(connlist)
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
            comp.set_connections(connlist)
            comps.append(comp)

        return comps

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def get_fake_client(self, def_dom_geom, quiet=False):
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
        return self.__is_fake

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    def set_connections(self, connlist):
        self.__conn_list = connlist

    @property
    def use_numeric_prefix(self):
        return self.__numeric_prefix

    def use_real_component(self):
        "This component should not register itself so the Java version is used"
        self.__is_fake = False


class HubDescription(ComponentData):
    def __init__(self, num, numeric_prefix=False, is_icetop=False,
                 hub_type=HubType.ALL):
        super(HubDescription, self).__init__("stringHub", num,
                                             numeric_prefix=numeric_prefix)

        connlist = []
        if hub_type == HubType.ALL or hub_type == HubType.PHYSICS_ONLY:
            connlist += [
                ("rdoutReq", Connector.INPUT),
                ("rdoutData", Connector.OUTPUT),
            ]
            if is_icetop:
                connlist.append(("icetopHit", Connector.OUTPUT))
            else:
                connlist.append(("stringHit", Connector.OUTPUT))
        if hub_type == HubType.ALL or hub_type == HubType.SECONDARY_ONLY:
            connlist += [
                ("moniData", Connector.OUTPUT),
                ("snData", Connector.OUTPUT),
                ("tcalData", Connector.OUTPUT),
            ]
        self.set_connections(connlist)

    def get_fake_client(self, def_dom_geom, quiet=False):
        "Create a FakeClient object using this component data"
        if not self.is_fake:
            return None

        return StringHub(self.name, self.num, def_dom_geom, self.connections,
                         quiet=quiet)


class TriggerDescription(ComponentData):
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

        self.set_connections(connlist)


class BuilderDescription(ComponentData):
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

        self.set_connections(connlist)


class DAQFakeRun(object):
    "Fake DAQRun"

    LOCAL_ADDR = ip.getLocalIpAddr()
    CNCSERVER_HOST = LOCAL_ADDR

    def __init__(self, cnc_host=CNCSERVER_HOST, cnc_port=DAQPort.CNCSERVER,
                 dump_rpc=False):
        """
        Create a fake DAQRun

        cnc_host - CnCServer host name/address
        cnc_port - CnCServer port number
        dump_rpc - if XML-RPC server should print connection info
        """

        self.__log_threads = []

        self.__client = RPCClient(cnc_host, cnc_port)

    @staticmethod
    def __create_cluster_desc_file(run_cfg_dir):
        path = os.path.join(run_cfg_dir, "sps-cluster.cfg")
        if not os.path.exists(path):
            with open(path, 'w') as fin:
                print >>fin, """<cluster name="localhost">
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
</cluster>"""

    @staticmethod
    def __get_run_time(start_time):
        diff = datetime.datetime.now() - start_time
        return float(diff.seconds) + (float(diff.microseconds) / 1000000.0)

    def __open_log(self, host, port):
        """
        Open a connection to the log server

        host - log host name/address
        port - log port number

        Returns the new socket
        """

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2)
        sock.connect((host, port))
        return sock

    def __run_internal(self, runset_id, run_num, duration, test_subrun=True,
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
            print "Found %d components" % (len(run_comps), )

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

        try:
            self.__client.rpc_runset_start_run(runset_id, run_num, run_options)

            start_time = datetime.datetime.now()

            time.sleep(1)

            self.__client.rpc_runset_list(runset_id)

            time.sleep(1)

            if test_subrun:
                self.__client.rpc_runset_subrun(runset_id, -1,
                                                [("0123456789abcdef",
                                                  0, 1, 2, 3, 4), ])

            do_switch = True

            runtime = self.__get_run_time(start_time)
            wait_secs = duration - runtime
            if wait_secs <= 0.0:
                wait_slice = 0.0
            else:
                if do_switch:
                    slices = 6
                else:
                    slices = 3
                wait_slice = wait_secs / float(slices)

            for switch in (False, True):
                if switch and do_switch:
                    self.__client.rpc_runset_switch_run(runset_id, run_num + 1)

                reps = 0
                while wait_secs > 0:
                    time.sleep(wait_slice)
                    try:
                        num_evts = self.__client.rpc_runset_events(runset_id,
                                                                   -1)
                    except:
                        num_evts = None

                    run_secs = self.__get_run_time(start_time)
                    if num_evts is not None:
                        print "RunSet %d had %d event%s after %.2f secs" % \
                            (runset_id, num_evts, "s" if num_evts != 1 else "",
                             run_secs)
                    else:
                        print "RunSet %d could not get event count after" \
                            " %.2f secs" % (runset_id, run_secs)

                    wait_secs = duration - run_secs

                    reps += 1
                    if do_switch and not switch and reps == 3:
                        break
        finally:
            try:
                self.__client.rpc_runset_stop_run(runset_id)
            except:
                print >>sys.stderr, "Cannot stop run for runset #%d" % runset_id
                traceback.print_exc()

    def __run_one(self, comp_list, run_cfg_dir, mock_run_cfg, run_num,
                  duration, verbose=False, test_subrun=False):
        """
        Simulate a run

        comp_list - list of components
        run_cfg - run configuration name
        run_num - run number
        duration - length of run in seconds
        """

        num_sets = self.__client.rpc_runset_count()
        if LOUD:
            print >>sys.stderr, "%d active runsets" % num_sets
            for cdict in self.__client.rpc_component_list_dicts():
                print >>sys.stderr, str(cdict)
            print >>sys.stderr, "---"

        leapfile = MockLeapsecondFile(run_cfg_dir)
        leapfile.create()

        self.hack_active_config(mock_run_cfg)

        runset_id = self.make_runset(comp_list, mock_run_cfg, run_num)

        if num_sets != self.__client.rpc_runset_count() - 1:
            print >>sys.stderr, "Expected %d run sets" % (num_sets + 1)

        try:
            self.__run_internal(runset_id, run_num, duration, verbose=verbose,
                                test_subrun=test_subrun)
        finally:
            traceback.print_exc()
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
            print >>sys.stderr, \
                "CnCServer still has %d components (expect %d)" % \
                (num, num_comps)

    def close_all(self, runset_id):
        try:
            self.__client.rpc_runset_break(runset_id)
        except:
            pass

        for thrd in self.__log_threads:
            thrd.stop()
        del self.__log_threads[:]

    @staticmethod
    def create_comps(comp_data, def_dom_geom, fork_clients=False,
                     quiet=False):
        "create and start components"
        comps = []
        for cdt in comp_data:
            client = cdt.get_fake_client(def_dom_geom, quiet=quiet)
            if client is None:
                continue

            if cdt.is_fake:
                if fork_clients:
                    if client.fork() == 0:
                        return

                client.start()
                client.register()

            comps.append(client)
        return comps

    @classmethod
    def create_mock_run_config(cls, run_cfg_dir, comp_list):
        trig_cfg = MockTriggerConfig("global-only")
        trig_cfg.add(6000, "ThroughputTrigger", 3, -1)

        cfg_file = MockRunConfigFile(run_cfg_dir)

        name_list = []
        for comp in comp_list:
            name_list.append(comp.fullname)

        cls.__create_cluster_desc_file(run_cfg_dir)

        return cfg_file.create(name_list, {}, trigCfg=trig_cfg)

    @staticmethod
    def hack_active_config(cluster_cfg):
        path = os.path.join(os.environ["HOME"], ".active")
        if not os.path.exists(path):
            print >>sys.stderr, "Setting ~/.active to \"%s\"" % cluster_cfg
            cur_cfg = None
        else:
            with open(path, 'r') as fin:
                cur_cfg = fin.read().split("\n")[0]

        if cur_cfg != cluster_cfg:
            print >>sys.stderr, "Changing ~/.active from \"%s\" to \"%s\"" % \
                (cur_cfg, cluster_cfg)
            with open(path, 'w') as fin:
                print >>fin, cluster_cfg

    @classmethod
    def make_mock_cluster_config(cls, run_cfg_dir, comps, num_hubs):
        mock_name = "localhost-cluster.cfg"
        path = os.path.join(run_cfg_dir, mock_name)
        if os.path.exists(path):
            return

        with open(path, 'w') as out:
            print >>out, "<cluster name=\"localhost\">"
            print >>out, "  <host name=\"localhost\">"

            for comp in comps:
                if comp.name == "stringHub":
                    continue

                if comp.name == "globalTrigger" or comp.name == "eventBuilder" or \
                   comp.name == "secondaryBuilders":
                    req = " required=\"true\""
                else:
                    req = ""

                print >>out, "    <component name=\"%s\"%s/>" % (comp.name, req)

            print >>out, "    <simulatedHub number=\"%d\" priority=\"1\"/>" % \
                (num_hubs, )
            print >>out, "  </host>"
            print >>out, "</cluster>"

    @classmethod
    def make_mock_run_config(cls, run_cfg_dir, comp_data, moni_period=None):
        mock_name = "fake-localhost"
        trig_cfg_name = "spts-IT-stdtest-01"

        path = os.path.join(run_cfg_dir, mock_name + ".xml")
        with open(path, 'w') as out:
            print >>out, "<runConfig>"
            if moni_period is not None:
                print >>out, "  <monitor period=\"%d\"/>" % moni_period
            print >>out, "  <randomConfig>"
            print >>out, "   <noiseRate>17.0</noiseRate>"
            for comp in comp_data:
                if comp.name != "stringHub":
                    continue

                print >>out, "  <string id=\"%d\"/>" % comp.num
            print >>out, "  </randomConfig>"

            print >>out, "  <triggerConfig>%s</triggerConfig>" % trig_cfg_name
            for comp in comp_data:
                if comp.name == "stringHub":
                    continue

                print >>out, "  <runComponent name=\"%s\"/>" % (comp.name, )

            print >>out, "</runConfig>"

        cls.make_mock_trigger_config(run_cfg_dir, trig_cfg_name)

        return (mock_name, trig_cfg_name)

    @classmethod
    def write_tag_and_value(cls, out, indent, name, value):
        print >>out, "%s<%s>%s</%s>" % (indent, name, value, name)

    @classmethod
    def write_trigger_config(cls, out, indent, trig_type, trig_cfg_id, src_id,
                             name, parameter_dict, readout_dict):
        indent2 = indent + "  "
        indent3 = indent2 + "  "
        readout_defaults = {
            "type": ("readoutType", 0),
            "offset": ("timeOffset", 0),
            "minus": ("timeMinus", 10000),
            "plus": ("timePlus", 10000),
        }

        print >>out
        print >>out, "%s<triggerConfig>" % indent
        cls.write_tag_and_value(out, indent2, "triggerType", str(trig_type))
        cls.write_tag_and_value(out, indent2, "triggerConfigId",
                                str(trig_cfg_id))
        cls.write_tag_and_value(out, indent2, "sourceId", str(src_id))
        cls.write_tag_and_value(out, indent2, "triggerName", name)
        if parameter_dict is not None:
            for name, value in parameter_dict.items():
                print >>out, "%s<parameterConfig>" % indent2
                cls.write_tag_and_value(out, indent3, "parameterName",
                                        str(name))
                cls.write_tag_and_value(out, indent3, "parameterValueName",
                                        str(value))
                print >>out, "%s</parameterConfig>" % indent2

        print >>out, "%s<readoutConfig>" % indent2
        for key in ("type", "offset", "minus", "plus"):
            name, def_value = readout_defaults[key]
            if readout_dict is not None and key in readout_dict:
                value = readout_dict[key]
            else:
                value = def_value
            cls.write_tag_and_value(out, indent3, name, str(value))
        print >>out, "%s</readoutConfig>" % indent2
        print >>out, "%s</triggerConfig>" % indent

    @classmethod
    def make_mock_trigger_config(cls, run_cfg_dir, trig_cfg_name):
        inice_id = 4000
        icetop_id = 5000
        global_id = 6000

        path = os.path.join(run_cfg_dir, "trigger", trig_cfg_name + ".xml")
        if not os.path.exists(path):
            with open(path, 'w') as out:
                indent = "  "
                print >>out, "<activeTriggers>"
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
                print >>out, "</activeTriggers>"

    def make_runset(self, comp_list, run_cfg, run_num):
        name_list = []
        for comp in comp_list:
            name_list.append(comp.fullname)

        runset_id = self.__client.rpc_runset_make(run_cfg, run_num, False)
        if runset_id < 0:
            raise DAQFakeRunException(("Cannot make runset from %s" +
                                       " (runset ID=%d)") %
                                      (name_list, runset_id))

        return runset_id

    def run_all(self, comps, start_num, num_runs, duration, run_cfg_dir,
                mock_run_cfg, verbose=False, test_subrun=False):
        run_num = start_num

        # grab the number of components before we add ours
        #
        num_comps = self.__client.rpc_component_count()

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
                self.__run_one(comps, run_cfg_dir, mock_run_cfg, run_num,
                               duration, verbose=verbose,
                               test_subrun=test_subrun)
            except:
                traceback.print_exc()
            run_num += 1

            # close all created components
            #
            self.__client.rpc_end_all()

            # wait for closed components to be removed from server
            #
            print "Waiting for components"
            self.__wait_for_components(num_new)


def main():
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
    parser.add_argument("-K", "--keep-old-files", dest="keep_old_files",
                        action="store_true", default=False,
                        help="Keep old runs from /tmp/pdaq/log and"
                        " /tmp/pdaq/pdaqlocal")
    parser.add_argument("-n", "--num-of-runs", type=int, dest="num_runs",
                        default=1,
                        help="Number of runs")
    parser.add_argument("-M", "--moni-period", type=int, dest="moni_period",
                        default=None,
                        help="Number of seconds between monitoring requests")
    parser.add_argument("-p", "--first-port-number", type=int,
                        dest="first_port", default=None,
                        help="First port number used for fake components")
    parser.add_argument("-q", "--quiet", dest="quiet",
                        action="store_true", default=False,
                        help="Fake components don't announce what they're"
                        " doing")
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
        DumpThreadsOnSignal(fd=sys.stderr)

    if args.first_port is not None:
        PortNumber.set_first(args.first_port)

    if not args.keep_old_files:
        logname = "/tmp/pdaq/log"
        for entry in os.listdir(logname):
            path = os.path.join(logname, entry)
            if os.path.isdir(path):
                shutil.rmtree(path)

        datname = "/tmp/pdaq/pdaqlocal"
        for entry in os.listdir(datname):
            path = os.path.join(datname, entry)
            if os.path.isfile(path):
                os.unlink(path)

    # get string/dom info
    def_dom_geom = DefaultDomGeometryReader.parse()

    # get list of components
    #
    if args.use_tiny:
        comp_data = ComponentData.create_tiny_data()
    elif args.use_small:
        comp_data = ComponentData.create_small_data()
    else:
        comp_data = ComponentData.create_all_data(args.num_hubs, def_dom_geom,
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

    DAQFakeRun.make_mock_cluster_config(run_cfg_dir, comp_data, args.num_hubs)

    mock_run_cfg, _ = DAQFakeRun.make_mock_run_config(run_cfg_dir,
                                                      comp_data,
                                                      args.moni_period)

    if args.extra_hubs <= 0:
        extra_data = None
    else:
        extra_data = ComponentData.create_hubs(args.extra_hubs,
                                               args.num_hubs + 1,
                                               args.fake_names, False)

    # create components
    #
    try:
        comps = DAQFakeRun.create_comps(comp_data, def_dom_geom,
                                        fork_clients=args.fork_clients,
                                        quiet=args.quiet)
    except socket.error, serr:
        if serr.errno != 111:
            raise
        raise SystemExit("Please start CnCServer before faking a run")

    if extra_data is not None:
        _ = DAQFakeRun.create_comps(extra_data, def_dom_geom,
                                    fork_clients=args.fork_clients,
                                    quiet=args.quiet)

    try:
        DAQConfigParser.getClusterConfiguration(None, useActiveConfig=True,
                                                configDir=run_cfg_dir,
                                                validate=False)
    except:
        DAQFakeRun.hack_active_config("sim-localhost")

    # create run object and initial run number
    #
    runner = DAQFakeRun()

    runner.run_all(comps, args.run_num, args.num_runs, args.duration,
                   run_cfg_dir, mock_run_cfg, verbose=args.verbose,
                   test_subrun=args.test_subrun)


if __name__ == "__main__":
    import argparse

    main()
