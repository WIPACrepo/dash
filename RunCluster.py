#!/usr/bin/env python

import os
import os.path
import sys
import traceback

from CachedConfigName import CachedConfigName
from ClusterDescription import ClusterDescription, JVMArgs
from Component import Component
from DefaultDomGeometry import DefaultDomGeometry


class RunClusterError(Exception):
    pass


class RunComponent(Component):
    def __init__(self, name, compid, logLevel, jvmPath, jvmServer, jvmHeapInit,
                 jvmHeapMax, jvmArgs, jvmExtra, host, isCtlServer):
        self.__jvm = JVMArgs(jvmPath, jvmServer, jvmHeapInit, jvmHeapMax,
                             jvmArgs, jvmExtra)
        self.__isCtlServer = isCtlServer

        super(RunComponent, self).__init__(name, compid, logLevel=logLevel,
                                           host=host)

    def __str__(self):
        nStr = self.fullName()

        return "%s@%s(%s)" % (nStr, str(self.logLevel()), self.__jvm)

    def isControlServer(self):
        return self.__isCtlServer

    def jvmArgs(self):
        return self.__jvm.args()

    def jvmExtraArgs(self):
        return self.__jvm.extraArgs()

    def jvmHeapInit(self):
        return self.__jvm.heapInit()

    def jvmHeapMax(self):
        return self.__jvm.heapMax()

    def jvmPath(self):
        return self.__jvm.path()

    def jvmServer(self):
        return self.__jvm.isServer()


class RunNode(object):
    def __init__(self, hostName, defaultLogLevel, defaultJVMPath,
                 defaultJVMServer, defaultJVMHeapInit, defaultJVMHeapMax,
                 defaultJVMArgs, defaultJVMExtraArgs):
        self.__locName = hostName
        self.__hostName = hostName
        self.__defaultLogLevel = defaultLogLevel
        self.__defaultJVM = JVMArgs(defaultJVMPath, defaultJVMServer,
                                    defaultJVMHeapInit, defaultJVMHeapMax,
                                    defaultJVMArgs, defaultJVMExtraArgs)
        self.__comps = []

    def __cmp__(self, other):
        val = cmp(self.__hostName, other.__hostName)
        if val == 0:
            val = cmp(self.__locName, other.__locName)
        return val

    def __str__(self):
        return "%s(%s)*%d" % (self.__hostName, self.__defaultLogLevel,
                              len(self.__comps))

    def addComponent(self, comp):
        if comp.logLevel() is not None:
            logLvl = comp.logLevel()
        else:
            logLvl = self.__defaultLogLevel
        if comp.jvmPath() is not None or comp.isControlServer():
            jvmPath = comp.jvmPath()
        else:
            jvmPath = self.__defaultJVM.path()
        if comp.jvmServer() is not None or comp.isControlServer():
            jvmServer = comp.jvmServer()
        else:
            jvmServer = self.__defaultJVM.isServer()
        if comp.jvmHeapInit() is not None or comp.isControlServer():
            jvmHeapInit = comp.jvmHeapInit()
        else:
            jvmHeapInit = self.__defaultJVM.heapInit()
        if comp.jvmHeapMax() is not None or comp.isControlServer():
            jvmHeapMax = comp.jvmHeapMax()
        else:
            jvmHeapMax = self.__defaultJVM.heapMax()
        if comp.jvmArgs() is not None or comp.isControlServer():
            jvmArgs = comp.jvmArgs()
        else:
            jvmArgs = self.__defaultJVM.args()
        if comp.jvmExtraArgs() is not None or comp.isControlServer():
            jvmExtra = comp.jvmExtraArgs()
        else:
            jvmExtra = self.__defaultJVM.extraArgs()
        self.__comps.append(RunComponent(comp.name(), comp.id(), logLvl,
                                         jvmPath, jvmServer, jvmHeapInit,
                                         jvmHeapMax, jvmArgs, jvmExtra,
                                         self.__hostName,
                                         comp.isControlServer()))

    def components(self):
        return self.__comps[:]

    def defaultLogLevel(self):
        return self.__defaultLogLevel

    def hostName(self):
        return self.__hostName

    def locName(self):
        return self.__locName


class SimAlloc(object):
    "Temporary class used to assign simHubs to hosts"
    def __init__(self, host, num):
        self.host = host
        self.number = num
        self.percent = 0.0
        self.allocated = 0

    def __str__(self):
        return "%s#%d%%.2f=%d" % (self.host, self.number, self.percent,
                                  self.allocated)


