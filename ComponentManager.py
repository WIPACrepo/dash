#!/usr/bin/env python
"""
DAQ component manager - handle launching and killing a set of components
"""

import os
import signal
import sys
import traceback

from utils import ip

from CachedConfigName import CachedFile
from ClusterDescription import HubComponent, JavaComponent, ReplayHubComponent
from DAQConfig import DAQConfigParser
from DAQConfigExceptions import DAQConfigException
from DAQConst import DAQPort
from DAQRPC import RPCClient
from LiveImports import MoniPort
from ParallelShell import ParallelShell
from Process import find_python_process
from RunSetState import RunSetState
from i3helper import reraise_excinfo
from locate_pdaq import find_pdaq_trunk


SVN_ID = "$Id: DAQLaunch.py 13550 2012-03-08 23:12:05Z dglo $"


class ComponentNotFoundInDatabase(Exception):
    "Thrown when a caller specified an unknown component"
    pass


class ComponentManager(object):
    "Manage pDAQ components"

    # the pDAQ release name
    #
    RELEASE = "1.0.0-SNAPSHOT"

    # Component Name -> JarParts mapping.  For constructing the name of
    # the proper jar file used for running the component, based on the
    # lower-case name of the component.
    __COMP_JAR_MAP = {
        "eventbuilder": ("eventBuilder-prod", "comp"),
        "secondarybuilders": ("secondaryBuilders", "comp"),
        "inicetrigger": ("trigger", "iitrig"),
        "simpletrigger": ("trigger", "simptrig"),
        "icetoptrigger": ("trigger", "ittrig"),
        "globaltrigger": ("trigger", "gtrig"),
        "amandatrigger": ("trigger", "amtrig"),
        "stringhub": ("StringHub", "comp"),
        "replayhub": ("StringHub", "replay")
        }

    @classmethod
    def __convert_dict(cls, compdicts):
        """
        Convert a list of CnCServer component dictionaries
        to a list of component objects
        """
        comps = []
        for cdict in compdicts:
            # XXX this should use the appropriate Component object
            comp = HubComponent(cdict["compName"], cdict["compNum"],
                                "??logLevel??", False)
            comp.host = cdict["host"]
            comp.set_jvm_options(None, "??jvmPath??", "??jvmServer??",
                                 "??jvmHeapInit??", "??jvmHeapMax??",
                                 "??jvmArgs??", "??jvmExtra??")
            comp.set_hit_spool_options(None, "??hsDir??", "??hsInterval??",
                                       "??hsMaxFiles??")
            comp.set_hub_options(None, "??alertEMail??", "??ntpHost??")
            comps.append(comp)
        return comps

    @classmethod
    def __create_and_expand(cls, dirname, fallback_dir, logger, dry_run=False):
        """
        Create the directory if it doesn't exist.
        Return the fully qualified path
        """
        if dirname is not None:
            if not os.path.isabs(dirname):
                # non-fully-qualified paths are relative
                # to metaproject top dir:
                meta_dir = find_pdaq_trunk()
                dirname = os.path.join(meta_dir, dirname)
            if not os.path.exists(dirname) and not dry_run:
                try:
                    os.makedirs(dirname)
                except OSError as oserr:
                    if fallback_dir is None:
                        reraise_excinfo(sys.exc_info())
                    else:
                        if logger is not None:
                            logger.error(("Problem making directory \"%s\"" +
                                          " (%s)") % (dirname, oserr.strerror))
                            logger.error("Using fallback directory \"%s\"" %
                                         str(fallback_dir))
                        dirname = fallback_dir
                        if not os.path.exists(dirname):
                            os.mkdir(dirname)

        return dirname

    @classmethod
    def __get_cnc_components(cls, cncrpc=None, runset_id=None):
        """
        Fetch the list of all components from CnCServer
        """
        if cncrpc is None:
            cncrpc = RPCClient('localhost', DAQPort.CNCSERVER)

        comps = []

        runsets = cls.__get_runsets(cncrpc)
        if runset_id is not None:
            if runset_id in runsets:
                comps += cls.__convert_dict(runsets[runset_id][1])
        else:
            unused = cls.__get_unused(cncrpc)
            comps += cls.__convert_dict(unused)
            for runset in runsets:
                comps += cls.__convert_dict(runset)
        return comps

    @classmethod
    def __get_runsets(cls, cncrpc):
        """
        Return a list of dictionaries describing the components in every RunSet
        Dictionary keys are 'type', 'compName', 'compNum', 'host', 'port', and
        'state'
        """
        runsets = []
        ids = cncrpc.rpc_runset_list_ids()
        for runid in ids:
            runsets.append(cncrpc.rpc_runset_list(runid))

        return runsets

    @classmethod
    def __get_unused(cls, cncrpc):
        return cncrpc.rpc_component_list_dicts([], False)

    @classmethod
    def __is_running(cls, proc_name):
        "Is this process running?"
        for _ in find_python_process(proc_name):
            return True
        return False

    @classmethod
    def __report_action(cls, logger, action, action_list, ignored):
        "Report which daemons were launched/killed and which were ignored"

        if logger is not None:
            if len(action_list) > 0:
                if len(ignored) > 0:
                    logger.info("%s %s, ignored %s" %
                                (action, ", ".join(action_list),
                                 ", ".join(ignored)))
                else:
                    logger.info("%s %s" % (action, ", ".join(action_list)))
            elif len(ignored) > 0:
                logger.info("Ignored %s" % ", ".join(ignored))

    @classmethod
    def __generate_kill_cmd(cls, comp, kill_with_9):
        if comp.is_hub:
            kill_str = "stringhub.componentId=%d " % comp.id
        else:
            kill_str = cls.get_component_jar(comp.name)

        user = os.environ['USER']

        if comp.is_localhost:
            ssh_prefix = ""
            kill_opt = "-fu %s" % (user, )
        else:
            ssh_prefix = "ssh %s " % (comp.host, )
            kill_opt = "-f"

        fmt_str = "%spkill %%s %s \"%s\"" % (ssh_prefix, kill_opt, kill_str)

        # add '-' on first command
        if kill_with_9:
            add9 = 0
        else:
            add9 = 1

        # only do one pass if we're using 'kill -9'
        for i in range(add9 + 1):
            # set '-9' flag
            if i == add9:
                niner = "-9"
            else:
                niner = ""

            # sleep for all commands after the first pass
            if i == 0:
                sleepr = ""
            else:
                sleepr = "sleep 2; "

            yield sleepr + (fmt_str % niner)

    @classmethod
    def __build_start_cmd(cls, comp, dry_run, verbose, config_dir, daq_data_dir,
                          bin_dir, log_port, live_port, event_check,
                          check_exists, logger):
        """
        Construct the command to start this component
        """
        my_ip_addr = ip.get_local_address(comp.host)
        jar_path = os.path.join(bin_dir, cls.get_component_jar(comp.name))
        if check_exists and not os.path.exists(jar_path) and not dry_run:
            if logger is not None:
                logger.error("%s jar file does not exist: %s" %
                             (comp.name, jar_path))
            return None

        jvm_path = comp.jvm_path

        jvm_args = "-Dicecube.daq.component.configDir='%s'" % config_dir
        if comp.jvm_server is not None and comp.jvm_server:
            jvm_args += " -server"
        if comp.jvm_heap_init is not None and len(comp.jvm_heap_init) > 0:
            jvm_args += " -Xms" + comp.jvm_heap_init
        if comp.jvm_heap_max is not None and len(comp.jvm_heap_max) > 0:
            jvm_args += " -Xmx" + comp.jvm_heap_max
        if comp.jvm_args is not None and len(comp.jvm_args) > 0:
            jvm_args += " " + comp.jvm_args
        if comp.jvm_extra_args is not None and len(comp.jvm_extra_args) > 0:
            jvm_args += " " + comp.jvm_extra_args

        if comp.is_real_hub:
            if comp.ntp_host is not None:
                jvm_args += " -Dicecube.daq.time.monitoring.ntp-host=%s" % \
                  (comp.ntp_host, )
            if comp.alert_email is not None:
                jvm_args += " -Dicecube.daq.stringhub.alert-email=%s" % \
                  (comp.alert_email, )
        else:
            if comp.num_replay_files_to_skip is not None and \
              comp.num_replay_files_to_skip > 0:
                jvm_args += " -Dreplay.skipFiles=%d" % \
                  (comp.num_replay_files_to_skip, )

        if comp.has_hitspool_options:
            if comp.hitspool_directory is not None:
                jvm_args += " -Dhitspool.directory=\"%s\"" % \
                  (comp.hitspool_directory, )
            if comp.hitspool_interval is not None:
                jvm_args += " -Dhitspool.interval=%.4f" % \
                  (comp.hitspool_interval, )
            if comp.hitspool_max_files is not None:
                jvm_args += " -Dhitspool.maxfiles=%d" % \
                  (comp.hitspool_max_files, )

        switches = "-d %s" % daq_data_dir
        switches += " -c %s:%d" % (my_ip_addr, DAQPort.CNCSERVER)
        if log_port is not None:
            switches += " -l %s:%d,%s" % \
              (my_ip_addr, log_port, comp.log_level)
        if live_port is not None:
            switches += " -L %s:%d,%s" % \
              (my_ip_addr, live_port, comp.log_level)
            switches += " -M %s:%d" % (my_ip_addr, MoniPort)

        if comp.is_hub:
            jvm_args += " -Dicecube.daq.stringhub.componentId=%d" % comp.id

        if event_check and comp.is_builder:
            jvm_args += " -Dicecube.daq.eventBuilder.validateEvents"

        # how are I/O streams handled?
        if not verbose:
            shell_redirect = " </dev/null >/dev/null 2>&1"
        else:
            shell_redirect = ""

        return "%s %s -jar %s %s %s &" % \
          (jvm_path, jvm_args, jar_path, switches, shell_redirect)

    @classmethod
    def __build_component_list(cls, cluster_config):
        comp_list = []
        for node in cluster_config.nodes():
            for comp in node.components:
                if not comp.is_control_server:
                    if comp.has_hitspool_options:
                        if comp.has_replay_options:
                            rcomp = ReplayHubComponent(comp.name, comp.id,
                                                       comp.log_level, False)
                            rcomp.num_replay_files_to_skip \
                              = comp.num_replay_files_to_skip
                        else:
                            rcomp = HubComponent(comp.name, comp.id,
                                                 comp.log_level, False)
                        rcomp.set_hit_spool_options(None,
                                                    comp.hitspool_directory,
                                                    comp.hitspool_interval,
                                                    comp.hitspool_max_files)
                        if comp.is_real_hub:
                            rcomp.set_hub_options(None, comp.alert_email,
                                                  comp.ntp_host)
                    else:
                        rcomp = JavaComponent(comp.name, comp.id,
                                              comp.log_level, False)

                    rcomp.host = node.hostname
                    rcomp.set_jvm_options(None, comp.jvm_path, comp.jvm_server,
                                          comp.jvm_heap_init, comp.jvm_heap_max,
                                          comp.jvm_args, comp.jvm_extra_args)

                    comp_list.append(rcomp)
        return comp_list

    @classmethod
    def count_active_runsets(cls):
        "Return the number of active runsets"
        # connect to CnCServer
        cnc = RPCClient('localhost', DAQPort.CNCSERVER)

        # Get the number of active runsets from CnCServer
        try:
            has_sets = cnc.rpc_runset_count() > 0
        except:
            has_sets = False

        runsets = {}

        active = 0
        if has_sets:
            inactive = (RunSetState.READY, RunSetState.IDLE,
                        RunSetState.DESTROYED, RunSetState.ERROR)

            for rid in cnc.rpc_runset_list_ids():
                runsets[rid] = cnc.rpc_runset_state(rid)
                if runsets[rid] not in inactive:
                    active += 1

        return (runsets, active)

    @classmethod
    def format_component_list(cls, comp_list):
        """
        Concatenate a list of components into a string showing names and IDs
        """
        comp_dict = {}
        for comp in comp_list:
            if comp.name not in comp_dict:
                comp_dict[comp.name] = [comp, ]
            else:
                comp_dict[comp.name].append(comp)

        has_order = True

        pair_list = []
        for k in sorted(list(comp_dict.keys()),
                        key=lambda nm: len(comp_dict[nm]), reverse=True):
            if len(comp_dict[k]) == 1 and comp_dict[k][0].num == 0:
                pair_name = comp_dict[k][0].name

                if not has_order:
                    pair_order = comp_dict[k][0].name
                else:
                    try:
                        pair_order = comp_dict[k][0].order
                    except AttributeError:
                        has_order = False
                        pair_order = comp_dict[k][0].name
            else:
                prev_num = None
                pair_name = k + "#"
                for comp in sorted(comp_dict[k], key=lambda c: c.num):
                    if prev_num is None:
                        pair_name += "%d" % comp.num
                    elif comp.num == prev_num + 1:
                        if not pair_name.endswith("-"):
                            pair_name += "-"
                    else:
                        if pair_name.endswith("-"):
                            pair_name += "%d" % prev_num
                        pair_name += ",%d" % comp.num
                    prev_num = comp.num

                if pair_name.endswith("-"):
                    pair_name += "%d" % prev_num

                if not has_order:
                    pair_order = comp_dict[k][0].name
                else:
                    try:
                        pair_order = comp_dict[k][0].order
                    except AttributeError:
                        has_order = False
                        pair_order = comp_dict[k][0].name

            if pair_order is None:
                pair_order = 0

            pair_list.append((pair_name, pair_order))

        str_list = []
        for pair in sorted(pair_list, key=lambda pair: pair[1]):
            str_list.append(pair[0])

        return ", ".join(str_list)

    @classmethod
    def get_active_components(cls, cluster_desc, config_dir=None,
                              validate=True, use_cnc=False, logger=None):
        "Return a list of objects describing all components known by CnCServer"
        if not use_cnc:
            comps = None
        else:
            # try to extract component info from CnCServer
            #
            try:
                comps = cls.__get_cnc_components()
                if logger is not None:
                    logger.info("Extracted active components from CnCServer")
            except:
                if logger is not None:
                    logger.error("Failed to extract active components:\n" +
                                 traceback.format_exc())
                comps = None

        if comps is None:
            try:
                active_config = \
                    DAQConfigParser.get_cluster_configuration\
                    (None, use_active_config=True, cluster_desc=cluster_desc,
                     config_dir=config_dir, validate=validate)
            except DAQConfigException as dce:
                if str(dce).find("RELAXNG") >= 0:
                    reraise_excinfo(sys.exc_info())
                active_config = None

            if active_config is not None:
                comps = cls.__build_component_list(active_config)
            else:
                comps = []

            if logger is not None:
                if active_config is not None:
                    logger.info("Extracted component list from %s" %
                                active_config.config_name)
                else:
                    logger.info("No active components found")

        return comps

    @classmethod
    def get_component_jar(cls, comp_name):
        """
        Return the name of the executable jar file for the named component.
        """

        parts = cls.__COMP_JAR_MAP.get(comp_name.lower(), None)
        if not parts:
            raise ComponentNotFoundInDatabase(comp_name)

        return "%s-%s-%s.jar" % (parts[0], cls.RELEASE, parts[1])

    @classmethod
    def kill(cls, comps, verbose=False, dry_run=False,
             kill_cnc=True, kill_with_9=False, logger=None, parallel=None):
        "Kill pDAQ python and java components"

        killed = []
        ignored = []

        server_name = "CnCServer"
        if kill_cnc:
            if cls.__kill_process(server_name, dry_run, logger):
                killed.append(server_name)
        elif not dry_run:
            ignored.append(server_name)

        # clear the active configuration
        if not dry_run:
            CachedFile.clear_active_config()

        cls.kill_components(comps, dry_run=dry_run, verbose=verbose,
                            kill_with_9=kill_with_9, logger=logger,
                            parallel=parallel)

        if verbose and not dry_run and logger is not None:
            logger.info("DONE killing Java Processes.")
        if len(killed) > 0 or len(ignored) > 0 or len(comps) > 0:
            jstr = cls.format_component_list(comps)
            jlist = jstr.split(", ")
            try:
                # CnCServer may be part of the list of launched components
                jlist.remove(server_name)
            except:
                pass
            cls.__report_action(logger, "Killed", killed + jlist, ignored)

    @classmethod
    def kill_components(cls, comp_list, dry_run=False, verbose=False,
                        kill_with_9=False, logger=None, parallel=None):
        """
        Kill the processes of the listed components
        """
        if parallel is None:
            parallel = ParallelShell(dry_run=dry_run, verbose=verbose,
                                     trace=verbose, timeout=30)

        cmd2host = {}
        for comp in comp_list:
            if comp.jvm_path is None:
                continue

            if comp.is_hub:
                kill_pat = "stringhub.componentId=%d " % comp.id
            else:
                kill_pat = cls.get_component_jar(comp.name)

            for cmd in cls.__generate_kill_cmd(comp, kill_with_9):
                if verbose or dry_run:
                    if logger is not None:
                        logger.info(cmd)
                if not dry_run:
                    parallel.add(cmd)
                    cmd2host[cmd] = comp.host

        if not dry_run:
            parallel.shuffle()
            parallel.start()
            parallel.wait()

            # check for ssh failures here
            for cmd, rtuple in parallel.command_results.items():
                rtn_code, results = rtuple
                if cmd in cmd2host:
                    node_name = cmd2host[cmd]
                else:
                    node_name = "unknown"
                # pkill return codes
                # 0 -> killed something
                # 1 -> no matched process to kill
                # 1 is okay..  expected if nothing is running
                if rtn_code > 1 and logger is not None:
                    logger.error(("Error non-zero return code ( %s ) "
                                  "for host: %s, cmd: %s") %
                                 (rtn_code, node_name, cmd))
                    logger.error("Results '%s'" % results)

    @classmethod
    def __kill_process(cls, proc_name, dry_run=False, logger=None):
        pid = int(os.getpid())

        rtnval = False
        for xpid in find_python_process(proc_name):
            if pid != xpid:
                if dry_run:
                    if logger is not None:
                        logger.info("kill -KILL %d" % xpid)
                else:
                    os.kill(xpid, signal.SIGKILL)
                rtnval = True
        return rtnval

    @classmethod
    def launch(cls, do_cnc, dry_run, verbose, cluster_config, dash_dir,
               config_dir, daq_data_dir, log_dir, log_dir_fallback, spade_dir,
               copy_dir, log_port, live_port, event_check=False,
               check_exists=True, start_missing=True, logger=None,
               parallel=None, force_restart=True):
        """Launch components"""

        # create missing directories
        spade_dir = cls.__create_and_expand(spade_dir, None, logger, dry_run)
        copy_dir = cls.__create_and_expand(copy_dir, None, logger, dry_run)
        log_dir = cls.__create_and_expand(log_dir, log_dir_fallback, logger,
                                          dry_run)
        daq_data_dir = cls.__create_and_expand(daq_data_dir, None, logger,
                                               dry_run)

        launched = []
        ignored = []

        prog_base = "CnCServer"

        if start_missing and not do_cnc:
            # get a list of the running processes
            do_cnc |= not cls.__is_running(prog_base)

        if do_cnc:
            path = os.path.join(dash_dir, prog_base + ".py")
            options = " -c %s -o %s -q %s" % \
                (config_dir, log_dir, daq_data_dir)
            if spade_dir is not None:
                options += ' -s ' + spade_dir
            if cluster_config.description is not None:
                options += ' -C ' + cluster_config.description
            if log_port is not None:
                options += ' -l localhost:%d' % log_port
            if live_port is not None:
                options += ' -L localhost:%d' % live_port
            if copy_dir is not None:
                options += " -a %s" % copy_dir
            if not force_restart:
                options += ' -F'
            if verbose:
                options += ' &'
            else:
                options += ' -d'

            cmd = "%s%s" % (path, options)
            if verbose or dry_run:
                if logger is not None:
                    logger.info(cmd)
            if not dry_run:
                # start CnCServer daemon
                # use parallel.system() so unit tests can override it
                parallel.system(cmd)
                launched.append(prog_base)
        elif not dry_run:
            ignored.append(prog_base)

        comps = cls.__build_component_list(cluster_config)

        cls.start_components(comps, dry_run, verbose, config_dir, daq_data_dir,
                             DAQPort.CATCHALL, live_port, event_check,
                             check_exists=check_exists, logger=logger,
                             parallel=parallel)

        if verbose and not dry_run and logger is not None:
            logger.info("DONE with starting Java Processes.")
        if len(launched) > 0 or len(ignored) > 0 or len(comps) > 0:
            jstr = cls.format_component_list(comps)
            jlist = jstr.split(", ")
            cls.__report_action(logger, "Launched", launched + jlist, ignored)

        # remember the active configuration
        cluster_config.write_cache_file(write_active_config=True)

    @classmethod
    def list_known_component_names(cls):
        "Return the list of all components supported by this object"
        return list(cls.__COMP_JAR_MAP.keys())

    @classmethod
    def start_components(cls, comp_list, dry_run, verbose, config_dir,
                         daq_data_dir, log_port, live_port, event_check,
                         check_exists=True, logger=None, parallel=None):
        """
        Start the components listed in 'comp_list'
        (All list elements should be Component objects)
        """
        if parallel is None:
            parallel = ParallelShell(dry_run=dry_run, verbose=verbose,
                                     trace=verbose, timeout=30)

        meta_dir = find_pdaq_trunk()

        # The dir where all the "executable" jar files are
        bin_dir = os.path.join(meta_dir, 'target', 'pDAQ-%s-dist' % cls.RELEASE,
                               'bin')
        if check_exists and not os.path.isdir(bin_dir):
            bin_dir = os.path.join(meta_dir, 'target',
                                   'pDAQ-%s-dist.dir' % cls.RELEASE, 'bin')
            if not os.path.isdir(bin_dir) and not dry_run:
                raise SystemExit("Cannot find jar file directory \"%s\"" %
                                 bin_dir)

        # how are I/O streams handled?
        if not verbose:
            quiet_str = " </dev/null >/dev/null 2>&1"
        else:
            quiet_str = ""

        cmd2host = {}
        for comp in comp_list:
            if comp.jvm_path is None:
                continue

            basecmd = cls.__build_start_cmd(comp, dry_run, verbose, config_dir,
                                            daq_data_dir, bin_dir, log_port,
                                            live_port, event_check,
                                            check_exists, logger)
            if basecmd is None:
                continue

            if comp.is_localhost:
                cmd = basecmd
            else:
                cmd = "ssh -n %s 'sh -c \"%s\"%s &'" % \
                    (comp.host, basecmd, quiet_str)

            cmd2host[cmd] = comp.host
            if verbose or dry_run:
                if logger is not None:
                    logger.info(cmd)
            if not dry_run:
                parallel.add(cmd)

        if verbose and not dry_run:
            parallel.show_all()
        if not dry_run:
            parallel.shuffle()
            parallel.start()
            if not verbose:
                # if we wait during verbose mode, the program hangs
                parallel.wait()

                # check for ssh failures here
                for cmd, rtuple in parallel.command_results.items():
                    rtn_code, results = rtuple
                    if cmd in cmd2host:
                        node_name = cmd2host[cmd]
                    else:
                        node_name = "unknown"
                    if rtn_code != 0 and logger is not None:
                        logger.error(("Error non zero return code ( %s )" +
                                      " for host: %s, cmd: %s") %
                                     (rtn_code, node_name, cmd))
                        logger.error("Results '%s'" % results)


if __name__ == '__main__':
    pass
