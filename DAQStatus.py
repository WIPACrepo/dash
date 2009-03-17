#!/usr/bin/env python

import optparse, sys
from os import environ
from os.path import join
from DAQConst import DAQPort
from DAQRPC import RPCClient

from SVNVersionInfo import get_version_info

SVN_ID  = "$Id: DAQStatus.py 3973 2009-03-17 20:38:52Z dglo $"

LINE_LENGTH = 78

def cmpComp(x, y):
    c = cmp(x[6], y[6])
    if c == 0:
        c = cmp(x[1], y[1])
        if c == 0:
            c = cmp(x[2], y[2])

    return c

def dumpComp(comp, numList, indent):
    """Dump list of component instances, breaking long lists across lines"""

    if comp is None or len(numList) == 0:
        return

    if len(numList) == 1 and numList[0] == 0:
        print indent + '  ' + comp
    else:
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
                        numStr += '-' + str(prevNum)
                        inRange = False
                    numStr += ' ' + str(n)
            prevNum = n
        if numStr is None:
            numStr = ""
        elif inRange:
            numStr += '-' + str(prevNum)

        if len(indent) > 0: indent = '|' + indent[1:]
        front = indent + '  ' + str(len(numList)) + ' ' + comp + 's: '
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
            while tmpLen > 0 and numStr[tmpLen] != ' ':
                tmpLen -= 1
            if tmpLen == 0:
                tmpLen = LINE_LENGTH - frontLen
                while tmpLen < len(numStr) and numStr[tmpLen] != ' ':
                    tmpLen += 1

            # split line at break point
            print front + numStr[0:tmpLen]

            # set numStr to remainder of string and strip leading whitespace
            numStr = numStr[tmpLen:]
            while len(numStr) > 0 and numStr[0] == ' ':
                numStr = numStr[1:]

            # after first line, set front string to whitespace
            if not frontCleared:
                front = ' '*len(front)
                frontCleared = True

def listTerse(compList, indent=''):
    compList.sort(cmpComp)

    prevState = None
    prevComp = None

    numList = []
    for c in compList:
        compChanged = cmp(prevComp, c[1]) != 0
        stateChanged = cmp(prevState, c[6]) != 0
        if compChanged or stateChanged:
            dumpComp(prevComp, numList, indent)
            prevComp = c[1]
            numList = []
        if stateChanged:
            prevState = c[6]
            print indent + prevState
        numList.append(c[2])
    dumpComp(prevComp, numList, indent)

def listVerbose(compList, indent=''):
    compList.sort(cmpComp)

    for c in compList:
        print '%s  #%d %s#%d at %s:%d M#%d %s' % \
            (indent, c[0], c[1], c[2], c[3], c[4], c[5], c[6])

if __name__ == "__main__":
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-v", "--verbose", action="store_true", dest="verbose")
    p.set_defaults(verbose = False)

    opt, args = p.parse_args()

    cncrpc = RPCClient("localhost", DAQPort.CNCSERVER)

    try:
        nc = cncrpc.rpc_get_num_components()
        lc = cncrpc.rpc_list_components()
        ns = int(cncrpc.rpc_num_sets())
        ids = cncrpc.rpc_runset_listIDs()
    except:
        nc = 0
        lc = []
        ns = 0
        ids = []

    print "CNC %s:%d" % ("localhost", DAQPort.CNCSERVER)

    print "-----------------------"
    print "%d unused components" % nc
    if opt.verbose:
        listVerbose(lc)
    else:
        listTerse(lc)

    print "-----------------------"
    print "%d run sets" % ns
    for runid in ids:
        ls = cncrpc.rpc_runset_list(runid)
        print '\tRunSet#%d' % runid
        if opt.verbose:
            listVerbose(ls, '\t')
        else:
            listTerse(ls, '\t')

    daqrpc = RPCClient("localhost", DAQPort.DAQRUN)
    try:
        state  = daqrpc.rpc_run_state()
    except:
        state = 'DAQRun DEAD'
    print "DAQ state is %s" % state
