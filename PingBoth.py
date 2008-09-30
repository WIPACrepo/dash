#!/usr/bin/env python

import thread
from DAQRPC import RPCClient, RPCServer
from time import sleep

# Python listens at 9001
# Java listens at 9000
class ServeAndPing(object):
    def __init__(self):
        self.server = RPCServer(9001, "localhost")
        self.client = RPCClient("localhost", 9000)
    def dothread(self):
        self.server.register_function(self.rpc_ping)
        self.server.serve_forever()
    def rpc_ping(self): return "Python"
    def run(self):
        thread.start_new_thread(self.dothread, ())
        while True:
            sleep(1)
            try:
                print "%s" % self.client.CnC.rpc_ping()
            except KeyboardInterrupt:
                raise SystemExit
            except Exception, e:
                print e
            
if __name__ == "__main__":
    sp = ServeAndPing()
    sp.run()
    
