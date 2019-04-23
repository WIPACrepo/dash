#!/usr/bin/env python

from __future__ import print_function

import os
import os.path
import traceback

from CachedConfigName import CachedConfigName
from ClusterDescription import ClusterDescription, HSArgs, HubComponent, \
    JVMArgs, ReplayHubComponent
from DefaultDomGeometry import DefaultDomGeometry


class RunClusterError(Exception):
    pass


class RunNode(object):
    def __init__(self, hostname, defaultHSDir, defaultHSIval,
                 defaultHSMaxFiles, defaultJVMPath, defaultJVMServer,
                 defaultJVMHeapInit, defaultJVMHeapMax, defaultJVMArgs,
                 defaultJVMExtraArgs, defaultLogLevel):
        self.__locName = hostname
        self.__hostname = hostname
        self.__defaultHS = HSArgs(defaultHSDir, defaultHSIval,
                                  defaultHSMaxFiles)
        self.__defaultJVM = JVMArgs(defaultJVMPath, defaultJVMServer,
                                    defaultJVMHeapInit, defaultJVMHeapMax,
                                    defaultJVMArgs, defaultJVMExtraArgs)
        self.__defaultLogLevel = defaultLogLevel
        self.__comps = []

    def __cmp__(self, other):
        val = cmp(self.__hostname, other.__hostname)
        if val == 0:
            val = cmp(self.__locName, other.__locName)
        return val

    def __str__(self):
        return "%s(%s)*%d" % (self.__hostname, self.__defaultLogLevel,
                              len(self.__comps))

    def addComponent(self, comp):
        comp.host = self.__hostname
        self.__comps.append(comp)

    def components(self):
        return self.__comps[:]

    @property
    def defaultLogLevel(self):
        return self.__defaultLogLevel

    @property
    def hostname(self):
        return self.__hostname

    @property
    def location(self):
        return self.__locName


class SimAlloc(object):
    "Temporary class used to assign simHubs to hosts"
    def __init__(self, comp):
        self.__comp = comp
        self.__number = 0
        self.__percent = 0.0

        self.__allocated = 0

    def __lt__(self, other):
        if self.__allocated < other.__allocated:
            return True
        elif self.__allocated == other.__allocated and \
             self.__comp.host > other.__comp.host:
            return True
        return False

    def __str__(self):
        return "%s#%d%%%.2f=%d" % (self.__comp.host, self.__number,
                                   self.__percent, self.__allocated)

    def add(self, comp):
        self.__number += comp.number

        pct = (10.0 / float(comp.priority)) * float(comp.number)
        self.__percent += pct
        return pct

    def adjustPercentage(self, pctTot, numHubs):
        self.__percent /= pctTot
        self.__allocated = int(self.__percent * numHubs)
        if self.__allocated > self.__number:
            # if we overallocated based on the percentage,
            #  adjust down to the maximum number
            self.__allocated = self.__number
        return self.__allocated

    def allocateOne(self):
        if self.__allocated >= self.__number:
            return False
        self.__allocated += 1
        return True

    @property
    def allocated(self):
        return self.__allocated

    @property
    def host(self):
        return self.__comp.host

    @property
    def percent(self):
        return self.__percent


