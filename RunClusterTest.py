#!/usr/bin/env python

from __future__ import print_function

import os
import re
import unittest
from DAQConfig import DAQConfigParser
from RunCluster import RunCluster, RunClusterError
from locate_pdaq import set_pdaq_config_dir


class DeployData(object):
    def __init__(self, host, name, compid=0):
        self.host = host
        self.name = name
        self.id = compid  # pylint: disable=invalid-name
        self.found = False

    def __str__(self):
        if self.id == 0 and not self.name.lower().endswith('hub'):
            return '%s/%s' % (self.host, self.name)
        return '%s/%s#%d' % (self.host, self.name, self.id)

    def change_host(self, new_host):
        self.host = new_host

    def clear(self):
        self.found = False

    @property
    def is_found(self):
        return self.found

    def mark_found(self):
        self.found = True

    def matches(self, host, name, compid):
        return self.host == str(host) and \
            self.name.lower() == name.lower() and \
            self.id == compid


class RunClusterTest(unittest.TestCase):
    CONFIG_DIR = os.path.abspath('src/test/resources/config')

    def __check_cluster(self, clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                        daq_log_dir, daq_data_dir, verbose=False):
        sorted_nodes = sorted(clu_cfg.nodes())

        # pylint: disable=unnecessary-lambda
        if verbose:
            print("=== RC -> %s" % (clu_cfg.config_name, ))
            for node in sorted_nodes:
                print("::  " + str(node))
                for comp in sorted(node.components):
                    print("        " + str(comp))

            print("=== EXP")
            for exp in sorted(exp_nodes,
                              key=lambda x: str(x)):
                print("::  " + str(exp))

        extra = {}
        for node in sorted_nodes:
            for comp in sorted(node.components):
                found = False
                for exp in exp_nodes:
                    if exp.matches(node.hostname, comp.name, comp.id):
                        if found:
                            self.fail("Found multiple matches for %s/%s#%d" %
                                      (node.hostname, comp.name, comp.id))
                        found = True
                        exp.mark_found()

                if not found:
                    if node not in extra:
                        extra[node] = []
                    extra[node].append(comp)

        if len(extra) > 0:  # pylint: disable=len-as-condition
            errmsg = "Found extra component%s:" % \
                     ("" if len(extra) == 1 else "s")
            for node, comp_list in list(extra.items()):
                cstr = None
                for comp in comp_list:
                    cfmt = comp.fullname
                    if cstr is None:
                        cstr = cfmt
                    else:
                        cstr += ", " + cfmt
                errmsg += "\n%s[%s]" % (node.hostname, cstr)
            self.fail(errmsg)

        missing = None
        for exp in exp_nodes:
            if not exp.is_found:
                if missing is None:
                    missing = str(exp)
                else:
                    missing += ", " + str(exp)

        if missing is not None:
            self.fail('Missing one or more components: ' + missing)

        self.assertEqual(clu_cfg.log_dir_for_spade, spade_dir,
                         'SPADE log directory is "%s", not "%s"' %
                         (clu_cfg.log_dir_for_spade, spade_dir))
        self.assertEqual(clu_cfg.log_dir_copies, log_copy_dir,
                         'Log copy directory is "%s", not "%s"' %
                         (clu_cfg.log_dir_copies, log_copy_dir))
        self.assertEqual(clu_cfg.daq_log_dir, daq_log_dir,
                         'DAQ log directory is "%s", not "%s"' %
                         (clu_cfg.daq_log_dir, daq_log_dir))
        self.assertEqual(clu_cfg.daq_data_dir, daq_data_dir,
                         'DAQ data directory is "%s", not "%s"' %
                         (clu_cfg.daq_data_dir, daq_data_dir))

    def __load_configs(self, cfg_name, cluster_name):
        cfg = DAQConfigParser.parse(RunClusterTest.CONFIG_DIR, cfg_name)

        cluster = RunCluster(cfg, cluster_name,
                             config_dir=RunClusterTest.CONFIG_DIR)

        if not cluster_name.endswith("-cluster"):
            fixed_name = cluster_name
        else:
            fixed_name = cluster_name[:-1]
        if fixed_name in ("sps", "spts"):
            full_name = cfg_name
        else:
            full_name = "%s@%s" % (cfg_name, fixed_name)

        self.assertEqual(cluster.config_name, full_name,
                         'Expected config name %s, not %s' %
                         (full_name, cluster.config_name))

        return (cfg, cluster)

    def setUp(self):
        set_pdaq_config_dir(RunClusterTest.CONFIG_DIR)

    def test_cluster_file(self):  # pylint: disable=no-self-use
        cfg = DAQConfigParser.parse(RunClusterTest.CONFIG_DIR, "simpleConfig")

        cluster = RunCluster(cfg, "localhost", RunClusterTest.CONFIG_DIR)

        cluster.clear_active_config()

        cluster.write_cache_file(write_active_config=False)
        cluster.write_cache_file(write_active_config=True)

    def test_deploy_localhost(self):
        cfg_name = 'simpleConfig'
        cluster_name = "localhost"

        (_, clu_cfg) = self.__load_configs(cfg_name, cluster_name)

        exp_nodes = [
            DeployData('localhost', 'inIceTrigger'),
            DeployData('localhost', 'globalTrigger'),
            DeployData('localhost', 'eventBuilder'),
            DeployData('localhost', 'SecondaryBuilders'),
            DeployData('localhost', 'stringHub', 1001),
            DeployData('localhost', 'stringHub', 1002),
            DeployData('localhost', 'stringHub', 1003),
            DeployData('localhost', 'stringHub', 1004),
            DeployData('localhost', 'stringHub', 1005),
        ]

        daq_log_dir = "logs"
        daq_data_dir = "data"
        spade_dir = 'spade'
        log_copy_dir = None

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)

    def test_deploy_spts64(self):
        cfg_name = 'simpleConfig'
        cluster_name = "spts64"

        (_, clu_cfg) = self.__load_configs(cfg_name, cluster_name)

        exp_nodes = [
            DeployData('spts64-iitrigger', 'inIceTrigger'),
            DeployData('spts64-gtrigger', 'globalTrigger'),
            DeployData('spts64-evbuilder', 'eventBuilder'),
            DeployData('spts64-expcont', 'SecondaryBuilders'),
            DeployData('spts64-2ndbuild', 'stringHub', 1001),
            DeployData('spts64-fpslave01', 'stringHub', 1002),
            DeployData('spts64-fpslave02', 'stringHub', 1003),
            DeployData('spts64-fpslave03', 'stringHub', 1004),
            DeployData('spts64-fpslave04', 'stringHub', 1005),
        ]

        daq_log_dir = "/mnt/data/pdaq/log"
        daq_data_dir = "/mnt/data/pdaqlocal"
        spade_dir = "/mnt/data/spade/pdaq/runs"
        log_copy_dir = "/mnt/data/pdaqlocal"

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)

    def test_deploy_too_many(self):
        cfg_name = 'tooManyConfig'
        cluster_name = "localhost"

        try:
            self.__load_configs(cfg_name, cluster_name)
        except RunClusterError as rce:
            if not str(rce).endswith("Only have space for 10 of 11 hubs"):
                self.fail("Unexpected exception: " + str(rce))

    def test_deploy_sps(self):
        cfg_name = 'sps-IC40-IT6-Revert-IceTop-V029'
        cluster_name = "sps"

        (_, clu_cfg) = self.__load_configs(cfg_name, cluster_name)

        exp_nodes = [
            DeployData('sps-trigger', 'inIceTrigger'),
            DeployData('sps-trigger', 'iceTopTrigger'),
            DeployData('sps-gtrigger', 'globalTrigger'),
            DeployData('sps-evbuilder', 'eventBuilder'),
            DeployData('sps-2ndbuild', 'SecondaryBuilders'),
            DeployData('sps-ichub21', 'stringHub', 21),
            DeployData('sps-ichub29', 'stringHub', 29),
            DeployData('sps-ichub30', 'stringHub', 30),
            DeployData('sps-ichub38', 'stringHub', 38),
            DeployData('sps-ichub39', 'stringHub', 39),
            DeployData('sps-ichub40', 'stringHub', 40),
            DeployData('sps-ichub44', 'stringHub', 44),
            DeployData('sps-ichub45', 'stringHub', 45),
            DeployData('sps-ichub46', 'stringHub', 46),
            DeployData('sps-ichub47', 'stringHub', 47),
            DeployData('sps-ichub48', 'stringHub', 48),
            DeployData('sps-ichub49', 'stringHub', 49),
            DeployData('sps-ichub50', 'stringHub', 50),
            DeployData('sps-ichub52', 'stringHub', 52),
            DeployData('sps-ichub53', 'stringHub', 53),
            DeployData('sps-ichub54', 'stringHub', 54),
            DeployData('sps-ichub55', 'stringHub', 55),
            DeployData('sps-ichub56', 'stringHub', 56),
            DeployData('sps-ichub57', 'stringHub', 57),
            DeployData('sps-ichub58', 'stringHub', 58),
            DeployData('sps-ichub59', 'stringHub', 59),
            DeployData('sps-ichub60', 'stringHub', 60),
            DeployData('sps-ichub61', 'stringHub', 61),
            DeployData('sps-ichub62', 'stringHub', 62),
            DeployData('sps-ichub63', 'stringHub', 63),
            DeployData('sps-ichub64', 'stringHub', 64),
            DeployData('sps-ichub65', 'stringHub', 65),
            DeployData('sps-ichub66', 'stringHub', 66),
            DeployData('sps-ichub67', 'stringHub', 67),
            DeployData('sps-ichub68', 'stringHub', 68),
            DeployData('sps-ichub69', 'stringHub', 69),
            DeployData('sps-ichub70', 'stringHub', 70),
            DeployData('sps-ichub71', 'stringHub', 71),
            DeployData('sps-ichub72', 'stringHub', 72),
            DeployData('sps-ichub73', 'stringHub', 73),
            DeployData('sps-ichub74', 'stringHub', 74),
            DeployData('sps-ichub75', 'stringHub', 75),
            DeployData('sps-ichub76', 'stringHub', 76),
            DeployData('sps-ichub77', 'stringHub', 77),
            DeployData('sps-ichub78', 'stringHub', 78),
            DeployData('sps-ithub01', 'stringHub', 201),
            DeployData('sps-ithub06', 'stringHub', 206),
        ]

        daq_log_dir = "/mnt/data/pdaq/log"
        daq_data_dir = "/mnt/data/pdaqlocal"
        spade_dir = "/mnt/data/spade/pdaq/runs"
        log_copy_dir = "/mnt/data/pdaqlocal"

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)

    @classmethod
    def __add_hubs(cls, nodes, hostname, num_to_add, hubnum):
        for _ in range(num_to_add):
            nodes.append(DeployData(hostname, 'replayHub', hubnum))
            hubnum += 1
            if hubnum > 86:
                if hubnum > 211:
                    break
                if hubnum < 200:
                    hubnum = 201

        return hubnum

    @classmethod
    def __add_hubs_from_run_config(cls, nodes, filename):
        # NOTE: only a fool parses XML code with regexps!
        hit_pat = re.compile(r'^\s*<hits hub="(\d+)" host="(\S+)"\s*/>\s*$')

        path = os.path.join(cls.CONFIG_DIR, filename)
        if not path.endswith(".xml"):
            path += ".xml"

        found = False
        with open(path, "r") as fin:
            for line in fin:
                mtch = hit_pat.match(line)
                if mtch is None:
                    continue

                hubnum = int(mtch.group(1))
                host = mtch.group(2)

                nodes.append(DeployData(host, 'replayHub', hubnum))
                found = True

        if not found:
            raise Exception("Didn't find any replayHub entries in %s" % path)

    def test_deploy_old_replay(self):
        cfg_name = "replay-oldtest"
        cluster_name = "replay"

        (_, clu_cfg) = self.__load_configs(cfg_name, cluster_name)

        exp_nodes = [
            DeployData('trigger', 'iceTopTrigger'),
            DeployData('trigger', 'iniceTrigger'),
            DeployData('trigger', 'globalTrigger'),
            DeployData('evbuilder', 'eventBuilder'),
            DeployData('expcont', 'CnCServer'),
            DeployData('2ndbuild', 'SecondaryBuilders'),
        ]
        hubnum = 1
        hubnum = self.__add_hubs(exp_nodes, 'daq01', 44, hubnum)
        hubnum = self.__add_hubs(exp_nodes, 'pdaq2', 10, hubnum)
        for name in ('fpslave01', 'fpslave02'):
            hubnum = self.__add_hubs(exp_nodes, name, 8, hubnum)
        for name in ('fpslave03', 'fpslave04'):
            hubnum = self.__add_hubs(exp_nodes, name, 7, hubnum)
        hubnum = self.__add_hubs(exp_nodes, 'ittest2', 7, hubnum)
        for name in ('fpslave05', 'ittest1'):
            hubnum = self.__add_hubs(exp_nodes, name, 3, hubnum)

        daq_log_dir = "/mnt/data/pdaq/log"
        daq_data_dir = "/mnt/data/pdaqlocal"
        spade_dir = "/mnt/data/pdaq/spade/runs"
        log_copy_dir = None

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)

    def test_deploy_replay(self):
        cfg_name = 'replay-test'
        cluster_name = "replay"

        (_, clu_cfg) = self.__load_configs(cfg_name, cluster_name)

        exp_nodes = [
            DeployData('trigger', 'iceTopTrigger'),
            DeployData('trigger', 'iniceTrigger'),
            DeployData('trigger', 'globalTrigger'),
            DeployData('evbuilder', 'eventBuilder'),
            DeployData('expcont', 'CnCServer'),
            DeployData('2ndbuild', 'SecondaryBuilders'),
        ]

        self.__add_hubs_from_run_config(exp_nodes, cfg_name)

        daq_log_dir = "/mnt/data/pdaq/log"
        daq_data_dir = "/mnt/data/pdaqlocal"
        spade_dir = "/mnt/data/pdaq/spade/runs"
        log_copy_dir = None

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)

    def test_deploy_replay_missing_host(self):
        cfg_name = 'replay-missing'
        cluster_name = "replay"

        cfg = DAQConfigParser.parse(RunClusterTest.CONFIG_DIR, cfg_name)

        try:
            RunCluster(cfg, cluster_name, RunClusterTest.CONFIG_DIR)
            self.fail("This should not succeed")
        except RunClusterError as rce:
            estr = str(rce)
            if estr != "Cannot find xxx09 for replay in %s" % cluster_name:
                raise

    def test_load_if_changed(self):
        cfg_name = 'sps-IC40-IT6-Revert-IceTop-V029'
        cluster_name = "sps"

        (run_cfg, clu_cfg) = self.__load_configs(cfg_name, cluster_name)

        exp_nodes = [
            DeployData('sps-trigger', 'inIceTrigger'),
            DeployData('sps-trigger', 'iceTopTrigger'),
            DeployData('sps-gtrigger', 'globalTrigger'),
            DeployData('sps-evbuilder', 'eventBuilder'),
            DeployData('sps-2ndbuild', 'SecondaryBuilders'),
            DeployData('sps-ichub21', 'stringHub', 21),
            DeployData('sps-ichub29', 'stringHub', 29),
            DeployData('sps-ichub30', 'stringHub', 30),
            DeployData('sps-ichub38', 'stringHub', 38),
            DeployData('sps-ichub39', 'stringHub', 39),
            DeployData('sps-ichub40', 'stringHub', 40),
            DeployData('sps-ichub44', 'stringHub', 44),
            DeployData('sps-ichub45', 'stringHub', 45),
            DeployData('sps-ichub46', 'stringHub', 46),
            DeployData('sps-ichub47', 'stringHub', 47),
            DeployData('sps-ichub48', 'stringHub', 48),
            DeployData('sps-ichub49', 'stringHub', 49),
            DeployData('sps-ichub50', 'stringHub', 50),
            DeployData('sps-ichub52', 'stringHub', 52),
            DeployData('sps-ichub53', 'stringHub', 53),
            DeployData('sps-ichub54', 'stringHub', 54),
            DeployData('sps-ichub55', 'stringHub', 55),
            DeployData('sps-ichub56', 'stringHub', 56),
            DeployData('sps-ichub57', 'stringHub', 57),
            DeployData('sps-ichub58', 'stringHub', 58),
            DeployData('sps-ichub59', 'stringHub', 59),
            DeployData('sps-ichub60', 'stringHub', 60),
            DeployData('sps-ichub61', 'stringHub', 61),
            DeployData('sps-ichub62', 'stringHub', 62),
            DeployData('sps-ichub63', 'stringHub', 63),
            DeployData('sps-ichub64', 'stringHub', 64),
            DeployData('sps-ichub65', 'stringHub', 65),
            DeployData('sps-ichub66', 'stringHub', 66),
            DeployData('sps-ichub67', 'stringHub', 67),
            DeployData('sps-ichub68', 'stringHub', 68),
            DeployData('sps-ichub69', 'stringHub', 69),
            DeployData('sps-ichub70', 'stringHub', 70),
            DeployData('sps-ichub71', 'stringHub', 71),
            DeployData('sps-ichub72', 'stringHub', 72),
            DeployData('sps-ichub73', 'stringHub', 73),
            DeployData('sps-ichub74', 'stringHub', 74),
            DeployData('sps-ichub75', 'stringHub', 75),
            DeployData('sps-ichub76', 'stringHub', 76),
            DeployData('sps-ichub77', 'stringHub', 77),
            DeployData('sps-ichub78', 'stringHub', 78),
            DeployData('sps-ithub01', 'stringHub', 201),
            DeployData('sps-ithub06', 'stringHub', 206),
        ]

        daq_log_dir = "/mnt/data/pdaq/log"
        daq_data_dir = "/mnt/data/pdaqlocal"
        spade_dir = "/mnt/data/spade/pdaq/runs"
        log_copy_dir = "/mnt/data/pdaqlocal"

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)

        new_path = os.path.join(RunClusterTest.CONFIG_DIR, "sps2-cluster.cfg")
        clu_cfg.load_if_changed(run_cfg, new_path)

        for node in exp_nodes:
            node.clear()
            if node.matches('sps-gtrigger', 'globalTrigger', 0):
                node.change_host("sps-trigger")

        self.__check_cluster(clu_cfg, exp_nodes, spade_dir, log_copy_dir,
                             daq_log_dir, daq_data_dir)


if __name__ == '__main__':
    unittest.main()
