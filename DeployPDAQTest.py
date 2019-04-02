#!/usr/bin/env python

import os
import tempfile
import unittest

import DeployPDAQ
from scmversion import SCM_REV_FILENAME


class MockNode(object):
    def __init__(self, hostname):
        self.__hostname = hostname

    @property
    def hostname(self):
        return self.__hostname


class MockClusterConfig(object):
    def __init__(self, hosts):
        self.__nodes = []
        for name in hosts:
            self.__nodes.append(MockNode(name))

    def nodes(self):
        return self.__nodes[:]

    def writeCacheFile(self):
        pass


class MockRSyncRunner(object):
    def __init__(self):
        self.__total_threads = None
        self.__running_threads = None
        self.__cmd_count = 0

    def add_expected(self, topdir, subdirs, delete, dry_run, remote_host,
                     rtncode, result="",
                     nice_level=DeployPDAQ.NICE_LEVEL_DEFAULT,
                     express=DeployPDAQ.EXPRESS_DEFAULT):
        pass

    def add_first(self, description, hostname, command):
        self.__cmd_count += 1

    def add_last(self, description, hostname, command):
        self.__cmd_count += 1

    def check(self):
        return False

    @property
    def num_remaining_commands(self):
        return 99

    @property
    def running_threads(self):
        if self.__running_threads is None:
            raise Exception("Threads have not been started")

        self.__running_threads -= (self.__total_threads / 2)
        return self.__running_threads

    def start(self, num_threads=None):
        if num_threads is None:
            self.__total_threads = DeployPDAQ.RSyncRunner.DEFAULT_THREADS
        else:
            self.__total_threads = int(num_threads)

        self.__running_threads = self.__total_threads

    @property
    def total_threads(self):
        return self.__total_threads

    @property
    def wait_seconds(self):
        return 0


class DeployPDAQTest(unittest.TestCase):
    def __check_deploy(self, hosts, subdirs, delete, dry_run, deep_dry_run,
                       nice_level=DeployPDAQ.NICE_LEVEL_DEFAULT,
                       express=DeployPDAQ.EXPRESS_DEFAULT):
        top_dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(top_dir, "target"))

        home_dir = os.path.join(top_dir, "home")
        os.mkdir(home_dir)

        home_cfg = os.path.join(home_dir, "config")
        os.mkdir(home_cfg)

        config = MockClusterConfig(hosts)

        runner = MockRSyncRunner()
        for host in hosts:
            runner.add_expected(top_dir, subdirs, delete, deep_dry_run,
                                host, 0, nice_level=nice_level,
                                express=express)

        trace_level = -1

        DeployPDAQ.deploy(config, top_dir, subdirs, delete, dry_run,
                          deep_dry_run, trace_level, nice_level=nice_level,
                          express=express, home=home_dir,
                          rsync_runner=runner)

        runner.check()

    def setUp(self):
        parent = os.path.dirname(SCM_REV_FILENAME)
        if not os.path.exists(parent):
            try:
                os.makedirs(parent)
            except:
                import traceback
                traceback.print_exc()

    def test_deploy_min(self):
        delete = False
        dry_run = False
        deep_dry_run = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run)

    def test_deploy_delete(self):
        delete = True
        dry_run = False
        deep_dry_run = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run)

    def test_deploy_deep_dry_run(self):
        delete = False
        dry_run = False
        deep_dry_run = True

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run)

    def test_deploy_dd(self):
        delete = True
        dry_run = False
        deep_dry_run = True

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run)

    def test_deploy_dry_run(self):
        delete = False
        dry_run = False
        deep_dry_run = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run)

    def test_deploy_nice(self):
        delete = False
        dry_run = False
        deep_dry_run = False
        nice_level = 5

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run,
                            nice_level)

    def test_deploy_express(self):
        delete = False
        dry_run = False
        deep_dry_run = False
        nice_level = 5
        express = True

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__check_deploy(hosts, subdirs, delete, dry_run, deep_dry_run,
                            nice_level, express)


if __name__ == '__main__':
    unittest.main()
