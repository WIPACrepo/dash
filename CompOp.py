#!/usr/bin/env python

from DAQClient import BeanTimeoutException
from ThreadGroup import Thread, ThreadGroup
from decorators import classproperty

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class ComponentOperationException(Exception):
    pass


class ComponentOperation(object):
    "Send a command or query to a component in a runset"

    def __str__(self):
        "Return the name of this operator"
        return self.name

    @classproperty
    def has_result(cls):
        "Does this operator return a result?"
        return True

    @classproperty
    def name(cls):
        "Return the name of this operator"
        name = cls.__name__
        if name is not None and name.startswith("Op"):
            return name[2:]
        return name


class VoidOperation(ComponentOperation):
    @classproperty
    def has_result(self):
        return False


class OpClose(VoidOperation):
    "Close the component's inputs and outputs"
    @classmethod
    def execute(cls, comp, _):
        return comp.close()


class OpConfigureComponent(VoidOperation):
    "Configure the component"
    @classmethod
    def execute(cls, comp, data):
        return comp.configure(data[0])


class OpConfigureLogging(VoidOperation):
    "Configure logging for the component"
    @classmethod
    def execute(cls, comp, data):
        return comp.logTo(data[0], data[1], data[2], data[3])


class OpConnect(VoidOperation):
    "Connect the component's inputs and outputs"
    @classmethod
    def execute(cls, comp, data):
        if comp not in data:
            return comp.connect()

        return comp.connect(data[comp])


class OpForcedStop(VoidOperation):
    "Force the running component to stop"
    @classmethod
    def execute(cls, comp, _):
        return comp.forcedStop()


class OpGetConnectionInfo(ComponentOperation):
    "Get the component's connector information"
    @classmethod
    def execute(cls, comp, _):
        return comp.listConnectorStates()


class OpGetGoodTime(ComponentOperation):
    "Get the component's good hit time"
    @classmethod
    def execute(cls, comp, data):
        return comp.mbean.getAttributes("stringhub", data)


class OpGetMultiBeanFields(ComponentOperation):
    "Get the component's good hit time"
    @classmethod
    def execute(cls, comp, data):
        return comp.mbean.getAttributes(data[0], data[1])


class OpGetReplayTime(ComponentOperation):
    "Get the replay hub's first hit time"
    @classmethod
    def execute(cls, comp, _):
        return comp.getReplayStartTime()


class OpGetRunData(ComponentOperation):
    "Get the builder's run data"
    @classmethod
    def execute(cls, comp, data):
        return comp.getRunData(data[0])


class OpGetSingleBeanField(ComponentOperation):
    "Get a single component MBean value"
    @classmethod
    def execute(cls, comp, data):
        return comp.mbean.get(data[0], data[1])


class OpGetState(ComponentOperation):
    "Get the component state"
    @classmethod
    def execute(cls, comp, _):
        return comp.state


class OpResetComponent(VoidOperation):
    "Reset the component"
    @classmethod
    def execute(cls, comp, _):
        return comp.reset()


class OpResetLogging(VoidOperation):
    "Reset the component's logging"
    @classmethod
    def execute(cls, comp, _):
        return comp.resetLogging()


class OpSetReplayOffset(VoidOperation):
    "Set time offset for replay hubs"
    @classmethod
    def execute(cls, comp, data):
        return comp.setReplayOffset(data[0])


class OpStartRun(VoidOperation):
    "Start the component"
    @classmethod
    def execute(cls, comp, data):
        return comp.startRun(data[0])


class OpStartSubrun(ComponentOperation):
    "Start the component"
    @classmethod
    def execute(cls, comp, data):
        return comp.startSubrun(data[0])


class OpStopLogging(VoidOperation):
    "Stop the component's logging"
    @classmethod
    def execute(cls, comp, data):
        if comp not in data:
            raise Exception("No log server found for %s" % (comp, ))
        data[comp].stop_serving()


class OpStopRun(VoidOperation):
    "Stop running components"
    @classmethod
    def execute(cls, comp, _):
        comp.stopRun()


class OpSwitchRun(VoidOperation):
    "Switch the component to a new run number"
    @classmethod
    def execute(cls, comp, data):
        comp.switchToNewRun(data[0])


class OpTerminate(VoidOperation):
    "Terminate the component"
    @classmethod
    def execute(cls, comp, _):
        comp.terminate()


