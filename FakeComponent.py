#!/usr/bin/env python

from __future__ import print_function

import datetime
import os
import random
import struct
import sys
import threading
import time
from CnCServer import Connector
from FakeClient import FakeClient, FakeClientException, PortNumber
from payload import PayloadReader, SimpleHit, MonitorASCII, StopMessage, \
    Supernova


class FakeError(Exception):
    """Component error"""


class PayloadGenerator(object):
    def __init__(self, first_tick=None, delay=None):
        if first_tick is None:
            self.__daq_tick = int(0x1234567890abcde)
        else:
            self.__daq_tick = int(first_tick)

        if delay is None:
            self.__delay = 1
        else:
            self.__delay = delay

    def __next__(self):
        try:
            return self.generate()
        finally:
            self.__daq_tick += int(1E10 * self.__delay)

    @property
    def daq_tick(self):
        return self.__daq_tick

    @property
    def delay(self):
        return self.__delay

    def generate(self):
        raise NotImplementedError()

    next = __next__  # XXX backward compatibility for Python 2


class MoniGenerator(PayloadGenerator):
    def __init__(self, doms, first_tick=None, delay=5):
        self.__doms = doms
        self.__spe_count = 5
        self.__mpe_count = 6
        self.__launches = 7
        self.__dropped = 0

        super(MoniGenerator, self).__init__(first_tick=first_tick, delay=delay)

    def generate(self):
        dom = random.choice(self.__doms)

        clock_bytes = self.daq_tick & 0xffffffffffff

        self.__spe_count += 4
        self.__mpe_count += 2
        self.__launches = (self.__launches + 4) & 0xff
        self.__dropped = (self.__dropped + 2) & 0xff
        ascii_data = "F %d %d %d %d" % (self.__spe_count, self.__mpe_count,
                                        self.__launches, self.__dropped)

        return MonitorASCII(self.daq_tick, int(dom.mbid, 16), clock_bytes,
                            ascii_data.encode())


class SimpleHitGenerator(PayloadGenerator):
    def __init__(self, src_id, doms, first_tick=None, delay=1):
        self.__src_id = src_id
        self.__doms = doms
        self.__delay = delay

        super(SimpleHitGenerator, self).__init__(first_tick=first_tick,
                                                 delay=delay)

    def generate(self):
        trig_type = 2
        config_id = 3
        dom = random.choice(self.__doms)

        return SimpleHit(self.daq_tick, trig_type, config_id, self.__src_id,
                         int(dom.mbid, 16), trig_type)


class SupernovaGenerator(PayloadGenerator):
    def __init__(self, doms, first_tick=None, delay=3):
        self.__doms = doms

        super(SupernovaGenerator, self).__init__(first_tick=first_tick,
                                                 delay=delay)

    def generate(self):
        dom = random.choice(self.__doms)
        scaler_bytes = [9, 8, 7, 6, 5, 4, 3, 2, 1]

        dom_clock = self.daq_tick & 0xffffffffffff

        return Supernova(self.daq_tick, int(dom.mbid, 16), dom_clock,
                         scaler_bytes)


class TimeCalibrationGenerator(SimpleHitGenerator):
    def __init__(self, src_id, doms, first_tick=None, delay=5):
        super(TimeCalibrationGenerator, self).__init__(src_id, doms,
                                                       first_tick=first_tick,
                                                       delay=delay)


