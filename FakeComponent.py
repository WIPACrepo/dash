#!/usr/bin/env python

import struct
import sys
import time
from CnCServer import Connector
from FakeClient import FakeClient, FakeClientException


class PayloadType(object):
    SIMPLE_HIT = 1
    TRIGGER_REQUEST = 9


class Error(Exception):
    """Error exception used in this class
    but not defined"""
    pass


class TriggerHandler(FakeClient):

    def __init__(self, compName, compNum, inputName, outputName,
                 prescale=1000):
        self.__prescale = prescale

        self.__outName = outputName
        self.__outConn = None
        self.__trigCount = 0
        self.__hitCount = 0

        connList = [(inputName, Connector.INPUT),
                    (outputName, Connector.OUTPUT)]
        mbeanDict = {}

        super(TriggerHandler, self).__init__(compName, compNum, connList,
                                             mbeanDict, createXmlRpcServer=True,
                                             addNumericPrefix=False)

    def makeTriggerRequest(self, trigType, cfgId, startTime, endTime):
        PAYLEN = 104

        RECTYPE_TRIGREQ = 4

        RR_TYPE = 0xf
        RR_GLOBAL = 0
        RR_SRC = -1
        RR_DOM = -1L

        uid = self.__trigCount
        self.__trigCount += 1

        rec = struct.pack(">iiqhiiiiqqhiiiiiqqqihh",
                          PAYLEN, PayloadType.TRIGGER_REQUEST, startTime,
                          RECTYPE_TRIGREQ, uid, trigType, cfgId,
                          self.sourceId(), startTime, endTime, RR_TYPE, uid,
                          self.sourceId(), 1, RR_GLOBAL, RR_SRC, startTime,
                          endTime, RR_DOM, 8, 0, 0)

        if len(rec) != PAYLEN:
            raise FakeClientException(('Expected %d-byte payload,'
                                       'not %d bytes') % (PAYLEN,
                                                          len(rec)))

        return rec

    def processData(self, data):
        if self.__outConn is None:
            self.__outConn = self.getOutputConnector(self.__outName)
            if self.__outConn is None:
                raise Error("Cannot find %s output connector" %
                            self.__outName)

        pos = 0
        while True:
            if pos + 4 > len(data):
                break

            payLen = struct.unpack(">i", data[pos: pos + 4])[0]
            if payLen == 4:
                print >>sys.stderr, "%s saw STOPMSG" % self.fullName()
                break

            if payLen < 16:
                print >>sys.stderr, "%s saw unexpected %d-byte payload" % \
                      (self.fullName(), payLen)
            elif len(data) < payLen:
                print >>sys.stderr, \
                      "%s expected %d bytes, but only %d are available" % \
                      (self.fullName(), payLen, len(data))
            else:
                payType, utc = struct.unpack(">iq", data[pos + 4: pos + 16])
                self.processPayload(payType, utc, data[pos + 16: pos + payLen])

            pos += payLen

    def send(self, data):
        self.__outConn.send(data)


class LocalTrigger(TriggerHandler):

    TRIG_TYPE = 99
    TRIG_CFGID = 99999

    def __init__(self, compName, compNum, inputName, prescale=1000):

        self.__outputName = "trigger"

        self.__hitCount = 0
        self.__trigCount = 0

        super(LocalTrigger, self).__init__(compName, compNum, inputName,
                                         self.__outputName, prescale)

    def processPayload(self, payType, utc, payload):
        if payType != PayloadType.SIMPLE_HIT:
            print >>sys.stderr, "Unexpected %s payload type %d" % \
                  (self.fullName(), payType)
            return

        self.__hitCount += 1
        if (self.__hitCount % self.__prescale) == 0:
            trigType, cfgId, srcId, domId, trigMode = \
                      struct.unpack(">iiiqh", payload)

            startTime = utc - 2500
            endTime = utc + 2500

            tr = self.makeTriggerRequest(self.TRIG_TYPE, self.TRIG_CFGID,
                                         startTime, endTime)
            self.send(tr)


class InIceTrigger(TriggerHandler):

    def __init__(self, prescale=1000):

        self.__outputName = "trigger"

        super(InIceTrigger, self).__init__("inIceTrigger", 0, "stringHit",
                                           self.__outputName, prescale)


