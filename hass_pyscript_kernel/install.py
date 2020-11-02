"""Command-line installer for pyscript kernel shim."""

import argparse
import json
import os
import shutil

from jupyter_client.kernelspec import KernelSpecManager
from jupyter_core.paths import SYSTEM_JUPYTER_PATH

from .shim import CONFIG_SETTINGS, PKG_NAME, load_config

SCRIPT_NAME = "jupyter-pyscript"


def install(target_dir, kernel_name):
    """Install a pyscript kernel with the given name in the target_dir."""
    if target_dir is None:
        #
        # use jupyter system path if the caller didn't specify
        #
        target_dir = os.path.join(SYSTEM_JUPYTER_PATH[0], "kernels", kernel_name)

    os.makedirs(target_dir, exist_ok=True)
    copy_files = ["logo-32x32.png", "logo-64x64.png"]
    if os.path.isfile(os.path.join(target_dir, "pyscript.conf")):
        #
        # don't copy pyscript.conf in upgrade case
        #
        new_install = False
    else:
        #
        # also copy pyscript.conf for new install
        #
        copy_files.append("pyscript.conf")
        new_install = True
    src_dir = os.path.join(os.path.dirname(__file__), "kernel_files")
    for file in copy_files:
        shutil.copy(os.path.join(src_dir, file), os.path.join(target_dir, file))

    #
    # create and write the kernel.json file
    #
    argv = ["python", "-m", PKG_NAME]
    if kernel_name != "pyscript":
        argv += ["-k", kernel_name]
    argv.append("{connection_file}")
    kernel_spec = {
        "argv": argv,
        "display_name": f"hass {kernel_name}",
        "language": "python",
    }

    with open(os.path.join(target_dir, "kernel.json"), "w") as ofd:
        json.dump(kernel_spec, ofd, indent=2, sort_keys=True)

    if new_install:
        print(f"installed new {kernel_name} kernel in {target_dir}")
        print(f"you will need to update the settings in {target_dir}/pyscript.conf")
    else:
        print(f"updated {kernel_name} kernel in {target_dir}")


def install_main():
    """Main function: execute install and other options."""
    parser = argparse.ArgumentParser(prog=SCRIPT_NAME)
    parser.add_argument("action", type=str, help="install|info")
    parser.add_argument(
        "-k", "--kernel-name", type=str, help="kernel name", default="pyscript", dest="kernel_name"
    )
    args = parser.parse_args()

    if args.action == "install":
        kernels = KernelSpecManager().find_kernel_specs()
        #
        # use existing target_dir; otherwise put alongside python3 or python
        #
        target_dir = kernels.get(args.kernel_name, None)
        if target_dir is None:
            for other in ["python3", "python"]:
                if other in kernels:
                    target_dir = os.path.join(os.path.dirname(kernels[other]), args.kernel_name)
                    break

        install(target_dir, args.kernel_name)

    elif args.action == "info":
        kernels = KernelSpecManager().find_kernel_specs()
        if args.kernel_name not in kernels:
            print(f"No installed kernel named {args.kernel_name} found")
        else:
            print(f"Kernel {args.kernel_name} installed in {kernels[args.kernel_name]}")
            print(f"Config settings from {kernels[args.kernel_name]}/pyscript.conf:")
            load_config(args.kernel_name)
            for opt in ["hass_host", "hass_url", "hass_token", "hass_proxy"]:
                print(f"    {opt} = {CONFIG_SETTINGS[opt]}")

    else:
        parser.print_help()
        print(
            """Actions:
install - install or update a Jupyter pyscript kernel

info - list information about an installed pyscript kernel
"""
        )
