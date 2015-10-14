#!/usr/bin/env python
#
# Create a new run configuration without one or more hubs

import os
import sys
from utils.Machineid import Machineid

from DAQConfig import DAQConfig, DAQConfigParser
from DAQConfig import DAQConfigException
from locate_pdaq import find_pdaq_config

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
        the file name of the output configuration
        the list of hub IDs to be removed
    """
    cfgDir = find_pdaq_config()
    if not os.path.exists(cfgDir):
        print >> sys.stderr, "Cannot find configuration directory"

    outCfgName = None
    forceCreate = False
    runCfgName = None
    hubIdList = []

    needOutCfgName = False

    usage = False
    for a in sys.argv[1:]:
        if a == "--force":
            forceCreate = True
            continue

        if a == "-o":
            needOutCfgName = True
            continue

        if needOutCfgName:
            outCfgName = a
            needOutCfgName = False
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
            "Usage: %s [-o output.xml] runConfig hubId [hubId ...]" % sys.argv[0]
        print >> sys.stderr, "  (Hub IDs can be \"6\", \"06\", \"6i\", \"6t\")"
        raise SystemExit()

    return (forceCreate, runCfgName, outCfgName, hubIdList)

if __name__ == "__main__":

    hostid = Machineid()
    if not hostid.is_build_host():
        print >> sys.stderr, "-" * 60
        print >> sys.stderr, \
            "Warning: RemoveHubs.py should be run on the build machine"
        print >> sys.stderr, "-" * 60

    (forceCreate, runCfgName, outCfgName, hubIdList) = parseArgs()

    configDir = find_pdaq_config()
    if not outCfgName:
        newPath = DAQConfig.createOmitFileName(configDir, runCfgName, hubIdList)
    else:
        newPath = os.path.join(configDir, outCfgName)
    if os.path.exists(newPath):
        if forceCreate:
            print >> sys.stderr, "WARNING: Overwriting %s" % newPath
        else:
            print >> sys.stderr, "WARNING: %s already exists" % newPath
            print >> sys.stderr, "Specify --force to overwrite this file"
            raise SystemExit()

    try:
        runCfg = DAQConfigParser.parse(configDir, runCfgName)
    except DAQConfigException as config_except:
        print >> sys.stderr, "WARNING: Error parsing %s" % runCfgName
        raise SystemExit(config_except)

    if runCfg is not None:
        newCfg = runCfg.omit(hubIdList)
        if newCfg is not None:
            with open(newPath, 'w') as fd:
                fd.write(newCfg)
            print "Created %s" % newPath
