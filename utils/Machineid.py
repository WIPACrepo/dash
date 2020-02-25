#!/usr/bin/env python
"""Identify machines for the pdaq system."""

from __future__ import print_function

import socket


class Machineid(object):
    BUILD_HOSTS = ["access"]
    CONTROL_HOSTS = ["expcont", "pdaq2"]
    SPADE_HOSTS = ["2ndbuild", "evbuilder"]

    # machine type constants
    BUILD_TYPE = 0x1
    CONTROL_TYPE = 0x2
    SPADE_TYPE = 0x4
    UNKNOWN_TYPE = 0x8000

    HOST_PAIRS = (
        (BUILD_HOSTS, BUILD_TYPE),
        (CONTROL_HOSTS, CONTROL_TYPE),
        (SPADE_HOSTS, SPADE_TYPE),
        )

    # cluster type constants
    UNKNOWN_CLUSTER = -1
    SPS_CLUSTER = 1
    SPTS_CLUSTER = 2
    MDFL_CLUSTER = 3

    def __init__(self, hostname=None):
        if hostname is None:
            self.__hname = socket.gethostname()
        else:
            self.__hname = hostname

        self.__cluster_type = self.__get_cluster_type()
        self.__host_type = self.__get_host_type()

    def __get_cluster_type(self):
        # figure out if we are part of a cluster
        if self.__hname.endswith("icecube.southpole.usap.gov"):
            # we are part of the south pole system
            return self.SPS_CLUSTER
        if self.__hname.endswith("icecube.wisc.edu"):
            if self.__hname.startswith("mdfl"):
                return self.MDFL_CLUSTER

            hlist = self.__hname.split(".")
            if len(hlist) > 4 and (hlist[1] == "spts" or hlist[1] == "sptsn"):
                # we are part of the south pole TEST system
                return self.SPTS_CLUSTER

        return self.UNKNOWN_CLUSTER

    def __get_host_type(self):
        # remove domain name and convert host name to lower case
        host_name = self.__hname.split('.', 1)[0].lower()

        # now figure out what type of host this is
        host_type = 0x0
        for hlist, hval in self.HOST_PAIRS:
            for host in hlist:
                if host_name.endswith(host):
                    # we are a build host
                    host_type |= hval
                    break

        if host_type == 0x0:
            host_type = self.UNKNOWN_TYPE

        return host_type

    def __str__(self):
        """Produces the informal string representation of this class"""

        host_types = []
        if self.is_build_host:
            host_types.append("Build")
        if self.is_control_host:
            host_types.append("Control")
        if self.is_spade_host:
            host_types.append("SPADE")
        if len(host_types) == 0:  # pylint: disable=len-as-condition
            host_types.append("Unknown")
        host_type_str = "/".join(host_types)

        cluster_type_str = "Unknown System"
        if self.__cluster_type == self.SPTS_CLUSTER:
            cluster_type_str = "South Pole Test System"
        elif self.__cluster_type == self.SPS_CLUSTER:
            cluster_type_str = "South Pole System"

        return "Host name: '%s'\nHost Type: '%s'\nCluster Type: '%s'" % (
            self.__hname, host_type_str, cluster_type_str)

    @property
    def is_build_host(self):
        """
        Returns true if this is a known pdaq build machine
        """
        return (self.__host_type & self.BUILD_TYPE) == self.BUILD_TYPE

    @property
    def is_control_host(self):
        """
        Returns true if this is a known pdaq control machine
        """
        return (self.__host_type & self.CONTROL_TYPE) == self.CONTROL_TYPE

    @property
    def is_spade_host(self):
        """
        Returns true if this is a known pdaq machine which writes data to SPADE
        """
        return (self.__host_type & self.SPADE_TYPE) == self.SPADE_TYPE

    @property
    def is_unknown_host(self):
        """
        Returns true if this is not a known pdaq build or control machine.
        If an unknown host and an unknown cluster, it is assumed that you can
        run anything you want.
        """
        return (self.__host_type & self.UNKNOWN_TYPE) == self.UNKNOWN_TYPE

    @property
    def is_mdfl_cluster(self):
        "Returns true if this is a member of the MDFL test system"
        return self.__cluster_type == self.MDFL_CLUSTER

    @property
    def is_sps_cluster(self):
        "Returns true if this is a member of the south pole cluster"
        return self.__cluster_type == self.SPS_CLUSTER

    @property
    def is_spts_cluster(self):
        "Returns true if this is a member of the south pole test system"
        return self.__cluster_type == self.SPTS_CLUSTER

    @property
    def is_unknown_cluster(self):
        """
        Returns true if this is not member of any known pdaq cluster.
        This will be used in conjunction with is_unknown_host to identify
        machines that do not need protection against running control
        scripts.
        """
        return self.__cluster_type == self.UNKNOWN_CLUSTER

    @property
    def hname(self):
        return self.__hname


def main():
    TEST = Machineid()
    print(TEST)


if __name__ == "__main__":
    main()
