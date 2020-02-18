#!/usr/bin/env python
#
# Extract a set of SNDAQ HitSpool tar files into the approriate subdirectories.
# Assumes that the tar files are SPADE/JADE-style compressed tar files
# containing another tar file and a meta.xml file, and that the internal tar
# file contains the final set of hitspool data files.
#
# The hitspool files will be extracted into subdirectories inside the directory
# holding the tarfiles, so if /foo/bar holds SNALERT_ichub01_XYZ.tar.gz and
# SNALERT_ithub11_XYZ.tar.gz, this script will extract the files into
# /foo/bar/ichub01/ and /foo/bar/ithub11
#
# Note that this will extract ALL tar files, so if /foo/bar contains one
# set of tar files in /foo/bar/123456 and another in /foo/bar/backup, both
# directories will end up with a set of hitspool subdirectories.

from __future__ import print_function

import fnmatch
import os
import re
import sys
import tarfile

HUB_PAT = re.compile(r"^.*i([ct])hub(\d+).*$")


def extract_for_real(tarname, tardir, subdir):
    hubnames = {}
    tar = tarfile.open(tarname, "r:*")
    try:
        for info in tar.getmembers():
            if not info.isfile():
                continue

            mtch = HUB_PAT.match(info.name)
            if mtch is None:
                print("No hubname found in %s; skipping" % info.name,
                      file=sys.stderr)
                continue

            hubtype = mtch.group(1)
            numstr = mtch.group(2)

            if hubtype == "c":
                inice = True
            elif hubtype == "t":
                inice = False
            else:
                print("Unknown hub type in \"%s\"; skipping" % info.name,
                      file=sys.stderr)

            try:
                hubnum = int(numstr)
            except ValueError:
                print("Bad hub number in \"%s\"; skipping" % info.name,
                      file=sys.stderr)

            if not inice and hubnum < 100:
                hubnum += 200

            hubname = "i%shub%s" % (hubtype, numstr)

            hubpath = os.path.join(tardir, hubname)
            if not os.path.isdir(hubpath):
                os.mkdir(hubpath)

            members = [info, ]
            tar.extractall(path=hubpath, members=members)

            namedir = os.path.dirname(info.name)
            if namedir != "":
                base = os.path.basename(info.name)
                os.rename(os.path.join(hubpath, info.name),
                          os.path.join(hubpath, base))
                os.removedirs(os.path.join(hubpath, namedir))

            if hubname not in hubnames:
                hubnames[hubname] = 1
            else:
                hubnames[hubname] += 1
    finally:
        tar.close()
        os.remove(tarname)

    keys = sorted(hubnames.keys())

    for hub in keys:
        if hubnames[hub] == 1:
            plural = ""
        else:
            plural = "s"

        print("Extracted %d %s file%s to %s" %
              (hubnames[hub], hub, plural, subdir))


def process(path):
    for root, _, files in os.walk(path):
        for filename in fnmatch.filter(files, "HS_SNALERT_*.tar.gz"):
            tarpath = os.path.join(root, filename)
            tar = tarfile.open(tarpath, "r:*")
            try:
                members = []
                for info in tar.getmembers():
                    if not info.isfile():
                        continue

                    if info.name.find(".tar") > 0:
                        members.append(info)

                if len(members) == 0:  # pylint: disable=len-as-condition
                    print("No tarfile found in %s" % tarpath, file=sys.stderr)
                elif len(members) > 1:
                    print("Found %d tarfiles in %s" %
                          (len(members), tarpath), file=sys.stderr)
                else:
                    tar.extractall(members=members)

                tardir = os.path.dirname(tarpath)

                if not root.startswith(path):
                    print("Cannot find subdirectory \"%s\" in \"%s\"" %
                          (root, path), file=sys.stderr)
                    subdir = root
                else:
                    subdir = root[len(path):]
                    if subdir.startswith("/"):
                        subdir = subdir[1:]
                    if subdir == "":
                        subdir = "."

                extract_for_real(members[0].name, tardir, subdir)
            finally:
                tar.close()


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    if len(args.paths) == 0:  # pylint: disable=len-as-condition
        args.append("/net/data2/pdaq/testdata/hitspool/from_sndaq_alerts")

    for path in args.paths:
        process(path)


if __name__ == "__main__":
    main()