class StringHub(FakeClient):
    def __init__(self, comp_name, comp_num, def_dom_geom, conn_list,
                 quiet=False):
        self.__doms = def_dom_geom.doms_on_string(comp_num)

        self.__hit_file_name = None
        self.__moni_file_name = None
        self.__sn_file_name = None
        self.__tcal_file_name = None

        self.__threads = []
        self.__running = True

        super(StringHub, self).__init__(comp_name, comp_num, conn_list,
                                        numeric_prefix=False,
                                        quiet=quiet)

    @classmethod
    def __time_difference(cls, now, then):
        if then is None:
            return 0.0

        dif = now - then
        return float(dif.seconds + dif.days * 86400) + \
            float(dif.microseconds) / 1E6

    def __send_payloads(self, src, conn):
        prev_tick = None
        prev_time = datetime.datetime.utcnow()

        while self.__running:
            # get the next payload
            payload = next(src)
            if payload is None:
                # if we're out of payloads, exit the loop
                break

            # wait until it's time to send this payload
            now = datetime.datetime.utcnow()
            if prev_tick is not None:
                time_diff = self.__time_difference(now, prev_time)
                tick_diff = float(payload.utime - prev_tick) / 1E10

                sleep_secs = time_diff - tick_diff
                if sleep_secs > 0.001:
                    time.sleep(sleep_secs)

            # remember time for next trip through this loop
            prev_tick = payload.utime
            prev_time = now

            # send the next payload
            conn.push(payload.bytes)

        stop = StopMessage()
        conn.push(stop.bytes)

    def set_hit_file(self, filename):
        if not os.path.exists(filename):
            raise FakeClientException("%s hit file \"%s\" does not exist" ^
                                      (self.fullname, filename))
        self.__hit_file_name = filename

    def set_moni_file(self, filename):
        if not os.path.exists(filename):
            raise FakeClientException("%s moni file \"%s\" does not exist" ^
                                      (self.fullname, filename))
        self.__moni_file_name = filename

    def set_sn_file(self, filename):
        if not os.path.exists(filename):
            raise FakeClientException("%s sn file \"%s\" does not exist" ^
                                      (self.fullname, filename))
        self.__sn_file_name = filename

    def set_tcal_file(self, filename):
        if not os.path.exists(filename):
            raise FakeClientException("%s tcal file \"%s\" does not exist" ^
                                      (self.fullname, filename))
        self.__tcal_file_name = filename

    def start_run(self, run_num):
        for name in ("stringHit", "icetopHit", "snData", "moniData",
                     "tcalData"):
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
                raise SystemExit("No channels found for %s:%s" % (self, name))

            if name == "moniData":
                if self.__moni_file_name is None:
                    src = MoniGenerator(self.__doms)
                else:
                    src = PayloadReader(self.__moni_file_name)
            elif name == "snData":
                if self.__sn_file_name is None:
                    src = SupernovaGenerator(self.__doms)
                else:
                    src = PayloadReader(self.__sn_file_name)
            elif name == "tcalData":
                if self.__tcal_file_name is None:
                    src = TimeCalibrationGenerator(self.num, self.__doms)
                else:
                    src = PayloadReader(self.__tcal_file_name)
            elif name in ("stringHit", "icetopHit"):
                if self.__hit_file_name is None:
                    src = SimpleHitGenerator(self.num, self.__doms)
                else:
                    src = PayloadReader(self.__hit_file_name)
            else:
                continue

            thrd = threading.Thread(name=name+"Thread",
                                    target=self.__send_payloads,
                                    args=(src, chan, ))
            thrd.start()

            self.__threads.append(thrd)

    def stop_run(self):
        self.__running = False


class TriggerHandler(FakeClient):
    TRIGGER_REQUEST_ID = 9

    def __init__(self, comp_name, comp_num, input_name, output_name,
                 prescale=1000, quiet=False):
        self.__prescale = prescale

        self.__out_name = output_name
        self.__out_conn = None
        self.__trig_count = 0
        self.__hit_count = 0

        conn_list = [
            (input_name, Connector.INPUT),
            (output_name, Connector.OUTPUT),
        ]
        mbean_dict = {}

        super(TriggerHandler, self).__init__(comp_name, comp_num, conn_list,
                                             mbean_dict=mbean_dict,
                                             numeric_prefix=False, quiet=quiet)

    def make_trigger_request(self, trig_type, cfg_id, start_time, end_time):
        # XXX this should be moved to payload.py
        paylen = 104

        rectype_trigreq = 4

        rr_type = 0xf
        rr_global = 0
        rr_src = -1
        rr_dom = -1

        uid = self.__trig_count
        self.__trig_count += 1

        rec = struct.pack(">iiqhiiiiqqhiiiiiqqqihh", paylen,
                          self.TRIGGER_REQUEST_ID, start_time, rectype_trigreq,
                          uid, trig_type, cfg_id, self.source_id, start_time,
                          end_time, rr_type, uid, self.source_id, 1, rr_global,
                          rr_src, start_time, end_time, rr_dom, 8, 0, 0)

        if len(rec) != paylen:
            raise FakeClientException(('Expected %d-byte payload,'
                                       'not %d bytes') % (paylen, len(rec)))

        return rec

    def send(self, data):
        self.__out_conn.send(data)


