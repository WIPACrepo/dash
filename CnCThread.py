#!/usr/bin/env python

import threading

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class CnCThread(threading.Thread):
    def __init__(self, name, log):
        self.__name = name
        self.__log = log

        threading.Thread.__init__(self, name=name)
        self.setDaemon(True)

    def _run(self):
        raise NotImplementedError()

    def run(self):
        try:
            self._run()
        except:
            self.__log.error(self.__name + ": " + exc_string())
