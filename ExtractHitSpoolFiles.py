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

import fnmatch
import os
import re
import sys
import tarfile

HUB_PAT = re.compile(r"^.*i([ct])hub(\d+).*$")


def extract_for_real(tarname, tardir, subdir):
    hubnames = {}
    tf = tarfile.open(tarname, "r:*")
    try:
        for info in tf.getmembers():
            if not info.isfile():
                continue

            m = HUB_PAT.match(info.name)
            if m is None:
                print >>sys.stderr, "No hubname found in %s; skipping" % \
                    info.name
                continue

            hubtype = m.group(1)
            numstr = m.group(2)

            if hubtype == "c":
                inice = True
            elif hubtype == "t":
                inice = False
            else:
                print >>sys.stderr, "Unknown hub type in \"%s\"; skipping" % \
                    info.name

            try:
                hubnum = int(numstr)
            except:
                print >>sys.stderr, "Bad hub number in \"%s\"; skipping" % \
                    info.name

            if not inice and hubnum < 100:
                hubnum += 200

            hubname = "i%shub%s" % (hubtype, numstr)

            hubpath = os.path.join(tardir, hubname)
            if not os.path.isdir(hubpath):
                os.mkdir(hubpath)

            members = [info, ]
            tf.extractall(path=hubpath, members=members)

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
        tf.close()
        os.remove(tarname)

    keys = hubnames.keys()
    keys.sort()

    for hub in keys:
        if hubnames[hub] == 1:
            plural = ""
        else:
            plural = "s"

        print "Extracted %d %s file%s to %s" % \
            (hubnames[hub], hub, plural, subdir)


def process(path):
    for root, dirs, files in os.walk(path):
        for filename in fnmatch.filter(files, "HS_SNALERT_*.tar.gz"):
            tarpath = os.path.join(root, filename)
            tf = tarfile.open(tarpath, "r:*")
            try:
                members = []
                for info in tf.getmembers():
                    if not info.isfile():
                        continue

                    if info.name.find(".tar") > 0:
                        members.append(info)

                if len(members) == 0:
                    print >>sys.stderr, "No tarfile found in %s" % tarpath
                elif len(members) > 1:
                    print >>sys.stderr, "Found %d tarfiles in %s" % \
                        (len(members), tarpath)
                else:
                    tf.extractall(members=members)

                tardir = os.path.dirname(tarpath)

                if not root.startswith(path):
                    print >>sys.stderr, \
                        "Cannot find subdirectory \"%s\" in \"%s\"" % \
                        (root, path)
                    subdir = root
                else:
                    subdir = root[len(path):]
                    if subdir.startswith("/"):
                        subdir = subdir[1:]
                    if subdir == "":
                        subdir = "."

                extract_for_real(members[0].name, tardir, subdir)
            finally:
                tf.close()


if __name__ == "__main__":
    import argparse

    op = argparse.ArgumentParser()
    op.add_argument("paths", nargs="*")
    args = op.parse_args()

    if len(args.paths) == 0:
        args.append("/net/data2/pdaq/testdata/hitspool/from_sndaq_alerts")

    for path in args.paths:
        process(path)
