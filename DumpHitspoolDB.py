#!/usr/bin/env python


import os
import sqlite3


DEFAULT_PATH = "/mnt/data/pdaqlocal/hitspool/hitspool.db"


def add_arguments(parser):
    parser.add_argument("hitspool_db", nargs="?",
                        help="Hitspool SQLLite3 database file")


def dump_db(args):
    if args.hitspool_db is None:
        path = DEFAULT_PATH
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
            print "%s [%d-%d] (%.02fs)" % \
                (filename, start_tick, stop_tick, secs)
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()

    add_arguments(p)

    args = p.parse_args()

    dump_db(args)
