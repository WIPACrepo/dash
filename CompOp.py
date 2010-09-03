#!/usr/bin/env python

import socket, threading

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class ComponentOperationException(Exception): pass

class Result(object):
    def __init__(self, name):
        self.__name = name

    def __str__(self): return self.__name

class ComponentOperation(threading.Thread):
    "Thread used to communicate with a component in a run set"

    "result for a hanging thread"
    RESULT_HANGING = Result("hanging")
    "result for an erroneous thread"
    RESULT_ERROR = Result("???")

    "thread will configure the component"
    CONFIG_COMP = "CONFIG_COMP"
    "thread will configure the component's logging"
    CONFIG_LOGGING = "CONFIG_LOGGING"
    "thread will connect the component's inputs and outputs"
    CONNECT = "CONNECT"
    "thread will force the running component to stop"
    FORCED_STOP = "FORCED_STOP"
    "thread will get the component's connector information"
    GET_CONN_INFO = "GET_CONN_INFO"
    "thread will get multiple component MBean values"
    GET_MULTI_BEAN = "GET_MULTI_BEAN"
    "thread will get a single component MBean value"
    GET_SINGLE_BEAN = "GET_SINGLE_BEAN"
    "thread will get the component state"
    GET_STATE = "GET_STATE"
    "thread will reset the component"
    RESET_COMP = "RESET_COMP"
    "thread will reset the component's logging"
    RESET_LOGGING = "RESET_LOGGING"
    "thread will stop the component's logging"
    STOP_LOGGING = "STOP_LOGGING"
    "thread will start the component running"
    START_RUN = "START_RUN"
    "thread will stop the running component"
    STOP_RUN = "STOP_RUN"

    def __init__(self, comp, log, operation, data):
        """
        Initialize a run set thread
        comp - component
        log - object used to log errors
        operation - RunSet operation
        data - tuple holding all data needed for the operation
        """
        self.__comp = comp
        self.__log = log
        self.__operation = operation
        self.__data = data

        self.__result = None
        self.__error = False

        name = "CnCServer:Comp*%s=%s" % (str(self.__comp), self.__operation)

        super(ComponentOperation, self).__init__(name=name)
        self.setDaemon(True)

    def __configComponent(self):
        "Configure the component"
        self.__result = self.__comp.configure(self.__data[0])

    def __configLogging(self):
        "Configure logging for the component"
        self.__comp.logTo(self.__data[0], self.__data[1], self.__data[2],
                          self.__data[3])

    def __connect(self):
        "Connect the component"
        if not self.__data.has_key(self.__comp):
            self.__result = self.__comp.connect()
        else:
            self.__result = self.__comp.connect(self.__data[self.__comp])

    def __forcedStop(self):
        "Force the running component to stop"
        self.__result = self.__comp.forcedStop()

    def __getConnectorInfo(self):
        "Get the component's connector information"
        self.__result = self.__comp.listConnectorStates()

    def __getMultiBeanFields(self):
        "Get the component's current state"
        self.__result = self.__comp.getMultiBeanFields(self.__data[0],
                                                       self.__data[1])

    def __getSingleBeanField(self):
        "Get the component's current state"
        self.__result = self.__comp.getSingleBeanField(self.__data[0],
                                                       self.__data[1])

    def __getState(self):
        "Get the component's current state"
        self.__result = self.__comp.state()

    def __resetComponent(self):
        "Reset the component"
        self.__comp.reset()

    def __resetLogging(self):
        "Reset logging for the component"
        self.__comp.resetLogging()

    def __startRun(self):
        "Start the component running"
        self.__result = self.__comp.startRun(self.__data[0])

    def __stopLogging(self):
        "Stop logging for the component"
        self.__data[self.__comp].stopServing()

    def __stopRun(self):
        "Stop the running component"
        self.__result = self.__comp.stopRun()

    def __runOperation(self):
        "Execute the requested operation"
        if self.__operation == ComponentOperation.CONFIG_COMP:
            self.__configComponent()
        elif self.__operation == ComponentOperation.CONFIG_LOGGING:
            self.__configLogging()
        elif self.__operation == ComponentOperation.CONNECT:
            self.__connect()
        elif self.__operation == ComponentOperation.FORCED_STOP:
            self.__forcedStop()
        elif self.__operation == ComponentOperation.GET_CONN_INFO:
            self.__getConnectorInfo()
        elif self.__operation == ComponentOperation.GET_MULTI_BEAN:
            self.__getMultiBeanFields()
        elif self.__operation == ComponentOperation.GET_SINGLE_BEAN:
            self.__getSingleBeanField()
        elif self.__operation == ComponentOperation.GET_STATE:
            self.__getState()
        elif self.__operation == ComponentOperation.RESET_COMP:
            self.__resetComponent()
        elif self.__operation == ComponentOperation.RESET_LOGGING:
            self.__resetLogging()
        elif self.__operation == ComponentOperation.START_RUN:
            self.__startRun()
        elif self.__operation == ComponentOperation.STOP_LOGGING:
            self.__stopLogging()
        elif self.__operation == ComponentOperation.STOP_RUN:
            self.__stopRun()
        else:
            raise ComponentOperationException("Unknown operation %s" %
                                              str(self.__operation))

    def component(self): return self.__comp
    def isError(self): return self.__error
    def result(self): return self.__result

    def run(self):
        "Main method for thread"
        try:
            self.__runOperation()
        except socket.error:
            self.__error = True
        except:
            self.__log.error("%s(%s): %s" % (str(self.__operation),
                                             str(self.__comp),
                                             exc_string()))
            self.__error = True

