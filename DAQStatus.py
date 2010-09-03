#!/usr/bin/env python

import optparse, sys
from os import environ
from os.path import join
from DAQConst import DAQPort
from DAQRPC import RPCClient
from LiveImports import SERVICE_NAME

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID  = "$Id: DAQStatus.py 5156 2010-09-03 22:00:36Z dglo $"

LINE_LENGTH = 78

def cmpComp(x, y):
    c = cmp(x["state"], y["state"])
    if c == 0:
        c = cmp(x["compName"], y["compName"])
        if c == 0:
            c = cmp(x["compNum"], y["compNum"])

    return c

def dumpComp(comp, numList, indent, indent2):
    """Dump list of component instances, breaking long lists across lines"""

    if comp is None or len(numList) == 0:
        return

    if len(numList) == 1 and numList[0] == 0:
        print indent + indent2 + comp
        return

    numStr = None
    prevNum = -1
    inRange = False
    for n in numList:
        if numStr is None:
            numStr = str(n)
        else:
            if prevNum + 1 == n:
                if not inRange:
                    inRange = True
            else:
                if inRange:
                    numStr += "-" + str(prevNum)
                    inRange = False
                numStr += " " + str(n)
        prevNum = n
    if numStr is None:
        numStr = ""
    elif inRange:
        numStr += "-" + str(prevNum)

    plural = getPlural(len(numList))
    front = "%s%s%d %s%s: " % (indent, indent2, len(numList), comp, plural)
    frontLen = len(front)
    frontCleared = False

    while len(numStr) > 0:
        # if list of numbers fits on the line, print it
        if frontLen + len(numStr) < LINE_LENGTH:
            print front + numStr
            break

        # look for break point
        tmpLen = LINE_LENGTH - frontLen
        if tmpLen >= len(numStr):
            tmpLen = len(numStr) - 1
        while tmpLen > 0 and numStr[tmpLen] != " ":
            tmpLen -= 1
        if tmpLen == 0:
            tmpLen = LINE_LENGTH - frontLen
            while tmpLen < len(numStr) and numStr[tmpLen] != " ":
                tmpLen += 1

        # split line at break point
        print front + numStr[0:tmpLen]

        # set numStr to remainder of string and strip leading whitespace
        numStr = numStr[tmpLen:]
        while len(numStr) > 0 and numStr[0] == " ":
            numStr = numStr[1:]

        # after first line, set front string to whitespace
        if not frontCleared:
            front = " "*len(front)
            frontCleared = True

def getPlural(num):
    if num == 1:
        return ""
    return "s"

def listTerse(compList, indent, indent2):
    compList.sort(cmpComp)

    prevState = None
    prevComp = None

    numList = []
    for c in compList:
        compChanged = cmp(prevComp, c["compName"]) != 0
        stateChanged = cmp(prevState, c["state"]) != 0
        if compChanged or stateChanged:
            dumpComp(prevComp, numList, indent, indent2)
            prevComp = c["compName"]
            numList = []
        if stateChanged:
            prevState = c["state"]
            print indent + prevState
        numList.append(c["compNum"])
    dumpComp(prevComp, numList, indent, indent2)

def listVerbose(compList, indent, indent2):
    compList.sort(cmpComp)

    for c in compList:
        print "%s%s#%d %s#%d at %s:%d M#%d %s" % \
            (indent, indent2, c["id"], c["compName"], c["compNum"], c["host"],
             c["rpcPort"], c["mbeanPort"], c["state"])

if __name__ == "__main__":
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Print detailed list")

    opt, args = p.parse_args()

    cncrpc = RPCClient("localhost", DAQPort.CNCSERVER)

    try:
        nc = cncrpc.rpc_component_count()
        lc = cncrpc.rpc_component_listDicts()
        ns = cncrpc.rpc_runset_count()
        ids = cncrpc.rpc_runset_listIDs()
        versInfo = cncrpc.rpc_version()
        vers = " (%s:%s)" % (versInfo["release"], versInfo["repo_rev"])
    except:
        nc = 0
        lc = []
        ns = 0
        ids = []
        vers = ""

    print "CNC %s:%d%s" % ("localhost", DAQPort.CNCSERVER, vers)

    indent = "    "

    if len(indent) == 0:
        indent2 = "  "
    else:
        indent2 = indent

    print "======================="
    print "%d unused component%s" % (nc, getPlural(nc))
    if opt.verbose:
        listVerbose(lc, indent, indent2)
    else:
        listTerse(lc, indent, indent2)

    print "-----------------------"
    print "%d run set%s" % (ns, getPlural(ns))
    for runid in ids:
        ls = cncrpc.rpc_runset_list(runid)
        print "%sRunSet#%d" % (indent, runid)
        if opt.verbose:
            listVerbose(ls, indent, indent2)
        else:
            listTerse(ls, indent, indent2)

    liverpc = RPCClient("localhost", DAQPort.DAQLIVE)

    try:
        lst = liverpc.rpc_status(SERVICE_NAME)
    except:
        lst = "???"

    print "======================="
    print "DAQLive %s:%d" % ("localhost", DAQPort.DAQLIVE)
    print "======================="
    print "Status: %s" % lst
