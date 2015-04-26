#!/usr/bin/env python
"""
A module for identifying the pDAQ release name (defaults to
'trunk') and extracting relevant source control details.
"""


import os
import pprint
import subprocess
import sys

from datetime import datetime
from locate_pdaq import find_pdaq_trunk

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# The release name, 'trunk' for unreleased, development versions
RELEASE = 'trunk'

# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()

# file which caches the revision information
SCM_REV_FILENAME = os.path.join(PDAQ_HOME, "target", ".deployed_rev")

# ignore these externals when calculating version information
#  (once contained ['cluster-config', 'config'] but both directories
#   have been removed from the pdaq metaproject)
EXTERNALS_TO_IGNORE = []

# field names for version info
FIELD_NAMES = ["release", "repo_rev", "date", "time"]


class SCMVersionError (Exception):
    """Base package exception"""
    pass


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
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, shell=shell, cwd=cwd)
    except OSError, e:
        raise SCMVersionError("Command: '%s' raised OSError: '%s'" % (cmd, e))

    ret_code = p.wait()
    if ret_code != 0:
        raise SCMVersionError("Command: '%s' returned non-zero code: '%s'" %
                              (cmd, ret_code))

    stdout, stderr = p.communicate()
    if len(stderr) != 0:
        raise SCMVersionError("Command: '%s' returned non-empty stderr: '%s'" %
                              (cmd, stderr))

    return stdout


def __get_git_info(dir):
    """
    Gather the Git version info for the specified directory
    """

    rel = RELEASE
    repo_rev = None
    modified = False
    date = None
    time = None

    proc = subprocess.Popen(["git", "branch"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=dir)
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
                            stderr=subprocess.STDOUT, cwd=dir)
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


def __get_hg_info(dir):
    """
    Gather the Mercurial version info for the specified directory
    """

    rel = RELEASE
    repo_rev = None
    modified = False
    date = None
    time = None

    proc = subprocess.Popen(["hg", "sum"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=dir)

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
                            stderr=subprocess.STDOUT, cwd=dir)
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


