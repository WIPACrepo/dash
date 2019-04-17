#!/usr/bin/env python

from __future__ import print_function

import shutil
import sys
import tempfile
import threading
import time
import traceback
import unittest
import xmlrpclib

from CnCExceptions import CnCServerException
from CnCServer import CnCServer
from Component import Component
from ComponentManager import ComponentManager
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQLog import LogSocketServer
from DAQRPC import RPCServer
from RunOption import RunOption
from RunSet import RunSet
from locate_pdaq import set_pdaq_config_dir

from DAQMocks \
    import MockClusterConfig, MockCnCLogger, MockDefaultDomGeometryFile, \
    MockLeapsecondFile, MockLogger, MockRunConfigFile, SocketReaderFactory, \
    SocketReader, SocketWriter


class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbean_port, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbean_port, connectors,
                                              quiet=True)

    def createLogger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet)


class FakeLogger(object):
    def __init__(self, port):
        if port is None:
            port = LogSocketServer.next_log_port

        self.__port = port

    def __str__(self):
        return "FakeLogger@%s" % (self.__port, )

    @property
    def port(self):
        return self.__port

    def stop_serving(self):
        pass


class FakeRunData(object):
    def __init__(self, runNum, runCfg, clu_cfg, dashlog=None):
        self.__run_number = runNum
        self.__run_config = runCfg
        self.__cluster_config = clu_cfg
        self.__dashlog = dashlog

        self.__finished = False

    def clone(self, parent, newNum):
        return FakeRunData(newNum, self.__run_config, self.__cluster_config,
                           dashlog=self.__dashlog)

    @property
    def cluster_configuration(self):
        return self.__cluster_config

    def connect_to_live(self):
        pass

    def destroy(self):
        pass

    def error(self, logmsg):
        if self.__dashlog is None:
            raise Exception("Mock logger has not been set")
        self.__dashlog.error(logmsg)

    @property
    def finished(self):
        return self.__finished

    @property
    def is_error_enabled(self):
        return self.__dashlog.is_error_enabled

    @property
    def log_directory(self):
        return None

    def report_first_good_time(self, runset):
        pass

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

    def stop_tasks(self):
        pass

    def update_counts_and_rate(self, run_set):
        pass


class MostlyRunSet(RunSet):
    LOGFACTORY = SocketReaderFactory()
    LOGDICT = {}

    def __init__(self, parent, run_config, cluster_config, components,
                 catchall, dashlog):
        self.__run_config = run_config
        self.__cluster_config = cluster_config
        self.__catchall = catchall
        self.__dashlog = dashlog
        self.__logDict = {}

        super(MostlyRunSet, self).__init__(parent, run_config, components,
                                           catchall)

    @classmethod
    def create_component_log(cls, run_dir, comp, host, port, quiet=True):
        if comp.fullname in cls.LOGDICT:
            return cls.LOGDICT[comp.fullname]

        if port is not None:
            log = cls.LOGFACTORY.createLog(comp.fullname, port,
                                           expectStartMsg=True)
        else:
            while True:
                port = LogSocketServer.next_log_port

                try:
                    log = cls.LOGFACTORY.createLog(comp.fullname, port,
                                                   expectStartMsg=True)
                    break
                except socket.error:
                    pass

        cls.LOGDICT[comp.fullname] = log

        #log.addExpectedRegexp(r'Howdy from \S+#\d+')

        comp.logTo(host, port, None, None)

        return log

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir=None, log_dir=None):
        return FakeRunData(run_num, self.__run_config, cluster_config,
                           dashlog=self.__dashlog)

    def cycle_components(self, comp_list, configDir, daqDataDir, logger,
                         log_port, live_port, verbose=False, kill_with_9=False,
                         event_check=False, check_exists=True):
        logger.error("Cycling components %s" %
                     (ComponentManager.format_component_list(comp_list), ))

    def final_report(self, comps, runData, had_error=False, switching=False):
        numEvts = 600
        numMoni = 0
        numSN = 0
        numTCal = 0
        numSecs = 6

        self.__dashlog.error("%d physics events collected in %d seconds"
                             " (%.2f Hz)" % (numEvts, numSecs,
                                             float(numEvts) / float(numSecs)))
        self.__dashlog.error("%d moni events, %d SN events, %d tcals" %
                             (numMoni, numSN, numTCal))

        if switching:
            verb = "switched"
        else:
            verb = "terminated"
        if had_error:
            result = "WITH ERROR"
        else:
            result = "SUCCESSFULLY"
        self.__dashlog.error("Run %s %s." % (verb, result))

    def finish_setup(self, run_data, start_time):
        run_data.error('Version info: BRANCH 0:0 unknown unknown')
        run_data.error("Run configuration: %s" %
                       (run_data.run_configuration.basename, ))
        run_data.error("Cluster: %s" %
                       (run_data.cluster_configuration.description, ))

    @staticmethod
    def report_good_time(run_data, name, daq_time):
        pass

    @staticmethod
    def switch_component_log(oldLog, runDir, comp):
        pass