class LocalTrigger(TriggerHandler):

    TRIG_TYPE = 99
    TRIG_CFGID = 99999

    def __init__(self, comp_name, comp_num, input_name, prescale=1000):

        self.__output_name = "trigger"

        self.__hit_count = 0
        self.__trig_count = 0

        super(LocalTrigger, self).__init__(comp_name, comp_num, input_name,
                                           self.__output_name, prescale)

    def xxx_process_payload(self, pay_type,
                            utc, payload):  # pylint: disable=unused-argument
        if pay_type != SimpleHit.TYPE_ID:
            print("Unexpected %s payload type %d" %
                  (self.fullname, pay_type), file=sys.stderr)
            return

        self.__hit_count += 1
        if (self.__hit_count % self.__prescale) == 0:
            # trig_type, cfg_id, src_id, dom_id, trig_mode = \
            #           struct.unpack(">iiiqh", payload)

            start_time = utc - 2500
            end_time = utc + 2500

            trig_req = self.make_trigger_request(self.TRIG_TYPE,
                                                 self.TRIG_CFGID,
                                                 start_time, end_time)
            self.send(trig_req)


class InIceTrigger(TriggerHandler):

    def __init__(self, prescale=1000):

        self.__output_name = "trigger"

        super(InIceTrigger, self).__init__("inIceTrigger", 0, "stringHit",
                                           self.__output_name,
                                           prescale=prescale)


class IceTopTrigger(TriggerHandler):

    def __init__(self, prescale=1000):

        self.__output_name = "trigger"

        super(IceTopTrigger, self).__init__("iceTopTrigger", 0, "icetopHit",
                                            self.__output_name, prescale)


class GlobalTrigger(TriggerHandler):
    TRIG_TYPE = -1
    TRIG_CFGID = -1

    def __init__(self, prescale=1000):

        self.__output_name = "glblTrig"

        self.__trig_count = 0

        super(GlobalTrigger, self).__init__("globalTrigger", 0, "trigger",
                                            self.__output_name, prescale)

    def xxx_process_payload(self, pay_type,
                            utc, payload):  # pylint: disable=unused-argument
        if pay_type != self.TRIGGER_REQUEST_ID:
            print("Unexpected %s payload type %d" %
                  (self.fullname, pay_type), file=sys.stderr)
            return

        _, _, _, _, _, start_time, end_time, _, _, _, num_req \
            = struct.unpack(">hiiiiqqhiii", payload[0:63])

        pos = 64

        elems = []
        for _ in range(num_req):
            elems.append(struct.unpack(">iiqqq", payload[pos: pos + 32]))
            pos += 32

        _, _, num_comp \
            = struct.unpack(">ihh", payload[pos: pos + 8])

        if num_comp > 0:
            print("%s ignoring %d composites" % (self.fullname, num_comp),
                  file=sys.stderr)

        trig_req = self.make_trigger_request(self.TRIG_TYPE, self.TRIG_CFGID,
                                             start_time, end_time)
        self.__out_conn.send(trig_req)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("-p", "--firstPortNumber", type=int, dest="first_port",
                        help="First port number used for fake components")
    parser.add_argument("component")

    args = parser.parse_args()

    if args.first_port is not None:
        PortNumber.set_next_number(args.first_port)

    low_name = args.component.lower()
    if low_name == "inicetrigger":
        comp = InIceTrigger()
    elif low_name == "icetoptrigger":
        comp = IceTopTrigger()
    elif low_name == "globaltrigger":
        comp = GlobalTrigger()
    else:
        parser.error("Unknown component \"%s\"" % args.component)

    comp.start()
    while True:
        try:
            comp.register()
        except FakeClientException:
            print("Waiting for CnCServer", file=sys.stderr)
            time.sleep(1)
            continue

        try:
            if not comp.monitor_server():
                break
        except:  # pylint: disable=bare-except
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
