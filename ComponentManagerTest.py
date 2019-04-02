#!/usr/bin/env python

from __future__ import print_function

import os
import socket
import sys
import tempfile
import threading
import unittest

from CachedConfigName import CachedFile
from Component import Component
from ComponentManager import ComponentManager
from DAQConst import DAQPort
from DAQMocks import MockRemoteManager
from DAQRPC import RPCServer
from RunSetState import RunSetState


class MockDeployComponent(Component):
    def __init__(self, name, id, log_level, hs_dir, hs_interval, hs_max_files,
                 jvm_path, jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                 jvm_extra_args, alert_email, ntp_host, num_replay_files=None,
                 host=None):
        self.__hs_dir = hs_dir
        self.__hs_interval = hs_interval
        self.__hs_max_files = hs_max_files
        self.__jvm_path = jvm_path
        self.__jvm_server = jvm_server is True
        self.__jvm_heap_init = jvm_heap_init
        self.__jvm_heap_max = jvm_heap_max
        self.__jvm_args = jvm_args
        self.__jvm_extra_args = jvm_extra_args
        self.__alert_email = alert_email
        self.__ntp_host = ntp_host
        self.__num_replay_files = num_replay_files
        self.__host = host

        super(MockDeployComponent, self).__init__(name, id, log_level)

    @property
    def alertEMail(self):
        return self.__alert_email

    @property
    def hasHitSpoolOptions(self):
        return self.__hs_dir is not None or self.__hs_interval is not None or \
            self.__hs_max_files is not None

    @property
    def hasReplayOptions(self):
        return self.__num_replay_files is not None

    @property
    def hitspoolDirectory(self):
        return self.__hs_dir

    @property
    def hitspoolInterval(self):
        return self.__hs_interval

    @property
    def hitspoolMaxFiles(self):
        return self.__hs_max_files

    @property
    def isControlServer(self):
        return False

    @property
    def host(self):
        return self.__host

    @property
    def isLocalhost(self):
        return self.__host is not None and self.__host == "localhost"

    @property
    def jvmArgs(self):
        return self.__jvm_args

    @property
    def jvmExtraArgs(self):
        return self.__jvm_extra_args

    @property
    def jvmHeapInit(self):
        return self.__jvm_heap_init

    @property
    def jvmHeapMax(self):
        return self.__jvm_heap_max

    @property
    def jvmPath(self):
        return self.__jvm_path

    @property
    def jvmServer(self):
        return self.__jvm_server

    @property
    def ntpHost(self):
        return self.__ntp_host

    @property
    def numReplayFilesToSkip(self):
        return self.__num_replay_files


class MockNode(object):
    LIST = []

    def __init__(self, hostname):
        self.__hostname = hostname
        self.__comps = []

    def __str__(self):
        return "%s[%s]" % (str(self.__hostname), str(self.__comps))

    def add_comp(self, comp_name, comp_id, log_level, hs_dir, hs_interval,
                 hs_max_files, jvm_path, jvm_server, jvm_heap_init,
                 jvm_heap_max, jvm_args, jvm_extra_args, alert_email, ntp_host):
        comp = MockDeployComponent(comp_name, comp_id, log_level, hs_dir,
                                   hs_interval, hs_max_files, jvm_path,
                                   jvm_server, jvm_heap_init, jvm_heap_max,
                                   jvm_args, jvm_extra_args, alert_email,
                                   ntp_host, host=self.__hostname)
        self.__comps.append(comp)
        return comp

    def components(self):
        return self.__comps

    @property
    def hostname(self):
        return self.__hostname


class MockClusterConfig(object):
    def __init__(self, name):
        self.__name = name
        self.__nodes = []

    def add_node(self, node):
        self.__nodes.append(node)

    @property
    def description(self):
        return None

    def nodes(self):
        return self.__nodes[:]

    def writeCacheFile(self, writeActiveConfig=False):
        pass


