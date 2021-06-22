#!/usr/bin/env python
"Generate a series of ID values"

import threading


class UniqueID(object):
    "Manage a unique ID among multiple threads"
    def __init__(self, val=1):
        "Create an ID generator, starting from 1 if `val` is not specified"
        self.__val = val
        self.__lock = threading.Lock()

    def __next__(self):
        "Get next ID (thread-safe)"
        with self.__lock:
            rtnval = self.__val
            self.__val += 1

        return rtnval

    next = __next__  # XXX backward compatibility for Python 2

    def peek_next(self):
        "Peek at the next ID"
        return self.__val
