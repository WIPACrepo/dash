#!/usr/bin/env python
#
# Create a new run configuration with only the specified hub(s)

from __future__ import print_function

import os
import sys
from utils.Machineid import Machineid

from DAQConfig import DAQConfig, DAQConfigParser
from DAQConfig import DAQConfigException

# find pDAQ's run configuration directory
from locate_pdaq import find_pdaq_config

# save path to configuration directory
CONFIG_DIR = find_pdaq_config()


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
    if not os.path.exists(CONFIG_DIR):
        print("Cannot find configuration directory", file=sys.stderr)

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
            path = os.path.join(CONFIG_DIR, a)
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
                    print("Unknown argument \"%s\"" % s, file=sys.stderr)
                    usage = True
                    continue

            if s.endswith("i"):
                s = s[:-1]

            try:
                num = int(s)
                hubIdList.append(num)
                continue
            except:
                print("Unknown argument \"%s\"" % a, file=sys.stderr)
                usage = True
                continue

    if not usage and runCfgName is None:
        print("No run configuration specified", file=sys.stderr)
        usage = True

    if not usage and len(hubIdList) == 0:
        print("No hub IDs specified", file=sys.stderr)
        usage = True

    if usage:
        print("Usage: %s runConfig hubId [hubId ...]" % sys.argv[0], file=sys.stderr)
        print("  (Hub IDs can be \"6\", \"06\", \"6i\", \"6t\")", file=sys.stderr)
        raise SystemExit()

    return (forceCreate, runCfgName, cluCfgName, hubIdList)


if __name__ == "__main__":

    hostid = Machineid()
    if not hostid.is_build_host:
        print("-" * 60, file=sys.stderr)
        print("Warning: AddHubs.py should be run on the build machine",
              file=sys.stderr)
        print("-" * 60, file=sys.stderr)

    (forceCreate, runCfgName, cluCfgName, hubIdList) = parseArgs()

    newPath = DAQConfig.createOmitFileName(CONFIG_DIR, runCfgName, hubIdList,
                                           keepList=True)
    if os.path.exists(newPath):
        if forceCreate:
            print("WARNING: Overwriting %s" % newPath, file=sys.stderr)
        else:
            print("WARNING: %s already exists" % newPath, file=sys.stderr)
            print("Specify --force to overwrite this file", file=sys.stderr)
            raise SystemExit()

    try:
        runCfg = DAQConfigParser.parse(CONFIG_DIR, runCfgName)
    except DAQConfigException as config_exp:
        print("WARNING: Error parsing %s" % runCfgName, file=sys.stderr)
        raise SystemExit(config_exp)

    if runCfg is not None:
        newCfg = runCfg.omit(hubIdList, keepList=True)
        if newCfg is not None:
            with open(newPath, 'w') as fd:
                fd.write(newCfg)
            print("Created %s" % newPath)
