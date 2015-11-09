#!/usr/bin/env python


class CnCServerException(Exception):
    pass


class MissingComponentException(CnCServerException):
    def __init__(self, compList):
        self.__compList = compList
        super(MissingComponentException, self).__init__(None)

    def __str__(self):
        return "Still waiting for " + str(self.__compList)

    def components(self):
        return self.__compList

class StartInterruptedException(CnCServerException):
    pass
