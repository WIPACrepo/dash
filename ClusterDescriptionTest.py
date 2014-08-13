#!/usr/bin/env python

import os
import tempfile
import unittest

from ClusterDescription import ClusterDescription, \
    ClusterDescriptionFormatError, XMLFormatError


class MockClusterWriter(object):
    @classmethod
    def writeLine(cls, fd, indent, name, value):
        print >>fd, "%s<%s>%s</%s>" % (indent, name, value, name)


class MockControlServer(object):
    def __init__(self):
        pass

    def isControlServer(self):
        return True

    def isSimHub(self):
        return False

    def jvm(self):
        return None

    def jvmArgs(self):
        return None

    def logLevel(self):
        return None

    def name(self):
        return "CnCServer"

    def num(self):
        return 0

    def required(self):
        return True

    def write(self, fd, indent):
        print >>fd, indent + "<controlServer/>"


class MockClusterComp(MockClusterWriter):
    def __init__(self, name, num=0, required=False, defaultJVM=None,
                 defaultJVMArgs=None, defaultLogLevel=None):
        self.__name = name
        self.__num = num
        self.__required = required

        self.__jvm = defaultJVM
        self.__jvmArgs = defaultJVMArgs
        self.__logLevel = defaultLogLevel

    def isControlServer(self):
        return False

    def isSimHub(self):
        return False

    def jvm(self):
        return self.__jvm

    def jvmArgs(self):
        return self.__jvmArgs

    def logLevel(self):
        if self.__logLevel is not None:
            return self.__logLevel

        return ClusterDescription.DEFAULT_LOG_LEVEL

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def required(self):
        return self.__required

    def setJVM(self, value):
        self.__jvm = value

    def setJVMArgs(self, value):
        self.__jvmArgs = value

    def setLogLevel(self, value):
        self.__logLevel = value

    def write(self, fd, indent):
        if self.__num == 0:
            numstr = ""
        else:
            numstr = " id=\"%d\"" % self.__num

        if not self.__required:
            reqstr = ""
        else:
            reqstr = " required=\"true\""

        multiline = self.__jvm is not None or self.__jvmArgs is not None or \
                    self.__logLevel is not None

        if multiline:
            endstr = ""
        else:
            endstr = "/"

        print >>fd, "%s<component name=\"%s\"%s%s%s>" % \
            (indent, self.__name, numstr, reqstr, endstr)

        if multiline:
            indent2 = indent + "  "

            if self.__jvm is not None:
                self.writeLine(fd, indent2, "jvm", self.__jvm)
            if self.__jvmArgs is not None:
                self.writeLine(fd, indent2, "jvmArgs", self.__jvmArgs)
            if self.__logLevel is not None:
                self.writeLine(fd, indent2, "logLevel", self.__logLevel)

            print >>fd, "%s</component>" % indent


class MockSimHubs(MockClusterWriter):
    def __init__(self, number, priority=1, ifUnused=False):
        self.__number = number
        self.__priority = priority
        self.__ifUnused = ifUnused

    def isControlServer(self):
        return False

    def isSimHub(self):
        return True

    def jvm(self):
        return None

    def jvmArgs(self):
        return None

    def logLevel(self):
        return None

    def name(self):
        return "SimHub"

    def num(self):
        return 0

    def required(self):
        return False

    def write(self, fd, indent):
        if self.__ifUnused:
            iustr = " ifUnused=\"true\""
        else:
            iustr = ""

        print >>fd, "%s<simulatedHub number=\"%d\" priority=\"%d\"%s/>" % \
            (indent, self.__number, self.__priority, iustr)


class MockClusterHost(object):
    def __init__(self, name, parent):
        self.__name = name
        self.__parent = parent
        self.__comps = None

    def __addComp(self, comp):
        if self.__comps is None:
            self.__comps = []
        self.__comps.append(comp)
        return comp

    def addComponent(self, name, num=0, required=False):
        c = MockClusterComp(name, num=num, required=required)

        return self.__addComp(c)

    def addControlServer(self):
        return self.__addComp(MockControlServer())

    def addSimHubs(self, number, priority, ifUnused=False):
        return self.__addComp(MockSimHubs(number, priority, ifUnused=ifUnused))

    def name(self):
        return self.__name

    def write(self, fd, indent):
        print >>fd, "%s<host name=\"%s\">" % (indent, self.__name)

        indent2 = indent + "  "
        if self.__comps:
            for c in self.__comps:
                c.write(fd, indent2)

        print >>fd, "%s</host>" % indent


