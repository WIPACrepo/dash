#!/usr/bin/env python
"""
A ThreadGroup implementation used by CompOp.py to manage groups of threads
(e.g. start, join, etc.) 
"""

import threading


class GThread(threading.Thread):
    "Thread which is part of a group of threads"

    def __init__(self, target=None, name=None, args=(), kwargs=None,
                 is_daemon=True):
        """
        Initialize a grouped thread
        target - object invoked by the run() method
        name - thread name
        args - arguments passed to the target
        kwargs - dictionary of keyword arguments passed to the target
        is_daemon - True if this thread should be a daemon thread
        """
        self.__run_method = target
        self.__args = args
        self.__kwargs = kwargs if kwargs is not None else {}

        self.__result = None
        self.__error = None

        super(GThread, self).__init__(name=name)
        if is_daemon:
            self.setDaemon(True)

    def __str__(self):
        return "Thread[tgt %s super %s]" % \
            (self.__run_method, str(super(GThread, self)))

    @property
    def error(self):
        "Return error (or None)"
        return self.__error

    @property
    def is_error(self):
        "Return True if this thread encountered an error"
        return self.__error is not None

    def report_exception(self,        # pylint: disable=no-self-use
                         exception):  # pylint: disable=unused-argument
        "Don't report exceptions"
        return

    def result(self):
        "Return cached result"
        return self.__result

    def run(self):
        "Main method for thread"
        if self.__run_method is None:
            self.__error = "!!! No run method for %s" % (self.name, )
        else:
            try:
                self.__run_method(*self.__args, **self.__kwargs)
            except Exception as exception:  # pylint: disable=broad-except
                self.report_exception(exception)
                self.__error = exception


class ThreadGroup(object):
    "Manage a group of threads"

    def __init__(self, name=None):
        "Create a thread group"
        self.__name = name

        self.__list = []

    def __len__(self):
        return len(self.__list)

    def __str__(self):
        return "ThreadGroup(%s)*%d" % (self.__name, len(self.__list))

    def __get_errors(self):
        """
        Count the number of threads still "alive" and the number which
        has problems
        """

        num_alive = 0
        num_errors = 0

        for thrd in self.__list:
            if thrd.is_alive():
                num_alive += 1
            try:
                if thrd.is_error:
                    num_errors += 1
            except AttributeError:  # thrown when 'thrd' is a plain Thread
                num_errors += 1

        return (num_alive, num_errors)

    def add(self, thread, start_immediate=False):
        "Add a thread to the group"
        self.__list.append(thread)
        if start_immediate:
            thread.start()

    @property
    def threads(self):
        "Iterate through all threads in this group"
        for thrd in self.__list:
            yield thrd

    def report_errors(self, logger, method):
        "Summarize errors to logger"
        if logger is None:
            # This can happen when multiple threads are trying to stop a run
            return None

        (num_alive, num_errors) = self.__get_errors()

        result = False
        if num_alive > 0:
            if num_alive == 1:
                plural = ""
            else:
                plural = "s"
            logger.error("Thread group %s contains %d running thread%s"
                         " after %s" %
                         (self.__name, num_alive, plural, method))
            result = True

        if num_errors > 0:
            if num_errors == 1:
                plural = ""
            else:
                plural = "s"
            logger.error("Thread group %s encountered %d error%s during %s" %
                         (self.__name, num_errors, plural, method))
            result = True

        return result

    def start(self):
        "Start all threads"
        for thread in self.__list:
            thread.start()

    def wait(self, wait_secs=2, reps=4):
        """
        Wait for all the threads to finish
        wait_secs - total number of seconds to wait
        reps - number of times to loop before deciding threads are hung
        NOTE:
        if all threads are hung, max wait time is (#threads * wait_secs * reps)
        """
        part_secs = float(wait_secs) / float(reps)
        for _ in range(reps):
            alive = False
            for thrd in self.__list:
                if thrd.is_alive():
                    thrd.join(part_secs)
                    alive |= thrd.is_alive()
            if not alive:
                break