class RunCluster(CachedConfigName):
    "Cluster->component mapping generated from a run configuration file"
    def __init__(self, cfg, descrName=None, configDir=None):
        "Create a cluster->component mapping from a run configuration file"
        super(RunCluster, self).__init__()

        name = os.path.basename(cfg.configFile())
        if name.endswith('.xml'):
            name = name[:-4]
        self.setConfigName(name)

        self.__hubList = self.__extractHubs(cfg)

        self.__clusterDesc = ClusterDescription(configDir, descrName)

        self.__nodes = self.__loadConfig(self.__clusterDesc, self.__hubList)

    def __str__(self):
        nodeStr = ""
        for n in self.__nodes:
            if len(nodeStr) > 0:
                nodeStr += " "
            nodeStr += "%s*%d" % (n.hostName(), len(n.components()))
        return self.configName() + "[" + nodeStr + "]"

    @classmethod
    def __addComponent(cls, hostMap, host, comp):
        "Add a component to the hostMap dictionary"
        if not host in hostMap:
            hostMap[host] = {}
        hostMap[host][str(comp)] = comp

    @classmethod
    def __addRealHubs(cls, clusterDesc, hubList, hostMap):
        "Add hubs with hard-coded locations to hostMap"
        for (host, comp) in clusterDesc.listHostComponentPairs():
            if not comp.isHub():
                continue
            for h in range(0, len(hubList)):
                if comp.id() == hubList[h].id():
                    cls.__addComponent(hostMap, host, comp)
                    del hubList[h]
                    break

    @classmethod
    def __addReplayHubs(cls, clusterDesc, hubList, hostMap):
        "Add replay hubs with locations hard-coded in the run config to hostMap"

        logLevel = clusterDesc.defaultLogLevel("StringHub")
        jvmPath = clusterDesc.defaultJVMPath("StringHub")
        jvmServer = clusterDesc.defaultJVMServer("StringHub")
        jvmHeapInit = clusterDesc.defaultJVMHeapInit("StringHub")
        jvmHeapMax = clusterDesc.defaultJVMHeapMax("StringHub")
        jvmArgs = clusterDesc.defaultJVMArgs("StringHub")
        jvmExtra = clusterDesc.defaultJVMExtraArgs("StringHub")

        i = 0
        while i < len(hubList):
            hub = hubList[i]
            if hub.host() is None:
                i += 1
                continue

            if hub.logLevel() is not None:
                lvl = hub.logLevel()
            else:
                lvl = logLevel
            comp = RunComponent(hub.name(), hub.id(), lvl, jvmPath, jvmServer,
                                jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra,
                                hub.host(), False)
            cls.__addComponent(hostMap, hub.host(), comp)
            del hubList[i]

    @classmethod
    def __addRequired(cls, clusterDesc, hostMap):
        "Add required components to hostMap"
        for (host, comp) in clusterDesc.listHostComponentPairs():
            if comp.required():
                cls.__addComponent(hostMap, host, comp)

    @classmethod
    def __cmpAlloc(cls, a, b):
        val = cmp(a.allocated, b.allocated)
        if val == 0:
            val = cmp(b.host, a.host)

        return val

    @classmethod
    def __addSimHubs(cls, clusterDesc, hubList, hostMap):
        "Add simulated hubs to hostMap"
        simList = cls.__getSortedSimHubs(clusterDesc, hostMap)
        if len(simList) == 0:
            missing = []
            for hub in hubList:
                missing.append(str(hub))
            raise RunClusterError("Cannot simulate %s hubs %s" %
                                  (clusterDesc.name, str(missing)))

        hubAlloc = {}
        maxHubs = 0
        pctTot = 0.0
        for sim in simList:
            if not hubAlloc.has_key(sim.host):
                hubAlloc[sim.host] = SimAlloc(sim.host, sim.number)
            else:
                # add to the maximum number of hubs for this host
                hubAlloc[sim.host].number += sim.number
            maxHubs += sim.number

            pct = (10.0 / float(sim.priority)) * float(sim.number)
            hubAlloc[sim.host].percent += pct
            pctTot += pct

        # make sure there's enough room for the requested hubs
        numHubs = len(hubList)
        if numHubs > maxHubs:
            raise RunClusterError("Only have space for %d of %d hubs" %
                                  (maxHubs, numHubs))

        # first stab at allocation: allocate based on percentage
        tot = 0
        for v in hubAlloc.values():
            v.percent /= pctTot
            v.allocated = int(v.percent * numHubs)
            if v.allocated > v.number:
                # if we overallocated based on the percentage,
                #  adjust down to the maximum number
                v.allocated = v.number
            tot += v.allocated

        # allocate remainder in order of total capacity
        while tot < numHubs:
            changed = False
            for v in sorted(hubAlloc.values(), reverse=True,
                            cmp=cls.__cmpAlloc):
                if v.allocated >= v.number:
                    continue

                v.allocated += 1
                tot += 1
                changed = True
                if tot >= numHubs:
                    break

            if tot < numHubs and not changed:
                raise RunClusterError("Only able to allocate %d of %d hubs" %
                                      (tot, numHubs))

        hubList.sort()

        hosts = []
        for v in sorted(hubAlloc.values(), reverse=True, cmp=cls.__cmpAlloc):
            hosts.append(v.host)

        logLevel = clusterDesc.defaultLogLevel("StringHub")
        jvmPath = clusterDesc.defaultJVMPath("StringHub")
        jvmServer = clusterDesc.defaultJVMServer("StringHub")
        jvmHeapInit = clusterDesc.defaultJVMHeapInit("StringHub")
        jvmHeapMax = clusterDesc.defaultJVMHeapMax("StringHub")
        jvmArgs = clusterDesc.defaultJVMArgs("StringHub")
        jvmExtra = clusterDesc.defaultJVMExtraArgs("StringHub")

        hubNum = 0
        for host in hosts:
            for _ in xrange(hubAlloc[host].allocated):
                hubComp = hubList[hubNum]
                if hubComp.logLevel() is not None:
                    lvl = hubComp.logLevel()
                else:
                    lvl = logLevel

                comp = RunComponent(hubComp.name(), hubComp.id(), lvl, jvmPath,
                                    jvmServer, jvmHeapInit, jvmHeapMax,
                                    jvmArgs, jvmExtra, host, False)
                cls.__addComponent(hostMap, host, comp)
                hubNum += 1

    @classmethod
    def __addTriggers(cls, clusterDesc, hubList, hostMap):
        "Add needed triggers to hostMap"
        needAmanda = False
        needInice = False
        needIcetop = False

        for hub in hubList:
            hid = hub.id() % 1000
            if hid == 0:
                needAmanda = True
            elif hid < 200:
                needInice = True
            else:
                needIcetop = True

        for (host, comp) in clusterDesc.listHostComponentPairs():
            if not comp.name().endswith('Trigger'):
                continue
            if comp.name() == 'amandaTrigger' and needAmanda:
                cls.__addComponent(hostMap, host, comp)
                needAmanda = False
            elif comp.name() == 'inIceTrigger' and needInice:
                cls.__addComponent(hostMap, host, comp)
                needInice = False
            elif comp.name() == 'iceTopTrigger' and needIcetop:
                cls.__addComponent(hostMap, host, comp)
                needIcetop = False

    @classmethod
    def __convertToNodes(cls, clusterDesc, hostMap):
        "Convert hostMap to an array of cluster nodes"
        hostKeys = hostMap.keys()
        hostKeys.sort()

        nodes = []
        for host in hostKeys:
            node = RunNode(str(host), clusterDesc.defaultLogLevel(),
                           clusterDesc.defaultJVMPath(),
                           clusterDesc.defaultJVMServer(),
                           clusterDesc.defaultJVMHeapInit(),
                           clusterDesc.defaultJVMHeapMax(),
                           clusterDesc.defaultJVMArgs(),
                           clusterDesc.defaultJVMExtraArgs())
            nodes.append(node)

            for compKey in hostMap[host].keys():
                node.addComponent(hostMap[host][compKey])

        return nodes

    @classmethod
    def __extractHubs(cls, cfg):
        "build a list of hub components used by the run configuration"
        hubList = []
        for comp in cfg.components():
            if comp.isHub():
                hubList.append(comp)
        return hubList

    @classmethod
    def __getSortedSimHubs(cls, clusterDesc, hostMap):
        "Get list of simulation hubs, sorted by priority"
        simList = []

        for (_, simHub) in clusterDesc.listHostSimHubPairs():
            if simHub is None:
                continue
            if not simHub.ifUnused or not simHub.host.name in hostMap:
                simList.append(simHub)

        simList.sort(cls.__sortByPriority)

        return simList

    @classmethod
    def __loadConfig(cls, clusterDesc, hubList):
        hostMap = {}

        cls.__addRequired(clusterDesc, hostMap)
        cls.__addTriggers(clusterDesc, hubList, hostMap)
        if len(hubList) > 0:
            cls.__addRealHubs(clusterDesc, hubList, hostMap)
            if len(hubList) > 0:
                cls.__addReplayHubs(clusterDesc, hubList, hostMap)
                if len(hubList) > 0:
                    cls.__addSimHubs(clusterDesc, hubList, hostMap)

        return cls.__convertToNodes(clusterDesc, hostMap)

    @staticmethod
    def __sortByPriority(x, y):
        "Sort simulated hub nodes by priority"
        val = cmp(x.priority, y.priority)
        if val == 0:
            val = cmp(x.host.name, y.host.name)
        return val

    def daqDataDir(self):
        return self.__clusterDesc.daqDataDir()

    def daqLogDir(self):
        return self.__clusterDesc.daqLogDir()

    def defaultLogLevel(self):
        return self.__clusterDesc.defaultLogLevel()

    def descName(self):
        return self.__clusterDesc.configName()

    def extractComponents(self, masterList):
        return self.extractComponentsFromNodes(self.__nodes, masterList)

    @classmethod
    def extractComponentsFromNodes(cls, nodeList, masterList):
        foundList = []
        missingList = []
        for comp in masterList:
            found = False
            for node in nodeList:
                for nodeComp in node.components():
                    if comp.name().lower() == nodeComp.name().lower() \
                       and comp.num() == nodeComp.id():
                        foundList.append(nodeComp)
                        found = True
                        break
                if found:
                    break
            if not found:
                missingList.append(comp)
        return (foundList, missingList)

    def getConfigName(self):
        "get the configuration name to write to the cache file"
        if self.__clusterDesc is None:
            return self.configName()
        return '%s@%s' % (self.configName(), self.__clusterDesc.configName())

    def getHubNodes(self):
        "Get a list of nodes on which hub components are running"
        hostMap = {}
        for node in self.__nodes:
            addHost = False
            for comp in node.components():
                if comp.isHub():
                    addHost = True
                    break

            if addHost:
                hostMap[node.hostName()] = 1

        return hostMap.keys()

    def loadIfChanged(self):
        if not self.__clusterDesc.loadIfChanged():
            return False

        self.__nodes = self.__loadConfig(self.__clusterDesc, self.__hubList)

    def logDirForSpade(self):
        return self.__clusterDesc.logDirForSpade()

    def logDirCopies(self):
        return self.__clusterDesc.logDirCopies()

    def nodes(self):
        return self.__nodes[:]