class OperationResult(object):
    def __init__(self, name):
        self.__name = str(name)

    def __str__(self):
        return self.__name

    __repr__ = __str__


class ComponentResult(OperationResult):
    def __init__(self, comp, operation, arguments, value):
        self.__comp = comp
        self.__operation = operation
        self.__arguments = arguments
        self.__value = value

        super(ComponentResult, self).__init__(operation)

    def __str__(self):
        if self.__arguments is None:
            astr = "NONE"
        elif isinstance(self.__arguments, list) or \
             isinstance(self.__arguments, tuple):
            astr = ",".join(str(arg) for arg in self.__arguments)
        else:
            astr = str(self.__arguments)

        return "%s:%s(%s) => <%s>%s" % \
            (self.__comp.fullname, self.__operation.name, astr,
             type(self.__value).__name__, self.__value)

    @property
    def arguments(self):
        return self.__arguments

    @property
    def component(self):
        return self.__comp

    @property
    def operation(self):
        return self.__operation

    @property
    def value(self):
        return self.__value


class ComponentThread(Thread):
    def __init__(self, operation, comp, args, logger):
        self.__operation = operation
        self.__comp = comp
        self.__args = args
        self.__logger = logger
        self.__result = None

        name = "%s->%s" % (self.__comp, self.__operation.name)
        super(ComponentThread, self).__init__(target=self.__execute, name=name)

    def __execute(self):
        self.__result = self.__operation.execute(self.__comp, self.__args)

    @property
    def component(self):
        return self.__comp

    def report_exception(self, exception):
        if isinstance(exception, BeanTimeoutException):
            self.__logger.error("%s(%s): %s" %
                                (self.__operation.name, self.__comp.fullname,
                                 exc_string()))
        else:
            if self.__args is None or len(self.__args) != 2:
                name = self.__comp.name
            else:
                name = ",".join(map(str, self.__args))
            self.__logger.error("%s(%s): %s" %
                                (self.__operation.name, name, exc_string()))

    @property
    def result(self):
        return ComponentResult(self.__comp, self.__operation, self.__args,
                               self.__result)


class ComponentGroup(ThreadGroup):
    "result for a hanging thread"
    RESULT_HANGING = OperationResult("hanging")
    "result for an erroneous thread"
    RESULT_ERROR = OperationResult("???")

    def __init__(self, op):
        "Create a runset thread group"
        self.__op = op

        super(ComponentGroup, self).__init__(name=op.name)

    @classmethod
    def has_value(cls, result, full_result=False):
        if result == ComponentGroup.RESULT_HANGING or \
           result == ComponentGroup.RESULT_ERROR or \
           result is None:
            return False

        if not full_result:
            return result

        if not isinstance(result, ComponentResult):
            return False

        return result.value is not None

    def results(self, full_result=False, comp_key=False, logger=None):
        if not self.__op.has_result:
            return None

        results = {}
        for thrd in self.threads:
            if thrd.isAlive():
                result = ComponentGroup.RESULT_HANGING
            elif thrd.is_error:
                result = ComponentGroup.RESULT_ERROR
            elif full_result:
                # return the entire result object
                result = thrd.result
            else:
                # return only the value from the result
                result = thrd.result.value

            if not comp_key:
                results[thrd] = result
            elif thrd.component in results:
                logger.error("Found multiple %s results for %s" %
                             (self.__op.name, thrd.component))
            else:
                results[thrd.component] = result
        return results

    @staticmethod
    def run_simple(operation, comps, args, logger, wait_secs=2, wait_reps=4,
                   full_result=False, report_errors=False):
        group = ComponentGroup(operation)
        for comp in comps:
            group.run_thread(comp, args, logger=logger)
        group.wait(wait_secs=wait_secs, reps=wait_reps)
        if report_errors:
            if group.report_errors(logger, operation.name):
                return None
        return group.results(full_result=full_result, comp_key=True,
                             logger=logger)

    def run_thread(self, comp, args, logger=None):
        "Add a thread to the group"
        thread = ComponentThread(self.__op, comp, args, logger)
        self.add(thread, start_immediate=True)

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
            for thrd in self.threads:
                if thrd.isAlive():
                    thrd.join(part_secs)
                    alive |= thrd.isAlive()
            if not alive:
                break


if __name__ == "__main__":
    pass
