from validate_configs import validate_runconfig
import glob
import os
import sys


if __name__ == "__main__":
        sys.path.append('..')
    from locate_pdaq import find_pdaq_config
    config_path = find_pdaq_config()

    print "Validating all runconfig files"
    print ""

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
            print "File is not valid! (%s)" % run_config
            print "-" * 60
            print ""
            print reason
            invalid_found = True

    if not invalid_found:
        print "No invalid run configuration files found (of %d)" % num