class MockServer(object):
    STATE_KEY = "state"
    COMPS_KEY = "comps"

    def __init__(self):
        self.__runsets = {}
        self.__unused = []
        self.__next_id = 1

        self.__server = RPCServer(DAQPort.CNCSERVER)
        self.__server.register_function(self.__list_comp_dicts,
                                        'rpc_component_list_dicts')
        self.__server.register_function(self.__runset_count,
                                        'rpc_runset_count')
        self.__server.register_function(self.__runset_list_ids,
                                        'rpc_runset_list_ids')
        self.__server.register_function(self.__runset_list_comps,
                                        'rpc_runset_list')
        self.__server.register_function(self.__runset_state,
                                        'rpc_runset_state')

        thrd = threading.Thread(name="MockServer",
                                target=self.__server.serve_forever, args=())
        thrd.setDaemon(True)
        thrd.start()

    def __list_comp_dicts(self, id_list=None, get_all=True):
        dictlist = []
        for comp in self.__unused:
            newc = {}
            for k in comp:
                newc[k] = comp[k]
            dictlist.append(newc)
        return dictlist

    def __runset_count(self):
        return len(self.__runsets)

    def __runset_list_comps(self, rsid):
        dictlist = []

        if rsid in self.__runsets:
            for comp in self.__runsets[rsid][self.COMPS_KEY]:
                newc = {}
                for key in comp:
                    if key == self.STATE_KEY:
                        continue
                    newc[key] = comp[key]
                dictlist.append(newc)

        return dictlist

    def __runset_list_ids(self):
        return list(self.__runsets.keys())

    def __runset_state(self, rsid):
        if rsid not in self.__runsets:
            return RunSetState.DESTROYED

        return self.__runsets[rsid][self.STATE_KEY]

    def add_unused_component(self, name, num, host):
        self.__unused.append({"compName": name, "compNum": num, "host": host})

    def add_runset(self, state, complist=None):
        fulldict = {}
        fulldict[self.STATE_KEY] = state
        if complist is not None:
            newlist = []
            for comp in complist:
                newdict = {}
                for k in comp:
                    newdict[k] = comp[k]
                newlist.append(newdict)
            fulldict[self.COMPS_KEY] = newlist

        rsid = self.__next_id
        self.__next_id += 1
        self.__runsets[rsid] = fulldict

    def close(self):
        self.__server.server_close()


