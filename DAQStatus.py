#!/usr/bin/env python

import optparse

from DAQRPC import RPCClient

def cmpComp(x, y):
    c = cmp(x[7], y[7])
    if c == 0:
        c = cmp(x[1], y[1])
        if c == 0:
            c = cmp(x[2], y[2])

    return c

def dumpComp(comp, numList):
    if len(numList) > 0:
        if len(numList) == 1:
            print '  ' + comp
        else:
            numStr = None
            for n in numList:
                if numStr is None:
                    numStr = str(n)
                else:
                    numStr += ' ' + str(n)

                    print '  ' + str(len(numList)) + ' ' + comp + 's: ' + \
                        numStr

def listTerse(list):
    list.sort(cmpComp)

    prevState = None
    prevComp = None

    numList = []
    for c in list:
        if cmp(prevState, c[7]) != 0:
            prevState = c[7]
            print prevState
        if cmp(prevComp, c[1]) != 0:
            dumpComp(prevComp, numList)
            prevComp = c[1]
            numList = [c[3], ]
    dumpComp(prevComp, numList)

def listVerbose(list):
    for c in list:
        print '\t#%d %s#%d at %s:%d M#%d %s' % \
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6])

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
            listVerbose(lc)
        else:
            listTerse(lc)

    daqrpc = RPCClient(daqserver, daqport)
    try:
        state  = daqrpc.rpc_run_state()
    except:
        state = 'DAQRun DEAD'
    print "DAQ state is %s" % state