class IceTopTrigger(TriggerHandler):

    def __init__(self, prescale=1000):

        self.__outputName = "trigger"

        super(IceTopTrigger, self).__init__("iceTopTrigger", 0, "icetopHit",
                                            self.__outputName, prescale)


class GlobalTrigger(TriggerHandler):

    TRIG_TYPE = -1
    TRIG_CFGID = -1

    def __init__(self, prescale=1000):

        self.__outputName = "glblTrig"

        self.__trigCount = 0

        super(GlobalTrigger, self).__init__("globalTrigger", 0, "trigger",
                                            self.__outputName, prescale)

    def processPayload(self, payType, utc, payload):
        if payType != PayloadType.TRIGGER_REQUEST:
            print >> sys.stderr, "Unexpected %s payload type %d" % \
                (self.fullName(), payType)
            return

        recType, uid, trigType, cfgId, srcId, startTime, endTime, \
                 rReqType, rReqUid, rReqSrcId, numReq = \
                 struct.unpack(">hiiiiqqhiii", payload[0:63])

        pos = 64

        elems = []
        for i in range(numReq):
            elems.append(struct.unpack(">iiqqq", payload[pos: pos + 32]))
            pos += 32

        compLen, compType, numComp = \
                 struct.unpack(">ihh", payload[pos: pos + 8])

        if numComp > 0:
            print >>sys.stderr, "%s ignoring %d composites" % self.fullName()

        tr = self.makeTriggerRequest(self.TRIG_TYPE, self.TRIG_CFGID,
                                     startTime, endTime)
        self.__outConn.send(tr)


class TrackEngine(TriggerHandler):

    HIT_LEN = 11

    def __init__(self, prescale=1000):

        self.__outputName = "trigger"

        super(TrackEngine, self).__init__("trackEngine", 0, "trackEngHit",
                                          self.__outputName, prescale)

    def processData(self, data):
        if self.__outConn is None:
            self.__outConn = self.getOutputConnector(self.__outputName)
            if self.__outConn is None:
                raise Error("Cannot find %s output connector" %
                            self.__outputName)

        pos = 0
        while True:
            if len(data) < self.HIT_LEN:
                print >>sys.stderr, \
                      "%s expected %d bytes, but only %d are available" % \
                      (self.fullName(), self.HIT_LEN, len(data))
                break

            major, minor, utc, lcMode = \
                   struct.unpack(">bbqb", data[pos: pos + self.HIT_LEN])

            if major == 0 and minor == 0 and utc == 0 and lcMode == 0:
                print >>sys.stderr, "%s saw STOPMSG" % self.fullName()
                break

            self.__hitCount += 1
            if (self.__hitCount % self.__prescale) == 0:
                startTime = utc - 2500
                endTime = utc + 2500

                tr = self.makeTriggerRequest(startTime, endTime)
                self.__outConn.send(tr)

            pos += self.HIT_LEN

if __name__ == "__main__":
    import optparse

    parser = optparse.OptionParser()

    parser.add_option("-p", "--firstPortNumber", type="int", dest="firstPort",
                      action="store", default=FakeClient.NEXT_PORT,
                      help="First port number used for fake components")

    opt, args = parser.parse_args()

    if opt.firstPort != FakeClient.NEXT_PORT:
        FakeClient.NEXT_PORT = opt.firstPort

    if len(args) == 0:
        parser.error("Please specify a component to be run")
    elif len(args) > 1:
        parser.error("Please specify only one component to be run")

    lowName = args[0].lower()
    if lowName == "trackengine":
        comp = TrackEngine()
    elif lowName == "inicetrigger":
        comp = InIceTrigger()
    elif lowName == "icetoptrigger":
        comp = IceTopTrigger()
    elif lowName == "globaltrigger":
        comp = GlobalTrigger()
    else:
        parser.error("Unknown component \"%s\"" % args[0])

    comp.start()
    while True:
        try:
            comp.register()
        except FakeClientException:
            print >>sys.stderr, "Waiting for CnCServer"
            time.sleep(1)
            continue

        try:
            if not comp.monitorServer():
                break
        except:
            import traceback
            traceback.print_exc()
