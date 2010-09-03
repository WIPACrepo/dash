#!/usr/bin/env python

import signal, sys, threading, traceback

class DumpThreadsOnSignal(object):
    def __init__(self, fd=sys.stderr, signum=signal.SIGQUIT):
        self.__fd = fd
        signal.signal(signum, self.__handleSignal)

    def __findThread(cls, tId):
        for t in threading.enumerate():
            if t.ident == tId:
                return t

        return None
    __findThread = classmethod(__findThread)

    def __handleSignal(self, signum, frame):
        self.dumpThreads(self.__fd)

    def dumpThreads(cls, fd):
        first = True
        for tId, stack in sys._current_frames().items():
            thrd = cls.__findThread(tId)
            if thrd is None:
                tStr = "Thread #%d" % tId
            else:
                tStr = "Thread %s" % thrd.name

            if first:
                first = False
            else:
                print >>fd

            print >>fd, tStr

            for filename, lineno, name, line in traceback.extract_stack(stack):
                print >>fd, "  File \"%s\", line %d, in %s" % \
                    (filename, lineno, name)
                if line is not None:
                    print >>fd, "    %s" % line.strip()

        print >>fd, "---------------------------------------------"
    dumpThreads = classmethod(dumpThreads)
