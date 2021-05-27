#!/usr/bin/env python
"""
Produce a report of the hourly and total data rates for all the components
in the IceCube DAQ, using data from the pDAQ .moni files.
"""

from __future__ import print_function

import os
import re
import sys
import time

MONISEC_PAT = \
    re.compile(r'^(.*):\s+(\d+-\d+-\d+ \d+:\d+:\d+)\.(\d+):\s*$')
MONILINE_PAT = re.compile(r'^\s+([^:]+):\s+(.*)$')

TRIG_PAT = re.compile(r'^\S+Trigger[0-9]*$')

TIMEFMT = '%Y-%m-%d %H:%M:%S'

COMP_FIELDS = {
    'amandaHub': {
        'moniData': 'RecordsSent',
        'snData': 'RecordsSent',
        'tcalData': 'RecordsSent',
        'rdoutReq': 'RecordsReceived',
        'rdoutData': 'RecordsSent'
    },
    'stringHub': {
        'DOM': 'NumHits',
        'sender': 'NumHitsReceived',
        'stringHit': 'RecordsSent',
        'moniData': 'RecordsSent',
        'snData': 'RecordsSent',
        'tcalData': 'RecordsSent',
        'rdoutReq': 'RecordsReceived',
        'rdoutData': 'RecordsSent'
    },
    'icetopHub': {
        'DOM': 'NumHits',
        'sender': 'NumHitsReceived',
        'icetopHit': 'RecordsSent',
        'moniData': 'RecordsSent',
        'snData': 'RecordsSent',
        'tcalData': 'RecordsSent',
        'rdoutReq': 'RecordsReceived',
        'rdoutData': 'RecordsSent'
    },
    'replayHub': {
        'DOM': 'NumHits',
        'sender': 'NumHitsReceived',
        'stringHit': 'RecordsSent',
        'moniData': 'RecordsSent',
        'snData': 'RecordsSent',
        'tcalData': 'RecordsSent',
        'rdoutReq': 'RecordsReceived',
        'rdoutData': 'RecordsSent'
    },
    'inIceTrigger': {
        'stringHit': 'RecordsReceived',
        'trigger': 'RecordsSent'
    },
    'iceTopTrigger': {
        'icetopHit': 'RecordsReceived',
        'trigger': 'RecordsSent'
    },
    'amandaTrigger': {
        'selfContained': 'RecordsReceived',
        'trigger': 'RecordsSent'
    },
    'globalTrigger': {
        'trigger': 'RecordsReceived',
        'glblTrig': 'RecordsSent'
    },
    'eventBuilder': {
        'glblTrig': 'RecordsReceived',
        'rdoutReq': 'RecordsSent',
        'rdoutData': 'RecordsReceived',
        'backEnd': 'NumEventsSent'
    },
    'secondaryBuilders': {
        'moniData': 'RecordsReceived',
        'moniBuilder': 'NumDispatchedData',
        'snData': 'RecordsReceived',
        'snBuilder': 'NumDispatchedData',
        'tcalData': 'RecordsReceived',
        'tcalBuilder': 'NumDispatchedData',
    },
}


class Component(object):
    """Component name/number"""

    def __init__(self, file_name=None):
        if file_name is None:
            comp_name = 'unknown'
            comp_num = 0
        else:
            if len(file_name) < 5 or file_name[-5:] != '.moni':
                raise Exception('Non-moni filename "%s"' % file_name)

            base_name = os.path.basename(file_name)
            idx = base_name.rfind('-')
            if idx <= 0:
                raise Exception("Didn't find '-' separator in \"%s\"" %
                                file_name)

            comp_name = base_name[:idx]
            if comp_name not in COMP_FIELDS:
                raise Exception('Unknown component "%s" in "%s"' %
                                (comp_name, file_name))

            try:
                comp_num = int(base_name[idx + 1: -5])
            except ValueError:
                comp_num = 0

            if comp_name == 'stringHub':
                if comp_num % 100 == 0:
                    comp_name = 'amandaHub'
                elif comp_num % 1000 >= 200:
                    comp_name = 'icetopHub'

        self.name = comp_name
        self.num = comp_num

        self.full_str = None
        self.__hash = None

    def __str__(self):
        if self.full_str is None:
            if self.num == 0:
                self.full_str = self.name
            else:
                self.full_str = "%s-%d" % (self.name, self.num)

        return self.full_str

    @property
    def compare_key(self):
        "Return the keys to be used by the Comparable methods"
        return (self.name, self.num)


