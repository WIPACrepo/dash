#!/usr/bin/env python
"""
a generator which reads a pDAQ .moni file and returns a stream of tuples
of (date_string, category, field, value)

Also contains parse_date() which is a method to convert date strings into
'datetime.datetime' values
"""

from __future__ import print_function

import ast
import datetime
import re
import sys

CATTIME_PAT = re.compile(r"^([^:]+):\s(\d+-\d+-\d+\s\d+:\d+:\d+\.\d+):\s*$")


def moni_stream(filename, fix_values=True, fix_profile=False,
                ignored_func=None, total_fields=None):
    """
    Read a pDAQ .moni file and return a stream of tuples containing
    (date_string, category, field, value).
    * if 'fix_values' is True, value strings will be translated into Python
      data types
    * if 'fix_profile' is True, all ProfileTimes fields have their lists of
      profiling data stripped down to just the counts
    * ignored_func(category, fieldname) is an optional function which
      returns True if this category field should be ignored
    * if a field name is in the 'total_fields' list and the value is a
      dictionary, a 'Total' entry will be added

    """
    cur_cat = None
    cur_date = None

    for line in open(filename, "r"):
        line = line.rstrip()

        if line == "":
            continue

        mtch = CATTIME_PAT.match(line)
        if mtch is not None:
            cur_cat = mtch.group(1)
            if cur_date != mtch.group(2):
                cur_date = mtch.group(2)

            continue

        colon = line.find(": ", 0)
        if colon < 0:
            continue

        fldstr = line[:colon].strip()

        # fix field name
        if fldstr.startswith("'") and fldstr.endswith("'"):
            field = fldstr[1:-1]
        elif fldstr.startswith('"') and fldstr.endswith('"'):
            field = fldstr[1:-1]
        else:
            field = fldstr

        if ignored_func is not None and ignored_func(cur_cat, field):
            continue

        valstr = line[colon+2:].strip()
        if not fix_values:
            value = valstr
        else:
            try:
                value = ast.literal_eval(valstr)
            except ValueError:
                value = valstr
            except SyntaxError:
                value = valstr

            # XXX this is a hack
            is_profile = fix_profile and field == "ProfileTimes"

            if is_profile and isinstance(value, dict):
                for dkey, dval in list(value.items()):
                    # only keep the "count" field
                    value[dkey] = int(dval[0])

            # should we add a Total entry for this field?
            add_total = total_fields is not None and field in total_fields
            if add_total and isinstance(value, dict):
                try:
                    total = sum(value.values())
                    value["Total"] = total
                except TypeError:
                    pass

        yield (cur_date, cur_cat, field, value)


def parse_date(datestr):
    "Parse a DAQ moni date string and return a datetime object"
    date_fmt = "%Y-%m-%d %H:%M:%S.%f"
    if date_fmt.find(".") > 0:
        return datetime.datetime.strptime(datestr, date_fmt)

    no_subsec_fmt = "%Y-%m-%d %H:%M:%S"
    return datetime.datetime.strptime(datestr, no_subsec_fmt)


def compute_delta(delta_values, category, field, value):
    key = "%s:%s" % (category, field)
    if key not in delta_values:
        delta_values[key] = value
        # don't have a 'delta' yet so don't return this value
        return None

    tmpval = value - delta_values[key]
    delta_values[key] = value
    return tmpval


def main():
    "Main program"

    # Sample method using moni_stream()
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--delta", dest="delta_fields", action="append",
                        help="Names of fields which should be 'deltafied'")
    parser.add_argument("-s", "--standard-fixes", dest="standard_fixes",
                        action="store_true", default=False,
                        help="Use the standard settings")
    parser.add_argument("-p", "--fix-profile-times", dest="fix_profile",
                        action="store_true", default=False,
                        help="Only include the count field from ProfileTimes")
    parser.add_argument("-t", "--total", dest="total_fields", action="append",
                        help=("Names of fields whose dictionary values should"
                              " include a 'Total' field"))
    parser.add_argument("-x", "--debug", dest="debug",
                        action="store_true", default=False,
                        help="Enable debugging")
    parser.add_argument(dest="files", nargs="+")

    args = parser.parse_args()

    # initialize delta and total field lists
    if not args.standard_fixes:
        delta_fields = args.delta_fields
        total_fields = args.total_fields
    else:
        delta_fields = [
            "RecordsSent", "TotalProcessed", "TotalRecordsReceived",
            "TotalRequestsCollected", "TotalRequestsReleased",
            "TotalStrandDepth", "SentTriggerCount", "TriggerCounter",
        ]
        if args.delta_fields is not None:
            delta_fields += args.delta_fields
        total_fields = ["QueuedInputs", ]
        if args.total_fields is not None:
            total_fields += args.total_fields

    for fname in args.files:
        if not fname.endswith(".moni"):
            print("Not processing \"%s\"" % (fname, ), file=sys.stderr)
            continue

        prev_date = None
        prev_cat = None
        first = True

        if delta_fields is not None:
            delta_values = {}

        for fields in moni_stream(fname, fix_profile=args.fix_profile,
                                  total_fields=total_fields):
            datestr, category, field, value = fields
            if prev_date != datestr or prev_cat != category:
                if first:
                    first = False
                else:
                    print()
                print("%s: %s:" % (category, datestr))
                prev_date = datestr
                prev_cat = category

            if isinstance(value, dict):
                for dkey, dval in list(value.items()):
                    fullname = "%s+%s" % (field, dkey)
                    if delta_fields is not None and fullname in delta_fields:
                        dval = compute_delta(delta_values, category, fullname,
                                             dval)
                    print("\t%s: %s" % (fullname, dval))
            else:
                if delta_fields is not None and field in delta_fields:
                    value = compute_delta(delta_values, category, field, value)
                print("\t%s: %s" % (field, value))


if __name__ == "__main__":
    import argparse

    main()
