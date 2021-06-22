#!/usr/bin/env python

from __future__ import print_function

import argparse
import glob
import os
import sys

from validate_configs import validate_runconfig


def main():
    "Main program"

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--config_dir", dest="config_dir",
                        action="store", default=None,
                        help="Run Config Directory")
    args = parser.parse_args()

    if args.config_dir is not None:
        config_path = args.config_dir
    else:
        sys.path.append('..')
        from locate_pdaq import find_pdaq_config
        config_path = find_pdaq_config()

    print("Validating all runconfig files in %s" % config_path)
    print("")

    invalid_found = False
    run_configs = glob.glob(os.path.join(config_path, '*.xml'))

    # remove the default dom geometry file from the above list
    for entry in run_configs:
        basename = os.path.basename(entry)
        if basename == 'default-dom-geometry.xml':
            run_configs.remove(entry)
            break

    num = 0
    for run_config in run_configs:
        num += 1
        valid, reason = validate_runconfig(run_config)

        if not valid:
            print("File is not valid! (%s)" % run_config)
            print("-" * 60)
            print("")
            print(reason)
            invalid_found = True

    if not invalid_found:
        print("No invalid run configuration files found (of %d)" % num)


if __name__ == "__main__":
    main()
