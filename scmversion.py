#!/usr/bin/env python
"""
A module for identifying the pDAQ release name (defaults to 'trunk') and
extracting relevant source control details.
"""

from __future__ import print_function

import os
import subprocess
import sys

from datetime import datetime
from locate_pdaq import find_pdaq_trunk


# The release name, 'trunk' for unreleased, development versions
__UNRELEASED = 'trunk'

# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()

# file which caches the revision information
TARGET_PATH = os.path.join(PDAQ_HOME, "target")
SCM_REV_FILENAME = os.path.join(TARGET_PATH, ".deployed_rev")

# ignore these externals when calculating version information
#  (once contained ['cluster-config', 'config'] but both directories
#   have been removed from the pdaq metaproject)
EXTERNALS_TO_IGNORE = []

# field names for version info
FIELD_NAMES = ["release", "repo_rev", "date", "time"]


class SCMVersionError(Exception):
    """Base package exception"""


SCM_GIT = "_git_"
SCM_MERCURIAL = "_hg_"
SCM_SUBVERSION = "_svn_"


def __exec_cmd(cmd, shell=False, cwd=None):
    """
    Run the sequence in cmd and return its stdout.  If the return code from
    running cmd is non-zero, its stderr is non-empty or an OSError is caught,
    then an SCMVersionError will be raised.  As a wrapper around
    subprocess.Popen() the optional shell and cwd args here are passed
    directly to the Popen call.
    """

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, shell=shell, cwd=cwd)
    except OSError as exc:
        raise SCMVersionError("Command: '%s' raised OSError: '%s'" %
                              (cmd, exc))

    ret_code = proc.wait()
    if ret_code != 0:
        raise SCMVersionError("Command: '%s' returned non-zero code: '%s'" %
                              (cmd, ret_code))

    rawout, rawerr = proc.communicate()

    if rawerr is not None:
        stderr = rawerr.decode().rstrip()
        if stderr != "":
            raise SCMVersionError("Command: '%s' returned non-empty stderr:"
                                  " '%s'" % (cmd, stderr))

    return rawout.decode().rstrip()