class ComponentManagerTest(unittest.TestCase):
    CONFIG_DIR = os.path.abspath('src/test/resources/config')

    def setUp(self):
        self.__srvr = None

    def tearDown(self):
        if self.__srvr is not None:
            self.__srvr.close()
        CachedFile.clearActiveConfig()

    def test_start_java(self):
        dry_run = False
        config_dir = '/foo/cfg'
        daq_data_dir = '/foo/baz'
        log_port = 1234

        hs_dir = "/mnt/data/testpath"
        hs_interval = 11.1
        hs_max_files = 12345

        jvm_path = "java"
        jvm_server = False
        jvm_heap_init = "1m"
        jvm_heap_max = "12m"
        jvm_args = "-Xarg"
        jvm_extra = "-Xextra"

        alert_email = "xxx@yyy.zzz"
        ntp_host = "NtPhOsT"

        verbose = False
        chk_exists = False

        log_level = 'DEBUG'

        rmtmgr = MockRemoteManager()

        for comp_name in ComponentManager.list_known_component_names():
            if comp_name[-3:] == 'hub':
                comp_name = comp_name[:-3] + "Hub"
                comp_id = 17
            else:
                comp_id = 0
                if comp_name.endswith("builder"):
                    comp_name = comp_name[:-7] + "Builder"

            for host in MockNode.LIST:
                node = MockNode(host)
                comp = node.add_comp(comp_name, comp_id, log_level, hs_dir,
                                     hs_interval, hs_max_files, jvm_path,
                                     jvm_server, jvm_heap_init, jvm_heap_max,
                                     jvm_args, jvm_extra, alert_email, ntp_host)

                for is_live in (True, False):
                    if is_live:
                        live_port = DAQPort.I3LIVE
                    else:
                        live_port = None

                    for event_check in (True, False):
                        rmtsh = rmtmgr.get(comp.host)
                        rmtsh.add_expected_java(comp, config_dir, daq_data_dir,
                                                log_port, live_port, verbose,
                                                event_check)

                        ComponentManager.start_components(node.components(),
                                                          dry_run, verbose,
                                                          config_dir,
                                                          daq_data_dir,
                                                          log_port, live_port,
                                                          event_check=event_check,
                                                          check_exists=chk_exists,
                                                          rmtmgr=rmtmgr)

                        rmtmgr.wait()
                        rmtmgr.check()

    def test_kill_java(self):
        rmtmgr = MockRemoteManager()

        for comp_name in ComponentManager.list_known_component_names():
            if comp_name[-3:] == 'hub':
                comp_id = 17
            else:
                comp_id = 0

            dry_run = False
            verbose = False

            hs_dir = "/mnt/data/tstkill"
            hs_interval = 12.3
            hs_max_files = 12345

            jvm_path = "java"
            jvm_server = False
            jvm_heap_init = "1m"
            jvm_heap_max = "12m"
            jvm_args = "-Xarg"
            jvm_extra = "-Xextra"

            alert_email = "abc@def"
            ntp_host = "NTP1"

            log_level = 'DEBUG'

            for host in MockNode.LIST:
                node = MockNode(host)
                node.add_comp(comp_name, comp_id, log_level, hs_dir,
                              hs_interval, hs_max_files, jvm_path, jvm_server,
                              jvm_heap_init, jvm_heap_max, jvm_args, jvm_extra,
                              alert_email, ntp_host)

                for kill_with_9 in (True, False):
                    rmtsh = rmtmgr.get(host)
                    rmtsh.add_expected_java_kill(comp_name, comp_id,
                                                 kill_with_9, verbose, host)

                    ComponentManager.kill_components(node.components(),
                                                     dry_run=dry_run,
                                                     verbose=verbose,
                                                     kill_with_9=kill_with_9,
                                                     rmtmgr=rmtmgr)

                    rmtsh.check()

    def test_launch(self):
        tmpdir = tempfile.mkdtemp()
        dry_run = False
        config_dir = os.path.join(tmpdir, 'cfg')
        daq_data_dir = os.path.join(tmpdir, 'data')
        dash_dir = os.path.join(tmpdir, 'dash')
        log_dir = os.path.join(tmpdir, 'log')
        spade_dir = os.path.join(tmpdir, 'spade')
        copy_dir = os.path.join(tmpdir, 'copy')
        log_port = 1234
        verbose = False
        chk_exists = False

        comp_name = 'eventBuilder'
        comp_id = 0

        hs_dir = "/a/b/c"
        hs_interval = 1.0
        hs_max_files = 1

        jvm_path = "java"
        jvm_server = False
        jvm_heap_init = "1m"
        jvm_heap_max = "12m"
        jvm_args = "-Xarg"
        jvm_extra = "-Xextra"

        alert_email = "abc@def.ghi"
        ntp_host = "tempus"

        log_level = 'DEBUG'

        rmtmgr = MockRemoteManager()

        # if there are N targets, range is 2^N
        for targets in range(2):
            do_cnc = (targets & 1) == 1

            for host in MockNode.LIST:
                node = MockNode(host)
                comp = node.add_comp(comp_name, comp_id, log_level, hs_dir,
                                     hs_interval, hs_max_files, jvm_path,
                                     jvm_server, jvm_heap_init, jvm_heap_max,
                                     jvm_args, jvm_extra, alert_email,
                                     ntp_host)

                cfg_name = 'mockCfg'

                config = MockClusterConfig(cfg_name)
                config.add_node(node)

                for is_live in (True, False):
                    if is_live:
                        live_port = DAQPort.I3LIVE
                    else:
                        live_port = None

                    for evt_chk in (True, False):
                        clu_desc = None

                        rmtsh = rmtmgr.get(comp.host)
                        rmtsh.add_expected_python(do_cnc, dash_dir, config_dir,
                                                  log_dir, daq_data_dir,
                                                  spade_dir, clu_desc,
                                                  cfg_name, copy_dir, log_port,
                                                  live_port)
                        rmtsh.add_expected_java(comp, config_dir, daq_data_dir,
                                                DAQPort.CATCHALL, live_port,
                                                verbose, evt_chk)

                        dry_run = False
                        log_dir_fallback = None

                        ComponentManager.launch(do_cnc, dry_run, verbose,
                                                config, dash_dir, config_dir,
                                                daq_data_dir, log_dir,
                                                log_dir_fallback, spade_dir,
                                                copy_dir, log_port, live_port,
                                                event_check=evt_chk,
                                                check_exists=chk_exists,
                                                start_missing=False,
                                                rmtmgr=rmtmgr)

                        rmtsh.check()

    def test_do_kill(self):
        dry_run = False
        verbose = False

        comp_name = 'eventBuilder'
        comp_id = 0

        hs_dir = "/x/y/z"
        hs_interval = 2.0
        hs_max_files = 100

        jvm_path = "java"
        jvm_server = False
        jvm_heap_init = "1m"
        jvm_heap_max = "12m"
        jvm_args = "-Xarg"
        jvm_extra = "-Xextra"

        alert_email = "alert@email"
        ntp_host = "ntp_host"

        log_level = 'DEBUG'
        run_logger = None

        rmtmgr = MockRemoteManager()

        # if there are N targets, range is 2^N
        for targets in range(2):
            do_cnc = (targets & 1) == 1

            for host in MockNode.LIST:
                node = MockNode(host)
                node.add_comp(comp_name, comp_id, log_level, hs_dir,
                              hs_interval, hs_max_files, jvm_path, jvm_server,
                              jvm_heap_init, jvm_heap_max, jvm_args, jvm_extra,
                              alert_email, ntp_host)

                for kill_with_9 in (True, False):
                    rmtsh = rmtmgr.get(host)
                    rmtsh.add_expected_python_kill(do_cnc, kill_with_9)
                    rmtsh.add_expected_java_kill(comp_name, comp_id,
                                                 kill_with_9, verbose, host)

                    ComponentManager.kill(node.components(), verbose=verbose,
                                          dry_run=dry_run, kill_cnc=do_cnc,
                                          kill_with_9=kill_with_9,
                                          logger=run_logger, rmtmgr=rmtmgr)

                    rmtsh.check()

    def test_count_active_no_server(self):
        (_, num) = ComponentManager.count_active_runsets()
        self.assertEqual(num, 0, "Didn't expect any runsets, got %d" % num)

    def test_count_active(self):
        self.__srvr = MockServer()
        (_, num) = ComponentManager.count_active_runsets()
        self.assertEqual(num, 0, "Didn't expect any runsets, got %d" % num)

        self.__srvr.add_runset(RunSetState.RUNNING)
        self.__srvr.add_runset(RunSetState.READY)
        (_, num) = ComponentManager.count_active_runsets()
        self.assertEqual(num, 1, "Expected %d runsets, got %d" % (1, num))

    def test_get_active_nothing(self):
        comps = ComponentManager.get_active_components(None)
        self.assertFalse(comps is None,
                         "get_active_components should not return None")

    def test_get_active_config(self):
        config_name = "simpleConfig"
        CachedFile.writeCacheFile(config_name, True)

        cluster_desc = "spts64"

        comps = ComponentManager.get_active_components(cluster_desc,
                                                       config_dir=self.CONFIG_DIR,
                                                       validate=False)
        self.assertFalse(comps is None,
                         "get_active_components should not return None")

        exp_comps = ("eventBuilder", "SecondaryBuilders", "globalTrigger",
                     "inIceTrigger", "stringHub#1001", "stringHub#1002",
                     "stringHub#1003", "stringHub#1004", "stringHub#1005")
        self.assertEqual(len(comps), len(exp_comps),
                         "Expected %d components, got %d (%s)" %
                         (len(exp_comps), len(comps), comps))

        names = []
        for comp in comps:
            names.append(comp.fullname)

        for cname in exp_comps:
            self.assertTrue(cname in names,
                            "Expected component %s is not in (%s)" %
                            (cname, names))

    def test_get_active_server(self):
        self.__srvr = MockServer()

        exp_unused = (("foo", 1, "www.icecube.wisc.edu"),
                      ("bar", 0, "localhost"))

        for ucomp in exp_unused:
            self.__srvr.add_unused_component(ucomp[0], ucomp[1], ucomp[2])

        exp_rs = (("abc", 2, "127.0.0.1"),
                  ("cde", 0, "www.google.com"))

        compdict = []
        for rcomp in exp_rs:
            compdict.append({
                "compName": rcomp[0],
                "compNum": rcomp[1],
                "host": rcomp[2],
            })
        self.__srvr.add_runset(RunSetState.RUNNING, compdict)

        cluster_desc = "spts64"
        cfgdir = self.CONFIG_DIR

        comps = ComponentManager.get_active_components(cluster_desc,
                                                       config_dir=cfgdir,
                                                       validate=False,
                                                       use_cnc=True)
        self.assertFalse(comps is None,
                         "get_active_components should not return None")

        tot_comps = len(exp_unused) + len(exp_rs)
        self.assertEqual(tot_comps, len(comps),
                         "Expected %d components, got %d (%s)" %
                         (tot_comps, len(comps), comps))

        names = []
        for comp in comps:
            names.append(comp.fullname)

        for exp_list in (exp_unused, exp_rs):
            for cname in exp_list:
                if cname[1] == 0:
                    exp_name = cname[0]
                else:
                    exp_name = "%s#%d" % (cname[0], cname[1])
                self.assertTrue(exp_name in names,
                                "Expected component %s is not in (%s)" %
                                (exp_name, names))



def main():
    "Main program"
    # make sure icecube.wisc.edu is valid
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    for rmt_host in ('localhost', 'icecube.wisc.edu'):
        try:
            sock.connect((rmt_host, 7))
            MockNode.LIST.append(rmt_host)
        except:
            print("Warning: May not be able to connect to %s" % (rmt_host, ),
                  file=sys.stderr)

    unittest.main()


if __name__ == '__main__':
    main()
