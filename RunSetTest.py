#!/usr/bin/env python

import numbers
import unittest

from ComponentManager import ComponentManager
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT, Prio
from RunOption import RunOption
from RunSet import RunSet, RunSetException
from locate_pdaq import set_pdaq_config_dir
from scmversion import get_scmversion_str

from DAQMocks import MockClusterConfig, MockComponent, MockLogger

CAUGHT_WARNING = True


class FakeLogger(object):
    def __init__(self):
        pass

    def stopServing(self):
        pass


class FakeRunConfig(object):
    def __init__(self, cfgdir, name):
        self.__cfgdir = cfgdir
        self.__name = name

    @property
    def basename(self):
        return self.__name

    def hasDOM(self, mbid):
        return True


class FakeCluster(object):
    def __init__(self, descName):
        self.__descName = descName

    @property
    def description(self):
        return self.__descName


class MyParent(object):
    def __init__(self):
        pass

    def saveCatchall(self, runDir):
        pass


class FakeMoniClient(object):
    def __init__(self):
        self.__expected = []

    def __compare_dicts(self, name, xvalue, value):
        for key in xvalue:
            if key not in value:
                raise AssertionError("Moni message \"%s\" value is missing"
                                     " field \"%s\"" % (name, key))

            self.__compare_values("%s.%s" % (name, key), xvalue[key],
                                  value[key])

        for key in value:
            if key not in xvalue:
                raise AssertionError("Moni message \"%s\" value has extra"
                                     " field \"%s\"" % (name, key))

    def __compare_lists(self, name, xvalue, value):
        raise NotImplementedError()

    def __compare_values(self, name, xvalue, value):
        if not isinstance(value, type(xvalue)):
            raise AssertionError("Expected moni message \"%s\" value type %s"
                                 ", not %s" % (name, type(xvalue).__name__,
                                               type(value).__name__))
        if isinstance(value, dict):
            self.__compare_dicts(name, xvalue, value)
        elif isinstance(value, list):
            self.__compare_lists(name, xvalue, value)
        elif xvalue != value:
            raise AssertionError("Expected moni message \"%s\" value %s<%s>"
                                 ", not %s<%s>" %
                                 (name, xvalue, type(xvalue).__name__,
                                  value, type(value).__name__))

    def add_moni(self, name, value, prio=Prio.ITS, time=None):
        self.__expected.append((name, value, prio, time))

    def send_moni(self, name, value, prio=Prio.ITS, time=None):
        if len(self.__expected) == 0:
            raise AssertionError("Received unexpected moni message \"%s\":"
                                 " %s" % (name, value))
        (xname, xvalue, xprio, _) = self.__expected.pop(0)
        if xname != name:
            raise AssertionError("Expected moni message \"%s\", not \"%s\"" %
                                 (xname, name))
        if xprio != prio:
            raise AssertionError("Expected moni message \"%s\" prio %s"
                                 ", not %s" % (name, xprio, prio))
        self.__compare_values(name, xvalue, value)


class FakeRunData(object):
    def __init__(self, run_num, run_cfg, clu_cfg, version_info, moni_client):
        self.__run_number = run_num
        self.__run_config = run_cfg
        self.__cluster_config = clu_cfg
        self.__version_info = version_info
        self.__moni_client = moni_client

        self.__logger = None
        self.__finished = False

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

    def info(self, logmsg):
        if self.__logger is None:
            raise Exception("Mock logger has not been set")
        self.__logger.info(logmsg)

    @property
    def isDestroyed(self):
        return self.__logger is not None

    @property
    def isErrorEnabled(self):
        return self.__logger.isErrorEnabled

    @property
    def log_directory(self):
        return None

    @property
    def release(self):
        return self.__version_info["release"]

    @property
    def repo_revision(self):
        return self.__version_info["repo_rev"]

    def reset(self):
        pass

    @property
    def revision_date(self):
        return self.__version_info["date"]

    @property
    def revision_time(self):
        return self.__version_info["time"]

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

    def set_subrun_number(self, num):
        pass

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop_tasks(self):
        pass


class MyRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger, moni_client):
        self.__runConfig = runConfig
        self.__logger = logger
        self.__moni_client = moni_client

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    @classmethod
    def create_component_log(cls, runDir, comp, host, port, liveHost,
                             livePort, quiet=True):
        return FakeLogger()

    def create_run_data(self, runNum, clusterConfig, runOptions, versionInfo,
                        spadeDir, copyDir=None, logDir=None):
        fake = FakeRunData(runNum, self.__runConfig, clusterConfig,
                           versionInfo, self.__moni_client)
        fake.set_mock_logger(self.__logger)
        return fake

    @classmethod
    def cycle_components(cls, compList, configDir, daqDataDir, logger, logPort,
                         livePort, verbose, killWith9, eventCheck,
                         checkExists=True):
        pass

    def final_report(self, comps, runData, had_error=False, switching=False):
        if True:
            numEvts = 0
            numMoni = 0
            numSN = 0
            numTCal = 0
            numSecs = 0

            if numSecs == 0:
                hz_str = ""
            else:
                hz = " (%.2f Hz)" % (float(numEvts) / float(numSecs), )

            self.__logger.error("%d physics events collected in %d seconds%s" %
                                (numEvts, numSecs, hz_str))
            self.__logger.error("%d moni events, %d SN events, %d tcals" %
                                (numMoni, numSN, numTCal))

        if switching:
            verb = "switched"
        else:
            verb = "terminated"
        if had_error:
            result = "WITH ERROR"
        else:
            result = "SUCCESSFULLY"
        self.__logger.error("Run %s %s." % (verb, result))

    def finish_setup(self, run_data, start_time):
        run_data.error("Version info: %s %s %s %s" %
                       (run_data.release,
                        run_data.repo_revision,
                        run_data.revision_date,
                        run_data.revision_time))
        run_data.error("Run configuration: %s" %
                       (run_data.run_configuration.basename, ))
        run_data.error("Cluster: %s" %
                       (run_data.cluster_configuration.description, ))

    def get_event_counts(self, run_num):
        return {
            "physicsEvents": 1,
            "eventPayloadTicks": -100,
            "wallTime": None,
            "moniEvents": 1,
            "moniTime": 99,
            "snEvents": 1,
            "snTime": 98,
            "tcalEvents": 1,
            "tcalTime": 97,
        }

    @staticmethod
    def report_good_time(run_data, name, daq_time):
        pass