def __get_git_info(svn_dir):
    """
    Gather the Git version info for the specified directory
    """

    rel = __UNRELEASED
    repo_rev = None
    modified = False
    date = None
    time = None

    proc = subprocess.Popen(["git", "branch"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=svn_dir)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("*"):
            tmprel = line[1:].strip()
            if tmprel != "master":
                rel = tmprel
            continue
    proc.stdout.close()
    proc.wait()

    proc = subprocess.Popen(["git", "show", "--summary"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=svn_dir)
    for line in proc.stdout:
        if line.startswith("Date:"):
            dstr = line.split(':', 1)[1].strip()

            (date, time) = __parse_date_time(dstr, "%a %b %d %H:%M:%S %Y")
            continue
        if line.startswith("commit"):
            repo_rev = line.split()[1]
            continue
    proc.stdout.close()
    proc.wait()

    return {
        "release": rel,
        "repo_rev": repo_rev + (modified and ":M" or ""),
        "date": date,
        "time": time,
    }


def __get_hg_info(svn_dir):
    """
    Gather the Mercurial version info for the specified directory
    """

    rel = __UNRELEASED
    repo_rev = None
    modified = False
    date = None
    time = None

    proc = subprocess.Popen(["hg", "sum"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=svn_dir)

    for line in proc.stdout:
        if line.startswith("branch:"):
            tmprel = line.split(':')[1].strip()
            if tmprel != "default":
                rel = tmprel
            continue
        if line.startswith("commit:"):
            if line.find("modified") > 0:
                modified = True
            continue
        if line.startswith("parent:"):
            repo_rev = line.split()[1].strip()
            continue
    proc.stdout.close()
    proc.wait()

    proc = subprocess.Popen(["hg", "log", "-r" + repo_rev],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=svn_dir)
    for line in proc.stdout:
        if line.startswith("date:"):
            dstr = line.split(':', 1)[1].strip()

            (date, time) = __parse_date_time(dstr, "%a %b %d %H:%M:%S %Y")
            continue
        if line.startswith("tag:"):
            tmprel = " ".join(line.split()[1:])
            if tmprel != "tip":
                rel = tmprel
            continue
    proc.stdout.close()
    proc.wait()

    return {
        "release": rel,
        "repo_rev": repo_rev + (modified and ":M" or ""),
        "date": date,
        "time": time,
    }


def __get_scmrel_from_homedir():
    """
    Try to extract a unique name from the top-level directory name
    """

    homename = os.path.basename(os.path.realpath(PDAQ_HOME))
    if homename.lower().startswith("pdaq"):
        homename = homename[4:]
        if len(homename) > 2 and (homename[0] == '_' or homename[0] == '-'):
            homename = homename[1:]
        lname = homename.lower()
        if lname != "current" and lname != __UNRELEASED.lower():
            return homename

    return __UNRELEASED


def __get_svn_externals(svn_dir, dir_url):
    """
    Return a list of externals.
    Each entry is a tuple containing (subdirectory, svn_url)
    """
    externals = []
    if dir_url is None:
        return externals

    repo_url = '/'.join(dir_url.split('/', 3)[:3])  # up to the 3rd '/'

    # Now run svnversion on each of the externals (note that svn chokes
    # on symlinks, so using cwd)
    external_output = __exec_cmd(["svn", "pg", "svn:externals",
                                  "--strict"], cwd=svn_dir)

    # build list of 2-element lists: [external, tail_url]
    for line in external_output.splitlines():
        if line == "":
            continue
        parts = line.split()

        if parts[0] in EXTERNALS_TO_IGNORE:
            continue

        externals.append((parts[0], parts[-1].split(repo_url)[1]))

    return externals


def __get_svn_info(svn_dir):
    """
    Gather the Subversion version info for the specified directory,
    including external project versions
    """

    date = None
    time = None

    # First, run svnversion on the dir
    proc = subprocess.Popen("svnversion", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=svn_dir)
    svn_rev = proc.communicate()[0].decode().rstrip()
    proc.stdout.close()

    # Get the repo URL used by the directory (used to see if any of the
    # externals have been switched)
    dir_url = None
    proc = subprocess.Popen(["svn", "info"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=svn_dir)
    for line in proc.stdout:
        line = line.decode().rstrip()
        if line.startswith("URL:"):
            dir_url = line.split()[1].strip()
        elif line.startswith("Last Changed Date:"):
            dstr = line.split(':', 1)[1].strip()

            # only care about first 3 fields (date time timezone)
            bflds = dstr.split(None, 3)[:3]
            dflds = [str(fld) for fld in bflds]

            (date, time) = __parse_date_time(" ".join(dflds),
                                             "%Y-%m-%d %H:%M:%S")
    proc.stdout.close()
    proc.wait()

    repo_rev = __get_svn_repo_revision(svn_dir, dir_url, svn_rev)

    # try to pull the release name out of the URL
    uflds = dir_url.split('/')
    if len(uflds) > 1 and uflds[-2] == "releases":
        rel = uflds[-1]
    else:
        rel = __UNRELEASED

    return {
        "release": rel,
        "repo_rev": repo_rev,
        "date": date,
        "time": time,
    }


def __get_svn_repo_revision(svn_dir, dir_url, svn_rev):
    # get the SVN versions from each external project
    versions = [__exec_cmd(["svnversion", "-n",
                            os.path.join(svn_dir, extern[0]), extern[1]])
                for extern in __get_svn_externals(svn_dir, dir_url)]

    # append the top-level version info
    versions.append(svn_rev)

    switched = modified = exported = False
    low_rev = sys.maxsize
    high_rev = 0
    for ver in versions:
        if ver == "exported":
            exported = True
            continue

        if ver.endswith("S"):
            switched = True
            ver = ver[:-1]

        if ver.endswith("M"):
            modified = True
            ver = ver[:-1]

        if ver.find(":") > -1:
            low, high = ver.split(":")
            low_rev = min(low_rev, int(low))
            high_rev = max(high_rev, int(high))
        else:
            low_rev = min(low_rev, int(ver))
            high_rev = max(high_rev, int(ver))

    mods = (modified and "M" or "") + (switched and "S" or "") + \
           (exported and "E" or "")

    return "%d%s%s" % (low_rev,
                       high_rev <= low_rev and "" or (":" + str(high_rev)),
                       mods == "" and "" or (":" + mods))


def __make_empty_info():
    """
    Create a content-free version info dictionary
    """
    empty = {}
    for fld in FIELD_NAMES:
        if fld == "release":
            val = __UNRELEASED
        elif fld == "repo_rev":
            val = "0:0"
        else:
            val = None
        empty[fld] = val
    return empty


def __parse_date_time(datestr, fmtstr):
    """
    Parse the date string according to the specified format.
    Return a tuple containing a `Y-M-D` string and an `H:M:S` string
    with timezone
    """
    dttm = None
    try:
        dttm = datetime.strptime(datestr, fmtstr + " %z")
    except ValueError:
        dflds = datestr.split()

        # pylint: disable=len-as-condition
        if len(dflds[-1]) > 0 and \
          (dflds[-1][0] == '-' or dflds[-1][0] == '+'):
            # try trimming timezone
            try:
                dttm = datetime.strptime(" ".join(dflds[:-1]), fmtstr)
            except ValueError:
                pass
    if dttm is None:
        raise SCMVersionError("Bad date \"%s\"" % datestr)

    return (dttm.strftime("%Y-%m-%d"), dttm.strftime("%H:%M:%S%z"))


def __scm_type(topdir, origdir=None):
    """
    Find the source control type used in `topdir`
    """
    if os.path.exists(os.path.join(topdir, ".svn")):
        return (SCM_SUBVERSION, topdir)
    if os.path.exists(os.path.join(topdir, ".hg")):
        return (SCM_MERCURIAL, topdir)
    if os.path.exists(os.path.join(topdir, ".git")):
        return (SCM_GIT, topdir)

    if os.path.isabs(topdir):
        absdir = topdir
    else:
        absdir = os.path.abspath(topdir)

    parent = os.path.dirname(absdir)
    if parent == absdir:
        raise SCMVersionError("Cannot determine repository type for %s" %
                              (origdir, ))

    return __scm_type(parent, origdir=(origdir is None and topdir or origdir))


def get_scmversion(svn_dir=None):
    """
    Extract release, revision, date, and time information for the specified
    directory from the appropriate source control management system
    """

    if svn_dir is None:
        svn_dir = PDAQ_HOME

    expanded = os.path.expanduser(svn_dir)
    if expanded != svn_dir:
        svn_dir = expanded

    info = None
    try:
        stuple = __scm_type(svn_dir)
        if stuple[0] == SCM_GIT:
            info = __get_git_info(stuple[1])
        if stuple[0] == SCM_MERCURIAL:
            info = __get_hg_info(stuple[1])
        if stuple[0] == SCM_SUBVERSION:
            info = __get_svn_info(stuple[1])
    except (OSError, SCMVersionError):
        # Eat the exception and look for the version saved during deployment
        if not os.path.exists(SCM_REV_FILENAME):
            # nothing cached, return an empty dictionary
            info = __make_empty_info()
        else:
            # Return contents of file written when pdaq was deployed
            with open(SCM_REV_FILENAME) as fin:
                line = fin.readline()
            flds = line.split(' ')
            if len(flds) != len(FIELD_NAMES):
                raise SCMVersionError("Cannot load cached version: expected"
                                      " %d fields, not %d from \"%s\"" %
                                      (len(FIELD_NAMES), len(flds), line))

            saved = {}
            for idx, fldname in enumerate(FIELD_NAMES):
                saved[fldname] = flds[idx]
            info = saved

    if info is not None and info["release"] == __UNRELEASED:
        info["release"] = __get_scmrel_from_homedir()

    return info


def get_scmversion_str(svn_dir=None, info=None):
    """
    Extract release, revision, date, and time information for the specified
    directory from the appropriate source control management system and
    return a space-separated string of those values
    """

    if info is None:
        info = get_scmversion(svn_dir)

    rtnstr = None
    for fld in FIELD_NAMES:
        if rtnstr is None:
            rtnstr = str(info[fld])
        else:
            rtnstr += " " + str(info[fld])
    return rtnstr


def store_scmversion(svn_dir=None):
    """
    Calculate and store the version information in a file for later querying.
    If there is a problem getting the version info, print a warning to stderr
    and don't write anything to the file.
    """

    if svn_dir is None:
        svn_dir = PDAQ_HOME

    expanded = os.path.expanduser(svn_dir)
    if expanded != svn_dir:
        svn_dir = expanded

    try:
        scmstr = get_scmversion_str(svn_dir)
    except SCMVersionError as exc:
        print("SCMVersionError: " + str(exc), file=sys.stderr)
        return ""

    if not os.path.exists(SCM_REV_FILENAME):
        if not os.path.exists(TARGET_PATH):
            raise SystemExit("%s has not been built, run"
                             " 'mvn assembly:assembly' first" % (PDAQ_HOME, ))

    with open(SCM_REV_FILENAME, "w") as svn_rev_file:
        svn_rev_file.write(scmstr)

    return scmstr


def main():
    "Main program"
    import argparse
    import pprint

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dir", type=str, dest="path",
                        action="store", default=PDAQ_HOME,
                        help="Location of directory tree being checked")
    args = parser.parse_args()

    rev_parent = os.path.dirname(SCM_REV_FILENAME)
    if not os.path.exists(rev_parent):
        os.makedirs(rev_parent)

    print("STORED -> %s" % store_scmversion(args.path))

    vinfo = get_scmversion(args.path)
    pprt = pprint.PrettyPrinter(indent=4)
    print("RAW -> %s" % pprt.pformat(vinfo))

    print("FORMATTED -> %s" % get_scmversion_str(info=vinfo))


if __name__ == "__main__":
    main()