def compute_rates(data_dict):
    """Compute rates from the data saved in the data dictionary"""
    keys = list(data_dict.keys())

    prev_time = None
    first_time = None

    rates = []

    for k in sorted(keys):
        if prev_time is None:
            first_time = k
        else:
            secs = k - prev_time
            vals = data_dict[k] - data_dict[prev_time]
            rates.append(float(vals) / float(secs))

        prev_time = k

    if len(rates) == 0:  # pylint: disable=len-as-condition
        rates = None
        tot_rate = None
    elif len(rates) == 1:
        if float(rates[0]) == 0.0:
            tot_rate = None
        else:
            tot_rate = rates[0]
        rates = None
    else:
        tot_secs = prev_time - first_time
        tot_vals = data_dict[prev_time] - data_dict[first_time]
        tot_rate = float(tot_vals) / float(tot_secs)

    return (tot_rate, rates)


def format_rates(rates):
    """format a list of rates"""
    r_str = '['
    need_comma = False
    for rate in rates:
        if not need_comma:
            need_comma = True
        else:
            r_str += ', '
        r_str += '%.1f' % rate
    return r_str + ']'


def process_dir(dir_name, time_interval):
    """Process all .moni files in the specified directory"""
    all_data = {}
    for entry in os.listdir(dir_name):
        if entry.endswith('.log') or entry.endswith('.html') or \
               entry.endswith('.xml') or entry == "logs-queued":
            continue

        try:
            comp = Component(entry)
        except ValueError as msg:
            print(str(msg), file=sys.stderr)
            continue

        all_data[comp] = process_file(os.path.join(dir_name, entry), comp,
                                      time_interval)

    return all_data


class Summary(object):
    def __init__(self, time_interval):
        self.__time_interval = time_interval

        self.__data = {}
        self.__last_saved = {}

    def __save(self, name, stime, vals):
        if vals.startswith('['):
            self.__save_list_sum(name, stime, vals)
        else:
            self.__save_value(name, stime, int(vals))

    def __save_list_sum(self, name, stime, val_str):
        tot = 0
        idx = 0
        while idx < len(val_str) and val_str[idx] != ']':
            nxt = val_str.find(',', idx)
            if nxt < idx:
                nxt = val_str.find(']', idx)
            sub_str = val_str[idx + 1: nxt]
            try:
                tot += int(sub_str)
            except ValueError:
                print("Couldn't get integer value for '%s'"
                      " ('%s' idx %d nxt %d)" % (sub_str, val_str, idx, nxt),
                      file=sys.stderr)
            idx = nxt + 1
        self.__save_value(name, stime, tot)

    def __save_value(self, name, stime, val):
        if val > 0:
            if name != "DOM":
                self.__data[name][stime] = val
            elif stime not in self.__data[name]:
                self.__data[name][stime] = val
            else:
                self.__data[name][stime] += val
            self.__last_saved[name] = stime

    def add(self, name, stime, vals):
        if self.__time_interval is None or \
           (stime > self.__last_saved[name] + self.__time_interval):
            self.__save(name, stime, vals)

    def data(self):
        return self.__data

    def register(self, name):
        if name not in self.__data:
            self.__data[name] = {}
            self.__last_saved[name] = 0.0


def process_file(file_name, comp, time_interval):
    """Process the specified file"""
    if comp.name not in COMP_FIELDS:
        flds = None
    else:
        flds = COMP_FIELDS[comp.name]

    summary = Summary(time_interval)

    sec_name = None
    sec_time = None

    with open(file_name, 'r') as fin:
        for line in fin:
            line = line.rstrip()
            if line == "":
                sec_name = None
                sec_time = None
                continue

            if sec_name is not None:
                if sec_name == "IGNORE":
                    continue

                mtch = MONILINE_PAT.match(line)
                if mtch is not None:
                    name = mtch.group(1)
                    vals = mtch.group(2)

                    if sec_name.find("Trigger") > 0 and \
                       name == "SentTriggerCount":
                        summary.add(sec_name, sec_time, vals)
                        continue

                    if flds is None or \
                       (sec_name in flds and flds[sec_name] == name):
                        summary.add(sec_name, sec_time, vals)
                    continue

            mtch = MONISEC_PAT.match(line)
            if mtch is not None:
                name = mtch.group(1)
                if name not in flds:
                    if name.startswith("DataCollectorMonitor"):
                        name = "DOM"
                    elif name.find("Trigger") >= 0:
                        sec_name = name
                    else:
                        sec_name = "IGNORE"
                        continue

                sec_name = name
                msec = float(mtch.group(3)) / 1000000.0
                sec_time = time.mktime(time.strptime(mtch.group(2),
                                                     TIMEFMT)) + msec

                summary.register(sec_name)

                continue

            print("Bad line: " + line, file=sys.stderr)

    return summary.data()