class MockClusterConfigFile(MockClusterWriter):
    def __init__(self, configDir, name):
        self.__configDir = configDir
        self.__name = name

        self.__dataDir = None
        self.__logDir = None
        self.__spadeDir = None

        self.__defaultJVM = None
        self.__defaultJVMArgs = None
        self.__defaultLogLevel = None

        self.__defaultComps = None

        self.__hosts = {}

    def addDefaultComponent(self, comp):
        if not self.__defaultComps:
            self.__defaultComps = []

        self.__defaultComps.append(comp)

    def addHost(self, name):
        if name in self.__hosts:
            raise Exception("Host \"%s\" is already added" % name)

        h = MockClusterHost(name, self)
        self.__hosts[name] = h
        return h

    def create(self):
        path = os.path.join(self.__configDir, "%s-cluster.cfg" % self.__name)

        with open(path, 'w') as fd:
            print >>fd, "<cluster name=\"%s\">" % self.__name

            indent = "  "

            if self.__dataDir is not None:
                self.writeLine(fd, indent, "daqDataDir", self.__dataDir)
            if self.__logDir is not None:
                self.writeLine(fd, indent, "daqLogDir", self.__logDir)
            if self.__spadeDir is not None:
                self.writeLine(fd, indent, "logDirForSpade", self.__spadeDir)

            if self.__defaultJVM is not None or \
               self.__defaultJVMArgs is not None or \
               self.__defaultLogLevel is not None or \
               self.__defaultComps is not None:
                print >>fd, indent + "<default>"

                indent2 = indent + "  "

                if self.__defaultJVM is not None:
                    self.writeLine(fd, indent2, "jvm",
                                     self.__defaultJVM)
                if self.__defaultJVMArgs is not None:
                    self.writeLine(fd, indent2, "jvmArgs",
                                     self.__defaultJVMArgs)
                if self.__defaultLogLevel is not None:
                    self.writeLine(fd, indent2, "logLevel",
                                     self.__defaultLogLevel)
                if self.__defaultComps:
                    for c in self.__defaultComps:
                        c.write(fd, indent2)
                print >>fd, indent + "</default>"

            for h in self.__hosts.itervalues():
                h.write(fd, indent)

            print >>fd, "</cluster>"

    def dataDir(self):
        if self.__dataDir is None:
            return ClusterDescription.DEFAULT_DATA_DIR

        return self.__dataDir

    def defaultJVM(self):
        return self.__defaultJVM

    def defaultJVMArgs(self):
        return self.__defaultJVMArgs

    def defaultLogLevel(self):
        if self.__defaultLogLevel is None:
            return ClusterDescription.DEFAULT_LOG_LEVEL

        return self.__defaultLogLevel

    def logDir(self):
        if self.__logDir is None:
            return ClusterDescription.DEFAULT_LOG_DIR

        return self.__logDir

    def setDataDir(self, value):
        self.__dataDir = value

    def setDefaultJVM(self, value):
        self.__defaultJVM = value

    def setDefaultJVMArgs(self, value):
        self.__defaultJVMArgs = value

    def setDefaultLogLevel(self, value):
        self.__defaultLogLevel = value

    def setLogDir(self, value):
        self.__logDir = value

    def setSpadeDir(self, value):
        self.__spadeDir = value

    def spadeDir(self):
        return self.__spadeDir


