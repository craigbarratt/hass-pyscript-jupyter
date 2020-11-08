# HASS Pyscript kernel shim for Jupyter

[Pyscript](https://github.com/custom-components/pyscript) provides a kernel that interfaces with the
Jupyter front-ends (eg, notebook, console, lab, and also VSCode). That allows you to develop and
test pyscript triggers, functions and automation logic interactively. Plus you can interact with
much of HASS by looking at state variables and calling services as you experiment and develop your
own logic and automations.

This repository provides a shim that sits between HASS pyscript and Jupyter. When Jupyter starts a
kernel, it is configured to run the script `hass_pyscript_kernel.py` in this repository. This script
uses the HASS web interface to do a service call to pyscript that starts the kernel. It then helps
establish the various socket connections between HASS/pyscript and Jupyter.

## Installation

To install the pyscript Jupyter kernel:
```
pip install hass_pyscript_kernel
jupyter pyscript install
```
Running `jupyter pyscript install` is only required on new installs, or if your old
version of `hass_pyscript_kernel` is prior to 1.0.0.

On a new install, you'll need to edit the `pyscript.conf` file. The install command above
will print its path. Replace these settings:

- `hass_host` with the host name or IP address where your HASS instance is running
- `hass_url` with the URL of your HASS httpd service
- `hass_token` with a long-lived access token created via the button at the bottom of
   your user profile page in HASS.
- Since you've added a HASS access token to this file, you should make sure you are
  comfortable with file permissions - anyone who can read this file could use the
  access token to use the HASS UI without being an authenticated user.
- `hass_proxy` with proxy url to use if HASS is not directly reachable.
  e.g. when using SSH to access your HASS instance, you can open a SOCKS5 tunnel to
  keep your Jupyter local. 

Confirm that Jupyter now recognizes the new pyscript kernel:
```
jupyter kernelspec list
```
and you can confirm the settings you added above with:
```
jupyter pyscript info
```

## Running Jupyter

You can open the browser-based Jupyter clients (eg, notebook and lab) as usual, eg:
```
jupyter notebook
```
and use the Jupyter menus to start a new `hass pyscript` kernel.

For the Jupyter command-line console, you can run:
```
jupyter console --kernel=pyscript
```

If Jupyter can't connect look at [this wiki page](https://github.com/craigbarratt/hass-pyscript-jupyter/wiki/Connection-problems)
for suggestions.

## Tutorial

There is a Jupyter notebook [tutorial](https://nbviewer.jupyter.org/github/craigbarratt/hass-pyscript-jupyter/blob/master/pyscript_tutorial.ipynb)
that covers many pyscript features.  It can be downlaoded and run interactively in Jupyter
notebook connected to your live HASS with pyscript.  You can download the `pyscript_tutorial.ipynb`
notebook using:
```
wget https://github.com/craigbarratt/hass-pyscript-jupyter/raw/master/pyscript_tutorial.ipynb
```
and open it with:
```
jupyter notebook pyscript_tutorial.ipynb
```

You can step through each command by hitting `<Shift>Enter`.  There are various ways to navigate
and run cells in Jupyter that you can read in the Jupyter documentation.

## Work Flow

Using the tutorial as examples, you can use a Jupyter client to interactively develop and test
functions, triggers and services.

Jupyter auto-completion (with `<TAB>`) is supported in Jupyter notebook, console and lab. It should
work after you have typed at least the first character. After you hit `<TAB>` you should see a
list of potential completions from which you can select. It's a great way to easily see available
state variables, functions or services.

In a Jupyter session, one or more functions can be defined in each code cell. Every time that
cell is executed (eg, `<Shift>Return`), those functions are redefined, and any existing trigger
decorators with the same function name are canceled and replaced by the new definition. You might
have other function and trigger definitions in another cell - they won't be affected (assuming
those function names are different), and they will only be replaced when you re-execute that
other cell.

See [more documentation](https://hacs-pyscript.readthedocs.io/en/stable/reference.html#workflow).

## Global Context

Each Jupyter session has its own separate global context, so functions and variables defined in each
interactive session are isolated from the script files and other Jupyter sessions.  Pyscript
provides some utility functions to switch global contexts, which allows an interactive Jupyter
session to interact directly with functions and global variables created by a script file, or even
another Jupyter session.

See the [documentation on global contexts](https://hacs-pyscript.readthedocs.io/en/stable/reference.html#global-context).

## Caveats

Here are some caveats about using specific clients with the pyscript Jupyter kernel:

For Jupyter notebook:
* Jupyter notebook supports a wide range of extensions, called nbextensions. Some of these might not
work correctly with pyscript's kernel. The black and isort nbextensions do work. If you are having
problems with notebooks running on the pyscript kernel, try disabling other nbextensions. Please
report nbextentions that you think are useful but don't work with pyscript's kernel and we'll
look at supporting them.

For Jupyter console:
* Jupyter console allows multi-line input (eg, a function definition) and delays excution by the
kernel until it is syntactically correct (ie, complete) and the indent on the last line is 0.  So if
you define a multi-line function or statement with indenting, you will need to hit `Enter` one more
time so there is an empty line indicating your code block is complete.

* Jupyter console generally assumes the kernel operates in a half-duplex manner - it sends a snippet
of code to the kernel to be executed, and the result (if any) and output (if any) are then displayed.
In pyscript, a trigger function runs asynchonously, so it can generate output at some future time.
In Jupyter notebook and lab, the right thing happens - whenever the output messages are generated, they
appear below the last cell that was executed. Jupyter notebook displays the running list of log output.
However, in Jupter console, it doesn't check for any output from the kernel until you hit `Enter` to
execute the next command. So the display of output in the console is delayed until you hit `Enter`.
The HASS log file will show any log output in real time, subject to the logging level threshold.

For Jupyter lab:
* In Jupyter lab, each tab starts a new session (which is same behavior with iPython - each tab will
have a different iPython instance), so each tab (eg, a notebook in one and a console in another)
will have different global contexts. If you wish, you can use the function `pyscript.set_global_ctx()`
to set the context in the other tabs to be the same as the first.

For VSCode:
* Like Jupyter console, `log` and `print` output from trigger functions won't be displayed by VSCode
since their output is generated after the current code cell execution is complete.  You'll need to
look at the HASS log file for log output from your trigger functions.
* Some unresolved bug causes VSCode to start two pyscript Jupyter kernels, and the second one is
typically shutdown soon after it starts. This seems to be benign - it should be invisible to the
user, although the global context names (eg, jupyter_0) will increment by 2 on each new session,
rather than 1.

## Contributing

Contributions are welcome! You are encouraged to submit PRs, bug reports, feature requests or
add to the Wiki with examples and tutorials. It would be fun to hear about unique and clever
applications you develop.

## Developing and installing locally

From a clone of this repository run:
```
python -m pip install -r requirements.txt
python setup.py bdist_wheel
pip install dist/hass_pyscript_kernel-VERSION-py3-none-any.whl
```
where `VERSION` is version specified in `hass_pyscript_kernel/version.py`.

## Useful Links

* [Pyscript Documentation](https://hacs-pyscript.readthedocs.io/en/stable/index.html)
* [PyPi Project Page](https://pypi.org/project/hass-pyscript-kernel)
* [Issues](https://github.com/craigbarratt/hass-pyscript-jupyter/issues)
* [Wiki](https://github.com/craigbarratt/hass-pyscript-jupyter/wiki)
* [GitHub repository](https://github.com/craigbarratt/hass-pyscript-jupyter) (please add a star if you like it!)
* [Jupyter notebook tutorial](https://nbviewer.jupyter.org/github/craigbarratt/hass-pyscript-jupyter/blob/master/pyscript_tutorial.ipynb)
* [Pyscript](https://github.com/custom-components/pyscript)

## Copyright

Copyright (c) 2020 Craig Barratt.  May be freely used and copied according to the terms of the
[Apache 2.0 License](LICENSE).
