#!/usr/bin/env python

import threading

class UniqueID(object):
    "Manage a unique ID among multiple threads"
    def __init__(self, val=1):
        self.__val = val
        self.__lock = threading.Lock()

    def next(self):
        self.__lock.acquire()
        try:
            rtnVal = self.__val
            self.__val += 1
        finally:
            self.__lock.release()

        return rtnVal

    def peekNext(self): return self.__val

if __name__ == "__main__": pass