def __get_svn_info(dir):
    """
    Gather the Subversion version info for the specified directory,
    including external project versions
    """

    rel = RELEASE
    repo_rev = None
    modified = False
    date = None
    time = None

    # First, run svnversion on the dir
    proc = subprocess.Popen("svnversion", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=dir)
    svn_rev = proc.communicate()[0].rstrip()
    proc.stdout.close()

    # Get the repo URL used by the dir (used to see if any of the
    # externals have been switched)
    dir_url = None
    proc = subprocess.Popen(["svn", "info"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=dir)
    for line in proc.stdout:
        if line.startswith("URL:"):
            dir_url = line.split()[1].strip()
            continue
        if line.startswith("Last Changed Date:"):
            dstr = line.split(':', 1)[1].strip()

            # only care about first 3 fields (date time timezone)
            dflds = dstr.split(None, 3)[:3]

            (date, time) = __parse_date_time(" ".join(dflds),
                                             "%Y-%m-%d %H:%M:%S")
            continue
    proc.stdout.close()

    repo_url = None

    if dir_url is None:
        external_output = ""
    else:
        # try to pull the release name out of the URL
        uflds = dir_url.split('/')
        if len(uflds) > 1 and uflds[-2] == "releases":
            rel = uflds[-1]

        repo_url = '/'.join(dir_url.split('/', 3)[:3]) # up to the 3rd '/'

        # Now run svnversion on each of the externals (note that svn chokes
        # on symlinks, so using cwd)
        external_output = __exec_cmd(["svn", "pg", "svn:externals", "--strict"],
                                     cwd=dir)

    # A list of 2-element lists: [external, tail_url]
    externals = []
    for line in external_output.splitlines():
        if len(line) == 0:
            continue
        parts = line.split()

        # print externals
        if parts[0] in EXTERNALS_TO_IGNORE:
            # from mantis issue: 4388
            # ignore 'cluster-config' and 'config'
            # settable from the EXTERNALS_TO_IGNORE list global
            continue

        externals.append([parts[0], parts[-1].split(repo_url)[1]])

    # A list of running svnversion on each external
    versions = [__exec_cmd(["svnversion", "-n",
                            os.path.join(dir, extern[0]), extern[1]])
                for extern in externals]
    versions.append(svn_rev)

    switched = modified = exported = False
    low_rev = sys.maxint
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

    spread = high_rev > low_rev
    repo_rev = "%d%s%s" % (low_rev,
                               spread and (":" + str(high_rev)) or "",
                               mods is not None and (":" + mods) or "")

    return {
        "release": rel,
        "repo_rev": repo_rev,
        "date": date,
        "time": time,
    }


def __make_empty_info():
    """
    Create a content-free version info dictionary
    """
    empty = {}
    for f in FIELD_NAMES:
        if f == "release":
            val = RELEASE
        elif f == "repo_rev":
            val = "0:0"
        else:
            val = None
        empty[f] = val
    return empty


def __parse_date_time(datestr, fmtstr):
    dt = None
    try:
        dt = datetime.strptime(datestr, fmtstr + " %z")
    except ValueError:
        dflds = datestr.split()
        if len(dflds[-1]) > 0 and \
           (dflds[-1][0] == '-' or dflds[-1][0] == '+'):
            # try trimming timezone
            try:
                dt = datetime.strptime(" ".join(dflds[:-1]), fmtstr)
            except ValueError:
                pass
    if dt is None:
        raise SCMVersionError("Bad date \"%s\"" % datestr)

    return (dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S%z"))


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
        raise SCMVersionError("Cannot determine repository type for " + origdir)

    return __scm_type(parent, origdir=(origdir is None and topdir or origdir))


def get_scmversion(dir=None):
    """
    Extract release, revision, date, and time information for the specified
    directory from the appropriate source control management system
    """

    if dir is None:
        dir = PDAQ_HOME

    expanded = os.path.expanduser(dir)
    if expanded != dir:
        dir = expanded

    try:
        stuple = __scm_type(dir)
        if stuple[0] == SCM_GIT:
            return __get_git_info(stuple[1])
        if stuple[0] == SCM_MERCURIAL:
            return __get_hg_info(stuple[1])
        if stuple[0] == SCM_SUBVERSION:
            return __get_svn_info(stuple[1])
    except (OSError, SCMVersionError), e:
        # Eat the exception and look for the version saved during deployment
        if not os.path.exists(SCM_REV_FILENAME):
            # nothing cached, return an empty dictionary
            return __make_empty_info()
        else:
            # Return contents of file written when pdaq was deployed
            line = file(SCM_REV_FILENAME).readlines()[0]
            flds = line.split(' ')
            if len(flds) != len(FIELD_NAMES):
                raise SCMVersionError("Cannot load cached version: expected"
                                      " %d fields, not %d from \"%s\""  %
                                      (len(FIELD_NAMES), len(flds), line))

            saved = {}
            for i in xrange(len(FIELD_NAMES)):
                saved[FIELD_NAMES[i]] = flds[i]
            return saved


def get_scmversion_str(dir=None, info=None):
    if info is None:
        info = get_scmversion(dir)

    rtnstr = None
    for fld in FIELD_NAMES:
        if rtnstr is None:
            rtnstr = str(info[fld])
        else:
            rtnstr += " " + str(info[fld])
    return rtnstr


def store_scmversion(dir=None):
    """
    Calculate and store the version information in a file for later querying.
    If there is a problem getting the version info, print a warning to stderr
    and don't write anything to the file.
    """

    if dir is None:
        dir = PDAQ_HOME

    expanded = os.path.expanduser(dir)
    if expanded != dir:
        dir = expanded

    try:
        scmstr = get_scmversion_str(dir)
    except SCMVersionError, e:
        print >>sys.stderr, "SCMVersionError: ", e
        return ""

    svn_rev_file = file(SCM_REV_FILENAME, "w")
    svn_rev_file.write(scmstr)
    svn_rev_file.close()

    return scmstr


if __name__ == "__main__":
    import optparse

    p = optparse.OptionParser()
    p.add_option("-d", "--dir", type="string", dest="dir",
                 action="store", default=PDAQ_HOME,
                 help="Location of directory tree being checked")
    opt, args = p.parse_args()

    rev_parent = os.path.dirname(SCM_REV_FILENAME)
    if not os.path.exists(rev_parent):
        os.makedirs(rev_parent)

    print "STORED -> " + store_scmversion(opt.dir)

    info = get_scmversion(opt.dir)
    print str(info)

    print get_scmversion_str(info=info)
