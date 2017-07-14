#!/usr/bin/env python
#
# Note that most of this functionality exists in the `psutil` package
# so this code should be reexamined if we ever add it to pDAQ

import os
import re
import subprocess
import time


class ProcessException(Exception):
    pass


def find_python_process(target):
    "Return the IDs of any Python processes containing the target string"
    for line in list_processes():
        match = re.match(r"\s*(\d+)\s+.+?[Pp]ython[\d\.]*\s+.+?%s" %
                         (target, ), line)
        if match is not None:
            yield int(match.group(1))


def list_processes():
    "Return a list of strings describing all running processes"
    proc = subprocess.Popen(("ps", "ahwwx"), close_fds=True,
                            stdout=subprocess.PIPE)
    lines = proc.stdout.readlines()
    if proc.wait():
        raise ProcessException("Failed to list processes")

    for line in lines:
        yield line.rstrip()