class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, clusterConfigObject, copyDir=None, runConfigDir=None,
                 daqDataDir=None, spadeDir=None, logIP='localhost',
                 logPort=-1, logFactory=None, dashlog=None,
                 force_restart=False):

        self.__clusterConfig = clusterConfigObject
        self.__logFactory = logFactory
        self.__dashlog = dashlog

        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              copyDir=copyDir,
                                              runConfigDir=runConfigDir,
                                              daqDataDir=daqDataDir,
                                              spadeDir=spadeDir,
                                              logIP=logIP, logPort=logPort,
                                              forceRestart=force_restart,
                                              quiet=True)

    def createClient(self, name, num, host, port, mbean_port, connectors):
        key = '%s#%d' % (name, num)
        key = 'server'
        if key not in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = MockLogger('Mock-%s' % key)

        return MostlyDAQClient(name, num, host, port, mbean_port, connectors,
                               MostlyCnCServer.APPENDERS[key])

    def createCnCLogger(self, quiet):
        key = 'server'
        if key not in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = MockLogger('Mock-%s' % key)

        return MockCnCLogger(key, appender=MostlyCnCServer.APPENDERS[key],
                             quiet=quiet)

    def createRunset(self, run_cfg, comp_list, logger):
        return MostlyRunSet(self, run_cfg, self.__clusterConfig, comp_list,
                            logger, self.__dashlog)

    def getClusterConfig(self, runConfig=None):
        return self.__clusterConfig

    def monitorLoop(self):
        pass

    def openLogServer(self, port, logDir):
        if MostlyRunSet.LOGFACTORY is None:
            raise Exception("MostlyRunSet log factory has not been set")
        return MostlyRunSet.LOGFACTORY.createLog("catchall", port,
                                                 expectStartMsg=False,
                                                 startServer=False)

    def saveCatchall(self, runDir):
        pass

    def startLiveThread(self):
        return None