class ComponentOperationGroup(object):
    def __init__(self, op):
        "Create a runset thread group"
        self.__op = op

        self.__list = []

    def getErrors(self):
        numAlive = 0
        numErrors = 0

        for t in self.__list:
            if t.isAlive():
                numAlive += 1
            if t.isError():
                numErrors += 1

        return (numAlive, numErrors)

    def reportErrors(self, logger, method):
        (numAlive, numErrors) = self.getErrors()

        if numAlive > 0:
            if numAlive == 1:
                plural = ""
            else:
                plural = "s"
            logger.error(("Thread group contains %d running thread%s" +
                          " after %s") % (numAlive, plural, method))
        if numErrors > 0:
            if numErrors == 1:
                plural = ""
            else:
                plural = "s"
            logger.error("Thread group encountered %d error%s during %s" %
                         (numErrors, plural, method))

    def start(self, comp, logger, data):
        "Start a thread after adding it to the group"
        thread = ComponentOperation(comp, logger, self.__op, data)
        self.__list.append(thread)
        thread.start()

    def results(self):
        if self.__op != ComponentOperation.GET_CONN_INFO and \
               self.__op != ComponentOperation.GET_MULTI_BEAN and \
               self.__op != ComponentOperation.GET_SINGLE_BEAN and \
               self.__op != ComponentOperation.GET_STATE:
            raise ComponentOperationException("Cannot get results for" +
                                              " operation %s" % self.__op)
        results = {}
        for t in self.__list:
            if t.isAlive():
                result = ComponentOperation.RESULT_HANGING
            elif t.isError():
                result = ComponentOperation.RESULT_ERROR
            else:
                result = t.result()
            results[t.component()] = result
        return results

    def wait(self, reps=4, waitSecs=2):
        """
        Wait for all the threads to finish
        reps - number of times to loop before deciding threads are hung
        waitSecs - total number of seconds to wait
        NOTE:
        if all threads are hung, max wait time is (#threads * waitSecs * reps)
        """
        partSecs = float(waitSecs) / float(reps)
        for i in range(reps):
            alive = False
            for t in self.__list:
                if t.isAlive():
                    t.join(partSecs)
                    alive |= t.isAlive()
            if not alive:
                break

if __name__ == "__main__":
    pass
