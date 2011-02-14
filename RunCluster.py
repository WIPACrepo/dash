#!/usr/bin/env python

import os, os.path, socket, sys, traceback

from CachedConfigName import CachedConfigName
from ClusterDescription import ClusterDescription
from Component import Component

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class RunClusterError(Exception): pass

class RunComponent(Component):
    def __init__(self, name, id, logLevel, jvm, jvmArgs, host):
        self.__jvm = jvm
        self.__jvmArgs = jvmArgs
        self.__host = host

        super(RunComponent, self).__init__(name, id, logLevel)

    def __str__(self):
        nStr = self.fullName()

        if self.__jvm is None:
            if self.__jvmArgs is None:
                jStr = "?"
            else:
                jStr = "? | %s" % self.__jvmArgs
        else:
            if self.__jvmArgs is None:
                jStr = self.__jvm
            else:
                jStr = "%s | %s" % (self.__jvm, self.__jvmArgs)

        return "%s@%s(%s)" % (nStr, str(self.logLevel()), jStr)

    def host(self): return self.__host
    def isControlServer(self): return False
    def jvm(self): return self.__jvm
    def jvmArgs(self): return self.__jvmArgs

class RunNode(object):
    def __init__(self, hostName, defaultLogLevel, defaultJVM, defaultJVMArgs):
        self.__locName = hostName
        self.__hostName = hostName
        self.__defaultLogLevel = defaultLogLevel
        self.__defaultJVM = defaultJVM
        self.__defaultJVMArgs = defaultJVMArgs
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
        if comp.jvm() is not None or comp.isControlServer():
            jvm = comp.jvm()
        else:
            jvm = self.__defaultJVM
        if comp.jvmArgs() is not None or comp.isControlServer():
            jvmArgs = comp.jvmArgs()
        else:
            jvmArgs = self.__defaultJVMArgs
        self.__comps.append(RunComponent(comp.name(), comp.id(), logLvl, jvm,
                                         jvmArgs, self.__hostName))

    def components(self): return self.__comps[:]

    def defaultLogLevel(self): return self.__defaultLogLevel
    def hostName(self): return self.__hostName
    def locName(self): return self.__locName