class RunCluster(CachedConfigName):
    "Cluster->component mapping generated from a run configuration file"
    def __init__(self, cfg, descrName=None, config_dir=None):
        "Create a cluster->component mapping from a run configuration file"
        super(RunCluster, self).__init__()

        self.__hubList = self.__extractHubs(cfg)

        self.__clusterDesc = ClusterDescription(config_dir, descrName)

        # set the name to the run config plus cluster config
        name = os.path.basename(cfg.fullpath)
        if name.endswith('.xml'):
            name = name[:-4]
        if self.__clusterDesc.name != "sps" and \
           self.__clusterDesc.name != "spts":
            name += "@" + self.__clusterDesc.name
        self.set_name(name)

        self.__nodes = self.__buildNodeMap(self.__clusterDesc, self.__hubList,
                                           cfg)

    def __str__(self):
        nodeStr = ""
        for n in self.__nodes:
            if len(nodeStr) > 0:
                nodeStr += " "
            nodeStr += "%s*%d" % (n.hostname, len(n.components()))
        return self.config_name + "[" + nodeStr + "]"

    @classmethod
    def __addComponent(cls, hostMap, host, comp):
        "Add a component to the hostMap dictionary"
        if host not in hostMap:
            hostMap[host] = {}
        hostMap[host][str(comp)] = comp

    @classmethod
    def __addRealHubs(cls, clusterDesc, hubList, hostMap):
        "Add hubs with hard-coded locations to hostMap"
        for (host, comp) in clusterDesc.listHostComponentPairs():
            if not comp.is_hub:
                continue
            for h in range(0, len(hubList)):
                if comp.id == hubList[h].id:
                    cls.__addComponent(hostMap, host, comp)
                    del hubList[h]
                    break

    @classmethod
    def __addReplayHubs(cls, clusterDesc, hubList, hostMap, runCfg):
        """
        Add replay hubs with locations hard-coded in the run config to hostMap
        """

        hsDir = clusterDesc.defaultHSDirectory("StringHub")
        hsIval = clusterDesc.defaultHSInterval("StringHub")
        hsMaxFiles = clusterDesc.defaultHSMaxFiles("StringHub")

        jvmPath = clusterDesc.defaultJVMPath("StringHub")
        jvmServer = clusterDesc.defaultJVMServer("StringHub")
        jvmHeapInit = clusterDesc.defaultJVMHeapInit("StringHub")
        jvmHeapMax = clusterDesc.defaultJVMHeapMax("StringHub")
        jvmArgs = clusterDesc.defaultJVMArgs("StringHub")
        jvmExtra = clusterDesc.defaultJVMExtraArgs("StringHub")

        alertEMail = clusterDesc.defaultAlertEMail("StringHub")
        ntpHost = clusterDesc.defaultNTPHost("StringHub")

        log_level = clusterDesc.defaultLogLevel("StringHub")

        if runCfg is None:
            numToSkip = None
        else:
            numToSkip = runCfg.numReplayFilesToSkip

        i = 0
        while i < len(hubList):
            hub = hubList[i]
            if hub.host is None:
                i += 1
                continue

            # die if host was not found in cluster config
            if clusterDesc.host(hub.host) is None:
                raise RunClusterError("Cannot find %s for replay in %s" %
                                      (hub.host, clusterDesc.name))

            if hub.log_level is not None:
                lvl = hub.log_level
            else:
                lvl = log_level

            comp = ReplayHubComponent(hub.name, hub.id, lvl, False)
            comp.host = hub.host

            comp.setJVMOptions(None, jvmPath, jvmServer, jvmHeapInit,
                               jvmHeapMax, jvmArgs, jvmExtra)
            comp.setHitSpoolOptions(None, hsDir, hsIval, hsMaxFiles)

            if numToSkip > 0:
                comp.setNumberToSkip(numToSkip)

            cls.__addComponent(hostMap, comp.host, comp)
            del hubList[i]

    @classmethod
    def __addRequired(cls, clusterDesc, hostMap):
        "Add required components to hostMap"
        for (host, comp) in clusterDesc.listHostComponentPairs():
            if comp.required:
                cls.__addComponent(hostMap, host, comp)

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
            if sim.host not in hubAlloc:
                # create new host entry
                hubAlloc[sim.host] = SimAlloc(sim)

            # add to the maximum number of hubs for this host
            pct = hubAlloc[sim.host].add(sim)

            maxHubs += sim.number
            pctTot += pct

        # make sure there's enough room for the requested hubs
        numHubs = len(hubList)
        if numHubs > maxHubs:
            raise RunClusterError("Only have space for %d of %d hubs" %
                                  (maxHubs, numHubs))

        # first stab at allocation: allocate based on percentage
        tot = 0
        for v in list(hubAlloc.values()):
            tot += v.adjustPercentage(pctTot, numHubs)

        # allocate remainder in order of total capacity
        while tot < numHubs:
            changed = False
            for v in sorted(list(hubAlloc.values()), reverse=True):
                if v.allocateOne():
                    tot += 1
                    changed = True
                    if tot >= numHubs:
                        break

            if tot < numHubs and not changed:
                raise RunClusterError("Only able to allocate %d of %d hubs" %
                                      (tot, numHubs))

        hubList.sort()

        hosts = []
        for v in sorted(list(hubAlloc.values()), reverse=True):
            hosts.append(v.host)

        jvmPath = clusterDesc.defaultJVMPath("StringHub")
        jvmServer = clusterDesc.defaultJVMServer("StringHub")
        jvmHeapInit = clusterDesc.defaultJVMHeapInit("StringHub")
        jvmHeapMax = clusterDesc.defaultJVMHeapMax("StringHub")
        jvmArgs = clusterDesc.defaultJVMArgs("StringHub")
        jvmExtra = clusterDesc.defaultJVMExtraArgs("StringHub")

        log_level = clusterDesc.defaultLogLevel("StringHub")

        if False:
            print()
            print("======= SimList")
            for sim in simList:
                print(":: %s<%s>" % (sim, type(sim)))
            print("======= HubList")
            for hub in hubList:
                print(":: %s<%s>" % (hub, type(hub)))

        hubNum = 0
        for host in hosts:
            for _ in range(hubAlloc[host].allocated):
                hubComp = hubList[hubNum]
                if hubComp.log_level is not None:
                    lvl = hubComp.log_level
                else:
                    lvl = log_level

                comp = HubComponent(hubComp.name, hubComp.id, lvl, False)
                comp.host = host

                comp.setJVMOptions(None, jvmPath, jvmServer, jvmHeapInit,
                                   jvmHeapMax, jvmArgs, jvmExtra)
                comp.setHitSpoolOptions(None, None, None, None)

                cls.__addComponent(hostMap, host, comp)
                hubNum += 1

    @classmethod
    def __addTriggers(cls, clusterDesc, hubList, hostMap):
        "Add needed triggers to hostMap"
        needAmanda = False
        needInice = False
        needIcetop = False

        for hub in hubList:
            hid = hub.id % 1000
            if hid == 0:
                needAmanda = True
            elif hid < 200:
                needInice = True
            else:
                needIcetop = True

        for (host, comp) in clusterDesc.listHostComponentPairs():
            if not comp.name.endswith('Trigger'):
                continue
            if comp.name == 'amandaTrigger' and needAmanda:
                cls.__addComponent(hostMap, host, comp)
                needAmanda = False
            elif comp.name == 'inIceTrigger' and needInice:
                cls.__addComponent(hostMap, host, comp)
                needInice = False
            elif comp.name == 'iceTopTrigger' and needIcetop:
                cls.__addComponent(hostMap, host, comp)
                needIcetop = False

    @classmethod
    def __convertToNodes(cls, clusterDesc, hostMap):
        "Convert hostMap to an array of cluster nodes"
        hostKeys = sorted(hostMap.keys())

        nodes = []
        for host in hostKeys:
            node = RunNode(str(host),
                           clusterDesc.defaultHSDirectory(),
                           clusterDesc.defaultHSInterval(),
                           clusterDesc.defaultHSMaxFiles(),
                           clusterDesc.defaultJVMPath(),
                           clusterDesc.defaultJVMServer(),
                           clusterDesc.defaultJVMHeapInit(),
                           clusterDesc.defaultJVMHeapMax(),
                           clusterDesc.defaultJVMArgs(),
                           clusterDesc.defaultJVMExtraArgs(),
                           clusterDesc.defaultLogLevel())
            nodes.append(node)

            for compKey in list(hostMap[host].keys()):
                node.addComponent(hostMap[host][compKey])

        return nodes

    @classmethod
    def __extractHubs(cls, runcfg):
        "build a list of hub components used by the run configuration"
        hubList = []
        for comp in runcfg.components():
            if comp.is_hub:
                hubList.append(comp)
        return hubList

    @classmethod
    def __getSortedSimHubs(cls, clusterDesc, hostMap):
        "Get list of simulation hubs, sorted by priority"
        simList = []

        for (_, simHub) in clusterDesc.listHostSimHubPairs():
            if simHub is None:
                continue
            if not simHub.ifUnused or simHub.host.name not in hostMap:
                simList.append(simHub)

        simList.sort(key=lambda x: x.priority)

        return simList

    @classmethod
    def __buildNodeMap(cls, clusterDesc, hubList, runCfg):
        hostMap = {}

        cls.__addRequired(clusterDesc, hostMap)
        cls.__addTriggers(clusterDesc, hubList, hostMap)
        if len(hubList) > 0:
            cls.__addRealHubs(clusterDesc, hubList, hostMap)
            if len(hubList) > 0:
                cls.__addReplayHubs(clusterDesc, hubList, hostMap, runCfg)
                if len(hubList) > 0:
                    cls.__addSimHubs(clusterDesc, hubList, hostMap)

        return cls.__convertToNodes(clusterDesc, hostMap)

    @property
    def daqDataDir(self):
        return self.__clusterDesc.daqDataDir

    @property
    def daqLogDir(self):
        return self.__clusterDesc.daqLogDir

    @property
    def defaultLogLevel(self):
        return self.__clusterDesc.defaultLogLevel()

    @property
    def description(self):
        return self.__clusterDesc.config_name

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
                    if comp.name.lower() == nodeComp.name.lower() \
                       and comp.num == nodeComp.id:
                        foundList.append(nodeComp)
                        found = True
                        break
                if found:
                    break
            if not found:
                missingList.append(comp)
        return (foundList, missingList)

    def getHubNodes(self):
        "Get a list of nodes on which hub components are running"
        hostMap = {}
        for node in self.__nodes:
            addHost = False
            for comp in node.components():
                if comp.is_hub:
                    addHost = True
                    break

            if addHost:
                hostMap[node.hostname] = 1

        return list(hostMap.keys())

    def loadIfChanged(self, runConfig=None, newPath=None):
        if not self.__clusterDesc.loadIfChanged(newPath=newPath):
            return False

        if runConfig is not None:
            self.__hubList = self.__extractHubs(runConfig)

        self.__nodes = self.__buildNodeMap(self.__clusterDesc, self.__hubList,
                                           runConfig)

    @property
    def logDirForSpade(self):
        return self.__clusterDesc.logDirForSpade

    @property
    def logDirCopies(self):
        return self.__clusterDesc.logDirCopies

    def nodes(self):
        return self.__nodes[:]


