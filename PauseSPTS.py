#!/usr/bin/env python

from __future__ import print_function

import os
import re

from RestartSPTS import isSPTSActive


# stolen from live/misc/util.py
def get_duration_from_string(s):
    """
    Return duration in seconds based on string <s>
    """
    m = re.search(r'^(\d+)$', s)
    if m:
        return int(m.group(1))
    m = re.search(r'^(\d+)s(?:ec(?:s)?)?$', s)
    if m:
        return int(m.group(1))
    m = re.search(r'^(\d+)m(?:in(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r'^(\d+)h(?:r(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 3600
    m = re.search(r'^(\d+)d(?:ay(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 86400
    raise ValueError('String "%s" is not a known duration format.  Try'
                     '30sec, 10min, 2days etc.' % s)


if __name__ == "__main__":
    import subprocess
    import sys

    from utils.Machineid import Machineid

    hostid = Machineid()
    if hostid.is_sps_cluster:
        raise SystemExit("This script should not be run on SPS")

    usage = False
    if len(sys.argv) == 1:
        print("%s: Please specify the number of minutes to pause" % sys.argv[0], file=sys.stderr)
        raise SystemExit("Usage: %s minutes-to-pause" % sys.argv[0])

    try:
        minutes = get_duration_from_string(sys.argv[1]) / 60
    except:
        raise SystemExit("%s: Bad duration \"%s\"" %
                         (sys.argv[0], sys.argv[1]))

    if len(sys.argv) > 2:
        print("%s: Ignoring extra arguments" % sys.argv[0], file=sys.stderr)

    print("Pausing for %d minutes" % minutes)
    with open(os.path.join(os.environ["HOME"], ".paused"), "w") as fd:
        print(str(minutes), file=fd)

    if isSPTSActive(2):
        print("Stopping current run")
        subprocess.call(["livecmd", "stop", "daq"])
