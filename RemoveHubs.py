#!/usr/bin/env python
#
# Create a new run configuration without one or more hubs

import os, sys

from CreateClusterConfig import ClusterConfigCreator
from DAQConfig import DAQConfig

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

def createClusterConfigName(fileName, hubIdList):
    configDir = os.path.join(metaDir, "cluster-config", "src", "main", "xml")
    return createConfigName(configDir, fileName, hubIdList)

def createConfigName(configDir, fileName, hubIdList):
    """
    Create a new file name from the original name and the list of omitted hubs
    """
    baseName = os.path.basename(fileName)
    if baseName.endswith(".xml"):
        baseName = baseName[:-4]

    noStr = ""
    for h in hubIdList:
        noStr += "-no" + getHubName(h)

    return os.path.join(configDir, baseName + noStr + ".xml")

def getHubName(num):
    """Get the standard representation for a hub number"""
    if num > 0 and num < 100:
        return "%02d" % num
    if num > 200 and num < 220:
        return "%02dt" % (num - 200)
    return "?%d?" % num

def parseArgs():
    """
    Parse command-line arguments
    Return a tuple containing:
        a boolean indicating if the file should be overwritten if it exists
        the run configuration name
        the list of hub IDs to be removed
    """
    cfgDir = os.path.join(metaDir, "config")
    if not os.path.exists(cfgDir):
        print >>sys.stderr, "Cannot find configuration directory"

    cluCfgName = None
    forceCreate = False
    runCfgName = None
    hubIdList = []

    needCluCfgName = False

    usage = False
    for a in sys.argv[1:]:
        if a == "--force":
            forceCreate = True
            continue

        if a == "-C":
            needCluCfgName = True
            continue

        if needCluCfgName:
            cluCfgName = a
            needCluCfgName = False
            continue

        if runCfgName is None:
            path = os.path.join(cfgDir, a)
            if not path.endswith(".xml"):
                path += ".xml"

            if os.path.exists(path):
                runCfgName = a
                continue

        for s in a.split(","):
            if s.endswith("t"):
                try:
                    num = int(s[:-1])
                    hubIdList.append(200 + num)
                    continue
                except:
                    print >>sys.stderr, "Unknown argument \"%s\"" % s
                    usage = True
                    continue

            if s.endswith("i"):
                s = s[:-1]

            try:
                num = int(s)
                hubIdList.append(num)
                continue
            except:
                print >>sys.stderr, "Unknown argument \"%s\"" % a
                usage = True
                continue

    if not usage and runCfgName is None:
        print >>sys.stderr, "No run configuration specified"
        usage = True

    if not usage and len(hubIdList) == 0:
        print >>sys.stderr, "No hub IDs specified"
        usage = True

    if usage:
        print >>sys.stderr, \
            "Usage: %s runConfig hubId [hubId ...]" % sys.argv[0]
        print >>sys.stderr, "  (Hub IDs can be \"6\", \"06\", \"6i\", \"6t\")"
        raise SystemExit()

    return (forceCreate, runCfgName, cluCfgName, hubIdList)

if __name__ == "__main__":
    (forceCreate, runCfgName, cluCfgName, hubIdList) = parseArgs()

    configDir = os.path.join(metaDir, "config")
    newPath = DAQConfig.createOmitFileName(configDir, runCfgName, hubIdList)
    if os.path.exists(newPath):
        if forceCreate:
            print >>sys.stderr, "WARNING: Overwriting %s" % newPath
        else:
            print >>sys.stderr, "WARNING: %s already exists" % newPath
            print >>sys.stderr, "Specify --force to overwrite this file"
            raise SystemExit()

    runCfg = DAQConfig.load(runCfgName)
    if runCfg is not None:
        newCfg = runCfg.omit(hubIdList)
        if newCfg is not None:
            fd = open(newPath, "w")
            newCfg.write(fd)
            fd.close()
            print "Created %s" % newPath

            if cluCfgName is not None:
                cluPath = createClusterConfigName(cluCfgName, hubIdList)
                if os.path.exists(cluPath):
                    if forceCreate:
                        print >>sys.stderr, "WARNING: Overwriting %s" % cluPath
                    else:
                        print >>sys.stderr, "WARNING: %s already exists" % \
                            cluPath
                        print >>sys.stderr, \
                            "Specify --force to overwrite this file"
                        raise SystemExit()

                ccc = ClusterConfigCreator("sps")
                fd = open(cluPath, "w")
                ccc.write(fd, newCfg)
                fd.close()
                print "Created %s" % cluPath