def report_data_rates(all_data, time_interval, print_secondary=False,
                      verbose=False):
    """Report the DAQ data rates"""
    if print_secondary:
        print('Data Rates:')
    hub_trig_list = [
        ('stringHub', 'DOM'),
        ('stringHub', 'sender'),
        ('stringHub', 'stringHit'),
        ('inIceTrigger', 'stringHit'),
        ('icetopHub', 'DOM'),
        ('icetopHub', 'sender'),
        ('icetopHub', 'icetopHit'),
        ('iceTopTrigger', 'icetopHit'),
    ]

    trig_list = []
    for trig in ('inIceTrigger', 'iceTopTrigger', 'globalTrigger'):
        for comp in list(all_data.keys()):
            if comp.name == trig:
                trig_list.append((trig, 'trigger'))
                for key in list(all_data[comp].keys()):
                    mtch = TRIG_PAT.match(key)
                    if mtch is not None:
                        trig_list.append((trig, key))

    trig_eb_list = [
        ('globalTrigger', 'glblTrig'),
        ('eventBuilder', 'glblTrig'), ('eventBuilder', 'rdoutReq'),
        ('amandaHub', 'rdoutReq'), ('stringHub', 'rdoutReq'),
        ('icetopHub', 'rdoutReq'),
        ('amandaHub', 'rdoutData'), ('stringHub', 'rdoutData'),
        ('icetopHub', 'rdoutData'),
        ('eventBuilder', 'rdoutData'),
        ('eventBuilder', 'backEnd')
    ]
    report_rates_internal(all_data, hub_trig_list + trig_list + trig_eb_list,
                          time_interval, verbose=verbose)


def report_monitor_rates(all_data, time_interval, verbose=False):
    """Report the DAQ monitoring rates"""
    print('Monitoring Rates:')
    report_list = [('amandaHub', 'moniData'), ('stringHub', 'moniData'),
                   ('icetopHub', 'moniData'),
                   ('secondaryBuilders', 'moniData'),
                   ('secondaryBuilders', 'moniBuilder')]
    report_rates_internal(all_data, report_list, time_interval,
                          verbose=verbose)


def report_rates_internal(all_data, report_list, time_interval, verbose=False):
    """Report the rates for the specified set of values"""
    comp_keys = sorted(all_data.keys())

    combined_comp = None
    combined_field = None
    combined_rate = None
    combined_split = None

    for rpt_tuple in report_list:  # pylint: disable=too-many-nested-blocks
        is_combined = rpt_tuple[0].endswith('Hub') or \
            (rpt_tuple[0].endswith('Trigger') and
             rpt_tuple[0] != 'globalTrigger' and rpt_tuple[1] == 'trigger')

        if combined_field is not None:
            if not is_combined or combined_field != rpt_tuple[1]:
                # pylint: disable=bad-string-format-type
                # PyLint thinks 'combined_rate' is None here, disable the check
                if combined_rate is None:
                    print('    %s.%s: Not enough data' %
                          (combined_comp, combined_field))
                elif time_interval is None or \
                  len(combined_split) == 0:  # pylint: disable=len-as-condition
                    print('    %s.%s: %.1f' %
                          (combined_comp, combined_field, combined_rate))
                else:
                    print('    %s.%s: %s  Total: %.1f' %
                          (combined_comp, combined_field,
                           format_rates(combined_split), combined_rate))

                combined_comp = None
                combined_field = None
                combined_rate = None
                combined_split = None

        if is_combined:
            if combined_field is None:
                combined_comp = 'All %ss' % rpt_tuple[0]
                combined_field = rpt_tuple[1]
                combined_rate = None
                combined_split = []
            elif combined_comp is not None:
                if rpt_tuple[0].endswith('Hub'):
                    combined_comp = 'All Hubs'
                else:
                    combined_comp = 'All Triggers'

        need_nl = False
        for comp in comp_keys:
            if not comp.name == rpt_tuple[0]:
                continue

            for sect in all_data[comp]:
                if sect != rpt_tuple[1]:
                    continue

                rate_tuple = compute_rates(all_data[comp][sect])
                if not is_combined or verbose:
                    if not is_combined:
                        indent = ''
                    else:
                        indent = '    '
                    if rate_tuple[0] is None:
                        print('    %s%s.%s: Not enough data' %
                              (indent, comp, sect))
                    elif rate_tuple[1] is None:
                        print('    %s%s.%s: %.1f' %
                              (indent, comp, sect, rate_tuple[0]))
                    else:
                        if time_interval is None:
                            print('    %s%s.%s: %.1f' %
                                  (indent, comp, sect, rate_tuple[0]))
                        else:
                            print('    %s%s.%s: %s  Total: %.1f' %
                                  (indent, comp, sect,
                                   format_rates(rate_tuple[1]),
                                   rate_tuple[0]))
                    need_nl = False

                if combined_comp is not None:
                    if rate_tuple[0] is not None:
                        if combined_rate is None:
                            combined_rate = 0.0
                        combined_rate += rate_tuple[0]
                    if rate_tuple[1] is not None:
                        tuple_len = len(rate_tuple[1])
                        if len(combined_split) < tuple_len:
                            for i in range(len(combined_split), tuple_len):
                                combined_split.append(0.0)
                        for i in range(0, tuple_len):
                            combined_split[i] += rate_tuple[1][i]

        if need_nl:
            print('')
            need_nl = False


