#!/usr/bin/env python
#
# moni_stream() is a generator which reads a pDAQ .moni file and returns
# tuples of (date, category, field, value)

import ast
import datetime
import re
import sys

CATTIME_PAT = re.compile(r"^([^:]+):\s(\d+-\d+-\d+\s\d+:\d+:\d+\.\d+):\s*$")
DICTELEM_PAT = re.compile(r"^\s*(\S+|'[^']+'):\s+([^:]+)"
                          r",\s+(?:(?:\S+|'[^']+'):\s+)")


def __fix_field_name(key):
    "Remove stray quote marks from a field name"
    if key.startswith("'") and key.endswith("'"):
        return key[1:-1]
    if key.startswith('"') and key.endswith('"'):
        return key[1:-1]
    return key


def __split_field_value(line):
    idx = line.find(": ", 0)
    if idx < 0:
        return None
    return __fix_field_name(line[:idx].strip()), line[idx+2:].strip()


def moni_stream(filename, ignored_func=None):
    """
    Read a pDAQ .moni file and return a stream of tuples containing
    (date_string, category, field, value_string)

    ignored_func(category, fieldname) is an optional function which
    returns True if this category field should be ignored
    """
    cur_cat = None
    cur_date = None

    for line in open(filename, "r"):
        line = line.rstrip()

        if len(line) == 0:
            continue

        mtch = CATTIME_PAT.match(line)
        if mtch is not None:
            cur_cat = mtch.group(1)
            if cur_date != mtch.group(2):
                cur_date = mtch.group(2)

            continue

        fldval = __split_field_value(line)
        if fldval is not None:
            if ignored_func is None or \
               not ignored_func(cur_cat, fldval[0]):
                yield (cur_date, cur_cat, fldval[0], fldval[1])
            continue

        print >>sys.stderr, "Unknown line: " + line


def parse_date(datestr):
    "Parse a DAQ moni date string and return a datetime object"
    date_fmt = "%Y-%m-%d %H:%M:%S.%f"
    if date_fmt.find(".") > 0:
        return datetime.datetime.strptime(datestr, date_fmt)

    no_subsec_fmt = "%Y-%m-%d %H:%M:%S"
    return datetime.datetime.strptime(datestr, no_subsec_fmt)


def main():
    "Sample method using moni_stream()"
    parg = argparse.ArgumentParser()
    parg.add_argument("-p", "--fix-profile-times", dest="fix_profile_times",
                      action="store_true", default=False,
                      help="")
    parg.add_argument("-x", "--debug", dest="debug",
                      action="store_true", default=False,
                      help="Enable debugging")
    parg.add_argument(dest="files", nargs="+")

    args = parg.parse_args()

    for fname in args.files:
        if not fname.endswith(".moni"):
            print >>sys.stderr, "Not processing \"%s\"" % (fname, )
            continue

        prev_date = None
        prev_cat = None
        first = True

        for datestr, category, field, valstr in moni_stream(fname):
            if prev_date != datestr or prev_cat != category:
                if first:
                    first = False
                else:
                    print
                print "%s: %s:" % (category, datestr)
                prev_date = datestr
                prev_cat = category

            try:
                value = ast.literal_eval(valstr)
            except ValueError, ve:
                print >>sys.stderr, "Bad value \"%s\"" % (valstr, )
                continue

            if isinstance(value, dict):
                for key, val in value.items():
                    print "\t%s+%s: %s" % (field, key, val)
            elif isinstance(value, list):
                print "\t%s: %s" % (field, value)
            else:
                print "\t%s: %s" % (field, value)


if __name__ == "__main__":
    import argparse

    main()
