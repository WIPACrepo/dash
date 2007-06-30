#!/usr/bin/env python

import optparse

from DAQRPC import RPCClient

def cmpComp(x, y):
    c = cmp(x[6], y[6])
    if c == 0:
        c = cmp(x[1], y[1])
        if c == 0:
            c = cmp(x[2], y[2])

    return c

def dumpComp(comp, numList, indent):
    if comp is None or len(numList) == 0:
        return

    if len(numList) == 1 and numList[0] == 0:
        print indent + '  ' + comp
    else:
        numStr = None
        for n in numList:
            if numStr is None:
                numStr = str(n)
            else:
                numStr += ' ' + str(n)

        front = indent + '  ' + str(len(numList)) + ' ' + comp + 's: '
        frontLen = len(front)

        lineLen = 78

        while len(numStr) > 0:
            if frontLen + len(numStr) < lineLen:
                print front + numStr
                break
            subStr = numStr[0:lineLen-frontLen]
            numStr = numStr[lineLen-frontLen:]
            if numStr[0] == ' ':
                numStr = numStr[1:]
            print front + subStr
            front = ' '*len(front)

def listTerse(list, indent=''):
    list.sort(cmpComp)

    prevState = None
    prevComp = None

    numList = []
    for c in list:
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

def listVerbose(list, indent=''):
    list.sort(cmpComp)

    for c in list:
        print '%s  #%d %s#%d at %s:%d M#%d %s' % \
            (indent, c[0], c[1], c[2], c[3], c[4], c[5], c[6])

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-v", "--verbose", action="store_true", dest="verbose")
    p.set_defaults(verbose = False)

    opt, args = p.parse_args()

    cncserver = "localhost"
    cncport   = 8080
    daqserver = "localhost"
    daqport   = 9000

    cncrpc = RPCClient(cncserver, cncport)

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

    print "CNC %s:%d" % (cncserver, cncport)

    print "-----------------------"
    print "%d unused components" % nc
    if opt.verbose:
        listVerbose(lc)
    else:
        listTerse(lc)

    print "-----------------------"
    print "%d run sets" % ns
    for id in ids:
        ls = cncrpc.rpc_runset_list(id)
        print '\tRunSet#%d' % id
        if opt.verbose:
            listVerbose(ls, '\t')
        else:
            listTerse(ls, '\t')

    daqrpc = RPCClient(daqserver, daqport)
    try:
        state  = daqrpc.rpc_run_state()
    except:
        state = 'DAQRun DEAD'
    print "DAQ state is %s" % state
