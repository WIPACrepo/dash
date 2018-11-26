from validate_configs import validate_trigger
import glob
import os
import sys

if __name__ == "__main__":
    sys.path.append('..')
    from locate_pdaq import find_pdaq_config
    config_path = find_pdaq_config()

    print "Validating all trigger configuration files"
    print "Will only print a status when a corrupt file is found"
    print "Note that there are some corrupt trigger files, " \
        "someone put quotes in the wrong place."
    print "-" * 60
    print ""

    trigger_config_path = os.path.join(config_path, "trigger")

    invalid_found = False
    trigger_configs = glob.glob(os.path.join(trigger_config_path, '*.xml'))
    for trigger_config in trigger_configs:
        valid, reason = validate_trigger(trigger_config)
        if not valid:
            print "File is not valid! (%s)" % trigger_config
            print "-" * 60
            print ""
            print reason
            invalid_found = True

    if not invalid_found:
        print "No invalid trigger configuration files found"