if __name__ == '__main__':
    from DAQConfig import DAQConfigParser
    from locate_pdaq import find_pdaq_config

    if len(sys.argv) <= 1:
        print >> sys.stderr, ('Usage: %s [-C clusterDesc]' +
                              ' configXML [configXML ...]') % sys.argv[0]
        sys.exit(1)

    configDir = find_pdaq_config()

    nameList = []
    grabDesc = False
    clusterDesc = None

    for name in sys.argv[1:]:
        if grabDesc:
            clusterDesc = name
            grabDesc = False
            continue

        if name.startswith('-C'):
            if clusterDesc is not None:
                raise Exception("Cannot specify multiple cluster descriptions")
            if len(name) > 2:
                clusterDesc = name[2:]
            else:
                grabDesc = True
            continue

        if os.path.basename(name) == DefaultDomGeometry.FILENAME:
            # ignore
            continue

        nameList.append(name)

    for name in nameList:
        cfg = DAQConfigParser.load(name, configDir)
        try:
            runCluster = RunCluster(cfg, clusterDesc)
        except NotImplementedError:
            print >> sys.stderr, 'For %s:' % name
            traceback.print_exc()
            continue
        except KeyboardInterrupt:
            break
        except:
            print >> sys.stderr, 'For %s:' % name
            traceback.print_exc()
            continue

        print 'RunCluster: %s (%s)' % \
            (runCluster.configName(), runCluster.descName())
        print '--------------------'
        if runCluster.logDirForSpade() is not None:
            print 'SPADE logDir: %s' % runCluster.logDirForSpade()
        if runCluster.logDirCopies() is not None:
            print 'Copied logDir: %s' % runCluster.logDirCopies()
        if runCluster.daqDataDir() is not None:
            print 'DAQ dataDir: %s' % runCluster.daqDataDir()
        if runCluster.daqLogDir() is not None:
            print 'DAQ logDir: %s' % runCluster.daqLogDir()
        print 'Default log level: %s' % runCluster.defaultLogLevel()
        for node in runCluster.nodes():
            print '  %s@%s logLevel %s' % \
                (node.locName(), node.hostName(), node.defaultLogLevel())
            comps = node.components()
            comps.sort()
            for comp in comps:
                print '    %s %s' % (str(comp), str(comp.logLevel()))
