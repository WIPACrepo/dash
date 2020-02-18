#!/usr/bin/env python

import shutil
import tempfile
import traceback
import unittest
from CnCExceptions import CnCServerException
from CnCServer import CnCServer
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQMocks import MockClusterConfig, MockCnCLogger, \
    MockDefaultDomGeometryFile, MockLeapsecondFile, MockLogger, \
    MockRunConfigFile, SocketReaderFactory, SocketWriter
from RunOption import RunOption
from RunSet import RunSet
from locate_pdaq import set_pdaq_config_dir
from utils import ip


class TinyMBeanClient(object):
    def __init__(self):
        pass

    def get_attributes(self, beanname, fldlist):
        if beanname != "stringhub":
            raise Exception("Unknown bean \"%s\"" % beanname)
        rtndict = {}
        for fld in fldlist:
            if fld == "LatestFirstChannelHitTime" or \
                fld == "NumberOfNonZombies" or \
                fld == "EarliestLastChannelHitTime":
                rtndict[fld] = 10
            else:
                raise Exception("Unknown beanField \"%s.%s\"" %
                                (beanname, fld))
        return rtndict


class TinyClient(object):
    def __init__(self, name, num, host, port, mbean_port, connectors):
        self.__name = name
        self.__num = num
        self.__connectors = connectors

        self.__id = next(DAQClient.ID)

        self.__host = host
        self.__port = port
        self.__mbean_port = mbean_port

        self.__state = 'idle'
        self.__order = None

        self.__log = None
        self.__mbean_client = TinyMBeanClient()

    def __str__(self):
        if self.__mbean_port == 0:
            mstr = ''
        else:
            mstr = ' M#%d' % self.__mbean_port
        return 'ID#%d %s#%d at %s:%d%s' % \
            (self.__id, self.__name, self.__num, self.__host, self.__port,
             mstr)

    def configure(self, config_name=None):
        self.__state = 'ready'

    def connect(self, conn_list=None):
        self.__state = 'connected'

    def connectors(self):
        return self.__connectors[:]

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    @property
    def id(self):
        return self.__id

    @property
    def is_dying(self):
        return False

    @property
    def is_replay_hub(self):
        return False

    @property
    def is_source(self):
        return True

    def log_to(self, log_host, log_port, live_host, live_port):
        if live_host is not None and live_port is not None:
            raise Exception('Cannot log to I3Live')

        self.__log = SocketWriter(log_host, log_port)
        self.__log.write_ts('Start of log at LOG=log(%s:%d)' %
                            (log_host, self.__log.port))
        self.__log.write_ts('Version info: BRANCH 0:0 unknown unknown')

    def map(self):
        return {"id": self.__id,
                "compName": self.__name,
                "compNum": self.__num,
                "host": self.__host,
                "rpcPort": self.__port,
                "mbeanPort": self.__mbean_port,
                "state": self.__state}

    @property
    def mbean(self):
        return self.__mbean_client

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def order(self):
        return self.__order

    @order.setter
    def order(self, num):
        self.__order = num

    def reset(self):
        self.__state = 'idle'

    def reset_logging(self):
        pass

    def start_run(self, run_num):
        self.__state = 'running'

    @property
    def state(self):
        return self.__state

    def stop_run(self):
        self.__state = 'ready'


class FakeRunData(object):
    def __init__(self, run_num, run_cfg, clu_cfg):
        self.__run_number = run_num
        self.__run_config = run_cfg
        self.__cluster_config = clu_cfg

        self.__logger = None
        self.__finished = False

    def __str__(self):
        return "FakeRunData[%d/%s/%s]" % \
            (self.__run_number, self.__run_config.basename,
             self.__cluster_config.description)

    @property
    def cluster_configuration(self):
        return self.__cluster_config

    def connect_to_live(self):
        pass

    def error(self, logmsg):
        if self.__logger is None:
            raise Exception("Mock logger has not been set")
        self.__logger.error(logmsg)

    @property
    def finished(self):
        return self.__finished

    @property
    def has_moni_client(self):
        return True

    @property
    def is_error_enabled(self):
        return self.__logger.is_error_enabled

    @property
    def log_directory(self):
        return None

    def reset(self):
        pass

    @property
    def run_configuration(self):
        return self.__run_config

    @property
    def run_directory(self):
        return "/bad/path"

    @property
    def run_number(self):
        return self.__run_number

    def send_event_counts(self, run_set=None):
        pass

    def set_finished(self):
        self.__finished = True

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop_tasks(self):
        pass


