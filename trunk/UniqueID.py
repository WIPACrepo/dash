#!/usr/bin/env python

import threading


class UniqueID(object):
    "Manage a unique ID among multiple threads"
    def __init__(self, val=1):
        self.__val = val
        self.__lock = threading.Lock()

    def __next__(self):
        with self.__lock:
            rtnVal = self.__val
            self.__val += 1

        return rtnVal

    next = __next__ # XXX backward compatibility for Python 2

    def peekNext(self):
        return self.__val


if __name__ == "__main__":
    pass
