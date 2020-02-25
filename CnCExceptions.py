#!/usr/bin/env python
"Exceptions used by CnCServer"


class CnCServerException(Exception):
    "Base CnCServer exception class"


class MissingComponentException(CnCServerException):
    "Thrown when a runset cannot be created due to a missing component"
    def __init__(self, comp_list):
        self.__comp_list = comp_list
        super(MissingComponentException, self).__init__(None)

    def __str__(self):
        "String description of this exception"
        return "Still waiting for " + str(self.__comp_list)

    @property
    def components(self):
        "List of missing components"
        return self.__comp_list


class StartInterruptedException(CnCServerException):
    "Thrown when a runset cannot be created because the process was halted"