def report_supernova_rates(all_data, time_interval, verbose=False):
    """Report the DAQ supernova rates"""
    print('Supernova _rates:')
    report_list = [('amandaHub', 'snData'), ('stringHub', 'snData'),
                   ('icetopHub', 'snData'), ('secondaryBuilders', 'snData'),
                   ('secondaryBuilders', 'snBuilder')]
    report_rates_internal(all_data, report_list, time_interval,
                          verbose=verbose)


def report_time_cal_rates(all_data, time_interval, verbose=False):
    """Report the DAQ time calibration rates"""
    print('TimeCal Rates:')
    report_list = [('amandaHub', 'tcalData'), ('stringHub', 'tcalData'),
                   ('icetopHub', 'tcalData'),
                   ('secondaryBuilders', 'tcalData'),
                   ('secondaryBuilders', 'tcalBuilder')]
    report_rates_internal(all_data, report_list, time_interval,
                          verbose=verbose)


def report_rates(all_data, time_interval, print_secondary=False,
                 verbose=False):
    """Report the DAQ rates"""
    if print_secondary:
        report_monitor_rates(all_data, time_interval, verbose=verbose)
        report_supernova_rates(all_data, time_interval, verbose=verbose)
        report_time_cal_rates(all_data, time_interval, verbose=verbose)
    report_data_rates(all_data, time_interval, print_secondary=print_secondary,
                      verbose=verbose)


def main():
    "Main program"

    bad_arg = False
    grab_time_interval = False

    time_interval = None
    print_secondary = True
    verbose = False

    dir_list = []
    file_list = []
    for arg in sys.argv[1:]:
        if grab_time_interval:
            time_interval = int(arg)
            grab_time_interval = False
        elif arg == '-v':
            if not verbose:
                verbose = True
        elif arg == '-d':
            print_secondary = False
        elif arg.startswith('-i'):
            if arg == '-i':
                grab_time_interval = True
            else:
                time_interval = int(arg[2:])
        elif os.path.isdir(arg):
            dir_list.append(arg)
        elif os.path.exists(arg):
            file_list.append(arg)
        else:
            print('Unknown argument "%s"' % arg, file=sys.stderr)
            bad_arg = True

    dir_len = len(dir_list)
    file_len = len(file_list)
    if dir_len > 0 and file_len > 0:
        print('Cannot specify both directories and files', file=sys.stderr)
        bad_arg = True
    elif dir_len == 0 and file_len == 0:
        print('Please specify a moni file or directory', file=sys.stderr)
        bad_arg = True

    if bad_arg:
        print(('Usage: %s' +
               ' [-d(ataOnly)]' +
               ' [-i timeInterval ]' +
               ' [-v(erbose)]' +
               ' (moniDir | moniFile [...])') % sys.argv[0], file=sys.stderr)
        sys.exit(1)

    if file_len > 0:
        all_data = {}
        for fname in file_list:
            try:
                comp = Component(fname)
            except ValueError as msg:
                print(str(msg), file=sys.stderr)
                comp = Component()

            all_data[comp] = process_file(fname, comp, time_interval)
            report_rates(all_data, time_interval,
                         print_secondary=print_secondary, verbose=verbose)
    else:
        for dname in dir_list:
            print('Directory ' + dname)
            all_data = process_dir(dname, time_interval)
            report_rates(all_data, time_interval,
                         print_secondary=print_secondary, verbose=verbose)


if __name__ == "__main__":
    main()
