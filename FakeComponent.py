#!/usr/bin/env python

import random
import struct
import sys
import threading
import time
from CnCServer import Connector
from FakeClient import FakeClient, FakeClientException
from payload import SimpleHit, MonitorASCII, Supernova


class FakeError(Exception):
    """Component error"""
    pass


class StringHub(FakeClient):
    def __init__(self, comp_name, comp_num, def_dom_geom, conn_list,
                 mbean_dict, quiet=False):
        self.__doms = def_dom_geom.getDomsOnString(comp_num)

        self.__threads = []
        self.__running = True

        super(StringHub, self).__init__(comp_name, comp_num, conn_list,
                                        mbean_dict, numeric_prefix=False,
                                        quiet=quiet)

    def __send_sn(self, conn):
        delay = 3

        daq_tick = 0x1234567890abcde
        while self.__running:
            dom = random.choice(self.__doms)
            scaler_bytes = [9, 8, 7, 6, 5, 4, 3, 2, 1]

            dom_clock = daq_tick & 0xffffffffffff

            snova = Supernova(daq_tick, int(dom.mbid(), 16), dom_clock,
                              scaler_bytes)
            conn.push(snova.bytes)

            time.sleep(delay)
            daq_tick += 10000000000 * delay

        stop = StopMessage()
        conn.push(stop.bytes)

    def __send_moni(self, conn):
        delay = 5

        daq_tick = 0x1234567890abcde
        spe_count = 5
        mpe_count = 6
        launches = 7
        dropped = 0

        while self.__running:
            dom = random.choice(self.__doms)

            dom_clock = daq_tick & 0xffffffffffff
            #clock_bytes = []
            #for idx in range(6):
            #    clock_bytes.insert(0, dom_clock & 0xff)
            clock_bytes = dom_clock

            spe_count += 4
            mpe_count += 2
            launches = (launches + 4) & 0xff
            dropped = (dropped + 2) & 0xff
            ascii_data = "F %d %d %d %d" % (spe_count, mpe_count, launches,
                                            dropped)

            moni = MonitorASCII(daq_tick, int(dom.mbid(), 16), clock_bytes,
                                ascii_data)
            conn.push(moni.bytes)

            time.sleep(delay)
            daq_tick += 10000000000 * delay

        stop = StopMessage()
        conn.push(stop.bytes)

    def __send_tcal(self, conn):
        self.__send_simple_hits(conn)

    def __send_simple_hits(self, conn):
        delay = 1

        daq_tick = 0x1234567890abcde
        while self.__running:
            trig_type = 2
            config_id = 3
            source_id = 4
            dom = random.choice(self.__doms)
            trig_mode = 5

            hit = SimpleHit(daq_tick, trig_type, config_id, source_id,
                            int(dom.mbid(), 16), trig_type)
            conn.push(hit.bytes)
            time.sleep(1)
            daq_tick += 10000000000 * delay

        stop = StopMessage()
        conn.push(stop.bytes)

    def start_run(self, run_num):
        for name in ("snData", "moniData", "tcalData"):
            engine = self.get_output_connector(name)
            if engine is None:
                continue

            chan = None
            for ech in engine.channels:
                if chan is None:
                    chan = ech
                else:
                    raise SystemExit("Multiple channels found for %s:%s" %
                                     (self, name))
            if chan is None:
                    raise SystemExit("No channels found for %s:%s" %
                                     (self, name))

            if name == "snData":
                func = self.__send_sn
            elif name == "moniData":
                func = self.__send_moni
            elif name == "tcalData":
                func = self.__send_tcal
            else:
                continue

            thrd = threading.Thread(name=name+"Thread", target=func,
                                    args=(chan, ))
            thrd.start()

            self.__threads.append(thrd)

    def stop_run(self):
        self.__running = False


