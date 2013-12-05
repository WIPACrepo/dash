"""Identify machines for the pdaq system."""
import socket


class Machineid:
    BUILD_HOSTS = ["access"]
    CONTROL_HOSTS = ["expcont", "pdaq2"]

    # cluster type constants
    SPS_CLUSTER, SPTS_CLUSTER, UNKNOWN_CLUSTER = range(3)

    # machine type constants
    BUILD_HOST, CONTROL_HOST, UNKNOWN_HOST = range(3)

    def __init__(self, hostname=None):
        if(hostname == None):
            self.hname = socket.gethostname()
        else:
            self.hname = hostname

        # figure out if we are part of a cluster
        if self.hname.endswith("icecube.southpole.usap.gov"):
            # we are part of the south pole system
            self.cluster_type = self.SPS_CLUSTER
        elif self.hname.endswith("spts.icecube.wisc.edu"):
            # we are part of the south pole TEST system
            self.cluster_type = self.SPTS_CLUSTER
        else:
            self.cluster_type = self.UNKNOWN_CLUSTER

        # now figure out what type of host this is
        split_host_name = self.hname.split('.', 1)[0]
        self.host_type = self.UNKNOWN_HOST
        for h in self.BUILD_HOSTS:
            if split_host_name.lower().find(h.lower()) >= 0:
            # we are a build host
                self.host_type = self.BUILD_HOST
        for h in self.CONTROL_HOSTS:
            if split_host_name.lower().find(h.lower()) >= 0:
            # we are a build host
                self.host_type = self.CONTROL_HOST

    def __str__(self):
        """Produces the informal string representation of this class"""

        host_type_str = "Unknown"
        if self.host_type == self.CONTROL_HOST:
            host_type_str = "Control Host"
        elif self.host_type == self.BUILD_HOST:
            host_type_str = "Build Host"

        cluster_type_str = "Unknown"
        if self.cluster_type == self.SPTS_CLUSTER:
            cluster_type_str = "South Pole Test System"
        elif self.cluster_type == self.SPS_CLUSTER:
            cluster_type_str = "South Pole System"

        return "Host name: '%s'\nHost Type: '%s'\nCluster Type: '%s'" % (
            self.hname, host_type_str, cluster_type_str)

    def is_build_host(self):
        """Returns true if this is a known pdaq build machine
        and false otherwise.
        This will be used to check for permissions to run DeployPDAQ"""

        return True if self.host_type == self.BUILD_HOST else False

    def is_control_host(self):
        """Returns true if this is a known pdaq control machine
        and false otherwise.
        This will be used to check for permissions to run DAQLaunch"""

        return True if self.host_type == self.CONTROL_HOST else False

    def is_unknown_host(self):
        """Returns true if this is not a known pdaq build or control machine
        and false otherwise.
        If an unknown host and an unknown cluster, it is assumed that you can
        run anything you want.
        """
        return True if self.host_type == self.UNKNOWN_HOST else False

    def is_sps_cluster(self):
        """Returns true if this is a member of the south pole cluster
        and false otherwise.
        """
        return True if self.cluster_type == self.SPS_CLUSTER else False

    def is_spts_cluster(self):
        """Returns true if this is a member of the south pole teest system and
        false otherwise.
        """
        return True if self.cluster_type == self.SPTS_CLUSTER else False

    def is_unknown_cluster(self):
        """Returns true if this is not member of any known pdaq cluster and
        false otherwise.
        This will be used in conjunction with isUnknownHost to identify
        machines that do not need protection against running control
        scripts.
        """
        return True if self.cluster_type == self.UNKNOWN_CLUSTER else False


if __name__ == "__main__":
    TEST = Machineid()
    print TEST
