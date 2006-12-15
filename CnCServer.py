#!/usr/bin/env python

import os
import sys
import Daemon
import optparse
from exc_string import *
from DAQElement import *
from Process import processList, findProcess

set_exc_string_encoding("ascii")

class CnCServer(DAQServer):
    """Command and Control Server"""

    def monitorLoop(self):
        """Monitor components to ensure they're still alive"""
        spinStr = '-\\|/'
        spinner = 0

        new = True
        lastCount = 0
        while True:
            if new:
                print "%d bins" % len(self.pool)
            else:
                sys.stderr.write(spinStr[spinner:spinner+1] + "\r")
                spinner = (spinner + 1) % len(spinStr)

            try:
                count = self.monitorClients(new)
            except Exception, ex:
                print exc_string()
                count = lastCount

            new = (lastCount != count)
            lastCount = count
            sleep(1)

    def run(self):
        """Server loop"""
        self.serve(self.monitorLoop)

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-k", "--kill",    action="store_true", dest="kill")
    p.add_option("-p", "--port",    action="store",      type="int", dest="port")
    p.add_option("-d", "--daemon",  action="store_true", dest="daemon")
    p.set_defaults(kill     = False,
                   nodaemon = False,
                   port     = 8080)
    opt, args = p.parse_args()

    pids = list(findProcess("CnCServer.py", processList()))

    if opt.kill:
        pid = int(os.getpid())
        for p in pids:
            if pid != p:
                print "Killing %d..." % p
                import signal
                os.kill(p, signal.SIGKILL)
                
        raise SystemExit

    if len(pids) > 1:
        print "ERROR: More than one instance of CnCServer.py is already running!"
        raise SystemExit

    if opt.daemon: Daemon.Daemon().Daemonize()
    
    cnc = CnCServer("CnCServer", opt.port)
    try:
        cnc.run()
    except KeyboardInterrupt, k:
        print "Interrupted."
        raise SystemExit
