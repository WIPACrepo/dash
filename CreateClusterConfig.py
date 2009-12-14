#!/usr/bin/env python
#
# Create an SPS cluster configuration from a run configuration file

import sys

from DAQConfig import DAQConfig

def writeLocation(fd, name, host, component, id=None):
    if id is None:
        idStr = ""
    else:
        idStr = " id=\"%02d\"" % id

    print >>fd, "    <location name=\"%s\" host=\"%s\">" % (name, host)
    print >>fd, "      <module name=\"%s\"%s/>" % (component, idStr)
    print >>fd, "    </location>"

def writeClusterConfig(fd, runCfg, spadeDir, copyDir, logLevel, cfgName=None,
                       clusterName="sps"):
    if cfgName is None:
        cfgStr = ""
    else:
        cfgStr = " configName=\"%s\"" % cfgName
    print >>fd, "<icecube%s>" % cfgStr
    print >>fd, "  <cluster name=\"%s\">" % clusterName

    print >>fd, "    <logDirForSpade>%s</logDirForSpade>" % spadeDir
    print >>fd, "    <logDirCopies>%s</logDirCopies>" % copyDir
    print >>fd, "    <defaultLogLevel>%s</defaultLogLevel>" % logLevel

    needInIce = False
    needIceTop = False

    for c in runCfg.getCompObjects():
        if not c.isHub(): continue

        id = c.id()
        if id < 100:
            hubName = "ichub%02d" % id
            needInIce = True
        else:
            hubName = "ithub%02d" % (id - 200)
            needIceTop = True

        writeLocation(fd, hubName, "%s-%s" % (clusterName, hubName),
                      "StringHub", id)
        print >>fd, ""

    writeLocation(fd, "2ndbuild", clusterName + "-2ndbuild",
                  "SecondaryBuilders")
    writeLocation(fd, "evbuilder", clusterName + "-evbuilder", "eventBuilder")

    print >>fd, "    <location name=\"trigger\" host=\"%s-trigger\">" % \
        clusterName
    if needInIce: print >>fd, "      <module name=\"inIceTrigger\"/>"
    if needIceTop: print >>fd, "      <module name=\"iceTopTrigger\"/>"
    print >>fd, "      <module name=\"globalTrigger\"/>"
    print >>fd, "    </location>"
    print >>fd, ""

    print >>fd, "    <location name=\"expcont\" host=\"%s-expcont\"/>" % \
        clusterName

    print >>fd, "  </cluster>"
    print >>fd, "</icecube>"

if __name__ == "__main__":
    spadeDir = "/mnt/data/pdaqlocal"
    copyDir = "/mnt/data/pdaq/log-copies"
    logLevel = "INFO"

    cfgList = []
    usage = False

    for arg in sys.argv[1:]:
        if not DAQConfig.configExists(arg):
            print >>sys.stderr, "Could not find run config: %s" % arg
            usage = True
        else:
            cfgList.append(arg)

    if usage:
        print >>sys.stderr, "Usage: %s runConfig" % sys.argv[0]
        raise SystemExit

    for cfgName in cfgList:
        runCfg = DAQConfig.load(cfgName)

        writeClusterConfig(sys.stdout, runCfg, spadeDir, copyDir, logLevel)
