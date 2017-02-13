#!/usr/bin/env python

import threading

from DAQClient import BeanTimeoutException

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class ComponentOperationException(Exception):
    pass


class Result(object):
    def __init__(self, name):
        self.__name = name

    def __str__(self):
        return self.__name


class ComponentOperation(threading.Thread):
    "Thread used to communicate with a component in a run set"

    "result for a hanging thread"
    RESULT_HANGING = Result("hanging")
    "result for an erroneous thread"
    RESULT_ERROR = Result("???")

    "thread will close the component's inputs and outputs"
    CLOSE = "CLOSE"
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
    "thread will get first or last good time from hubs"
    GET_GOOD_TIME = "GET_GOOD_TIME"
    "thread will get multiple component MBean values"
    GET_MULTI_BEAN = "GET_MULTI_BEAN"
    "thread will get first hit time from replay hubs"
    GET_REPLAY_TIME = "GET_REPLAY_TIME"
    "thread will get run data from builders"
    GET_RUN_DATA = "GET_RUN_DATA"
    "thread will get a single component MBean value"
    GET_SINGLE_BEAN = "GET_SINGLE_BEAN"
    "thread will get the component state"
    GET_STATE = "GET_STATE"
    "thread will reset the component"
    RESET_COMP = "RESET_COMP"
    "thread will reset the component's logging"
    RESET_LOGGING = "RESET_LOGGING"
    "thread will set time offset for replay hubs"
    SET_REPLAY_OFFSET = "SET_REPLAY_OFFSET"
    "thread will start the component running"
    START_RUN = "START_RUN"
    "thread will start a subrun on the component"
    START_SUBRUN = "START_SUBRUN"
    "thread will stop the component's logging"
    STOP_LOGGING = "STOP_LOGGING"
    "thread will stop the running component"
    STOP_RUN = "STOP_RUN"
    "thread will switch the component to a new run number"
    SWITCH_RUN = "SWITCH_RUN"
    "thread will terminate the component"
    TERMINATE = "TERMINATE"

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

        name = "CompOp*%s=%s" % (str(self.__comp), self.__operation)

        super(ComponentOperation, self).__init__(name=name)
        self.setDaemon(True)

    def __close(self):
        "Close the component's inputs and outputs"
        self.__comp.close()

    def __configComponent(self):
        "Configure the component"
        self.__result = self.__comp.configure(self.__data[0])

    def __configLogging(self):
        "Configure logging for the component"
        self.__comp.logTo(self.__data[0], self.__data[1], self.__data[2],
                          self.__data[3])

    def __connect(self):
        "Connect the component"
        if not self.__comp in self.__data:
            self.__result = self.__comp.connect()
        else:
            self.__result = self.__comp.connect(self.__data[self.__comp])

    def __forcedStop(self):
        "Force the running component to stop"
        self.__result = self.__comp.forcedStop()

    def __getConnectorInfo(self):
        "Get the component's connector information"
        self.__result = self.__comp.listConnectorStates()

    def __getGoodTime(self):
        "Get the component's good hit time"
        self.__result = self.__comp.mbean.getAttributes("stringhub",
                                                        self.__data)

    def __getMultiBeanFields(self):
        "Get the component's current state"
        self.__result = self.__comp.mbean.getAttributes(self.__data[0],
                                                        self.__data[1])

    def __getReplayTime(self):
        "Get the replay hub's first hit time"
        self.__result = self.__comp.getReplayStartTime()

    def __getRunData(self):
        "Get the builder's run data"
        self.__result = self.__comp.getRunData(self.__data[0])

    def __getSingleBeanField(self):
        "Get a single bean.field value from the component"
        self.__result = self.__comp.mbean.get(self.__data[0], self.__data[1])

    def __getState(self):
        "Get the component's current state"
        self.__result = self.__comp.state

    def __resetComponent(self):
        "Reset the component"
        self.__comp.reset()

    def __resetLogging(self):
        "Reset logging for the component"
        self.__comp.resetLogging()

    def __setReplayOffset(self):
        "Set the replay hub's time offset"
        self.__comp.setReplayOffset(self.__data[0])

    def __startRun(self):
        "Start the component running"
        self.__result = self.__comp.startRun(self.__data[0])

    def __startSubrun(self):
        "Start a subrun on the component"
        self.__result = self.__comp.startSubrun(self.__data[0])

    def __stopLogging(self):
        "Stop logging for the component"
        if not self.__comp in self.__data:
            raise Exception("No log server found for " + str(self.__comp))
        self.__data[self.__comp].stopServing()

    def __stopRun(self):
        "Stop the running component"
        self.__result = self.__comp.stopRun()

    def __switchRun(self):
        "Stop the running component"
        self.__result = self.__comp.switchToNewRun(self.__data[0])

    def __terminate(self):
        "Terminate the component"
        self.__comp.terminate()

    def __runOperation(self):
        "Execute the requested operation"
        if self.__operation == ComponentOperation.CLOSE:
            self.__close()
        elif self.__operation == ComponentOperation.CONFIG_COMP:
            self.__configComponent()
        elif self.__operation == ComponentOperation.CONFIG_LOGGING:
            self.__configLogging()
        elif self.__operation == ComponentOperation.CONNECT:
            self.__connect()
        elif self.__operation == ComponentOperation.FORCED_STOP:
            self.__forcedStop()
        elif self.__operation == ComponentOperation.GET_CONN_INFO:
            self.__getConnectorInfo()
        elif self.__operation == ComponentOperation.GET_GOOD_TIME:
            self.__getGoodTime()
        elif self.__operation == ComponentOperation.GET_MULTI_BEAN:
            self.__getMultiBeanFields()
        elif self.__operation == ComponentOperation.GET_REPLAY_TIME:
            self.__getReplayTime()
        elif self.__operation == ComponentOperation.GET_RUN_DATA:
            self.__getRunData()
        elif self.__operation == ComponentOperation.GET_SINGLE_BEAN:
            self.__getSingleBeanField()
        elif self.__operation == ComponentOperation.GET_STATE:
            self.__getState()
        elif self.__operation == ComponentOperation.RESET_COMP:
            self.__resetComponent()
        elif self.__operation == ComponentOperation.RESET_LOGGING:
            self.__resetLogging()
        elif self.__operation == ComponentOperation.SET_REPLAY_OFFSET:
            self.__setReplayOffset()
        elif self.__operation == ComponentOperation.START_RUN:
            self.__startRun()
        elif self.__operation == ComponentOperation.START_SUBRUN:
            self.__startSubrun()
        elif self.__operation == ComponentOperation.STOP_LOGGING:
            self.__stopLogging()
        elif self.__operation == ComponentOperation.STOP_RUN:
            self.__stopRun()
        elif self.__operation == ComponentOperation.SWITCH_RUN:
            self.__switchRun()
        elif self.__operation == ComponentOperation.TERMINATE:
            self.__terminate()
        else:
            raise ComponentOperationException("Unknown operation %s" %
                                              str(self.__operation))

    def component(self):
        return self.__comp

    @property
    def isError(self):
        return self.__error

    def result(self):
        return self.__result

    def run(self):
        "Main method for thread"
        try:
            self.__runOperation()
        except BeanTimeoutException:
            self.__log.error("%s(%s): %s" % (str(self.__operation),
                                             str(self.__comp), exc_string()))
            self.__error = True
        except:
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
            if t.isError:
                numErrors += 1

        return (numAlive, numErrors)

    def reportErrors(self, logger, method):
        if logger is None:
            # This can happen when multiple threads are trying to stop a run
            return

        (numAlive, numErrors) = self.getErrors()

        if numAlive > 0:
            if numAlive == 1:
                plural = ""
            else:
                plural = "s"
            logger.error(("Thread group %s contains %d running thread%s" +
                          " after %s") % (self.__op, numAlive, plural, method))
        if numErrors > 0:
            if numErrors == 1:
                plural = ""
            else:
                plural = "s"
            logger.error("Thread group %s encountered %d error%s during %s" %
                         (self.__op, numErrors, plural, method))

    def start(self, comp, logger, data):
        "Start a thread after adding it to the group"
        thread = ComponentOperation(comp, logger, self.__op, data)
        self.__list.append(thread)
        thread.start()

    def results(self):
        if self.__op != ComponentOperation.GET_CONN_INFO and \
               self.__op != ComponentOperation.GET_GOOD_TIME and \
               self.__op != ComponentOperation.GET_MULTI_BEAN and \
               self.__op != ComponentOperation.GET_REPLAY_TIME and \
               self.__op != ComponentOperation.GET_RUN_DATA and \
               self.__op != ComponentOperation.GET_SINGLE_BEAN and \
               self.__op != ComponentOperation.GET_STATE and \
               self.__op != ComponentOperation.START_SUBRUN:
            raise ComponentOperationException("Cannot get results for" +
                                              " operation %s" % self.__op)
        results = {}
        for t in self.__list:
            if t.isAlive():
                result = ComponentOperation.RESULT_HANGING
            elif t.isError:
                result = ComponentOperation.RESULT_ERROR
            else:
                result = t.result()
            results[t.component()] = result
        return results

    @staticmethod
    def runSimple(op, comps, args, logger, errorName=None, waitSecs=2,
                  waitReps=4):
        tGroup = ComponentOperationGroup(op)
        for c in comps:
            tGroup.start(c, logger, args)
        tGroup.wait(waitSecs=waitSecs, reps=waitReps)
        if errorName is not None:
            tGroup.reportErrors(logger, errorName)
            return None
        return tGroup.results()

    def wait(self, waitSecs=2, reps=4):
        """
        Wait for all the threads to finish
        waitSecs - total number of seconds to wait
        reps - number of times to loop before deciding threads are hung
        NOTE:
        if all threads are hung, max wait time is (#threads * waitSecs * reps)
        """
        partSecs = float(waitSecs) / float(reps)
        for _ in range(reps):
            alive = False
            for t in self.__list:
                if t.isAlive():
                    t.join(partSecs)
                    alive |= t.isAlive()
            if not alive:
                break

if __name__ == "__main__":
    pass
