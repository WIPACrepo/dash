#!/usr/bin/env python

import threading

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class CnCThread(threading.Thread):
    "A thread which handles one iteration of a CnCTask"
    def __init__(self, name, log):
        self.__name = name
        self.__log = log

        self.__closed = False

        threading.Thread.__init__(self, name=name)
        self.setDaemon(True)

    def _run(self):
        "This method should implement the core logic of the thread"
        raise NotImplementedError()

    def close(self):
        self.__closed = True

    def error(self, msg):
        self.__log.error(msg)

    @property
    def isClosed(self):
        return self.__closed

    @property
    def name(self):
        return self.__name

    def run(self):
        try:
            self._run()
        except:
            self.__log.error(self.__name + ": " + exc_string())
