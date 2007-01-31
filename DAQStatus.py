#!/usr/bin/env python

from DAQRPC import RPCClient

if __name__ == "__main__":
    cncserver = "localhost"
    cncport   = 8080
    daqserver = "localhost"
    daqport   = 9000

    cncrpc = RPCClient(cncserver, cncport)

    try:
        nc = cncrpc.rpc_get_num_components()
        lc = cncrpc.rpc_show_components()
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
    for c in lc: print '\t', c

    print "-----------------------"
    print "%d run sets" % ns
    for id in ids:
        ls = cncrpc.rpc_runset_list(id)
        print '\tRunSet#%d' % id
        for c in ls:
            print '\t  ID#%d %s#%d at %s:%d M#%d %s' % \
                (c[0], c[1], c[2], c[3], c[4], c[5], c[6])

    daqrpc = RPCClient(daqserver, daqport)
    try:
        state  = daqrpc.rpc_run_state()
    except:
        state = 'DAQRun DEAD'
    print "DAQ state is %s" % state