class RunCluster(CachedConfigName):
    "Cluster->component mapping generated from a run configuration file"
    def __init__(self, cfg, descrName=None, configDir=None):
        "Create a cluster->component mapping from a run configuration file"
        super(RunCluster, self).__init__()

        name = os.path.basename(cfg.configFile())
        if name.endswith('.xml'):
            name = name[:-4]
        self.setConfigName(name)

        clusterDesc = self.__getClusterDescription(descrName, configDir)
        self.__descName = clusterDesc.configName()

        hostMap = {}

        hubList = self.__extractHubs(cfg)

        self.__addRequired(clusterDesc, hostMap)
        self.__addTriggers(clusterDesc, hubList, hostMap)
        if len(hubList) > 0:
            self.__addRealHubs(clusterDesc, hubList, hostMap)
            if len(hubList) > 0:
                self.__addSimHubs(clusterDesc, hubList, hostMap)

        self.__logDirForSpade = clusterDesc.logDirForSpade()
        self.__logDirCopies = clusterDesc.logDirCopies()
        self.__defaultLogLevel = clusterDesc.defaultLogLevel()
        self.__defaultJVM = clusterDesc.defaultJVM()
        self.__defaultJVMArgs = clusterDesc.defaultJVMArgs()

        self.__nodes = []
        self.__convertToNodes(hostMap)

    def __str__(self):
        nodeStr = ""
        for n in self.__nodes:
            if len(nodeStr) > 0:
                nodeStr += " "
            nodeStr += "%s*%d" % (n.hostName(), len(n.components()))
        return self.configName() + "[" + nodeStr + "]"

    def __addComponent(self, hostMap, host, comp):
        "Add a component to the hostMap dictionary"
        if not hostMap.has_key(host):
            hostMap[host] = {}
        hostMap[host][str(comp)] = comp

    def __addRealHubs(self, clusterDesc, hubList, hostMap):
        "Add hubs with hard-coded locations to hostMap"
        for (host, comp) in clusterDesc.listHostComponentPairs():
            if not comp.isHub():
                continue
            for h in range(0,len(hubList)):
                if comp.id() == hubList[h].id():
                    self.__addComponent(hostMap, host, comp)
                    del hubList[h]
                    break

    def __addRequired(self, clusterDesc, hostMap):
        "Add required components to hostMap"
        for (host, comp) in clusterDesc.listHostComponentPairs():
            if comp.required():
                self.__addComponent(hostMap, host, comp)

    def __addSimHubs(self, clusterDesc, hubList, hostMap):
        "Add simulated hubs to hostMap"
        simList = self.__getSortedSimHubs(clusterDesc, hostMap)
        if len(simList) == 0:
            missing = []
            for hub in hubList:
                missing.append(str(hub))
            raise RunClusterError("Cannot simulate %s hubs %s" %
                                  (clusterDesc.name, str(missing)))

        hubAlloc = []
        for i in range(len(simList)):
            hubAlloc.append(0)

        hubNum = 0
        for hub in hubList:
            looped = False
            while True:
                if hubAlloc[hubNum] < simList[hubNum].number:
                    hubAlloc[hubNum] += 1
                    hubNum += 1
                    if hubNum >= len(hubAlloc):
                        hubNum = 0
                    break

                # move to next host
                hubNum += 1
                if hubNum >= len(hubAlloc):
                    if looped:
                        raise RunClusterError(("Cannot assign hub %s;" +
                                               " out of hubs") % hub)
                    hubNum = 0
                    looped = True

        allocMap = {}
        for i in range(len(simList)):
            allocMap[simList[i].host.name] = hubAlloc[i]

        hubList.sort()

        allocHosts = allocMap.keys()
        allocHosts.sort()

        logLevel = clusterDesc.defaultLogLevel("StringHub")
        jvm = clusterDesc.defaultJVM("StringHub")
        jvmArgs = clusterDesc.defaultJVMArgs("StringHub")

        hubNum = 0
        for host in allocHosts:
            for i in range(0, allocMap[host]):
                hubComp = hubList[hubNum]
                if hubComp.logLevel() is not None:
                    lvl = hubComp.logLevel()
                else:
                    lvl = logLevel

                comp = RunComponent(hubComp.name(), hubComp.id(), lvl, jvm,
                                    jvmArgs, host)
                self.__addComponent(hostMap, host, comp)
                hubNum += 1

    def __addTriggers(self, clusterDesc, hubList, hostMap):
        "Add needed triggers to hostMap"
        needAmanda = False
        needInice = False
        needIcetop = False

        for hub in hubList:
            id = hub.id() % 1000
            if id == 0:
                needAmanda = True
            elif id < 200:
                needInice = True
            else:
                needIcetop = True

        for (host, comp) in clusterDesc.listHostComponentPairs():
            if not comp.name().endswith('Trigger'):
                continue
            if comp.name() == 'amandaTrigger' and needAmanda:
                self.__addComponent(hostMap, host, comp)
                needAmanda = False
            elif comp.name() == 'inIceTrigger' and needInice:
                self.__addComponent(hostMap, host, comp)
                needInice = False
            elif comp.name() == 'iceTopTrigger' and needIcetop:
                self.__addComponent(hostMap, host, comp)
                needIcetop = False

    def __convertToNodes(self, hostMap):
        "Convert hostMap to an array of cluster nodes"
        hostKeys = hostMap.keys()
        hostKeys.sort()

        for host in hostKeys:
            node = RunNode(host, self.__defaultLogLevel, self.__defaultJVM,
                           self.__defaultJVMArgs)
            self.__nodes.append(node)

            for compKey in hostMap[host].keys():
                node.addComponent(hostMap[host][compKey])

    def __extractHubs(self, cfg):
        "build a list of hub components used by the run configuration"
        hubList = []
        for comp in cfg.components():
            if comp.isHub():
                hubList.append(comp)
        return hubList

    def __getClusterDescription(self, name, configDir):
        "Get the appropriate cluster description"
        if name is None:
            name = ClusterDescription.getClusterFromHostName()

        if configDir is None:
            configDir = os.path.abspath(os.path.join(metaDir, 'config'))

        return ClusterDescription(configDir, name)

    def __getSortedSimHubs(self, clusterDesc, hostMap):
        "Get list of simulation hubs, sorted by priority"
        simList = []

        for (host, simHub) in clusterDesc.listHostSimHubPairs():
            if simHub is None: continue
            if not simHub.ifUnused or not hostMap.has_key(simHub.host.name):
                simList.append(simHub)

        simList.sort(self.__sortByPriority)

        return simList

    def __sortByPriority(x, y):
        "Sort simulated hub nodes by priority"
        val = cmp(y.priority, x.priority)
        if val == 0:
            val = cmp(x.host.name, y.host.name)
        return val

    __sortByPriority = staticmethod(__sortByPriority)

    def defaultLogLevel(self): return self.__defaultLogLevel
    def descName(self): return self.__descName

    def getConfigName(self):
        "get the configuration name to write to the cache file"
        if self.__descName is None:
            return self.configName()
        return '%s@%s' % (self.configName(), self.__descName)

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

    def logDirForSpade(self): return self.__logDirForSpade
    def logDirCopies(self) : return self.__logDirCopies
    def nodes(self): return self.__nodes[:]

if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print >>sys.stderr, ('Usage: %s [-C clusterDesc]' +
                             ' configXML [configXML ...]') % sys.argv[0]
        sys.exit(1)

    configDir = os.path.abspath(os.path.join(metaDir, 'config'))

    from DAQConfig import DAQConfigParser

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

        if os.path.basename(name) == 'default-dom-geometry.xml':
            # ignore
            continue

        nameList.append(name)

    for name in nameList:
        cfg = DAQConfigParser.load(name, configDir)
        try:
            runCluster = RunCluster(cfg, clusterDesc)
        except NotImplementedError, ue:
            print >>sys.stderr, 'For %s:' % name
            traceback.print_exc()
            continue
        except KeyboardInterrupt:
            break
        except:
            print >>sys.stderr, 'For %s:' % name
            traceback.print_exc()
            continue

        print 'RunCluster: %s (%s)' % \
            (runCluster.configName(), runCluster.descName())
        print '--------------------'
        if runCluster.logDirForSpade() is not None:
            print 'SPADE logDir: %s' % runCluster.logDirForSpade()
        if runCluster.logDirCopies() is not None:
            print 'Copied logDir: %s' % runCluster.logDirCopies()
        print 'Default log level: %s' % runCluster.defaultLogLevel()
        for node in runCluster.nodes():
            print '  %s@%s logLevel %s' % \
                (node.locName(), node.hostName(), node.defaultLogLevel())
            comps = node.components()
            comps.sort()
            for comp in comps:
                print '    %s %s' % (str(comp), str(comp.logLevel()))
