#!/usr/bin/env python
#
# Create a new run configuration without one or more hubs

import os, sys

from DAQConfig import DAQConfig

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class XMLError(Exception): pass
class ProcessError(XMLError): pass
class BadFileError(XMLError): pass

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

    forceCreate = False
    cfg = None
    hubIdList = []

    usage = False
    for a in sys.argv[1:]:
        if a == "--force":
            forceCreate = True
            continue

        if cfg is None:
            path = os.path.join(cfgDir, a)
            if not path.endswith(".xml"):
                path += ".xml"

            if os.path.exists(path):
                cfg = a
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

    if not usage and cfg is None:
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

    return (forceCreate, cfg, hubIdList)

if __name__ == "__main__":
    (forceCreate, fileName, hubIdList) = parseArgs()

    configDir = os.path.join(metaDir, "config")
    newPath = DAQConfig.createOmitFileName(configDir, fileName, hubIdList)
    if os.path.exists(newPath):
        if forceCreate:
            print >>sys.stderr, "WARNING: Overwriting %s" % newPath
        else:
            print >>sys.stderr, "WARNING: %s already exists" % newPath
            print >>sys.stderr, "Specify --force to overwrite this file"
            raise SystemExit()

    runCfg = DAQConfig.load(fileName)
    if runCfg is not None:
        newCfg = runCfg.omit(hubIdList)
        if newCfg is not None:
            fd = open(newPath, "w")
            newCfg.write(fd)
            fd.close()
            print "Created %s" % newPath
