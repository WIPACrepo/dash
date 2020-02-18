#!/usr/bin/env python

from __future__ import print_function

import os

if os.name == 'nt':
    # We are running on WinXP or 2000 or NT or something like that
    # so we can't use this module :-(
    pass
else:
    import resource
    import time

    class Daemon(object):
        """
        Loosely follows Chad Schroeder's example at
        http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/278731
        """
        @classmethod
        def daemonize(cls):
            "Method which actually sets up the calling program as a daemon"
            pid = os.fork()          # Can raise OSError
            if pid != 0:
                os._exit(0)          # Parent does a minimal exit
            os.setsid()              # Become session leader
            pid = os.fork()          # Fork again to avoid zombies
            if pid != 0:
                os._exit(0)

            os.chdir("/")            # Avoid unmount errors
            os.umask(0)

            # Close all file descriptors, ignoring ones that weren't open
            maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
            if maxfd == resource.RLIM_INFINITY:
                maxfd = 1024
            for fnum in range(0, maxfd):
                try:
                    os.close(fnum)
                except OSError:
                    pass

            # Redirect stdin, stdout, stderr to /dev/null
            os.open("/dev/null", os.O_RDWR)  # stdin
            os.dup2(0, 1)
            os.dup2(0, 2)    # stdout, stderr


def main():
    "Main program"

    # Example
    daemon = Daemon()
    daemon.daemonize()
    time.sleep(3)
    print("Done.")  # You WILL NOT see this output


if __name__ == "__main__":
    main()
