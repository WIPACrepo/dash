#!/usr/bin/env python

import thread, os, sys, time

class Rebootable(object):
    """
    J. Jacobsen Nov. 2006
    
    Interface/mixin to allow for a process to restart itself completely,
    consistent with serving RPC methods.  Starts a new thread and
    returns, so that the RPC call can complete without deadlocking.  The
    server should close its listening socket before calling do_reboot(),
    so that the client can try to connect and succeed only when a fresh
    instance of the server is in place.
    
    If called outside an RPC context, caller should just do_reboot and
    then sleep until the process dies.
    
    I tried implementing with the exec family of functions, but these
    don't seem to work well on intel mac in combination with pthreads.
    spawn+abort is an adequate replacement, since we don't care if the
    process number changes.
    """

    def __init__(self, restartDelaySec=2):
        self.restartDelaySec = restartDelaySec
        
    def reboot(self):
        """
        Helper function which causes actual reboot after a short delay to
        allow any RPC methods to return
        """
        time.sleep(self.restartDelaySec)
        os.spawnvpe(os.P_NOWAIT, sys.argv[0], sys.argv, os.environ)
        os.abort()

    def do_reboot(self):
        """
        Cause reboot/restart operation to occur, using reboot()
        helper function in a separate thread
        """
        thread.start_new_thread(self.reboot, ())
