#!/usr/bin/env python

from CnCTask import CnCTask

class CnCSingleThreadTask(CnCTask):
    """
    A task which does one thing (or one set of things) on a regular basis.
    """
    def __init__(self, taskMgr, runset, dashlog, liveMoni=None, period=None,
                 needLiveMoni=True):
        """
        If `liveMoni` is None and `needLiveMoni` is True, nothing will be run.
        If `liveMoni` is None and `needLiveMoni` is False, the task will be run
        but (obviously) nothing will be sent to I3Live.

        `detailTimer` is a secondary timer which can be used to trigger an
        additional, more detailed report at a lower interval than the usual one.
        """
        self.__runset = runset
        self.__needLiveMoni = needLiveMoni
        self.__liveMoniClient = liveMoni
        self.__detailTimer = None

        self.__thread = self.initializeThread(runset, dashlog, liveMoni)
        self.__badCount = 0

        if self.__needLiveMoni and self.__liveMoniClient is None:
            name = None
            period = None
        else:
            name = self.NAME
            if period is None:
                period = self.PERIOD
            self.__detailTimer = self.createDetailTimer(taskMgr)

        super(CnCSingleThreadTask, self).__init__(name, taskMgr, dashlog,
                                                  self.DEBUG_BIT, name, period)

    def _check(self):
        """
        For the current period:
        * If the previous thread has finished, start a new thread
        * If the previous thread has not finished, increment `badCount`;
          if the thread hasn't finished after 3 checks, call taskFailed()
        """
        if self.__needLiveMoni and self.__liveMoniClient is None:
            # we need to send data to Live and it's not available;
            # don't do anything
            return
        if self.__thread is None:
            # we can't do anything without a CnCThread object
            return

        # if the previous thread finished...
        if not self._running():

            # reset the "bad thread" counter
            self.__badCount = 0

            # if we have a detail timer, check if it's gone off
            sendDetails = False
            if self.__detailTimer is not None and \
                    self.__detailTimer.isTime():
                sendDetails = True
                self.__detailTimer.reset()

            # create and start a new thread
            self.__thread = self.__thread.getNewThread(sendDetails)
            self.__thread.start()
        else:
            # remember that the current thread hasn't finished
            self.__badCount += 1

            # if the situation isn't critical, just whine a little
            if not self._isFailed():
                self.logError("WARNING: %s thread is hanging (#%d)" %
                              (self.NAME, self.__badCount))
            else:
                # give up on this task
                self.taskFailed()
                # stop the interval timer so it won't be run again
                self.endTimer()


    def _reset(self):
        "Reset tasks at the end of the run"
        self.__detailTimer = None
        self.__badCount = 0

    def _running(self):
        "Is the current thread still running?"
        return self.__thread is not None and self.__thread.isAlive()

    def _isFailed(self):
        "Criteria for deciding that this task can no longer be performed"
        return self.__thread is None or self.__badCount > 3

    def close(self):
        "Close any running thread"
        if self._running():
            self.__thread.close()

    def createDetailTimer(self, taskMgr):
        "No detail timer is needed by default"
        return None

    def gatherLast(self):
        """
        Gather final set of data
        """
        if not self._isFailed() and not self._running():
            # gather one last set of stats
            thrd = self.__thread.getNewThread(True)
            thrd.start()

    def taskFailed(self):
        """
        Subclasses need to implement this class to define what happens when
        self._isFailed() becomes True.  This usually involves logging an error
        but may also include other actions up to stopping the current run
        (as is done in RateTask).
        """
        raise NotImplementedError()

    def initializeThread(self, runset, dashlog, liveMoni):
        "Create a new task-specific thread which is run at each interval"
        raise NotImplementedError()

    def stopRunset(self, callerName):
        "Signal the runset that this run has failed"
        self.__runset.setError(callerName)

    def waitUntilFinished(self):
        "If a thread is running, wait until it's finished"
        if self.__needLiveMoni and self.__liveMoniClient is None:
            return

        if self._running():
            self.__thread.join()
