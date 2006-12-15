#!/usr/bin/env python

import resource
import time
import sys
import os

class Daemon(object):
    """
    Loosely follows Chad Schroeder's example at
    http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/278731
    """
    def Daemonize(self):
        "Method which actually sets up the calling program as a daemon"
        pid = os.fork()          # Can raise OSError
        if pid != 0: os._exit(0) # Parent does a minimal exit
        os.setsid()              # Become session leader
        pid = os.fork()          # Fork again to avoid zombies
        if pid != 0: os._exit(0)
        os.chdir("/")            # Avoid unmount errors
        os.umask(0)

        # Close all fd's, ignoring ones that weren't open
        maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
        if(maxfd == resource.RLIM_INFINITY):
            maxfd = 1024
        for fd in xrange(0, maxfd):
            try:
                os.close(fd)
            except OSError:
                pass

        # Redirect stdin, stdout, stderr to /dev/null
        os.open("/dev/null", os.O_RDWR) # stdin
        os.dup2(0, 1); os.dup2(0, 2)    # stdout, stderr
        return

if __name__ == "__main__":
    # Example
    d = Daemon()
    d.Daemonize()
    time.sleep(3)
    print "Done." # You WILL NOT see this output