class MockRunSet(RunSet):
    def __init__(self, parent, run_config, comp_list, logger, client_log=None):
        self.__run_config = run_config
        self.__dash_log = logger
        self.__client_log = client_log
        self.__dead_comp = []

        super(MockRunSet, self).__init__(parent, run_config, comp_list, logger)

    def create_component_log(self, run_dir, comp, port, quiet=True):
        return self.__client_log

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir=None, log_dir=None):
        mrd = FakeRunData(run_num, self.__run_config, cluster_config)
        mrd.set_mock_logger(self.__dash_log)
        return mrd

    def final_report(self, comps, run_data, had_error=False, switching=False):
        if switching:
            verb = "switched"
        else:
            verb = "terminated"
        if had_error:
            result = "WITH ERROR"
        else:
            result = "SUCCESSFULLY"
        self.__dash_log.error("Run %s %s." % (verb, result))

    def finish_setup(self, run_data, start_time):
        self.__dash_log.error('Version info: BRANCH 0:0 unknown unknown')
        self.__dash_log.error("Run configuration: %s" %
                              (run_data.run_configuration.basename, ))
        self.__dash_log.error("Cluster: %s" %
                              (run_data.cluster_configuration.description, ))

    @staticmethod
    def report_good_time(run_data, name, pay_time):
        pass


class MockServer(CnCServer):
    APPENDER = MockLogger('server')

    def __init__(self, cluster_config_object=None, copy_dir=None,
                 run_config_dir=None, daq_data_dir=None, spade_dir=None,
                 log_port=None, live_port=None, force_restart=False,
                 client_log=None, log_factory=None):
        self.__cluster_config = cluster_config_object
        self.__client_log = client_log
        self.__log_factory = log_factory

        super(MockServer, self).__init__(copy_dir=copy_dir,
                                         run_config_dir=run_config_dir,
                                         daq_data_dir=daq_data_dir,
                                         spade_dir=spade_dir,
                                         log_host='localhost',
                                         log_port=log_port,
                                         live_host='localhost',
                                         live_port=live_port,
                                         force_restart=force_restart,
                                         test_only=True)

    def create_client(self, name, num, host, port, mbean_port, connectors):
        return TinyClient(name, num, host, port, mbean_port, connectors)

    def create_cnc_logger(self, quiet):
        return MockCnCLogger("CnC", appender=MockServer.APPENDER, quiet=quiet)

    def create_runset(self, run_config, comp_list, logger):
        return MockRunSet(self, run_config, comp_list, logger,
                          client_log=self.__client_log)

    def get_cluster_config(self, run_config=None):
        return self.__cluster_config

    def open_log_server(self, port, log_dir):
        if self.__log_factory is None:
            raise Exception("MockServer log factory has not been set")
        return self.__log_factory.create_log("catchall", port,
                                             expect_start_msg=False,
                                             start_server=False)

    def save_catchall(self, run_dir):
        pass


