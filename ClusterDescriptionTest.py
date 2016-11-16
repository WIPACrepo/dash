#!/usr/bin/env python


import os
import tempfile
import unittest

from ClusterDescription import ClusterDescription, \
    ClusterDescriptionFormatError, XMLFormatError
from DAQMocks import MockClusterConfigFile, MockCluCfgFileComp

class MockRunConfig(object):
    def __init__(self, name):
        self.__name = name

    def configName(self):
        return self.__name


class TestClusterDescription(unittest.TestCase):
    CFGDIR = None
    DEBUG = False

    def __checkComp(self, h, c, mockComps):
        mock = None
        for m in mockComps:
            if c.name == m.name and c.num == m.num:
                mock = m
                break

        self.assertFalse(mock is None, "Cannot find component \"%s\"" %
                         c.name)
        self.assertEqual(mock.isControlServer, c.isControlServer,
                         "Expected %s ctlSrvr to be %s, not %s for %s<%s>" %
                         (mock.name, mock.isControlServer,
                          c.isControlServer, c, type(c)))
        self.assertEqual(mock.isSimHub, c.isSimHub,
                         "Expected %s simHub to be %s, not %s for %s<%s>" %
                         (mock.name, mock.isSimHub, c.isSimHub, c, type(c)))
        self.assertEqual(mock.logLevel, c.logLevel,
                         "Expected %s log level \"%s\", not \"%s\" for %s<%s>" %
                         (mock.name, mock.logLevel, c.logLevel, c, type(c)))
        self.assertEqual(mock.required, c.required,
                         "Expected %s required to be %s, not %s for %s<%s>" %
                         (mock.name, mock.required, c.required, c, type(c)))
        if c.isControlServer:
            self.assertFalse(c.hasJVMOptions,
                             "Expected no JVM options for %s<%s>" %
                             (c, type(c)))
        else:
            self.assertTrue(c.hasJVMOptions,
                             "Expected JVM options for %s<%s>" %
                             (c, type(c)))
            self.assertEqual(mock.jvmExtraArgs, c.jvmExtraArgs, "Expected %s"
                             " JVM extra args \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvmExtraArgs, c.jvmExtraArgs, c,
                              type(c)))
            self.assertEqual(mock.jvmHeapInit, c.jvmHeapInit, "Expected %s"
                             " JVM heapInit \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvmHeapInit, c.jvmHeapInit, c,
                              type(c)))
            self.assertEqual(mock.jvmHeapMax, c.jvmHeapMax, "Expected %s"
                             " JVM heapMax \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvmHeapMax, c.jvmHeapMax, c,
                              type(c)))
            self.assertEqual(mock.jvmPath, c.jvmPath, "Expected %s"
                             " JVM path \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvmPath, c.jvmPath, c, type(c)))
            self.assertEqual(mock.jvmServer, c.jvmServer, "Expected %s JVM"
                             " server \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvmServer, c.jvmServer, c,
                              type(c)))

    def setUp(self):
        if self.CFGDIR is None or not os.path.isdir(self.CFGDIR):
            self.CFGDIR = tempfile.mkdtemp()

    def tearDown(self):
        pass

    def testNoClusterEnd(self):
        name = "no-cluster-end"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "%s: no element found: line 2, column 0" % path
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNoHost(self):
        name = "no-host"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\"/>" % name

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNamelessHost(self):
        name = "nameless-host"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host/>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiName(self):
        name = "multiname"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host><name>bar</name><name>bar2</name>"
            print >>fd, "    <jvm/>"
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "Multiple <name> nodes found"
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testEmptyNameNode(self):
        name = "empty-name-node"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host><name/>"
            print >>fd, "    <jvm/>"
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = '"%s" has <host> node without "name" attribute' % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiTextNode(self):
        name = "multitext"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host><name>a<x/>b</name>"
            print >>fd, "    <jvm/>"
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "Found multiple <name> text nodes"
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNoNameText(self):
        name = "no-name-text"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host><name><x/></name>"
            print >>fd, "    <jvm/>"
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testDupHosts(self):
        name = "duphosts"
        hname = "host1"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\"/>" % hname
            print >>fd, "  <host name=\"%s\"/>" % hname
            print >>fd, "</cluster>"

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple entries for host \"%s\"" % hname
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNamelessComp(self):
        name = "nameless-comp"
        hname = "hostx"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\">" % hname
            print >>fd, "    <component/>"
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <component> node" +
                      " without \"name\" attribute") % (name, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNamelessDfltComp(self):
        name = "nameless-comp"
        hname = "hostx"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <default>"
            print >>fd, "    <component/>"
            print >>fd, "  </default>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" default section has <component> node" +
                      " without \"name\" attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testBadCompId(self):
        name = "bad-comp-id"
        hname = "hostx"
        cname = "foo"
        cid = "abc"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\">" % hname
            print >>fd, "    <component name=\"%s\" id=\"%s\"/>" % (cname, cid)
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" component \"%s\" has" +
                      " bad ID \"%s\"") % (name, hname, cname, cid)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNoSimPrio(self):
        name = "no-sim-id"
        hname = "hostx"
        snum = 1

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\">" % hname
            print >>fd, "    <simulatedHub number=\"%s\"/>" % snum
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " without \"priority\" attribute") % (name, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testBadSimId(self):
        name = "bad-sim-id"
        hname = "hostx"
        snum = "abc"
        sprio = 1

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\">" % hname
            print >>fd, "    <simulatedHub number=\"%s\" priority=\"%s\"/>" % \
                (snum, sprio)
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " with bad number \"%s\"") % (name, hname, snum)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testBadSimPrio(self):
        name = "bad-sim-prio"
        hname = "hostx"
        snum = 1
        sprio = "abc"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\">" % hname
            print >>fd, "    <simulatedHub number=\"%s\" priority=\"%s\"/>" % \
                (snum, sprio)
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " with bad priority \"%s\"") % (name, hname, sprio)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testEmpty(self):
        name = "empty"

        mock = MockClusterConfigFile(self.CFGDIR, name)

        mock.create()

        try:
            cd = ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testDefaults(self):
        name = "dflts"

        dataDir = "/daq/data"
        logDir = "/daq/log"
        spadeDir = "/daq/spade"

        mock = MockClusterConfigFile(self.CFGDIR, name)
        mock.setDataDir(dataDir)
        mock.setLogDir(logDir)
        mock.setSpadeDir(spadeDir)

        hsDir = "xxxDir"
        hsInterval = 12.0
        hsMaxFiles = 111

        jvmPath = "xxxjvm"
        jvmArgs = "jvmArgs"
        jvmHeapInit = "2g"
        jvmHeapMax = "8g"
        jvmServer = False
        jvmExtraArgs = "xxxArgs"

        logLevel = "logLvl"

        mock.setDefaultHSDirectory(hsDir)
        mock.setDefaultHSInterval(hsInterval)
        mock.setDefaultHSMaxFiles(hsMaxFiles)
        mock.setDefaultJVMArgs(jvmArgs)
        mock.setDefaultJVMExtraArgs(jvmExtraArgs)
        mock.setDefaultJVMHeapInit(jvmHeapInit)
        mock.setDefaultJVMHeapMax(jvmHeapMax)
        mock.setDefaultJVMPath(jvmPath)
        mock.setDefaultJVMServer(jvmServer)
        mock.setDefaultLogLevel(logLevel)

        acomp = MockCluCfgFileComp("foo", 1, hitspoolDirectory="hsDir",
                                   hitspoolInterval=21.0, hitspoolMaxFiles=10,
                                   jvmPath="abc", jvmHeapInit="1g",
                                   jvmHeapMax="3g", jvmServer=True,
                                   jvmArgs="def", jvmExtraArgs="ghi",
                                   logLevel="xyz")
        mock.addDefaultComponent(acomp)

        bcomp = MockCluCfgFileComp("bar")
        mock.addDefaultComponent(bcomp)

        h = mock.addHost("host1")
        foo = h.addComponent("foo", required=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        cd = ClusterDescription(self.CFGDIR, name)

        if self.DEBUG:
            cd.dump()

        self.assertEqual(name + "-cluster", cd.configName,
                         "Expected cfgname \"%s-cluster\", not \"%s\"" %
                         (name, cd.configName))

        self.assertEqual(mock.dataDir, cd.daqDataDir,
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.dataDir, cd.daqDataDir))
        self.assertEqual(mock.logDir, cd.daqLogDir,
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.logDir, cd.daqLogDir))
        self.assertEqual(mock.spadeDir, cd.logDirForSpade,
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spadeDir, cd.logDirForSpade))

        self.assertEqual(mock.defaultJVMArgs(), cd.defaultJVMArgs(),
                         "Expected default JVMArgs \"%s\", not \"%s\"" %
                         (mock.defaultJVMArgs(), cd.defaultJVMArgs()))
        self.assertEqual(mock.defaultJVMExtraArgs(),
                         cd.defaultJVMExtraArgs(),
                         "Expected default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (mock.defaultJVMExtraArgs(),
                          cd.defaultJVMExtraArgs()))
        self.assertEqual(mock.defaultJVMHeapInit(), cd.defaultJVMHeapInit(),
                         "Expected default JVMHeapInit \"%s\", not \"%s\"" %
                         (mock.defaultJVMHeapInit(),
                          cd.defaultJVMHeapInit()))
        self.assertEqual(mock.defaultJVMHeapMax(), cd.defaultJVMHeapMax(),
                         "Expected default JVMHeapMax \"%s\", not \"%s\"" %
                         (mock.defaultJVMHeapMax(), cd.defaultJVMHeapMax()))
        self.assertEqual(mock.defaultJVMPath(), cd.defaultJVMPath(),
                         "Expected default JVMPath \"%s\", not \"%s\"" %
                         (mock.defaultJVMPath(), cd.defaultJVMPath()))
        self.assertEqual(mock.defaultJVMServer(), cd.defaultJVMServer(),
                         "Expected default JVMServer \"%s\", not \"%s\"" %
                         (mock.defaultJVMServer(), cd.defaultJVMServer()))
        self.assertEqual(mock.defaultLogLevel, cd.defaultLogLevel(),
                         "Expected default LogLevel \"%s\", not \"%s\"" %
                         (mock.defaultLogLevel, cd.defaultLogLevel()))

        self.assertEqual(acomp.jvmArgs, cd.defaultJVMArgs(acomp.name),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvmArgs,
                          cd.defaultJVMArgs(acomp.name)))
        self.assertEqual(acomp.jvmExtraArgs,
                         cd.defaultJVMExtraArgs(acomp.name),
                         "Expected %s default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvmExtraArgs,
                          cd.defaultJVMExtraArgs(acomp.name)))
        self.assertEqual(acomp.jvmHeapInit,
                         cd.defaultJVMHeapInit(acomp.name),
                         "Expected %s default JVMHeapInit \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvmHeapInit,
                          cd.defaultJVMHeapInit(acomp.name)))
        self.assertEqual(acomp.jvmHeapMax,
                         cd.defaultJVMHeapMax(acomp.name),
                         "Expected %s default JVMHeapMax \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvmHeapMax,
                          cd.defaultJVMHeapMax(acomp.name)))
        self.assertEqual(acomp.jvmPath, cd.defaultJVMPath(acomp.name),
                         "Expected %s default JVMPath \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvmPath,
                          cd.defaultJVMPath(acomp.name)))
        self.assertEqual(acomp.jvmServer,
                         cd.defaultJVMServer(acomp.name),
                         "Expected %s default JVMServer \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvmServer,
                          cd.defaultJVMServer(acomp.name)))
        self.assertEqual(acomp.logLevel, cd.defaultLogLevel(acomp.name),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (acomp.name, acomp.logLevel,
                          cd.defaultLogLevel(acomp.name)))

        self.assertEqual(mock.defaultJVMArgs(),
                         cd.defaultJVMArgs(bcomp.name),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (bcomp.name, mock.defaultJVMArgs(),
                          cd.defaultJVMArgs(bcomp.name)))
        self.assertEqual(mock.defaultJVMExtraArgs(),
                         cd.defaultJVMExtraArgs(bcomp.name),
                         "Expected %s default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.defaultJVMExtraArgs(),
                          cd.defaultJVMExtraArgs(bcomp.name)))
        self.assertEqual(mock.defaultJVMHeapInit(),
                         cd.defaultJVMHeapInit(bcomp.name),
                         "Expected %s default JVM HeapInit \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.defaultJVMHeapInit(),
                          cd.defaultJVMHeapInit(bcomp.name)))
        self.assertEqual(mock.defaultJVMHeapMax(),
                         cd.defaultJVMHeapMax(bcomp.name),
                         "Expected %s default JVM HeapMax \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.defaultJVMHeapMax(),
                          cd.defaultJVMHeapMax(bcomp.name)))
        self.assertEqual(mock.defaultJVMPath(),
                         cd.defaultJVMPath(bcomp.name),
                         "Expected %s default JVMPath \"%s\", not \"%s\"" %
                         (bcomp.name, mock.defaultJVMPath(),
                          cd.defaultJVMPath(bcomp.name)))
        self.assertEqual(mock.defaultJVMServer(),
                         cd.defaultJVMServer(bcomp.name),
                         "Expected %s default JVMServer \"%s\", not \"%s\"" %
                         (bcomp.name, mock.defaultJVMServer(),
                          cd.defaultJVMServer(bcomp.name)))
        self.assertEqual(mock.defaultLogLevel,
                         cd.defaultLogLevel(bcomp.name),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (bcomp.name, mock.defaultLogLevel,
                          cd.defaultLogLevel(bcomp.name)))

    def testDefaultInheritance(self):
        name = "compdflts"

        dataDir = "/daq/data"
        logDir = "/daq/log"
        spadeDir = "/daq/spade"

        dfltHSDir = "xxxHSDir"
        dfltInterval = 99.0
        dfltMaxFiles = 99

        dfltPath = "xxxjvm"
        dfltHeapInit = "2g"
        dfltHeapMax = "8g"
        dfltServer = False
        dfltArgs = "jvmArgs"
        dfltExtra = "jvmExtra"

        dfltLogLvl = "logLvl"

        numFields = 10

        (FLD_PATH, FLD_HEAP_INIT, FLD_HEAP_MAX, FLD_SERVER, FLD_JVMARGS,
         FLD_EXTRAARGS, FLD_LOGLVL, FLD_HSDIR, FLD_HSIVAL, FLD_HSMAX) \
         = range(numFields)

        for i in range(numFields):
            if self.DEBUG:
                print  "########## I %d" % i

            # create a cluster config file
            mock = MockClusterConfigFile(self.CFGDIR, name)
            mock.setDataDir(dataDir)
            mock.setLogDir(logDir)
            mock.setSpadeDir(spadeDir)

            # set hitspool defaults
            mock.setDefaultHSDirectory(dfltHSDir)
            mock.setDefaultHSInterval(dfltInterval)
            mock.setDefaultHSMaxFiles(dfltMaxFiles)

            # set JVM defaults
            mock.setDefaultJVMArgs(dfltArgs)
            mock.setDefaultJVMExtraArgs(dfltExtra)
            mock.setDefaultJVMHeapInit(dfltHeapInit)
            mock.setDefaultJVMHeapMax(dfltHeapMax)
            mock.setDefaultJVMPath(dfltPath)
            mock.setDefaultJVMServer(dfltServer)

            # set log level defaults
            mock.setDefaultLogLevel(dfltLogLvl)

            # add host
            hostname = "someHost"
            h = mock.addHost(hostname)

            # temporary values will be used to set up
            # component-specific default values
            (tmpHsDir, tmpIval, tmpMaxF, tmpPath, tmpHInit, tmpHMax,
             tmpServer, tmpArgs, tmpExtra, tmpLogLvl) = \
                (None, ) * numFields

            # set component-level defaults
            plainName = "foo"
            if i == FLD_PATH:
                plainPath = "plainPath"
                tmpPath = plainPath
            else:
                plainPath = dfltPath
            if i == FLD_HEAP_INIT:
                plainHeapInit = "1g"
                tmpHInit = plainHeapInit
            else:
                plainHeapInit = dfltHeapInit
            if i == FLD_HEAP_MAX:
                plainHeapMax = "3g"
                tmpHMax = plainHeapMax
            else:
                plainHeapMax = dfltHeapMax
            if i == FLD_SERVER:
                plainServer = not dfltServer
                tmpServer = plainServer
            else:
                plainServer = dfltServer == True
            if i == FLD_JVMARGS:
                plainArgs = "plainArgs"
                tmpArgs = plainArgs
            else:
                plainArgs = dfltArgs
            if i == FLD_EXTRAARGS:
                plainExtra = "plainExtra"
                tmpExtra = plainExtra
            else:
                plainExtra = dfltExtra
            if i == FLD_LOGLVL:
                plainLogLvl = "plainLvl"
                tmpLogLvl = plainLogLvl
            else:
                plainLogLvl = dfltLogLvl
            if i == FLD_HSDIR:
                plainHSDir = "plainDir"
                tmpHsDir = plainHSDir
            else:
                plainHSDir = dfltHSDir
            if i == FLD_HSIVAL:
                plainIval = dfltInterval + 1.1
                tmpIval = plainIval
            else:
                plainIval = dfltInterval
            if i == FLD_HSMAX:
                plainMaxF = dfltMaxFiles + 1
                tmpMaxF = plainMaxF
            else:
                plainMaxF = dfltMaxFiles

            # add component-specific default (only one value will be active)
            acomp = MockCluCfgFileComp(plainName, 0,
                                       hitspoolDirectory=tmpHsDir,
                                       hitspoolInterval=tmpIval,
                                       hitspoolMaxFiles=tmpMaxF,
                                       jvmPath=tmpPath,
                                       jvmHeapInit=tmpHInit,
                                       jvmHeapMax=tmpHMax,
                                       jvmServer=tmpServer,
                                       jvmArgs=tmpArgs, jvmExtraArgs=tmpExtra,
                                       logLevel=tmpLogLvl)
            mock.addDefaultComponent(acomp)

            # add unaltered component
            foo = h.addComponent(plainName, required=True)

            # add a component which will override a single value
            instName = "bar"
            bar = h.addComponent(instName, required=True)

            j = (i + 1) % numFields
            if self.DEBUG:
                print  "########## J %d" % j

            if j == FLD_PATH:
                instPath = "instPath"
                bar.setJVMPath(instPath)
            else:
                instPath = dfltPath
            if j == FLD_HEAP_INIT:
                instHeapInit = "instInit"
                bar.setJVMHeapInit(instHeapInit)
            else:
                instHeapInit = dfltHeapInit
            if j == FLD_HEAP_MAX:
                instHeapMax = "instMax"
                bar.setJVMHeapMax(instHeapMax)
            else:
                instHeapMax = dfltHeapMax
            if j == FLD_SERVER:
                instServer = not dfltServer
                bar.setJVMServer(instServer)
            else:
                instServer = dfltServer == True
            if j == FLD_JVMARGS:
                instArgs = "instArgs"
                bar.setJVMArgs(instArgs)
            else:
                instArgs = dfltArgs
            if j == FLD_EXTRAARGS:
                instExtra = "instExtra"
                bar.setJVMExtraArgs(instExtra)
            else:
                instExtra = dfltExtra
            if j == FLD_LOGLVL:
                instLogLvl = "instLvl"
                bar.setLogLevel(instLogLvl)
            else:
                instLogLvl = dfltLogLvl
            if j == FLD_HSDIR:
                instHSDir = "instHSDir"
                bar.setHitspoolDirectory(instHSDir)
            else:
                instHSDir = dfltHSDir
            if j == FLD_HSIVAL:
                instIval = dfltInterval + 2.2
                bar.setHitspoolInterval(instIval)
            else:
                instIval = dfltInterval
            if j == FLD_HSMAX:
                instMaxF = dfltMaxFiles + 2
                bar.setHitspoolMaxFiles(instMaxF)
            else:
                instMaxF = dfltMaxFiles

            # create file
            mock.create()

            if self.DEBUG:
                with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                    print  ":::::::::: %s-cluster.cfg" % name
                    for line in fd:
                        print ":: ", line,

            cd = ClusterDescription(self.CFGDIR, name)

            if self.DEBUG:
                cd.dump()

            self.assertEqual(name + "-cluster", cd.configName,
                             "Expected cfgname \"%s-cluster\", not \"%s\"" %
                             (name, cd.configName))

            self.assertEqual(dataDir, cd.daqDataDir,
                             "Expected data dir \"%s\", not \"%s\"" %
                             (dataDir, cd.daqDataDir))
            self.assertEqual(logDir, cd.daqLogDir,
                             "Expected log dir \"%s\", not \"%s\"" %
                             (logDir, cd.daqLogDir))
            self.assertEqual(spadeDir, cd.logDirForSpade,
                             "Expected SPADE dir \"%s\", not \"%s\"" %
                             (spadeDir, cd.logDirForSpade))

            self.assertEqual(dfltHSDir, cd.defaultHSDirectory(),
                             "Expected default HS directory \"%s\","
                             " not \"%s\"" %
                             (dfltHSDir, cd.defaultHSDirectory()))
            self.assertEqual(dfltInterval, cd.defaultHSInterval(),
                             "Expected default HS interval \"%s\","
                             " not \"%s\"" %
                             (dfltInterval, cd.defaultHSInterval()))
            self.assertEqual(dfltMaxFiles, cd.defaultHSMaxFiles(),
                             "Expected default HS maximum files \"%s\","
                             " not \"%s\"" %
                             (dfltMaxFiles, cd.defaultHSMaxFiles()))

            self.assertEqual(dfltArgs, cd.defaultJVMArgs(),
                             "Expected default JVMArgs \"%s\", not \"%s\"" %
                             (dfltArgs, cd.defaultJVMArgs()))
            self.assertEqual(dfltExtra, cd.defaultJVMExtraArgs(),
                             "Expected default JVMExtraArgs \"%s\","
                             " not \"%s\"" %
                             (dfltExtra, cd.defaultJVMExtraArgs()))
            self.assertEqual(dfltHeapInit, cd.defaultJVMHeapInit(),
                             "Expected default JVMHeapInit \"%s\", not \"%s\"" %
                             (dfltHeapInit, cd.defaultJVMHeapInit()))
            self.assertEqual(dfltHeapMax, cd.defaultJVMHeapMax(),
                             "Expected default JVMHeapMax \"%s\", not \"%s\"" %
                             (dfltHeapMax, cd.defaultJVMHeapMax()))
            self.assertEqual(dfltPath, cd.defaultJVMPath(),
                             "Expected default JVMPath \"%s\", not \"%s\"" %
                             (dfltPath, cd.defaultJVMPath()))
            self.assertEqual(dfltServer, cd.defaultJVMServer(),
                             "Expected default JVMServer \"%s\", not \"%s\"" %
                             (dfltServer, cd.defaultJVMServer()))

            self.assertEqual(dfltLogLvl, cd.defaultLogLevel(),
                             "Expected default LogLevel \"%s\", not \"%s\"" %
                             (dfltLogLvl, cd.defaultLogLevel()))

            for comp in cd.host(hostname).getComponents():
                if comp.name == plainName:
                    (hsDir, hsIval, hsMaxF, args, extra, heapInit, heapMax,
                     path, server, logLevel) \
                     = (plainHSDir, plainIval, plainMaxF, plainArgs,
                        plainExtra, plainHeapInit, plainHeapMax, plainPath,
                        plainServer, plainLogLvl)
                else:
                    (hsDir, hsIval, hsMaxF, args, extra, heapInit, heapMax,
                     path, server, logLevel) \
                     = (instHSDir, instIval, instMaxF, instArgs, instExtra,
                        instHeapInit, instHeapMax, instPath, instServer,
                        instLogLvl)

                hasJVMOptions = args is not None and \
                                extra is not None and \
                                heapInit is not None and \
                                heapMax is not None and \
                                path is not None

                self.assertEqual(hasJVMOptions, comp.hasJVMOptions,
                                 "Expected %s<%s> hasJVMOptions %s, not %s" %
                                 (comp.name, type(comp), hasJVMOptions,
                                  comp.hasJVMOptions))
                if comp.hasJVMOptions:
                    self.assertEqual(args, comp.jvmArgs,
                                     "Expected %s<%s> JVMArgs \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), args,
                                      comp.jvmArgs))
                    self.assertEqual(extra, comp.jvmExtraArgs,
                                     "Expected %s<%s> JVMExtra \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), extra,
                                      comp.jvmExtraArgs))
                    self.assertEqual(heapInit, comp.jvmHeapInit,
                                     "Expected %s<%s> JVMHeapInit \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), heapInit,
                                      comp.jvmHeapInit))
                    self.assertEqual(heapMax, comp.jvmHeapMax,
                                     "Expected %s<%s> JVMHeapMax \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), heapMax,
                                      comp.jvmHeapMax))
                    self.assertEqual(path, comp.jvmPath, "Expected %s<%s>"
                                     " JVMPath \"%s\", not \"%s\"" %
                                     (comp.name, type(comp), path,
                                      comp.jvmPath))
                    self.assertEqual(server, comp.jvmServer, "Expected %s<%s>"
                                     " JVMServer \"%s\", not \"%s\"" %
                                     (comp.name, type(comp), server,
                                      comp.jvmServer))
                    self.assertEqual(logLevel, comp.logLevel, "Expected %s<%s>"
                                     " LogLevel \"%s\", not \"%s\"" %
                                     (comp.name, type(comp), logLevel,
                                      comp.logLevel))

                if comp.isRealHub:
                    self.assertEqual(hsDir, comp.hitspoolDirectory,
                                     "Expected %s<%s> HS directory \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hsDir,
                                      comp.hitspoolDirectory))
                    self.assertEqual(hsIval, comp.hitspoolInterval,
                                     "Expected %s<%s> HS interval \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hsIval,
                                      comp.hitspoolInterval))
                    self.assertEqual(hsMaxF, comp.hitspoolMaxFiles,
                                     "Expected %s<%s> HS max files \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hsMaxF,
                                      comp.hitspoolMaxFiles))

    def testComponents(self):
        name = "comps"

        dataDir = "/daq/data"
        logDir = "/daq/log"
        spadeDir = "/daq/spade"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        mock.setDataDir(dataDir)
        mock.setLogDir(logDir)
        mock.setSpadeDir(spadeDir)

        h1 = mock.addHost("host1")
        mockComps.append(h1.addControlServer())

        foo = h1.addComponent("foo", required=True)
        foo.setJVMPath("newJVM")
        foo.setJVMArgs("newArgs")
        foo.setJVMExtraArgs("newExtra")
        foo.setJVMHeapInit("newInit")
        foo.setJVMHeapMax("newMax")
        foo.setJVMServer(False)
        foo.setLogLevel("logLvl")
        mockComps.append(foo)

        bar = h1.addComponent("bar", 123)
        mockComps.append(bar)

        numSim = 15
        prioSim = 2

        sim = h1.addSimHubs(numSim, prioSim, ifUnused=True)
        mockComps.append(sim)

        h2 = mock.addHost("host2")
        sim = h2.addSimHubs(numSim, prioSim)
        mockComps.append(sim)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        cd = ClusterDescription(self.CFGDIR, name)

        if self.DEBUG:
            cd.dump()

        self.assertEqual(mock.dataDir, cd.daqDataDir,
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.dataDir, cd.daqDataDir))
        self.assertEqual(mock.logDir, cd.daqLogDir,
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.logDir, cd.daqLogDir))
        self.assertEqual(mock.spadeDir, cd.logDirForSpade,
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spadeDir, cd.logDirForSpade))

        for h, c in cd.listHostComponentPairs():
            self.__checkComp(h, c, mockComps)
        for h, c in cd.listHostSimHubPairs():
            self.__checkComp(h, c, mockComps)
            self.assertEqual(numSim, c.number,
                             "Expected simHub number %s, not %s" %
                             (numSim, c.number))
            self.assertEqual(prioSim, c.priority,
                             "Expected simHub priority %s, not %s" %
                             (prioSim, c.priority))

    def testDupComponents(self):
        name = "dupcomps"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        host = mock.addHost("host1")
        comp = host.addComponent("foo")
        host.addComponent("foo")

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = ("Multiple entries for component \"%s\""
                      " in host \"%s\"") % (comp.name, host.name)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiHostComponents(self):
        name = "multihost-comps"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        h1 = mock.addHost("host1")
        c1 = h1.addComponent("foo")

        h2 = mock.addHost("host2")
        c2 = h2.addComponent("foo")

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple entries for component \"%s\"" % \
                     c1.name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testDupSimHubs(self):
        """duplicate simHub lines at different priorities are allowed"""
        name = "dupsim"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        host = mock.addHost("host1")
        sim = host.addSimHubs(15, 2, ifUnused=True)
        host.addSimHubs(10, 1)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        ClusterDescription(self.CFGDIR, name)

    def testAddDupPrio(self):
        """duplicate simHub lines at the same priority are not valid"""
        name = "dupprio"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        hname = "host1"
        host = mock.addHost(hname)

        prio = 2
        sim = host.addSimHubs(15, prio, ifUnused=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        cd = ClusterDescription(self.CFGDIR, name)
        h = cd.host(hname)
        try:
            h.addSimulatedHub(7, prio, False)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple <simulatedHub> nodes at prio %d for %s" % \
                     (prio, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiJVM(self):
        name = "multiJVM"

        hostname = "foo"
        compName = "fooComp"
        args = None
        extra = None
        heapInit = "2g"
        heapMax = "4g"
        path = None
        server = False

        cluPath = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(cluPath, "w") as fd:
            print >>fd, "<cluster name=\"%s\">" % name
            print >>fd, "  <host name=\"%s\">" % hostname
            print >>fd, "    <component name=\"%s\">" % compName
            print >>fd, "      <jvm heapInit=\"xxx\"/>"
            print >>fd, "      <jvm heapInit=\"%s\"/>" % heapInit
            print >>fd, "      <jvm heapMax=\"%s\"/>" % heapMax
            print >>fd, "    </component>"
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

        cd = ClusterDescription(self.CFGDIR, name)

        for comp in cd.host(hostname).getComponents():
            self.assertEqual(args, comp.jvmArgs,
                             "Expected %s JVMArgs \"%s\", not \"%s\"" %
                             (comp.name, args, comp.jvmArgs))
            self.assertEqual(extra, comp.jvmExtraArgs,
                             "Expected %s JVMExtra \"%s\", not \"%s\"" %
                             (comp.name, extra, comp.jvmExtraArgs))
            self.assertEqual(heapInit, comp.jvmHeapInit,
                             "Expected %s JVMHeapInit \"%s\", not \"%s\"" %
                             (comp.name, heapInit, comp.jvmHeapInit))
            self.assertEqual(heapMax, comp.jvmHeapMax,
                             "Expected %s JVMHeapMax \"%s\", not \"%s\"" %
                             (comp.name, heapMax, comp.jvmHeapMax))
            self.assertEqual(path, comp.jvmPath,
                             "Expected %s JVMPath \"%s\", not \"%s\"" %
                             (comp.name, path, comp.jvmPath))
            self.assertEqual(server, comp.jvmServer,
                             "Expected %s JVMServer \"%s\", not \"%s\"" %
                             (comp.name, server, comp.jvmServer))

if __name__ == '__main__':
    unittest.main()
