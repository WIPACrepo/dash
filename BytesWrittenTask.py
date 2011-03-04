"""This class should query the event builder once every ten minutes for the 
number of bytes that are written to disk.  That number is sent to i3live with 
the variable name 'eventBuilderNumBytesWritten'.  
"""

from CnCTask import CnCTask
from CnCThread import CnCThread
from RunSetDebug import RunSetDebug
from LiveImports import Prio

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class BytesWrittenThread(CnCThread):
    "A thread which reports the number of bytes written by event builder"
    def __init__(self, runset, dashlog, liveMoni, sendDetails):
        self.__comps = runset.components()
        self.__dashlog = dashlog
        self.__liveMoniClient = liveMoni
        self.__sendDetails = sendDetails

        super(BytesWrittenThread, self).__init__(
            "CnCServer:BytesWrittenThread", dashlog)

    def _run(self):
        """Query the event builder for the number of bytes written and
        send it off to i3live"""

        for c in self.__comps:
            if c.name()=='eventBuilder':
                # c is a reference to the event builder component
                numBytesWritten = 0

                try:
                    numBytesWritten = c.getSingleBeanField("eventBuilder", "numBytesWritten")
                except Exception, e:
                    self.__dashlog.error("Cannot get numBytesWritten %s: %s" % (c.fullName(), exc_string()))
                    print "Exception: ", e
                    continue

                try:
                    numBytesWritten = int(numBytesWritten)
                except ValueError:
                    self.__dashlog.error("Cannot get numBytesWritten (%s) %s: %s" % (numBytesWritten, c.fullName(), exc_string()))
                    continue
                
                
                self.__liveMoniClient.sendMoni("eventBuilderNumBytesWritten", numBytesWritten, Prio.ITS)
                


class BytesWrittenTask(CnCTask):
    """The CNC task manager will call this as a task.  The check method below
    will check and see if it's time to send out a report of the number of bytes
    written by the event builder to i3live.  If so it'll create that thread, otherwise
    wait until the next time it's called.
    """

    NAME = "BytesWritten"
    # the period (in seconds ) in which the CnCTask will call check
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.BYTES_WRITTEN_TASK

    # active DOM periodic report timer
    REPORT_NAME = "ActiveReport"
    # the period ( in seconds ) in which the byteswrittenthread gets
    # instantiated
    REPORT_PERIOD = 600


    def __init__(self, taskMgr, runset, dashlog, liveMoni, period=None):
        self.__runset = runset
        self.__liveMoniClient = liveMoni

        self.__thread = None
        self.__badCount = 0

        if self.__liveMoniClient is None:
            name = None
            period = None
            self.__detailTimer = None
        else:
            name = self.NAME
            if period is None: 
                period = self.PERIOD
            self.__detailTimer = \
                taskMgr.createIntervalTimer(self.REPORT_NAME,
                                            self.REPORT_PERIOD)

        super(BytesWrittenTask, self).__init__("BytesWritten", taskMgr, dashlog,
                                               self.DEBUG_BIT, name, period)

    def _check(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is None or not self.__thread.isAlive():
            self.__badCount = 0

            sendDetails = False
            if self.__detailTimer is not None and \
                    self.__detailTimer.isTime():
                sendDetails = True
                self.__detailTimer.reset()

            self.__thread = \
                BytesWrittenThread(self.__runset, self.logger(),
                                self.__liveMoniClient, sendDetails)
            self.__thread.start()
        else:
            self.__badCount += 1
            if self.__badCount <= 3:
                self.logError("WARNING: BytesWritten thread is hanging (#%d)" %
                              self.__badCount)
            else:
                self.logError("ERROR: Bytes written monitoring seems to be" +
                              " stuck, monitoring will not be done")
                self.endTimer()

    def _reset(self):
        self.__badCount = 0
        self.__thread = None
        self.__detailTimer = None

    def close(self):
        pass

    def waitUntilFinished(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
