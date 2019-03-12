#!/usr/bin/env python

from __future__ import print_function

import os
import sqlite3

from DAQTime import PayloadTime


HITSPOOL_DIR = "/mnt/data/pdaqlocal/hitspool"
HSDB_PATH = os.path.join(HITSPOOL_DIR, "hitspool.db")


def add_arguments(parser):
    parser.add_argument("-r", "--raw", dest="rawtimes",
                        action="store_true", default=False,
                        help="Dump times as DAQ ticks (0.1ns)")
    parser.add_argument("hitspool_db", nargs="?",
                        help="Hitspool SQLLite3 database file")


def dump_db(args):
    if args.hitspool_db is None:
        path = HSDB_PATH
    else:
        path = args.hitspool_db

    if not os.path.exists(path):
        raise SystemExit("HitSpool DB %s does not exist" % path)

    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    try:
        for row in cursor.execute("select filename, start_tick, stop_tick"
                                  " from hitspool"):
            filename, start_tick, stop_tick = row
            secs = (stop_tick - start_tick) / 1E10
            if args.rawtimes:
                start_val = start_tick
                stop_val = stop_tick
            else:
                start_val = PayloadTime.toDateTime(start_tick)
                stop_val = PayloadTime.toDateTime(stop_tick)
            if os.path.exists(os.path.join(HITSPOOL_DIR, filename)):
                rmstr = ""
            else:
                rmstr = " [NO FILE]"
            print("%s [%s-%s] (%.02fs)%s" % \
                (filename, start_val, stop_val, secs, rmstr))
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()

    add_arguments(p)

    args = p.parse_args()

    dump_db(args)
