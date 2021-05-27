#!/usr/bin/env python
"Utility script which pauses runs when RestartSPTS.py is active"

from __future__ import print_function

import os
import re

from RestartSPTS import is_spts_active


# stolen from live/misc/util.py
def get_duration_from_string(dstr):
    """
    Return duration in seconds based on string <s>
    """
    mtch = re.search(r'^(\d+)$', dstr)
    if mtch is not None:
        return int(mtch.group(1))
    mtch = re.search(r'^(\d+)s(?:ec(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1))
    mtch = re.search(r'^(\d+)m(?:in(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1)) * 60
    mtch = re.search(r'^(\d+)h(?:r(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1)) * 3600
    mtch = re.search(r'^(\d+)d(?:ay(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1)) * 86400
    raise ValueError('String "%s" is not a known duration format.  Try'
                     '30sec, 10min, 2days etc.' % str(dstr))


def main():
    "Main program"

    import subprocess
    import sys

    from utils.Machineid import Machineid

    hostid = Machineid()
    if hostid.is_sps_cluster:
        raise SystemExit("This script should not be run on SPS")

    if len(sys.argv) == 1:
        print("%s: Please specify the number of minutes to pause" %
              sys.argv[0], file=sys.stderr)
        raise SystemExit("Usage: %s minutes-to-pause" % sys.argv[0])

    try:
        minutes = get_duration_from_string(sys.argv[1]) / 60
    except ValueError:
        raise SystemExit("%s: Bad duration \"%s\"" %
                         (sys.argv[0], sys.argv[1]))

    if len(sys.argv) > 2:
        print("%s: Ignoring extra arguments" % sys.argv[0], file=sys.stderr)

    print("Pausing for %d minutes" % minutes)
    with open(os.path.join(os.environ["HOME"], ".paused"), "w") as fout:
        print(str(minutes), file=fout)

    if is_spts_active(2):
        print("Stopping current run")
        subprocess.call(["livecmd", "stop", "daq"])


if __name__ == "__main__":
    main()
