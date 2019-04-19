#!/usr/bin/env python


import os
import tempfile
import unittest

from CachedConfigName import CachedConfigName
from DAQConst import DAQPort
from DAQLaunch import add_arguments_both, add_arguments_launch, \
     add_arguments_kill, launch, kill
from DAQMocks import MockClusterConfigFile, MockParallelShell, \
    MockRunConfigFile


class MockArguments(object):
    def __init__(self):
        pass

    def add_argument(self, *args, **kwargs):
        """
        Use 'dest' and 'default' keywords to create an argument attribute
        """
        if "dest" not in kwargs:
            raise Exception("No 'dest' for %s" % str(args))
        if "default" in kwargs:
            dflt = kwargs["default"]
        else:
            dflt = None
        setattr(self, kwargs["dest"], dflt)

    def set_argument(self, name, value):
        """
        Update the value on an existing argument attribute
        """
        if not hasattr(self, name):
            raise Exception("Unknown argument \"%s\"" % (name, ))
        setattr(self, name, value)


class TestDAQLaunch(unittest.TestCase):
    def __create_cluster_config_file(self, config_dir, clu_desc, daq_data_dir,
                                     log_dir, spade_dir, comp_host_dict):
        clu_cfg_file = MockClusterConfigFile(config_dir, clu_desc)

        clu_cfg_file.setDataDir(daq_data_dir)
        clu_cfg_file.setLogDir(log_dir)
        clu_cfg_file.setSpadeDir(spade_dir)

        ctlhost = clu_cfg_file.addHost("ctlhost")
        ctlhost.addControlServer()

        clu_hosts = {}
        for name, host in list(comp_host_dict.items()):
            if host not in clu_hosts:
                clu_hosts[host] = clu_cfg_file.addHost(host)
            clu_hosts[host].addComponent(name)

        sim = clu_cfg_file.addHost("simhost")
        sim.addSimHubs(10, 1)

        clu_cfg_file.create()

        return clu_cfg_file

    def tearDown(self):
        # clear cached config directory
        CachedConfigName.clear_active_config()

    def test_launch_only_cnc(self):
        tmp_dir = tempfile.mkdtemp()
        config_dir = os.path.join(tmp_dir, 'cfg')
        daq_data_dir = os.path.join(tmp_dir, 'data')
        dash_dir = os.path.join(tmp_dir, 'dash')
        log_dir = os.path.join(tmp_dir, 'log')
        spade_dir = os.path.join(tmp_dir, 'spade')

        comp_host_dict = {
            "inIceTrigger": "trigger",
            "globalTrigger": "trigger",
            "eventBuilder": "builder",
            "secondaryBuilders": "builder",
            "ichub01": "ichub01",
        }

        clu_cfg_file = self.__create_cluster_config_file(config_dir, "xxx",
                                                         daq_data_dir, log_dir,
                                                         spade_dir,
                                                         comp_host_dict)

        run_cfg_file = MockRunConfigFile(config_dir)
        cfg_name = run_cfg_file.create(list(comp_host_dict.keys()), {})

        copy_dir = None
        log_port = None
        live_port = DAQPort.I3LIVE_ZMQ

        force_restart = False
        logger = None
        check_exists = False

        shell = MockParallelShell()
        shell.addExpectedPython(True, dash_dir, config_dir, log_dir,
                                daq_data_dir, spade_dir, clu_cfg_file.name,
                                cfg_name, copy_dir, log_port, live_port,
                                forceRestart=force_restart)

        args = MockArguments()
        add_arguments_both(args)
        add_arguments_launch(args)
        args.set_argument("clusterDesc", clu_cfg_file.name)
        args.set_argument("config_name", cfg_name)
        args.set_argument("validate", False)
        args.set_argument("verbose", False)
        args.set_argument("dryRun", False)
        args.set_argument("event_check", False)
        args.set_argument("forceRestart", force_restart)

        launch(config_dir, dash_dir, logger, args=args, parallel=shell,
               check_exists=check_exists)

    def test_kill_only_cnc(self):
        tmp_dir = tempfile.mkdtemp()
        config_dir = os.path.join(tmp_dir, 'cfg')
        daq_data_dir = os.path.join(tmp_dir, 'data')
        log_dir = os.path.join(tmp_dir, 'log')
        spade_dir = os.path.join(tmp_dir, 'spade')

        comp_host_dict = {
            "inIceTrigger": "trigger",
            "globalTrigger": "trigger",
            "eventBuilder": "builder",
            "secondaryBuilders": "builder",
            "ichub01": "ichub01",
        }

        clu_cfg_file = self.__create_cluster_config_file(config_dir, "xxx",
                                                         daq_data_dir, log_dir,
                                                         spade_dir,
                                                         comp_host_dict)

        kill_with_9 = False
        logger = None

        shell = MockParallelShell()
        shell.addExpectedPythonKill(True, kill_with_9=kill_with_9)

        run_cfg_file = MockRunConfigFile(config_dir)
        cfg_name = run_cfg_file.create(list(comp_host_dict.keys()), {})

        # set the cached config name
        ccfg = CachedConfigName()
        ccfg.set_name(cfg_name)
        ccfg.write_cache_file(write_active_config=True)

        args = MockArguments()
        add_arguments_both(args)
        add_arguments_kill(args)
        args.set_argument("clusterDesc", clu_cfg_file.name)
        args.set_argument("validate", False)
        args.set_argument("serverKill", True)
        args.set_argument("verbose", False)
        args.set_argument("dryRun", False)
        args.set_argument("kill_with_9", kill_with_9)
        args.set_argument("force", True)

        kill(config_dir, logger, args=args)


if __name__ == '__main__':
    unittest.main()
