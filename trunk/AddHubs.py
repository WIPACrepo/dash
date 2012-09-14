#!/usr/bin/env python
#
# Create a new run configuration with only the specified hub(s)

import os
import sys
from utils import ip

from DAQConfig import DAQConfig, DAQConfigParser

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if "PDAQ_HOME" in os.environ:
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()


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
        print >> sys.stderr, "Cannot find configuration directory"

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
                    print >> sys.stderr, "Unknown argument \"%s\"" % s
                    usage = True
                    continue

            if s.endswith("i"):
                s = s[:-1]

            try:
                num = int(s)
                hubIdList.append(num)
                continue
            except:
                print >> sys.stderr, "Unknown argument \"%s\"" % a
                usage = True
                continue

    if not usage and runCfgName is None:
        print >> sys.stderr, "No run configuration specified"
        usage = True

    if not usage and len(hubIdList) == 0:
        print >> sys.stderr, "No hub IDs specified"
        usage = True

    if usage:
        print >> sys.stderr, \
            "Usage: %s runConfig hubId [hubId ...]" % sys.argv[0]
        print >> sys.stderr, "  (Hub IDs can be \"6\", \"06\", \"6i\", \"6t\")"
        raise SystemExit()

    return (forceCreate, runCfgName, cluCfgName, hubIdList)

if __name__ == "__main__":

    hostname = ip.getHostNameNoDomain()
    if(hostname.lower() == "expcont"):
        print >> sys.stderr, "-" * 60
        print >> sys.stderr, "Warning: Running AddHubs.py on expcont"
        print >> sys.stderr, "-" * 60

    (forceCreate, runCfgName, cluCfgName, hubIdList) = parseArgs()

    configDir = os.path.join(metaDir, "config")
    newPath = DAQConfig.createOmitFileName(configDir, runCfgName, hubIdList,
                                           keepList=True)
    if os.path.exists(newPath):
        if forceCreate:
            print >> sys.stderr, "WARNING: Overwriting %s" % newPath
        else:
            print >> sys.stderr, "WARNING: %s already exists" % newPath
            print >> sys.stderr, "Specify --force to overwrite this file"
            raise SystemExit()

    runCfg = DAQConfigParser.load(runCfgName, configDir)
    if runCfg is not None:
        newCfg = runCfg.omit(hubIdList, keepList=True)
        if newCfg is not None:
            with open(newPath, 'w') as fd:
                newCfg.write(fd)
            print "Created %s" % newPath
