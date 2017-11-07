"""Identify machines for the pdaq system."""
import socket


class Machineid(object):
    BUILD_HOSTS = ["access"]
    CONTROL_HOSTS = ["expcont", "pdaq2"]
    SPADE_HOSTS = ["2ndbuild", "evbuilder"]

    # cluster type constants
    SPS_CLUSTER, SPTS_CLUSTER, UNKNOWN_CLUSTER = range(3)

    # machine type constants
    UNKNOWN_HOST = 0x0
    BUILD_HOST = 0x1
    CONTROL_HOST = 0x2
    SPADE_HOST = 0x4

    def __init__(self, hostname=None):
        if hostname is None:
            self.__hname = socket.gethostname()
        else:
            self.__hname = hostname

        # figure out if we are part of a cluster
        if self.__hname.endswith("icecube.southpole.usap.gov"):
            # we are part of the south pole system
            self.__cluster_type = self.SPS_CLUSTER
        elif self.__hname.endswith("spts.icecube.wisc.edu"):
            # we are part of the south pole TEST system
            self.__cluster_type = self.SPTS_CLUSTER
        else:
            self.__cluster_type = self.UNKNOWN_CLUSTER

        # now figure out what type of host this is
        split_host_name = self.__hname.split('.', 1)[0].lower()
        self.__host_type = self.UNKNOWN_HOST
        for h in self.BUILD_HOSTS:
            if split_host_name.endswith(h):
                # we are a build host
                self.__host_type |= self.BUILD_HOST
                break
        for h in self.CONTROL_HOSTS:
            if split_host_name.endswith(h):
                # we are a build host
                self.__host_type |= self.CONTROL_HOST
                break
        for h in self.SPADE_HOSTS:
            if split_host_name.endswith(h):
                # we are a build host
                self.__host_type |= self.CONTROL_HOST
                break

    def __str__(self):
        """Produces the informal string representation of this class"""

        host_types = []
        if (self.__host_type & self.BUILD_HOST) == self.BUILD_HOST:
            host_types.append("Build")
        if (self.__host_type & self.CONTROL_HOST) == self.CONTROL_HOST:
            host_types.append("Control")
        if (self.__host_type & self.SPADE_HOST) == self.SPADE_HOST:
            host_types.append("SPADE")
        if len(host_types) == 0:
            host_types.append("Unknown")
        host_type_str = "/".join(host_types)

        cluster_type_str = "Unknown"
        if self.__cluster_type == self.SPTS_CLUSTER:
            cluster_type_str = "South Pole Test System"
        elif self.__cluster_type == self.SPS_CLUSTER:
            cluster_type_str = "South Pole System"

        return "Host name: '%s'\nHost Type: '%s'\nCluster Type: '%s'" % (
            self.__hname, host_type_str, cluster_type_str)

    def is_build_host(self):
        """
        Returns true if this is a known pdaq build machine
        """
        return True if self.__host_type == self.BUILD_HOST else False

    def is_control_host(self):
        """
        Returns true if this is a known pdaq control machine
        """
        return True if self.__host_type == self.CONTROL_HOST else False

    @classmethod
    def is_host(cls, hostbits):
        """
        Return True if this host is one of the types specified in 'hostbits'
        """
        hostid = Machineid()
        return (hostid.__host_type & hostbits) != 0

    def is_spade_host(self):
        """
        Returns true if this is a known pdaq machine which writes data to SPADE
        """
        return True if self.__host_type == self.CONTROL_HOST else False

    def is_unknown_host(self):
        """
        Returns true if this is not a known pdaq build or control machine
        and false otherwise.
        If an unknown host and an unknown cluster, it is assumed that you can
        run anything you want.
        """
        return True if self.__host_type == self.UNKNOWN_HOST else False

    def is_sps_cluster(self):
        """Returns true if this is a member of the south pole cluster
        and false otherwise.
        """
        return True if self.__cluster_type == self.SPS_CLUSTER else False

    def is_spts_cluster(self):
        """Returns true if this is a member of the south pole teest system and
        false otherwise.
        """
        return True if self.__cluster_type == self.SPTS_CLUSTER else False

    def is_unknown_cluster(self):
        """Returns true if this is not member of any known pdaq cluster and
        false otherwise.
        This will be used in conjunction with isUnknownHost to identify
        machines that do not need protection against running control
        scripts.
        """
        return True if self.__cluster_type == self.UNKNOWN_CLUSTER else False

    @property
    def hname(self):
        return self.__hname


if __name__ == "__main__":
    TEST = Machineid()
    print TEST