class TestClusterDescription(unittest.TestCase):
    CFGDIR = None
    DEBUG = False

    def __checkComp(self, h, c, mockComps):
        mock = None
        for m in mockComps:
            if c.name() == m.name() and c.num() == m.num():
                mock = m
                break

        self.assertFalse(mock is None, "Cannot find component \"%s\"" %
                         c.name())
        self.assertEqual(mock.isControlServer(), c.isControlServer(),
                         "Expected %s ctlSrvr to be %s, not %s" %
                         (mock.name(), mock.isControlServer(),
                          c.isControlServer()))
        self.assertEqual(mock.isSimHub(), c.isSimHub(),
                         "Expected %s simHub to be %s, not %s" %
                         (mock.name(), mock.isSimHub(),
                          c.isSimHub()))
        self.assertEqual(mock.jvm(), c.jvm(),
                         "Expected %s JVM \"%s\", not \"%s\"" %
                         (mock.name(), mock.jvm(), c.jvm()))
        self.assertEqual(mock.jvmArgs(), c.jvmArgs(),
                         "Expected %s JVM args \"%s\", not \"%s\"" %
                         (mock.name(), mock.jvmArgs(), c.jvmArgs()))
        self.assertEqual(mock.logLevel(), c.logLevel(),
                         "Expected %s JVM \"%s\", not \"%s\"" %
                         (mock.name(), mock.logLevel(), c.logLevel()))
        self.assertEqual(mock.required(), c.required(),
                         "Expected %s required to be %s, not %s" %
                         (mock.name(), mock.required(), c.required()))

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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
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
        except XMLFormatError, fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
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
        except XMLFormatError, fmterr:
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
        except ClusterDescriptionFormatError, fmterr:
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
        except XMLFormatError, fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <component> node" +
                      " without \"name\" attribute") % (name, hname)
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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
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
        except XMLFormatError, fmterr:
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
        except ClusterDescriptionFormatError, fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testDefaults(self):
        name = "dflts"

        mock = MockClusterConfigFile(self.CFGDIR, name)

        dataDir = "/daq/data"
        logDir = "/daq/log"
        spadeDir = "/daq/spade"

        mock.setDataDir(dataDir)
        mock.setLogDir(logDir)
        mock.setSpadeDir(spadeDir)

        jvm = "xxxjvm"
        jvmArgs = "jvmArgs"
        logLevel = "logLvl"

        mock.setDefaultJVM(jvm)
        mock.setDefaultJVMArgs(jvmArgs)
        mock.setDefaultLogLevel(logLevel)

        acomp = MockClusterComp("a", 1, defaultJVM="abc", defaultJVMArgs="def",
                                defaultLogLevel="xyz")
        mock.addDefaultComponent(acomp)

        bcomp = MockClusterComp("b")
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

        self.assertEqual(name + "-cluster", cd.configName(),
                         "Expected cfgname \"%s-cluster\", not \"%s\"" %
                         (name, cd.configName()))

        self.assertEqual(mock.dataDir(), cd.daqDataDir(),
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.dataDir(), cd.daqDataDir()))
        self.assertEqual(mock.logDir(), cd.daqLogDir(),
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.logDir(), cd.daqLogDir()))
        self.assertEqual(mock.spadeDir(), cd.logDirForSpade(),
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spadeDir(), cd.logDirForSpade()))

        self.assertEqual(mock.defaultJVM(), cd.defaultJVM(),
                         "Expected default JVM \"%s\", not \"%s\"" %
                         (mock.defaultJVM(), cd.defaultJVM()))
        self.assertEqual(mock.defaultJVMArgs(), cd.defaultJVMArgs(),
                         "Expected default JVMArgs \"%s\", not \"%s\"" %
                         (mock.defaultJVMArgs(), cd.defaultJVMArgs()))
        self.assertEqual(mock.defaultLogLevel(), cd.defaultLogLevel(),
                         "Expected default LogLevel \"%s\", not \"%s\"" %
                         (mock.defaultLogLevel(), cd.defaultLogLevel()))

        self.assertEqual(acomp.jvm(), cd.defaultJVM(acomp.name()),
                         "Expected %s default JVM \"%s\", not \"%s\"" %
                         (acomp.name(), acomp.jvm(),
                          cd.defaultJVM(acomp.name())))
        self.assertEqual(acomp.jvmArgs(), cd.defaultJVMArgs(acomp.name()),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (acomp.name(), acomp.jvmArgs(),
                          cd.defaultJVMArgs(acomp.name())))
        self.assertEqual(acomp.logLevel(), cd.defaultLogLevel(acomp.name()),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (acomp.name(), acomp.logLevel(),
                          cd.defaultLogLevel(acomp.name())))

        self.assertEqual(mock.defaultJVM(), cd.defaultJVM(bcomp.name()),
                         "Expected %s default JVM \"%s\", not \"%s\"" %
                         (bcomp.name(), mock.defaultJVM(),
                          cd.defaultJVM(bcomp.name())))
        self.assertEqual(mock.defaultJVMArgs(), cd.defaultJVMArgs(bcomp.name()),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (bcomp.name(), mock.defaultJVMArgs(),
                          cd.defaultJVMArgs(bcomp.name())))
        self.assertEqual(mock.defaultLogLevel(),
                         cd.defaultLogLevel(bcomp.name()),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (bcomp.name(), mock.defaultLogLevel(),
                          cd.defaultLogLevel(bcomp.name())))

    def testComponents(self):
        name = "comps"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        dataDir = "/daq/data"
        logDir = "/daq/log"
        spadeDir = "/daq/spade"

        mock.setDataDir(dataDir)
        mock.setLogDir(logDir)
        mock.setSpadeDir(spadeDir)

        h1 = mock.addHost("host1")
        mockComps.append(h1.addControlServer())

        foo = h1.addComponent("foo", required=True)
        foo.setJVM("newJVM")
        foo.setJVMArgs("newArgs")
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

        self.assertEqual(mock.dataDir(), cd.daqDataDir(),
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.dataDir(), cd.daqDataDir()))
        self.assertEqual(mock.logDir(), cd.daqLogDir(),
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.logDir(), cd.daqLogDir()))
        self.assertEqual(mock.spadeDir(), cd.logDirForSpade(),
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spadeDir(), cd.logDirForSpade()))

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
        except ClusterDescriptionFormatError, fmterr:
            errmsg = ("Multiple entries for component \"%s@WARN(?)\"" +
                      " in host \"%s\"") % (comp.name(), host.name())
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
        except ClusterDescriptionFormatError, fmterr:
            errmsg = "Multiple entries for component \"%s@WARN(?)\"" % c1.name()
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testDupSimHubs(self):
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

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError, fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has multiple" +
                      " <simulatedHub> nodes") % (name, host.name())
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testAddDupSimHub(self):
        name = "dupsim"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        hname = "host1"
        host = mock.addHost(hname)
        sim = host.addSimHubs(15, 2, ifUnused=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print ":: ", line,

        cd = ClusterDescription(self.CFGDIR, name)
        h = cd.host(hname)
        try:
            h.addSimulatedHub("xxx")
        except ClusterDescriptionFormatError, fmterr:
            errmsg = "Multiple <simulatedHub> nodes for %s" % hname
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))


if __name__ == '__main__':
    unittest.main()