class RealComponent(Component):
    def __init__(self, name, num, catchall_host, catchall_port, verbose=False):
        super(RealComponent, self).__init__(name, num, host="localhost")

        self.__log_socket = SocketWriter(catchall_host, catchall_port)

        self.__id = None
        self.__state = "UNKNOWN"
        self.__run_number = None

        self.__daqlog = None
        self.__livelog = None
        self.__bean_data = {}
        self.__event_counts = None

        self.__UNUSEDconnections = []

        self.__cmd = self.__create_cmd_server()
        self.__mbean = self.__create_mbean_server()

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER, verbose=verbose)

    def __create_cmd_server(self):
        cmd_srvr = RPCServer(LogSocketServer.next_log_port)
        cmd_srvr.register_function(self.__cmd_configure, 'xmlrpc.configure')
        cmd_srvr.register_function(self.__cmd_connect, 'xmlrpc.connect')
        cmd_srvr.register_function(self.__cmd_get_run_number,
                                   'xmlrpc.getRunNumber')
        cmd_srvr.register_function(self.__cmd_get_state, 'xmlrpc.getState')
        cmd_srvr.register_function(self.__cmd_log_to, 'xmlrpc.logTo')
        cmd_srvr.register_function(self.__cmd_reset, 'xmlrpc.reset')
        cmd_srvr.register_function(self.__cmd_reset_logging,
                                   'xmlrpc.resetLogging')
        cmd_srvr.register_function(self.__cmd_set_first_good_time,
                                   'xmlrpc.setFirstGoodTime')
        cmd_srvr.register_function(self.__cmd_set_last_good_time,
                                   'xmlrpc.setLastGoodTime')
        cmd_srvr.register_function(self.__cmd_start_run, 'xmlrpc.startRun')
        cmd_srvr.register_function(self.__cmd_stop_run, 'xmlrpc.stopRun')
        cmd_srvr.register_function(self.__cmd_switch_to_new_run,
                                   'xmlrpc.switchToNewRun')

        tname = "RPCSrvr*" + str(self.fullname)
        thrd = threading.Thread(name=tname, target=cmd_srvr.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        return cmd_srvr

    def __create_mbean_server(self):
        mbean_srvr = RPCServer(LogSocketServer.next_log_port)
        mbean_srvr.register_function(self.__mbean_get_value, 'mbean.get')
        mbean_srvr.register_function(self.__mbean_list, 'mbean.listMBeans')
        mbean_srvr.register_function(self.__mbean_get_attributes,
                                       'mbean.getAttributes')
        mbean_srvr.register_function(self.__mbean_list_getters,
                                       'mbean.listGetters')

        tname = "MBeanSrvr*" + str(self.fullname)
        thrd = threading.Thread(name=tname, target=mbean_srvr.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        return mbean_srvr

    def __cmd_configure(self, cfg_name):
        self.__log_socket.write("Config %s#%s with %s" %
                                (self.name, self.num, cfg_name))

        self.__state = "ready"
        return "CONFIGURED"

    def __cmd_connect(self, conn_list=None):
        try:
            return self.__cmd_connect_internal(conn_list)
        except:
            import traceback; traceback.print_exc()
            raise

    def __cmd_connect_internal(self, conn_list=None):
        if conn_list is not None:
            for cdict in conn_list:
                self.__UNUSEDconnections.append(cdict)

        self.__state = "connected"
        return "CONNECTED"

    def __cmd_get_run_number(self):
        return self.__run_number

    def __cmd_get_state(self):
        return self.__state

    def __cmd_log_to(self, log_host, log_port, live_host, live_port):
        if log_host is not None:
            self.__daqlog = MockLogger("DAQLog(%s)" % (self.fullname, ))
            #self.__daqlog.error("Howdy from %s" % (self.fullname, ))
        if live_host is not None:
            self.__livelog = MockLogger("LiveLog(%s)" % (self.fullname, ))
        return "LOGGING"

    def __cmd_reset(self):
        self.__state = "idle"
        return "IGNORED"

    def __cmd_reset_logging(self):
        if self.__daqlog is not None:
            self.__daqlog.checkStatus(100)
            self.__daqlog.close()
            self.__daqlog = None

        if self.__livelog is not None:
            self.__livelog.checkStatus(100)
            self.__livelog.close()
            self.__livelog = None

        return "RESETLOG"

    def __cmd_set_first_good_time(self, first_time):
        return "SetFGT"

    def __cmd_set_last_good_time(self):
        print("Not setting %s LastGoodTime to %s" %
              (self.fullname, last_time), file=sys.stderr)
        return "SetLGT"

    def __cmd_start_run(self, run_number):
        self.__run_number = run_number
        self.__state = "running"
        return "RUNNING"

    def __cmd_stop_run(self):
        self.__log("Stop %s" % (self.fullname, ))

        self.__state = "ready"
        return "STOPPED"

    def __cmd_switch_to_new_run(self, new_number):
        self.__log("Switch %s to run#%d" % (self.fullname, new_number))

        self.__run_number = new_number
        self.__state = "running"
        return "SWITCHED"

    def __log(self, msg):
        if self.__daqlog is None and self.__livelog is None:
            self.__log_socket.write(msg)
        else:
            if self.__daqlog is not None:
                self.__daqlog.write(msg)
            if self.__livelog is not None:
                self.__livelog.write(msg)

    def __mbean_get_attributes(self, bean, attr_list):
        values = {}
        for attr in attr_list:
            values[attr] = self.__mbean_get_value(bean, attr)
        return values

    def __mbean_get_value(self, bean, attr):
        if bean in self.__bean_data:
            if attr in self.__bean_data[bean]:
                return self.__bean_data[bean][attr]

        raise Exception("Unknown %s bean/attribute \"%s.%s\"" %
                        (self.fullname, bean, attr))

    def __mbean_list(self):
        return NotImplementedError("mbean_list")

    def __mbean_list_getters(self, bean):
        return NotImplementedError("mbean_list_getters")

    def check_status(self, reps=100):
        rtnval = True
        if self.__daqlog is not None:
            rtnval &= self.__daqlog.checkStatus(100)

        if self.__livelog is not None:
            rtnval &= self.__livelog.checkStatus(100)

        return rtnval

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

        for lname, log in (("DAQ", self.__daqlog), ("LIVE", self.__livelog)):
            if log is not None:
                log.checkStatus(100)
                if not log.isEmpty:
                    raise Exception("%s log for %s is not empty" %
                                    (lname, self.fullname, ))
                log.close()

        self.__daqlog = None
        self.__livelog = None

    @property
    def cmd_port(self):
        return self.__cmd.portnum

    @property
    def id(self):
        return self.__id

    @property
    def loggers(self):
        if self.__daqlog is not None:
            yield self.__daqlog
        if self.__livelog is not None:
            yield self.__livelog

    @property
    def mbean_port(self):
        return self.__mbean.portnum

    def register(self, conn_array):
        cmd_port = self.__cmd.portnum
        mbean_port = self.__mbean.portnum
        reg_data = self.__cnc.rpc_component_register(self.name, self.num,
                                                     'localhost', cmd_port,
                                                     mbean_port, conn_array)

        self.__id = reg_data["id"]
        self.__cmd_log_to(reg_data["logIP"], reg_data["logPort"],
                          reg_data["liveIP"], reg_data["livePort"])

    def set_bean_field_value(self, bean_name, fld_name, value):
        if bean_name is None:
            raise Exception("%s bean name cannot be None" % (self.fullname, ))
        if fld_name is None:
            raise Exception("%s field name cannot be None" % (self.fullname, ))

        if bean_name not in self.__bean_data:
            self.__bean_data[bean_name] = {}
        self.__bean_data[bean_name][fld_name] = value

    def set_run_data(self, v1, v2, v3, v4=None, v5=None):
        if v4 is None and v5 is None:
            self.__event_counts = (int(v1), int(v2), int(v3))
        else:
            self.__event_counts = (int(v1), int(v2), int(v3), int(v4), int(v5))

    @property
    def state(self):
        return self.__state


class RateTracker(object):
    def __init__(self, runNum, ticksInc, evtsInc, moniInc, snInc,
                 tcalInc):
        self.__runNumber = runNum
        self.__ticksInc = ticksInc
        self.__evtsInc = evtsInc
        self.__moniInc = moniInc
        self.__snInc = snInc
        self.__tcalInc = tcalInc

        self.reset()

    def addFinalLogMsgs(self, logger):
        numSecs = self.__numTicks / 10000000000
        logger.addExpectedExact(("%d physics events collected" +
                                 " in %d seconds (%0.2f Hz)") %
                                (self.__numEvts, numSecs,
                                 float(self.__numEvts) /
                                 float(numSecs)))
        logger.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                (self.__numMoni, self.__numSN, self.__numTcal))

    def getTotals(self):
        return (self.__numEvts, self.__numMoni, self.__numSN, self.__numTcal)

    def reset(self):
        self.__firstEvtTime = None
        self.__numTicks = 0
        self.__numEvts = 0
        self.__numMoni = 0
        self.__numSN = 0
        self.__numTcal = 0

    def updateRunData(self, cnc, runsetId, comps):
        self.__numTicks += self.__ticksInc
        self.__numEvts += self.__evtsInc
        self.__numMoni += self.__moniInc
        self.__numSN += self.__snInc
        self.__numTcal += self.__tcalInc

        if self.__firstEvtTime is None:
            self.__firstEvtTime = self.__numTicks

        lastEvtTime = self.__firstEvtTime + self.__numTicks

        for comp in comps:
            if comp.name == "eventBuilder":
                comp.set_run_data(self.__numEvts, self.__firstEvtTime,
                                  lastEvtTime, self.__firstEvtTime, lastEvtTime)
                comp.set_bean_field_value("backEnd", "EventData",
                                          (self.__runNumber, self.__numEvts,
                                           lastEvtTime))
                comp.set_bean_field_value("backEnd", "FirstEventTime",
                                          self.__firstEvtTime)
                comp.set_bean_field_value("backEnd", "GoodTimes",
                                          (self.__firstEvtTime, lastEvtTime))
            elif comp.name == "secondaryBuilders":
                comp.set_run_data(self.__numTcal, self.__numSN, self.__numMoni)

        cnc.updateRates(runsetId)


class CnCServerTest(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = 0x53494d552101

    def setUp(self):
        self.__copy_dir = tempfile.mkdtemp()
        self.__run_config_dir = tempfile.mkdtemp()
        self.__daq_data_dir = tempfile.mkdtemp()
        self.__spade_dir = tempfile.mkdtemp()

        self.comps = []
        self.cnc = None

        MostlyCnCServer.APPENDERS.clear()

        set_pdaq_config_dir(self.__run_config_dir, override=True)

    def tearDown(self):
        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkStatus(10)

        if self.cnc is not None:
            try:
                self.cnc.closeServer()
            except:
                pass

        for comp in self.comps:
            comp.close()
        del self.comps[:]

        if self.__copy_dir is not None:
            shutil.rmtree(self.__copy_dir, ignore_errors=True)
            self.__copy_dir = None
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)
            self.__run_config_dir = None
        if self.__daq_data_dir is not None:
            shutil.rmtree(self.__daq_data_dir, ignore_errors=True)
            self.__daq_data_dir = None
        if self.__spade_dir is not None:
            shutil.rmtree(self.__spade_dir, ignore_errors=True)
            self.__spade_dir = None

        set_pdaq_config_dir(None, override=True)

    def __addRange(self, rangeStr, rStart, rCurr):
        if not rangeStr.endswith(" "):
            rangeStr += ","
        if rStart == rCurr:
            rangeStr += "%d" % rCurr
        else:
            rangeStr += "%d-%d" % (rStart, rCurr)
        return rangeStr

    def __list_components_legibly(self, comps):
        cycleList = sorted(self.comps[:])

        compDict = {}
        for c in cycleList:
            if c.name not in compDict:
                compDict[c.name] = []
            compDict[c.name].append(c.num)

        strList = []
        for name in compDict:
            numList = compDict[name]

            if len(numList) == 1:
                num = numList[0]
                if num == 0:
                    strList.append(name)
                else:
                    strList.append("%s#%d" % (name, num))
                continue

            rangeStr = "name "
            rStart = None
            rCurr = None
            for n in numList:
                if rCurr is None:
                    rStart = n
                    rCurr = n
                elif rCurr == n - 1:
                    rCurr = n
                else:
                    rangeStr = self.__addRange(rangeStr, rStart, rCurr)
                    rStart = n
                    rCurr = n
                    strList.append(self.__addRange(rangeStr, rStart, rCurr))

        return ", ".join(strList)

    def __run_everything(self, force_restart=False, switch_run=False):
        catchall = MostlyRunSet.LOGFACTORY.createLog("master", 18999)
        dashlog = MockLogger('dashlog')

        comp_data = [('stringHub', self.HUB_NUMBER, (("hit", "o", 1), )),
                     ('inIceTrigger', 0, (("hit", "i", 2), ("trig", "o", 3), )),
                     ('eventBuilder', 0, (("trig", "i", 4), )), ]
        comp_host = 'localhost'

        clu_cfg = MockClusterConfig("clusterFoo")
        for cdata in comp_data:
            clu_cfg.addComponent("%s#%d" % (cdata[0], cdata[1]), "java", "",
                                 comp_host)

        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+')

        self.cnc = MostlyCnCServer(clusterConfigObject=clu_cfg,
                                   copyDir=self.__copy_dir,
                                   runConfigDir=self.__run_config_dir,
                                   daqDataDir=self.__daq_data_dir,
                                   spadeDir=self.__spade_dir,
                                   logPort=catchall.port,
                                   dashlog=dashlog,
                                   force_restart=force_restart)
        t = threading.Thread(name="CnCRun", target=self.cnc.run, args=())
        t.setDaemon(True)
        t.start()

        catchall.checkStatus(100)

        for cdata in comp_data:
            if cdata[1] == 0:
                fullname = cdata[0]
            else:
                fullname = "%s#%d" % (cdata[0], cdata[1])
            catchall.addExpectedText('Registered %s' % (fullname, ))

            comp = RealComponent(cdata[0], cdata[1], "localhost",
                                 catchall.port)
            comp.register(cdata[2])

            self.comps.append(comp)

        catchall.checkStatus(100)

        cdict = self.cnc.rpc_component_list_dicts()
        self.assertEqual(len(self.comps), len(cdict),
                         'Expected %s components, not %d' %
                         (len(self.comps), len(cdict)))
        for d in cdict:
            comp = None
            for c in self.comps:
                if d["compName"] == c.name and d["compNum"] == c.num:
                    comp = c
                    break

            self.assertTrue(comp is not None,
                            "Unknown component %s#%d" %
                            (d["compName"], d["compNum"]))
            self.assertEqual(comp_host, d["host"],
                             'Expected %s host %s, not %s' %
                             (comp.fullname, comp_host, d["host"]))
            self.assertEqual(comp.cmd_port, d["rpcPort"],
                             'Expected %s cmdPort %d, not %d' %
                             (comp.fullname, comp.cmd_port, d["rpcPort"]))
            self.assertEqual(comp.mbean_port, d["mbeanPort"],
                             'Expected %s mbeanPort %d, not %d' %
                             (comp.fullname, comp.mbean_port,
                              d["mbeanPort"]))

        run_cfg_file = MockRunConfigFile(self.__run_config_dir)

        comp_list = []
        for comp in self.comps:
            if not comp.isHub:
                comp_list.append(comp.fullname)

        hub2dom = {
            self.HUB_NUMBER:
            [MockRunConfigFile.createDOM(self.DOM_MAINBOARD_ID, 2,
                                         "SrvrTst", "ABCDEF"), ],
        }

        run_cfg = run_cfg_file.create(comp_list, hub2dom)

        MockDefaultDomGeometryFile.create(self.__run_config_dir, hub2dom)

        leap_file = MockLeapsecondFile(self.__run_config_dir)
        leap_file.create()

        catchall.addExpectedTextRegexp('Loading run configuration .*')
        catchall.addExpectedTextRegexp('Loaded run configuration .*')

        for comp in self.comps:
            catchall.addExpectedExact('Config %s#%d with %s' %
                                      (comp.name, comp.num, run_cfg))

        catchall.addExpectedTextRegexp(r"Built runset #\d+: .*")

        runNum = 444

        set_id = self.cnc.rpc_runset_make(run_cfg, runNum, strict=False)
        for comp in self.comps:
            self.assertEqual('ready', comp.state,
                             'Unexpected state %s for %s' %
                             (comp.state, comp.fullname))

        time.sleep(1)

        catchall.checkStatus(100)

        rscomps = self.cnc.rpc_runset_list(set_id)
        self.assertEqual(len(self.comps), len(rscomps),
                         "Expected one component, not %d" % len(self.comps))
        for rscomp in rscomps:
            badcomp = None
            for centry in self.comps:
                if centry.id != rscomp["id"]:
                    badcomp = centry
                    break

                comp = centry
                self.assertTrue(comp is not None,
                                "Unknown component %s#%d" %
                                (rscomp["compName"], rscomp["compNum"]))

                self.assertEqual(comp.name, rscomp["compName"],
                                 ("Component#%d name should be \"%s\","
                                  "not \"%s\"") %
                                 (comp.id, comp.name, rscomp["compName"]))
                self.assertEqual(comp.num, rscomp["compNum"],
                                 ("Component#%d \"%s\" number should be %d,"
                                  " not %d") %
                                 (comp.id, comp.fullname, comp.num,
                                  rscomp["compNum"]))
                self.assertEqual(comp_host, rscomp["host"],
                                 ("Component#%d \"%s\" host should be"
                                  " \"%s\", not \"%s\"") %
                                 (comp.id, comp.fullname, comp_host,
                                  rscomp["host"]))
                self.assertEqual(comp.cmd_port, rscomp["rpcPort"],
                                 ("Component#%d \"%s\" rpcPort should be"
                                  " \"%s\", not \"%s\"") %
                                 (comp.id, comp.fullname, comp.cmd_port,
                                  rscomp["rpcPort"]))
                self.assertEqual(comp.mbean_port, rscomp["mbeanPort"],
                                 "Component#%d \"%s\" mbeanPort should be"
                                 " \"%s\", not \"%s\"" %
                                 (comp.id, comp.fullname, comp.mbean_port,
                                  rscomp["mbeanPort"]))

        catchall.checkStatus(100)
        for comp in self.comps:
            comp.check_status(100)

        for comp in self.comps:
            for log in comp.loggers:
                log.addExpectedTextRegexp(r"Start of log at LOG=log(\S+:\d+)")
                log.addExpectedExact('Test msg')
                log.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+')

        catchall.addExpectedText("Starting run #%d on \"%s\"" %
                                 (runNum, clu_cfg.description))

        dashlog.addExpectedRegexp(r"Version info: \S+ \S+ \S+ \S+")
        dashlog.addExpectedExact("Run configuration: %s" % (run_cfg, ))
        dashlog.addExpectedExact("Cluster: %s" % clu_cfg.description)

        moniType = RunOption.MONI_TO_NONE

        for comp in self.comps:
            for log in comp.loggers:
                log.addExpectedExact('Start #%d on %s' %
                                     (runNum, comp.fullname))

        dashlog.addExpectedExact("Starting run %d..." % runNum)

        for comp in self.comps:
            if comp.name == "stringHub":
                comp.set_bean_field_value("stringhub",
                                          "LatestFirstChannelHitTime", 10)
                comp.set_bean_field_value("stringhub",
                                          "NumberOfNonZombies", 10)

        catchall.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        catchall.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        self.assertEqual(self.cnc.rpc_runset_start_run(set_id, runNum,
                                                       moniType), 'OK')

        catchall.checkStatus(100)
        dashlog.checkStatus(100)
        for comp in self.comps:
            comp.check_status(100)

        rateTracker = RateTracker(runNum, 10000000000, 100, 0, 0, 0)

        if switch_run:
            for _ in range(5):
                rateTracker.updateRunData(self.cnc, set_id, self.comps)

            for comp in self.comps:
                for log in comp.loggers:
                    log.addExpectedExact('Switch %s to run#%d' %
                                         (comp.fullname, runNum + 1))

            dashlog.addExpectedRegexp(r"Version info: \S+ \S+ \S+ \S+")
            dashlog.addExpectedExact("Run configuration: %s" % (run_cfg, ))
            dashlog.addExpectedExact("Cluster: %s" % clu_cfg.description)

            newNum = runNum + 1

            dashlog.addExpectedExact("Switching to run %d..." % newNum)

            rateTracker.updateRunData(self.cnc, set_id, self.comps)

            rateTracker.addFinalLogMsgs(dashlog)
            dashlog.addExpectedExact("Run switched SUCCESSFULLY.")

            dashlog.addExpectedExact("Not logging to file so cannot queue to"
                                     " SPADE")

            self.cnc.rpc_runset_switch_run(set_id, newNum)

            (numEvts, numMoni, numSN, numTcal) = rateTracker.getTotals()

            runNum = newNum

            catchall.checkStatus(100)
            dashlog.checkStatus(100)
            for comp in self.comps:
                for log in comp.loggers:
                    log.checkStatus(100)

            rateTracker.reset()

        for _ in range(5):
            rateTracker.updateRunData(self.cnc, set_id, self.comps)

        rateTracker.updateRunData(self.cnc, set_id, self.comps)

        for comp in self.comps:
            for log in comp.loggers:
                log.addExpectedExact("Stop %s" % comp.fullname)

        rateTracker.addFinalLogMsgs(dashlog)

        dashlog.addExpectedExact("Run terminated SUCCESSFULLY.")

        dashlog.addExpectedExact("Not logging to file so cannot queue to"
                                 " SPADE")
        for comp in self.comps:
            if comp.name == "stringHub":
                comp.set_bean_field_value("stringhub",
                                          "EarliestLastChannelHitTime", 10)

        if force_restart:
            cycleStr = self.__list_components_legibly(self.comps)
            catchall.addExpectedText("Cycling components %s" % cycleStr)

        self.assertEqual(self.cnc.rpc_runset_stop_run(set_id), 'OK')

        catchall.checkStatus(100)
        dashlog.checkStatus(100)
        for comp in self.comps:
            for log in comp.loggers:
                log.checkStatus(100)

        if force_restart:
            try:
                rs = self.cnc.rpc_runset_list(set_id)
                self.fail("Runset #%d should have been destroyed" % set_id)
            except CnCServerException:
                pass
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 0)
        else:
            self.assertEqual(len(self.cnc.rpc_runset_list(set_id)),
                             len(comp_data))
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 1)

            serverAppender = MostlyCnCServer.APPENDERS['server']

            self.assertEqual(self.cnc.rpc_runset_break(set_id), 'OK')

            serverAppender.checkStatus(100)

            self.assertEqual(self.cnc.rpc_component_count(), len(comp_data))
            self.assertEqual(self.cnc.rpc_runset_count(), 0)

            serverAppender.checkStatus(100)

        catchall.checkStatus(100)
        for comp in self.comps:
            for log in comp.loggers:
                log.checkStatus(100)

        self.cnc.closeServer()

    def test_everything(self):
        self.__run_everything()

    def test_everything_again(self):
        self.__run_everything()

    def test_force_restart(self):
        self.__run_everything(force_restart=True)

    def test_switch_run(self):
        self.__run_everything(switch_run=True)


if __name__ == '__main__':
    unittest.main()