class TestDAQServer(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = 0x53494d552101

    def __create_log(self, name, port, expect_start_msg=True):
        return self.__log_factory.create_log(name, port, expect_start_msg)

    def __verify_reg_array(self, rtn_array, exp_id, log_host, log_port,
                           live_host, live_port):
        num_elem = 6
        self.assertEqual(num_elem, len(rtn_array),
                         'Expected %d-element array, not %d elements' %
                         (num_elem, len(rtn_array)))
        self.assertEqual(exp_id, rtn_array["id"],
                         'Registration should return client ID#%d, not %d' %
                         (exp_id, rtn_array["id"]))
        self.assertEqual(log_host, rtn_array["logIP"],
                         'Registration should return loghost %s, not %s' %
                         (log_host, rtn_array["logIP"]))
        self.assertEqual(log_port, rtn_array["logPort"],
                         'Registration should return logport#%d, not %d' %
                         (log_port, rtn_array["logPort"]))
        self.assertEqual(live_host, rtn_array["liveIP"],
                         'Registration should return livehost %s, not %s' %
                         (live_host, rtn_array["liveIP"]))
        self.assertEqual(live_port, rtn_array["livePort"],
                         'Registration should return liveport#%d, not %d' %
                         (live_port, rtn_array["livePort"]))

    def setUp(self):
        self.__log_factory = SocketReaderFactory()

        self.__run_config_dir = None
        self.__daq_data_dir = None

        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        try:
            self.__log_factory.tearDown()
        except:
            traceback.print_exc()

        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)
            self.__run_config_dir = None
        if self.__daq_data_dir is not None:
            shutil.rmtree(self.__daq_data_dir, ignore_errors=True)
            self.__daq_data_dir = None

        MockServer.APPENDER.check_status(10)

        set_pdaq_config_dir(None, override=True)

    def test_register(self):
        log_port = 11853
        logger = self.__create_log('file', log_port)

        live_host = ''
        live_port = 0

        cnc = MockServer(log_port=log_port, log_factory=self.__log_factory)

        self.assertEqual(cnc.rpc_component_list_dicts(), [])

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mport = 667

        exp_id = DAQClient.ID.peek_next()

        if num == 0:
            full_name = name
        else:
            full_name = "%s#%d" % (name, num)

        logger.add_expected_text('Registered %s' % full_name)

        rtn_array = cnc.rpc_component_register(name, num, host, port, mport, [])

        local_addr = ip.get_local_address()

        self.__verify_reg_array(rtn_array, exp_id, local_addr, log_port,
                                live_host, live_port)

        self.assertEqual(cnc.rpc_component_count(), 1)

        foo_dict = {"id": exp_id,
                    "compName": name,
                    "compNum": num,
                    "host": host,
                    "rpcPort": port,
                    "mbeanPort": mport,
                    "state": "idle"}
        self.assertEqual(cnc.rpc_component_list_dicts(), [foo_dict, ])

        logger.check_status(100)

    def test_register_with_log(self):
        log_port = 23456
        logger = self.__create_log('log', log_port)

        cnc = MockServer(log_port=log_port, log_factory=self.__log_factory)

        logger.check_status(100)

        live_host = ''
        live_port = 0

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mport = 667

        exp_id = DAQClient.ID.peek_next()

        if num == 0:
            full_name = name
        else:
            full_name = "%s#%d" % (name, num)

        logger.add_expected_text('Registered %s' % full_name)

        rtn_array = cnc.rpc_component_register(name, num, host, port, mport, [])

        local_addr = ip.get_local_address()

        self.__verify_reg_array(rtn_array, exp_id, local_addr, log_port,
                                live_host, live_port)

        logger.check_status(100)

    def test_no_runset(self):
        log_port = 11545

        logger = self.__create_log('main', log_port)

        cnc = MockServer(log_port=log_port,
                         log_factory=self.__log_factory)

        logger.check_status(100)

        moni_type = RunOption.MONI_TO_NONE

        self.assertRaises(CnCServerException, cnc.rpc_runset_break, 1)
        self.assertRaises(CnCServerException, cnc.rpc_runset_list, 1)
        self.assertRaises(CnCServerException, cnc.rpc_runset_start_run, 1, 1,
                          moni_type)
        self.assertRaises(CnCServerException, cnc.rpc_runset_stop_run, 1)

        logger.check_status(100)

    def test_runset(self):
        self.__run_config_dir = tempfile.mkdtemp()
        self.__daq_data_dir = tempfile.mkdtemp()

        set_pdaq_config_dir(self.__run_config_dir, override=True)

        log_port = 21765

        logger = self.__create_log('main', log_port)

        client_port = DAQPort.EPHEMERAL_BASE

        client_logger = self.__create_log('client', client_port)

        comp_id = DAQClient.ID.peek_next()
        comp_name = 'stringHub'
        comp_num = self.HUB_NUMBER
        comp_host = 'localhost'
        comp_port = 666
        comp_bean_port = 0

        clu_cfg = MockClusterConfig("clusterFoo")
        clu_cfg.add_component("%s#%d" % (comp_name, comp_num), "java", "",
                              comp_host)

        cnc = MockServer(cluster_config_object=clu_cfg, copy_dir="copyDir",
                         run_config_dir=self.__run_config_dir,
                         daq_data_dir=self.__daq_data_dir, spade_dir="/tmp",
                         log_port=log_port, client_log=client_logger,
                         log_factory=self.__log_factory)

        logger.check_status(100)

        self.assertEqual(cnc.rpc_component_count(), 0)
        self.assertEqual(cnc.rpc_runset_count(), 0)
        self.assertEqual(cnc.rpc_component_list_dicts(), [])

        if comp_num == 0:
            full_name = comp_name
        else:
            full_name = "%s#%d" % (comp_name, comp_num)

        logger.add_expected_text('Registered %s' % full_name)

        cnc.rpc_component_register(comp_name, comp_num, comp_host, comp_port,
                                   comp_bean_port, [])

        logger.check_status(100)

        self.assertEqual(cnc.rpc_component_count(), 1)
        self.assertEqual(cnc.rpc_runset_count(), 0)

        conn_err = "No connection map entry for ID#%s %s#%d .*" % \
            (comp_id, comp_name, comp_num)
        logger.add_expected_text_regexp(conn_err)

        rc_file = MockRunConfigFile(self.__run_config_dir)

        hub_dom_dict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.create_dom(self.DOM_MAINBOARD_ID, 3,
                                          "DSrvrTst", "Z98765"), ],
        }

        run_config = rc_file.create([], hub_dom_dict)

        leapfile = MockLeapsecondFile(self.__run_config_dir)
        leapfile.create()

        MockDefaultDomGeometryFile.create(self.__run_config_dir, hub_dom_dict)

        logger.add_expected_text_regexp('Loading run configuration .*')
        logger.add_expected_text_regexp('Loaded run configuration .*')
        logger.add_expected_text_regexp(r"Built runset #\d+: .*")

        run_num = 456

        rsid = cnc.rpc_runset_make(run_config, run_num, strict=False)

        logger.check_status(100)

        self.assertEqual(cnc.rpc_component_count(), 0)
        self.assertEqual(cnc.rpc_runset_count(), 1)

        runsets = cnc.rpc_runset_list(rsid)
        self.assertEqual(len(runsets), 1)

        rsc = runsets[0]
        self.assertEqual(comp_id, rsc["id"])
        self.assertEqual(comp_name, rsc["compName"])
        self.assertEqual(comp_num, rsc["compNum"])
        self.assertEqual(comp_host, rsc["host"])
        self.assertEqual(comp_port, rsc["rpcPort"])
        self.assertEqual(comp_bean_port, rsc["mbeanPort"])
        self.assertEqual("ready", rsc["state"])

        logger.check_status(100)

        logger.add_expected_text("Starting run #%d on \"%s\"" %
                                 (run_num, clu_cfg.description))

        logger.add_expected_text_regexp(r"Version info: \S+ \S+ \S+ \S+")
        client_logger.add_expected_text_regexp(r"Version info: \S+ \S+ \S+"
                                               r" \S+")

        logger.add_expected_text("Run configuration: %s" % run_config)
        logger.add_expected_text("Cluster: %s" % clu_cfg.description)

        moni_type = RunOption.MONI_TO_NONE

        logger.add_expected_text("Starting run %d..." % run_num)

        logger.add_expected_text_regexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.add_expected_text_regexp(r"Waited \d+\.\d+ seconds for Hubs")

        self.assertEqual(cnc.rpc_runset_start_run(rsid, run_num, moni_type),
                         'OK')

        logger.check_status(10)
        client_logger.check_status(10)

        logger.add_expected_text("Run terminated SUCCESSFULLY")

        logger.add_expected_text("Not logging to file so cannot queue to"
                                 " SPADE")

        self.assertEqual(cnc.rpc_runset_stop_run(rsid), 'OK')

        logger.check_status(10)

        self.assertEqual(cnc.rpc_component_count(), 0)
        self.assertEqual(cnc.rpc_runset_count(), 1)

        logger.check_status(10)

        self.assertEqual(cnc.rpc_runset_break(rsid), 'OK')

        logger.check_status(10)

        self.assertEqual(cnc.rpc_component_count(), 1)
        self.assertEqual(cnc.rpc_runset_count(), 0)

        logger.check_status(10)
        client_logger.check_status(10)


if __name__ == '__main__':
    unittest.main()
