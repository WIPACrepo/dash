#!/usr/bin/env python
#
# Create an SPS cluster configuration from a run configuration file

import sys
import os

from DAQConfig import DAQConfigParser
# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py            
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class CCCException(Exception): pass

class ClusterConfigCreator(object):
    CLUSTER = { "sps" :
                    { "spadeDir" : "/mnt/data/pdaqlocal",
                      "copyDir" : "/mnt/data/pdaq/log-copies",
                      "logLevel" : "INFO",
                      }
                }

    def __init__(self, clusterName):
        if not self.CLUSTER.has_key(clusterName):
            raise CCCException("Unknown cluster name \"%s\"" % clusterName)

        self.__clusterName = clusterName

    def __writeLocation(self, fd, name, component, id=None):
        host = self.__clusterName + "-" + name

        if component is None:
            print >>fd, "    <location name=\"%s\" host=\"%s\"/>" % \
                (name, host)
        else:
            if id is None:
                idStr = ""
            else:
                idStr = " id=\"%02d\"" % id

            print >>fd, "    <location name=\"%s\" host=\"%s\">" % (name, host)
            if type(component) != list:
                print >>fd, "      <module name=\"%s\"%s/>" % (component, idStr)
            else:
                for c in component:
                    print >>fd, "      <module name=\"%s\"%s/>" % (c, idStr)
            print >>fd, "    </location>"

    def write(self, fd, runCfg, cfgName=None):
        if cfgName is None:
            cfgStr = ""
        else:
            cfgStr = " configName=\"%s\"" % cfgName

        print >>fd, "<icecube%s>" % cfgStr
        print >>fd, "  <cluster name=\"%s\">" % self.__clusterName

        print >>fd, "    <logDirForSpade>%s</logDirForSpade>" % \
            self.CLUSTER[self.__clusterName]["spadeDir"]
        print >>fd, "    <logDirCopies>%s</logDirCopies>" % \
            self.CLUSTER[self.__clusterName]["copyDir"]
        print >>fd, "    <defaultLogLevel>%s</defaultLogLevel>" % \
            self.CLUSTER[self.__clusterName]["logLevel"]

        needInIce = False
        needIceTop = False

        for c in runCfg.components():
            if not c.isHub(): continue

            id = c.id()
            if id < 100:
                hubName = "ichub%02d" % id
                needInIce = True
            else:
                hubName = "ithub%02d" % (id - 200)
                needIceTop = True

            if id == 0:
                raise Exception("Got 0 ID from %s<%s>" % (str(c), str(type(c))))

            self.__writeLocation(fd, hubName, "StringHub", id)
            print >>fd, ""

        self.__writeLocation(fd, "2ndbuild", "SecondaryBuilders")
        self.__writeLocation(fd, "evbuilder", "eventBuilder")

        trigList = []
        if needInIce: trigList.append("inIceTrigger")
        if needIceTop: trigList.append("iceTopTrigger")
        trigList.append("globalTrigger")
        self.__writeLocation(fd, "trigger", trigList)
        print >>fd, ""

        self.__writeLocation(fd, "expcont", None)

        print >>fd, "  </cluster>"
        print >>fd, "</icecube>"

if __name__ == "__main__":
    clusterName = "sps"
    cfgList = []
    usage = False

    # configExists has a keyword argument that builds a dir
    # like this.  load( does not and wants a directory
    # to stay consistent use the same construction
    # in both places
    configDir = os.path.join(metaDir, "config")

    for arg in sys.argv[1:]:
        if not DAQConfigParser.configExists(arg, configDir=configDir):
            print >>sys.stderr, "Could not find run config: %s" % arg
            usage = True
        else:
            cfgList.append(arg)

    if usage:
        print >>sys.stderr, "Usage: %s runConfig" % sys.argv[0]
        raise SystemExit

    ccc = ClusterConfigCreator(clusterName)
    for cfgName in cfgList:
        runCfg = DAQConfigParser.load(cfgName, configDir)

        ccc.write(sys.stdout, runCfg)
