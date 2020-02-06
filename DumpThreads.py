#!/usr/bin/env python
#
# Add this hunk of code to a program:
#
#     if sys.version_info > (2, 3):
#         from DumpThreads import DumpThreadsOnSignal
#         DumpThreadsOnSignal(file_handle=sys.stderr, logger=self.__log)
#
# then type ^\ (control-backslash) to dump all threads while running

from __future__ import print_function

import signal
import sys
import threading
import traceback


class DumpThreadsOnSignal(object):
    def __init__(self, file_handle=None, logger=None, signum=signal.SIGQUIT):
        if file_handle is None and logger is None:
            self.__file_handle = sys.stderr
        else:
            self.__file_handle = file_handle
        self.__logger = logger

        signal.signal(signum, self.__handleSignal)

    @staticmethod
    def __findThread(tId):
        for t in threading.enumerate():
            if t.ident == tId:
                return t

        return None

    def __handleSignal(self, signum, frame):
        self.dumpThreads(self.__file_handle, self.__logger)

    @classmethod
    def dumpThreads(cls, file_handle=None, logger=None):
        first = True
        for tId, stack in list(sys._current_frames().items()):
            thrd = cls.__findThread(tId)
            if thrd is None:
                tStr = "Thread #%d" % tId
            else:
                # changed to get the string representation
                # of the thread as it has state, name, and
                # such embedded in it
                tStr = "Thread %s" % thrd

            if first:
                first = False
            elif file_handle is not None:
                print(file=file_handle)

            for filename, lineno, name, line in traceback.extract_stack(stack):
                tStr += "\n  File \"%s\", line %d, in %s" % \
                    (filename, lineno, name)
                if line is not None:
                    tStr += "\n    %s" % line.strip()

            if file_handle is not None:
                print(tStr, file=file_handle)
            if logger is not None:
                logger.error(tStr)

        if file_handle is not None:
            print("---------------------------------------------",
                  file=file_handle)