class TestRunSet(unittest.TestCase):
    def __add_hub_mbeans(self, compList):
        for comp in compList:
            if comp.isSource:
                bean = "stringhub"
                for fld in ("EarliestLastChannelHitTime",
                            "LatestFirstChannelHitTime",
                            "NumberOfNonZombies"):
                    try:
                        comp.mbean.get(bean, fld)
                    except:
                        comp.mbean.addData(bean, fld, 1)

    def __add_moni_run_update(self, runset, moni_client, run_num):
        ec_dict = runset.get_event_counts(run_num)
        run_update = {
            "version": 0,
            "run": run_num,
            "subrun": 0,
        }
        for stream in ("physics", "moni", "sn", "tcal"):
            for fld in ("Events", "Time"):
                key = stream + fld
                if key in ec_dict:
                    if fld != "Time":
                        run_update[key] = ec_dict[key]
                    elif isinstance(ec_dict[key], numbers.Number):
                        dttm = PayloadTime.toDateTime(ec_dict[key])
                        run_update[key] = str(dttm)
                    else:
                        run_update[key] = str(ec_dict[key])
        moni_client.add_moni("run_update", run_update)

    def __buildClusterConfig(self, compList, baseName):
        jvmPath = "java-" + baseName
        jvmArgs = "args=" + baseName

        clusterCfg = MockClusterConfig("CC-" + baseName)
        for c in compList:
            clusterCfg.addComponent(c.fullname, jvmPath, jvmArgs,
                                    "host-" + c.fullname)

        return clusterCfg

    def __buildCompList(self, nameList):
        compList = []

        num = 1
        for name in nameList:
            c = MockComponent(name, num)
            c.setOrder(num)
            compList.append(c)
            num += 1

        return compList

    def __buildCompString(self, nameList):
        compStr = None

        prev = None
        prevNum = None
        for idx, name in enumerate(nameList + (None, )):
            if prev is not None:
                if prev == name:
                    continue

                if prevNum == idx:
                    newStr = "%s#%d" % (prev, prevNum)
                else:
                    newStr = "%s#%d-%d" % (prev, prevNum, idx)

                if compStr is None:
                    compStr = newStr
                else:
                    compStr += ", " + newStr

            prev = name
            prevNum = idx + 1

        return compStr

    def __checkStatus(self, runset, compList, expState):
        statDict = runset.status()
        self.assertEqual(len(statDict), len(compList))
        for c in compList:
            self.assertTrue(c in statDict, 'Could not find ' + str(c))
            self.assertEqual(statDict[c], expState,
                             "Component %s: %s != expected %s" %
                             (c, statDict[c], expState))

    def __checkStatusDict(self, runset, compList, expStateDict):
        statDict = runset.status()
        self.assertEqual(len(statDict), len(compList))
        for c in compList:
            self.assertTrue(c in statDict, 'Could not find ' + str(c))
            self.assertEqual(statDict[c], expStateDict[c],
                             "Component %s: %s != expected %s" %
                             (c, statDict[c], expStateDict[c]))

    def __isCompListConfigured(self, compList):
        for c in compList:
            if not c.isConfigured:
                return False

        return True

    def __isCompListRunning(self, compList, runNum=-1):
        for c in compList:
            if c.runNum is None:
                return False
            if c.runNum != runNum:
                return False

        return True

    def __runSubrun(self, compList, runNum, moni_client, expectError=None):
        logger = MockLogger('LOG')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runConfig = FakeRunConfig(None, "XXXrunSubXXX")

        cluCfg = FakeCluster("cluster-foo")

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        if len(compList) > 0:
            self.assertTrue(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.assertFalse(self.__isCompListRunning(compList),
                             "Components should not be running")

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        expState = "running"

        try:
            stopErr = runset.stop_run("StopSubrun", timeout=0)
        except RunSetException as ve:
            if "is not running" not in str(ve):
                raise
            stopErr = False

        self.assertFalse(stopErr, "stop_run() encountered error")

        for comp in compList:
            if comp.isSource:
                comp.mbean.addData("stringhub", "LatestFirstChannelHitTime",
                                   10)
                comp.mbean.addData("stringhub", "NumberOfNonZombies", 1)

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        domList = [('53494d550101', 0, 1, 2, 3, 4),
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        data = [domList[0], ['53494d550122', ] + domList[1][2:]]

        subrunNum = -1

        logger.addExpectedExact("Subrun %d: flashing DOM (%s)" %
                                (subrunNum, data))

        try:
            runset.subrun(subrunNum, data)
            if expectError is not None:
                self.fail("subrun should not have succeeded")
        except RunSetException as ve:
            if expectError is None:
                raise
            if not str(ve).endswith(expectError):
                self.fail("Expected subrun to fail with \"%s\", not \"%s\"" %
                          (expectError, str(ve)))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        for comp in compList:
            if comp.isSource:
                comp.mbean.addData("stringhub", "EarliestLastChannelHitTime",
                                   10)

        self.__stopRun(runset, runNum, runConfig, cluCfg, moni_client,
                       components=compList, logger=logger)

    def __runTests(self, compList, runNum, hangType=None):
        logger = MockLogger('foo#0')

        num = 1
        sources = 0
        for c in compList:
            c.setOrder(num)
            if c.isSource:
                sources += 1
            num += 1

        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")

        expId = RunSet.ID_SOURCE.peekNext()

        cluCfg = FakeCluster("cluster-foo")

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        expState = "configuring"

        i = 0
        while True:
            cfgWaitStr = None
            for c in compList:
                if c.getConfigureWait() > i:
                    if cfgWaitStr is None:
                        cfgWaitStr = c.fullname
                    else:
                        cfgWaitStr += ', ' + c.fullname

            if cfgWaitStr is None:
                break

            logger.addExpectedExact("RunSet #%d (%s): Waiting for %s %s" %
                                    (expId, expState, expState, cfgWaitStr))
            i += 1

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        expState = "ready"
        if len(compList) > 0:
            self.assertTrue(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.assertFalse(self.__isCompListRunning(compList),
                             "Components should not be running")

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        self.assertRaises(RunSetException, runset.stop_run, ("RunTest"))
        logger.checkStatus(10)

        expState = "running"

        try:
            self.__startRun(runset, runNum, runConfig, cluCfg,
                            components=compList, logger=logger)
            if sources == 0:
                self.fail("Should not be able to start a run with no sources")
        except RunSetException as rse:
            if sources != 0:
                raise
            estr = str(rse)
            if estr.find("Could not get runset") < 0 or \
               estr.find("latest first time") < 0:
                self.fail("Unexpected exception during start: " + str(rse))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        expState = "stopping"

        for comp in compList:
            if comp.isSource:
                comp.mbean.addData("stringhub", "EarliestLastChannelHitTime",
                                   10)

        self.__stopRun(runset, runNum, runConfig, cluCfg, moni_client,
                       components=compList, logger=logger, hangType=hangType)

        expState = "ready"

        if hangType != 2:
            self.__checkStatus(runset, compList, expState)
        else:
            expStateDict = {}
            for comp in compList:
                if comp.name == "foo":
                    expStateDict[comp] = expState
                else:
                    expStateDict[comp] = "forcingStop"
            self.__checkStatusDict(runset, compList, expStateDict)
        logger.checkStatus(10)

        runset.reset()

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, expState))

        if len(compList) > 0:
            self.assertFalse(self.__isCompListConfigured(compList),
                             "Components should be configured")
            self.assertFalse(self.__isCompListRunning(compList),
                             "Components should not be running")

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

    def __startRun(self, runset, runNum, runConfig, cluCfg,
                   runOptions=RunOption.MONI_TO_NONE, versionInfo=None,
                   spadeDir="/tmp", copyDir=None, logDir=None,
                   components=None, logger=None):

        global CAUGHT_WARNING
        if not LIVE_IMPORT and not CAUGHT_WARNING:
            CAUGHT_WARNING = True
            logger.addExpectedRegexp(r"^Cannot import IceCube Live.*")

        has_source = False
        if components is not None:
            for comp in components:
                if comp.isSource:
                    has_source = True
                    bean = "stringhub"
                    for fld in ("LatestFirstChannelHitTime",
                                "NumberOfNonZombies"):
                        try:
                            comp.mbean.get(bean, fld)
                        except:
                            comp.mbean.addData(bean, fld, 10)

        if versionInfo is None:
            versionInfo = {
                "filename": "fName",
                "revision": "1234",
                "date": "date",
                "time": "time",
                "author": "author",
                "release": "rel",
                "repo_rev": "1repoRev",
            }

        expState = "running"

        logger.addExpectedExact("Starting run #%d on \"%s\"" %
                                (runNum, cluCfg.description))

        if has_source:
            logger.addExpectedExact("Version info: " +
                                    get_scmversion_str(info=versionInfo))
            logger.addExpectedExact("Run configuration: %s" %
                                    runConfig.basename)
            logger.addExpectedExact("Cluster: %s" % cluCfg.description)

        logger.addExpectedExact("Starting run %d..." % runNum)

        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        runset.start_run(runNum, cluCfg, runOptions, versionInfo,
                         spadeDir, copyDir, logDir)
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id, runNum, expState))

        if components is not None and len(components) > 0:
            self.assertTrue(self.__isCompListConfigured(components),
                            'Components should be configured')
            self.assertTrue(self.__isCompListRunning(components, runNum),
                            'Components should not be running')

        self.__checkStatus(runset, components, expState)
        logger.checkStatus(10)

    def __stopRun(self, runset, runNum, runConfig, cluCfg, moni_client,
                  components=None, logger=None, hangType=0):
        expState = "stopping"

        compList = components
        if compList is not None:
            compList.sort(key=lambda x: x.order())

        if hangType == 0:
            stopName = "TestRunSet"
        elif hangType == 1:
            stopName = "TestHang1"
        elif hangType == 2:
            stopName = "TestHang2"
        else:
            stopName = "Test"
        logger.addExpectedExact("Stopping the run (%s)" % stopName)

        hangStr = None
        forceStr = None
        if hangType > 0:
            hangList = []
            forceList = []
            for c in components:
                if c.isHanging:
                    extra = "(ERROR)"
                    hangList.append(c.fullname + extra)
                    forceList.append(c.fullname)
            hangStr = ", ".join(hangList)
            forceStr = ", ".join(forceList)

            if len(hangList) < len(components):
                logger.addExpectedExact("RunSet #%d run#%d (%s):"
                                        " Waiting for %s %s" %
                                        (runset.id, runNum, expState,
                                         expState, hangStr))

            if len(forceList) == 1:
                plural = ""
            else:
                plural = "s"
            logger.addExpectedExact("RunSet #%d run#%d (%s):"
                                    " Forcing %d component%s to stop: %s" %
                                    (runset.id, runNum, "forcingStop",
                                     len(hangList), plural, forceStr))
            if hangType > 1:
                logger.addExpectedExact("ForcedStop failed for " + forceStr)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")

        expState = "ready"

        if hangType > 1:
            expState = "forcingStop"
            logger.addExpectedExact("Run terminated WITH ERROR.")
            logger.addExpectedExact("RunSet #%d run#%d (%s):"
                                    " Could not stop %s" %
                                    (runset.id, runNum, expState, forceStr))
        else:
            logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        logger.addExpectedExact("Not logging to file so cannot queue to"
                                " SPADE")

        self.__add_moni_run_update(runset, moni_client, runNum)

        if hangType < 2:
            self.assertFalse(runset.stop_run(stopName, timeout=0),
                             "stop_run() encountered error")
            expState = "ready"
        else:
            try:
                if not runset.stop_run(stopName, timeout=0):
                    self.fail("stop_run() should have failed")
            except RunSetException as rse:
                expMsg = "RunSet #%d run#%d (%s): Could not stop %s" % \
                         (runset.id, runNum, expState, forceStr)
                self.assertEqual(str(rse), expMsg,
                                 ("For hangType %d expected exception %s," +
                                  " not %s") % (hangType, expMsg, rse))
            expState = "error"

        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id, runNum, expState))
        self.assertFalse(runset.stopping(), "RunSet #%d is still stopping")

        if len(components) > 0:
            self.assertTrue(self.__isCompListConfigured(components),
                            "Components should be configured")
            self.assertFalse(self.__isCompListRunning(components),
                             "Components should not be running")

        if hangType == 0:
            self.__checkStatus(runset, components, expState)
        logger.checkStatus(10)

    def setUp(self):
        set_pdaq_config_dir("src/test/resources/config", override=True)

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        # create the leapsecond alertstamp file so we don't get superfluous
        # log messages
        RunSet.is_leapsecond_silenced()

    def tearDown(self):
        set_pdaq_config_dir(None, override=True)

    def testEmpty(self):
        self.__runTests([], 1)

    def testSet(self):
        compList = self.__buildCompList(("foo", "bar"))
        compList[0].setConfigureWait(1)

        self.__runTests(compList, 2)

    def testSubrunGood(self):
        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))

        moni_client = FakeMoniClient()

        self.__runSubrun(compList, 3, moni_client)

    def testSubrunOneBad(self):

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))
        compList[1].setBadHub()

        moni_client = FakeMoniClient()

        self.__runSubrun(compList, 4, moni_client, expectError="on %s" %
                         compList[1].fullname)

    def testSubrunBothBad(self):

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))
        compList[0].setBadHub()
        compList[1].setBadHub()

        moni_client = FakeMoniClient()

        self.__runSubrun(compList, 5, moni_client,
                         expectError="on any string hubs")

    def testStopHang(self):
        hangType = 1

        compList = self.__buildCompList(("foo", "bar"))
        compList[1].setHangType(hangType)

        RunSet.TIMEOUT_SECS = 5

        self.__runTests(compList, 6, hangType=hangType)

    def testForcedStopHang(self):
        hangType = 2

        compList = self.__buildCompList(("foo", "bar"))
        compList[1].setHangType(hangType)

        RunSet.TIMEOUT_SECS = 5

        self.__runTests(compList, 7, hangType=hangType)

    def testRestartFailCluCfg(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        baseName = "failCluCfg"

        clusterCfg = self.__buildClusterConfig(compList[1:], baseName)

        logger.addExpectedExact(("Cannot restart %s: Not found" +
                                 " in cluster config %s") %
                                (compList[0].fullname, clusterCfg))

        cycleList = sorted(compList[1:])

        errMsg = None
        for c in cycleList:
            if errMsg is None:
                errMsg = "Cycling components " + c.fullname
            else:
                errMsg += ", " + c.fullname
        if errMsg is not None:
            logger.addExpectedExact(errMsg)

        runset.restart_components(compList[:], clusterCfg, None, None, None,
                                  None, False, False, False)

    def testRestartExtraComp(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        extraComp = MockComponent("queen", 10)

        longList = compList[:]
        longList.append(extraComp)

        baseName = "failCluCfg"

        clusterCfg = self.__buildClusterConfig(longList, baseName)

        logger.addExpectedExact("Cannot remove component %s from RunSet #%d" %
                                (extraComp.fullname, runset.id))

        longList.sort()

        errMsg = None
        for c in longList:
            if errMsg is None:
                errMsg = "Cycling components " + c.fullname
            else:
                errMsg += ", " + c.fullname
        if errMsg is not None:
            logger.addExpectedExact(errMsg)

        runset.restart_components(longList, clusterCfg, None, None, None,
                                  None, False, False, False)

    def testRestart(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        clusterCfg = self.__buildClusterConfig(compList, "restart")

        errMsg = None
        for c in compList:
            if errMsg is None:
                errMsg = "Cycling components " + c.fullname
            else:
                errMsg += ", " + c.fullname
        if errMsg is not None:
            logger.addExpectedExact(errMsg)

        runset.restart_components(compList[:], clusterCfg, None, None, None,
                                  None, False, False, False)

    def testRestartAll(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        clusterCfg = self.__buildClusterConfig(compList, "restartAll")

        errMsg = None
        for c in compList:
            if errMsg is None:
                errMsg = "Cycling components " + c.fullname
            else:
                errMsg += ", " + c.fullname
        if errMsg is not None:
            logger.addExpectedExact(errMsg)

        runset.restart_all_components(clusterCfg, None, None, None, None,
                                      False, False, False)

    def testShortStopWithoutStart(self):
        compList = self.__buildCompList(("one", "two", "three"))
        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        compStr = "one#1, two#2, three#3"

        stopName = "ShortStop"
        logger.addExpectedExact("Stopping the run (%s)" % stopName)

        logger.addExpectedRegexp("Could not stop run .* RunSetException.*")
        logger.addExpectedExact("Failed to transition to ready: idle[%s]" %
                                compStr)
        logger.addExpectedExact("RunSet #%d (error): Could not stop idle[%s]" %
                                (runset.id, compStr))

        try:
            self.assertFalse(runset.stop_run(stopName, timeout=0),
                             "stop_run() encountered error")
            self.fail("stop_run() on new runset should throw exception")
        except Exception as ex:
            if str(ex) != "RunSet #%d is not running" % runset.id:
                raise

    def testShortStopNormal(self):
        compList = self.__buildCompList(("oneHub", "two", "three"))
        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        runset.configure()

        runNum = 100
        cluCfg = FakeCluster("foo-cluster")

        self.__add_hub_mbeans(compList)

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        self.__stopRun(runset, runNum, runConfig, cluCfg, moni_client,
                       components=compList, logger=logger)

    def testShortStopHang(self):
        compList = self.__buildCompList(("oneHub", "two", "three"))
        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        runset.configure()

        runNum = 100
        cluCfg = FakeCluster("bar-cluster")

        self.__add_hub_mbeans(compList)

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        hangType = 2
        for c in compList:
            c.setHangType(hangType)

        RunSet.TIMEOUT_SECS = 5

        self.__stopRun(runset, runNum, runConfig, cluCfg, moni_client,
                       components=compList, logger=logger, hangType=hangType)

    def testBadStop(self):
        compNames = ("firstHub", "middle", "middle", "middle", "middle", "last")
        compList = self.__buildCompList(compNames)
        runConfig = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), runConfig, compList, logger, moni_client)

        runset.configure()

        runNum = 543
        cluCfg = FakeCluster("bogusCluster")

        self.__add_hub_mbeans(compList)

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        for comp in compList:
            comp.setStopFail()

        RunSet.TIMEOUT_SECS = 5


        compStr = self.__buildCompString(compNames)

        stopName = "BadStop"
        logger.addExpectedExact("Stopping the run (%s)" % stopName)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        logger.addExpectedExact("Not logging to file so cannot queue to"
                                " SPADE")

        logger.addExpectedExact(("RunSet #1 run#%d (forcingStop):" +
                                 " Forcing 6 components to stop: %s") %
                                (runNum, compStr))
        logger.addExpectedExact("StopRun failed for " + compStr)
        logger.addExpectedExact("Failed to transition to ready: stopping[%s]" %
                                compStr)

        stopErrMsg = ("RunSet #%d run#%d (error): Could not stop" +
                      " stopping[%s]") % (runset.id, runNum, compStr)
        logger.addExpectedExact(stopErrMsg)

        self.__add_moni_run_update(runset, moni_client, runNum)

        try:
            try:
                runset.stop_run(stopName, timeout=0)
            except RunSetException as rse:
                self.assertEqual(str(rse), stopErrMsg,
                                 "Expected exception %s, not %s" %
                                 (rse, stopErrMsg))
        finally:
            pass

    def testListCompRanges(self):

        compNames = ("fooHub", "barHub", "fooHub", "fooHub", "fooHub",
                     "barHub", "barHub", "zabTrigger", "fooHub", "fooHub",
                     "barHub", "bazBuilder")

        compList = []

        nextNum = 1
        for name in compNames:
            if name.endswith("Hub"):
                num = nextNum
            else:
                num = 0
            c = MockComponent(name, num)
            c.setOrder(nextNum)
            compList.append(c)

            nextNum += 1

        compstr = ComponentManager.format_component_list(compList)

        expStr = "fooHub#1,3-5,9-10, barHub#2,6-7,11, zabTrigger, bazBuilder"
        self.assertEqual(compstr, expStr,
                         "Expected legible list \"%s\", not \"%s\"" %
                         (expStr, compstr))


if __name__ == '__main__':
    unittest.main()