if __name__ == '__main__':
    import sys

    from DAQConfig import DAQConfigParser
    from locate_pdaq import find_pdaq_config

    if len(sys.argv) <= 1:
        raise SystemExit('Usage: %s [-C clusterDesc] configXML'
                         ' [configXML ...]' % sys.argv[0])

    pdaqDir = find_pdaq_config()
    if pdaqDir is None or len(pdaqDir) == 0:
        raise SystemExit("Cannot find pDAQ configuration directory")

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
        (ndir, nbase) = os.path.split(name)
        if ndir is None or len(ndir) == 0:
            config_dir = pdaqDir
        else:
            config_dir = ndir
        cfg = DAQConfigParser.parse(config_dir, nbase)
        try:
            runCluster = RunCluster(cfg, clusterDesc)
        except NotImplementedError:
            print('For %s:' % name, file=sys.stderr)
            traceback.print_exc()
            continue
        except KeyboardInterrupt:
            break
        except:
            print('For %s:' % name, file=sys.stderr)
            traceback.print_exc()
            continue

        print('RunCluster: %s (%s)' % \
            (runCluster.config_name, runCluster.description))
        print('--------------------')
        if runCluster.logDirForSpade is not None:
            print('SPADE logDir: %s' % runCluster.logDirForSpade)
        if runCluster.logDirCopies is not None:
            print('Copied logDir: %s' % runCluster.logDirCopies)
        if runCluster.daqDataDir is not None:
            print('DAQ dataDir: %s' % runCluster.daqDataDir)
        if runCluster.daqLogDir is not None:
            print('DAQ logDir: %s' % runCluster.daqLogDir)
        print('Default log level: %s' % runCluster.defaultLogLevel)
        for node in runCluster.nodes():
            print('  %s@%s logLevel %s' % \
                (node.location, node.hostname, node.defaultLogLevel))
            comps = sorted(node.components())
            for comp in comps:
                print('    %s %s' % (comp, comp.log_level))
