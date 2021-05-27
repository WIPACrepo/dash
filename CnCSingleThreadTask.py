#!/usr/bin/env python
"""
RunData task which does one thing (or one set of things) on a regular basis
"""

from CnCTask import CnCTask
from decorators import classproperty


class CnCSingleThreadTask(CnCTask):
    """
    A task which does one thing (or one set of things) on a regular basis.
    """
    def __init__(self, task_mgr, runset, dashlog, live_moni=None, period=None,
                 need_live_moni=True):
        """
        If `live_moni` is None and `need_live_moni` is True, nothing is run
        If `live_moni` is None and `need_live_moni` is False, the task is
        run but (obviously) nothing is sent to I3Live.

        `detail_time` is a secondary timer which can be used to trigger an
        additional, more detailed report at a lower interval than the usual
        one.
        """
        self.__runset = runset
        self.__need_live_moni = need_live_moni
        self.__live_moni_client = live_moni
        self.__bad_count = 0

        if self.__need_live_moni and self.__live_moni_client is None:
            name = None
            period = None
            self.__detail_time = None
        else:
            name = self.name
            if period is None:
                period = self.period

            # pylint: disable=assignment-from-none
            self.__detail_time = self.create_detail_timer(task_mgr)

        super(CnCSingleThreadTask, self).__init__(name, task_mgr, dashlog,
                                                  name, period)

        self.__thread = self.initialize_thread(runset, dashlog, live_moni)

    def _check(self):
        """
        For the current period:
        * If the previous thread has finished, start a new thread
        * If the previous thread has not finished, increment `bad_count`;
          if the thread hasn't finished after 3 checks, call task_failed()
        """
        if self.__need_live_moni and self.__live_moni_client is None:
            # we need to send data to Live and it's not available;
            # don't do anything
            return
        if self.__thread is None:
            # we can't do anything without a CnCThread object
            return

        # if the previous thread finished...
        if not self._running():

            # reset the "bad thread" counter
            self.__bad_count = 0

            # if we have a detail timer, check if it's gone off
            send_details = False
            if self.__detail_time is not None and \
                    self.__detail_time.is_time():
                send_details = True
                self.__detail_time.reset()

            # create and start a new thread
            self.__thread = self.__thread.get_new_thread(send_details)
            self.__thread.start()
        else:
            # remember that the current thread hasn't finished
            self.__bad_count += 1

            # if the situation isn't critical, just whine a little
            if not self._is_failed():
                self.log_error("WARNING: %s thread is hanging (#%d)" %
                               (self.name, self.__bad_count))
            else:
                # give up on this task
                self.task_failed()
                # stop the interval timer so it won't be run again
                self.end_timer()

    def _is_failed(self):
        "Criteria for deciding that this task can no longer be performed"
        return self.__thread is None or self.__bad_count > 3

    def _reset(self):
        "Reset tasks at the end of the run"
        self.__detail_time = None
        self.__bad_count = 0

    def _running(self):
        "Is the current thread still running?"
        return self.__thread is not None and self.__thread.is_alive()

    def close(self):
        "Close any running thread"
        if self._running():
            self.__thread.close()

    @classmethod
    def create_detail_timer(cls, task_mgr):  # pylint: disable=unused-argument
        "No detail timer is needed by default"
        return None

    def gather_last(self):
        "Gather final set of data"
        if not self._is_failed() and not self._running():
            # gather one last set of stats
            thrd = self.__thread.get_new_thread(True)
            thrd.start()

    @classproperty
    def name(cls):  # pylint: disable=no-self-argument
        "Name of this task"
        raise NotImplementedError()

    @classproperty
    def period(cls):  # pylint: disable=no-self-argument
        "Number of seconds between tasks"
        raise NotImplementedError()

    def task_failed(self):
        """
        Subclasses need to implement this class to define what happens when
        self._is_failed() becomes True.  This usually involves logging an error
        but may also include other actions up to stopping the current run
        (as is done in RateTask).
        """
        raise NotImplementedError()

    def initialize_thread(self, runset, dashlog, live_moni):
        "Create a new task-specific thread which is run at each interval"
        raise NotImplementedError()

    def stop_runset(self, caller_name):
        "Signal the runset that this run has failed"
        self.__runset.set_run_error(caller_name)

    def wait_until_finished(self):
        "If a thread is running, wait until it's finished"
        if self.__need_live_moni and self.__live_moni_client is None:
            return

        if self._running():
            self.__thread.join()
