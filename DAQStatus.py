#!/usr/bin/env python

from DAQRPC import RPCClient

if __name__ == "__main__":
    cncserver = "localhost"
    cncport   = 8080
    daqserver = "localhost"
    daqport   = 9000

    cncrpc = RPCClient(cncserver, cncport)

    nc = cncrpc.rpc_get_num_components()
    lc = cncrpc.rpc_show_components()
    ns = int(cncrpc.rpc_num_sets())
    print "CNC %s:%d -- %d unused components, %d run sets" % (cncserver, cncport, nc, ns)
    for c in lc: print '\t', c

    print "-----------------------"
    daqrpc = RPCClient(daqserver, daqport)
    state  = daqrpc.rpc_run_state()
    print "DAQ state is %s" % state
