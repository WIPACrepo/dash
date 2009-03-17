""" A module for parsing svn keywords, getting & storing the svn
version number and identifying the pDAQ release name (defaults to
'trunk').  Note that when running svnversion on the meta project dir,
this descends into all the externals of the meta-project, in-effect
extending what svnversion does."""

import os
import pprint
import sys

# The release name, 'trunk' for unreleased, development versions
RELEASE = 'trunk'

from subprocess import Popen, PIPE

SVN_ID = "$Id: SVNVersionInfo.py 3973 2009-03-17 20:38:52Z dglo $"

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

this_dir = os.path.dirname(__file__)

svn_rev_filename = os.path.join(this_dir, ".deployed_svn_rev")

class SVNVersionError (Exception): pass

def _exec_cmd(cmd, shell=False, cwd=None):
    """ Run the sequence in cmd and return its stdout.  If the return
    code from running cmd is non-zero, its stderr is non-empty or an
    OSError is caught, then an SVNVersionError will be raised.  As a
    wrapper around subprocess.Popen() the optional shell and cwd args
    here are passed directly to the Popen call."""

    try:
        p = Popen(cmd, shell=shell, cwd=cwd, stdout=PIPE, stderr=PIPE)
    except OSError, e:
        raise SVNVersionError, "Command: '%s' raised OSError: '%s'" % (cmd, e) 

    ret_code = p.wait()
    if ret_code != 0:
        raise SVNVersionError, \
              "Command: '%s' returned non-zero code: '%s'" % (cmd, ret_code)

    stdout, stderr = p.communicate()
    if len(stderr) != 0:
        raise SVNVersionError, \
              "Command: '%s' returned non-empty stderr: '%s'" % (cmd, stderr)

    return stdout

def _calc_svnversion():
    """ Calculate the svnversion value from the top of the meta
    project dir, descending into external dirs as svnversion itself
    does not do."""

    # First, run svnversion on the metaDir
    metaDir_ver = _exec_cmd(["svnversion", "-n", metaDir])

    # Get the repo URL used by the metaDir (used to see if any of the
    # externals have been switched)
    metaDir_url = _exec_cmd(["svn info | grep 'URL: ' | awk '{print $NF}'"],
                            shell=True, cwd=metaDir)[:-1]
    repo_url = '/'.join(metaDir_url.split('/', 3)[:3]) # up to the 3rd '/'

    # Now run svnversion on each of the externals (note that svn chokes
    # on symlinks, so using cwd)
    external_output = _exec_cmd(["svn", "pg", "svn:externals", "--strict"],
                                cwd=metaDir)

    # A list of 2-element lists: [external, tail_url]
    externals = []
    for line in external_output.splitlines():
        if len(line) == 0:
            continue
        parts = line.split()
        externals.append([parts[0], parts[-1].split(repo_url)[1]])

    # A list of running svnversion on each external
    versions = [_exec_cmd(["svnversion", "-n", os.path.join(metaDir, extern[0]),
                           extern[1]]) for extern in externals]
    versions.append(metaDir_ver)

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
        
    spread = high_rev > low_rev
    return "%d%s%s%s%s" % (low_rev,
                           spread and (":" + str(high_rev)) or "",
                           modified and "M" or "",
                           switched and "S" or "",
                           exported and "E" or "")

    
def get_svnversion():

    """ Attempt to return the global svn revision number for this
    metaDir by first using svnversion and if that fails (because of an
    OSError (svn is not present)) look for the results of a previous
    call to store_svnversion() (presumably done at deploy time by
    DeployPDAQ.py), if that too fails (file does not exist) then
    return '0:0:0' """

    try:
        ver = _calc_svnversion()
    except (OSError, SVNVersionError), e:
        # Eat the exception and look for the version saved during deployment
        if os.path.exists(svn_rev_filename):
            # Return contents of file written when pdaq was deployed
            return file(svn_rev_filename).readlines()[0]
        else:
            return "0:0:0"

    return ver

def store_svnversion():

    """ Calculate and store the svnversion information in a file for
    later querying release version info (by get_svnversion()) on
    machines where svn does not exist.  Print a warning to stderr if
    there was a problem getting the svnversion info but proceed anyway
    saving '0:0' as the version."""

    try:
        ver = _calc_svnversion()
    except SVNVersionError, e:
        print >>sys.stderr, "SVNVersionError: ", e
        ver = "0:0"

    svn_rev_file = file(svn_rev_filename, "w")
    svn_rev_file.write(ver)
    svn_rev_file.close()

    return ver


def get_version_info(svn_id):

    """ Split provided subversion keyword Id value and return tuple of
    release identifiers: (filename, release, revision, date, time,
    author).  All values will be 'unknown' if there is a problem
    parsing input values."""

    ids = svn_id.split()
    # Check that svn_id has 7 fields, as the Id keyword should
    if len(ids) != 7:
        ids = ['unknown'] * 7

    return {'filename' : ids[1],
            'revision' : ids[2],
            'date'     : ids[3],
            'time'     : ids[4],
            'author'   : ids[5],
            'release'  : RELEASE,
            'repo_rev' : get_svnversion()}


if __name__ == '__main__':
    print store_svnversion()
    PP = pprint.PrettyPrinter(indent=2)
    PP.pprint(get_version_info(SVN_ID))
    print "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
          "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    