class TriggerHandler(FakeClient):

    def __init__(self, comp_name, comp_num, inputName, outputName,
                 prescale=1000, quiet=False):
        self.__prescale = prescale

        self.__outName = outputName
        self.__outConn = None
        self.__trigCount = 0
        self.__hitCount = 0

        conn_list = [
            (inputName, Connector.INPUT),
            (outputName, Connector.OUTPUT),
        ]
        mbean_dict = {}

        super(TriggerHandler, self).__init__(comp_name, comp_num, conn_list,
                                             mbean_dict, numeric_prefix=False,
                                             quiet=quiet)

    def makeTriggerRequest(self, trigType, cfgId, startTime, endTime):
        # XXX this should be moved to payload.py
        PAYLEN = 104

        PAYTYPE_TRIGREQ = 9
        RECTYPE_TRIGREQ = 4

        RR_TYPE = 0xf
        RR_GLOBAL = 0
        RR_SRC = -1
        RR_DOM = -1L

        uid = self.__trigCount
        self.__trigCount += 1

        rec = struct.pack(">iiqhiiiiqqhiiiiiqqqihh", PAYLEN, PAYTYPE_TRIGREQ,
                          startTime, RECTYPE_TRIGREQ, uid, trigType, cfgId,
                          self.sourceId(), startTime, endTime, RR_TYPE, uid,
                          self.sourceId(), 1, RR_GLOBAL, RR_SRC, startTime,
                          endTime, RR_DOM, 8, 0, 0)

        if len(rec) != PAYLEN:
            raise FakeClientException(('Expected %d-byte payload,'
                                       'not %d bytes') % (PAYLEN, len(rec)))

        return rec

    def XXXprocessData(self, data):
        if self.__outConn is None:
            self.__outConn = self.get_output_connector(self.__outName)
            if self.__outConn is None:
                raise FakeError("Cannot find %s output connector" %
                                (self.__outName, ))

        pos = 0
        while True:
            if pos + 4 > len(data):
                break

            payLen = struct.unpack(">i", data[pos: pos + 4])[0]
            if payLen == 4:
                print >>sys.stderr, "%s saw STOPMSG" % self.fullname
                break

            if payLen < 16:
                print >>sys.stderr, "%s saw unexpected %d-byte payload" % \
                      (self.fullname, payLen)
            elif len(data) < payLen:
                print >>sys.stderr, \
                      "%s expected %d bytes, but only %d are available" % \
                      (self.fullname, payLen, len(data))
            else:
                payType, utc = struct.unpack(">iq", data[pos + 4: pos + 16])
                self.XXXprocessPayload(payType, utc,
                                       data[pos + 16: pos + payLen])

            pos += payLen

    def XXXprocessPayload(self, payType, utc, payload):
        raise NotImplementedError("Unimplemented")

    def send(self, data):
        self.__outConn.send(data)

    def sourceId(self):
        raise NotImplementedError("Unimplemented")


class LocalTrigger(TriggerHandler):

    TRIG_TYPE = 99
    TRIG_CFGID = 99999

    def __init__(self, comp_name, comp_num, inputName, prescale=1000):

        self.__outputName = "trigger"

        self.__hitCount = 0
        self.__trigCount = 0

        super(LocalTrigger, self).__init__(comp_name, comp_num, inputName,
                                           self.__outputName, prescale)

    def XXXprocessPayload(self, payType, utc, payload):
        if payType != SimpleHit.TYPE_ID:
            print >>sys.stderr, "Unexpected %s payload type %d" % \
                  (self.fullname, payType)
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

    def XXXprocessPayload(self, payType, utc, payload):
        if payType != PayloadType.TRIGGER_REQUEST:
            print >> sys.stderr, "Unexpected %s payload type %d" % \
                (self.fullname, payType)
            return

        recType, uid, trigType, cfgId, srcId, startTime, endTime, \
            rReqType, rReqUid, rReqSrcId, numReq \
            = struct.unpack(">hiiiiqqhiii", payload[0:63])

        pos = 64

        elems = []
        for i in range(numReq):
            elems.append(struct.unpack(">iiqqq", payload[pos: pos + 32]))
            pos += 32

        compLen, compType, numComp \
            = struct.unpack(">ihh", payload[pos: pos + 8])

        if numComp > 0:
            print >>sys.stderr, "%s ignoring %d composites" % self.fullname

        tr = self.makeTriggerRequest(self.TRIG_TYPE, self.TRIG_CFGID,
                                     startTime, endTime)
        self.__outConn.send(tr)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("-p", "--firstPortNumber", type=int, dest="firstPort",
                        default=FakeClient.NEXT_PORT,
                        help="First port number used for fake components")
    parser.add_argument("component")

    args = parser.parse_args()

    if args.firstPort != FakeClient.NEXT_PORT:
        FakeClient.NEXT_PORT = args.firstPort

    lowName = args.component.lower()
    if lowName == "inicetrigger":
        comp = InIceTrigger()
    elif lowName == "icetoptrigger":
        comp = IceTopTrigger()
    elif lowName == "globaltrigger":
        comp = GlobalTrigger()
    else:
        parser.error("Unknown component \"%s\"" % args.component)

    comp.start()
    while True:
        try:
            comp.register()
        except FakeClientException:
            print >>sys.stderr, "Waiting for CnCServer"
            time.sleep(1)
            continue

        try:
            if not comp.monitor_server():
                break
        except:
            import traceback
            traceback.print_exc()
