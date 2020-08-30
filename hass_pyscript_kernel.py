"""Pyscript kernel shim for Jupyter."""

#
# Github: https://github.com/craigbarratt/hass-pyscript-jupyter
#
# Copyright (c) 2020 Craig Barratt.  May be freely used and copied according to the
# terms of the Apache 2.0 License:
#
#    https://github.com/craigbarratt/hass-pyscript-jupyter/blob/master/LICENSE
#

import argparse
import asyncio
import json
import requests
import secrets
import sys
import traceback

#
# Set HASS_HOST to the host name or IP address where your HASS is running.
# This should be a host name or IP address ou can ping from the Jupyter
# client machine.
#
HASS_HOST = "YOUR_HASS_HOST_OR_IP"

#
# Set HASS_URL to the URL of your HASS http interface. Typically the host
# name portion will be the same as HASS_HOST above.
#
HASS_URL = "http://YOUR_HASS_HOST_OR_IP:8123"

#
# Set HASS_TOKEN to a long-term access token created via the button
# at the bottom of your user profile page in HASS.
#
HASS_TOKEN = "REPLACE_WITH_THE_LONG_TERM_ACCESS_KEY_FROM_HASS"

#
# Our program name we print when --verbose is used
#
SCRIPT_NAME = "hass_pyscript_kernel.py"


def do_request(url, headers, data=None):
    """Do a GET or POST with the given URL."""
    try:
        req_type = "POST" if data else "GET"
        return requests.request(req_type, url, headers=headers, data=data)
    except requests.exceptions.ConnectionError as err:
        print(f"{SCRIPT_NAME}: unable to connect to {url} ({err})")
        sys.exit(1)
    except requests.exceptions.Timeout as err:
        print(f"{SCRIPT_NAME}: timeout connecting to {url} ({err})")
        sys.exit(1)
    except Exception as err:  # pylint: disable=broad-except
        print(f"{SCRIPT_NAME}: got error {err} (url={url})")
        sys.exit(1)


class RelayPort:
    """Define the RelayPort class, that does full-duplex forwarding between TCP endpoints."""

    def __init__(self, name, kernel_port, client_host, client_port, verbose=0):
        """Initialize a relay port."""
        self.name = name
        self.client_host = client_host
        self.client_port = client_port
        self.kernel_host = HASS_HOST
        self.kernel_port = kernel_port
        self.verbose = verbose

        self.client2kernel_task = None
        self.kernel2client_task = None
        self.kernel_connect_task = None
        self.client_server = None
        self.kernel_reader = None
        self.kernel_writer = None

    async def client_server_start(self, status_q):
        """Start a server that listens for client connections."""

        async def client_connected(reader, writer):
            try:
                if self.verbose >= 3:
                    print(
                        f"{SCRIPT_NAME}: {self.name} connected to jupyter client; now trying pyscript kernel at {self.kernel_host}:{self.kernel_port}"
                    )
                my_exit_q = asyncio.Queue(0)
                client_reader = reader
                client_writer = writer
                await status_q.put(["task_start", asyncio.current_task()])

                kernel_reader, kernel_writer = await asyncio.open_connection(
                    self.kernel_host, self.kernel_port
                )

                if self.verbose >= 3:
                    print(
                        f"{SCRIPT_NAME}: {self.name} pyscript kernel connected at {self.kernel_host}:{self.kernel_port}"
                    )

                client2kernel_task = asyncio.create_task(
                    self.forward_data_task(
                        "c2k", client_reader, kernel_writer, my_exit_q, 0
                    )
                )
                kernel2client_task = asyncio.create_task(
                    self.forward_data_task(
                        "k2c", kernel_reader, client_writer, my_exit_q, 1
                    )
                )
                for task in [client2kernel_task, kernel2client_task]:
                    await status_q.put(["task_start", task])

                exit_status = await my_exit_q.get()
                if self.verbose >= 3:
                    print(f"{SCRIPT_NAME}: {self.name} shutting down connections (exit_status={exit_status})")
                for task in [client2kernel_task, kernel2client_task]:
                    try:
                        task.cancel()
                        await task
                    except asyncio.CancelledError:
                        pass
                for sock in [client_writer, kernel_writer]:
                    sock.close()
                for task in [asyncio.current_task(), client2kernel_task, kernel2client_task]:
                    await status_q.put(["task_end", task])
                if exit_status:
                    await status_q.put(["exit", exit_status])
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception as err:  # pylint: disable=broad-except
                print(
                    f"{SCRIPT_NAME}: {self.name} client_connected got exception {err}; {traceback.format_exc(-1)}"
                )

        if self.verbose >= 3:
            print(
                f"{SCRIPT_NAME}: {self.name} listening for jupyter client at {self.client_host}:{self.client_port}"
            )
        self.client_server = await asyncio.start_server(
            client_connected, self.client_host, self.client_port
        )

    async def client_server_stop(self):
        """Stop the server waiting for client connections."""
        if self.client_server:
            self.client_server.close()
            self.client_server = None

    async def forward_data_task(self, dir_str, reader, writer, exit_q, exit_status):
        """Forward data from one side to the other."""
        try:
            while True:
                data = await reader.read(8192)
                if len(data) == 0:
                    await exit_q.put(exit_status)
                    return
                if self.verbose >= 4:
                    print(
                        f"{SCRIPT_NAME}: {self.name} {dir_str}: {data} ## {data.hex()}"
                    )
                writer.write(data)
                await writer.drain()
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as err:  # pylint: disable=broad-except
            print(
                f"{SCRIPT_NAME}: {self.name} {dir_str} got exception {err}; {traceback.format_exc(-1)}"
            )
            await exit_q.put(1)
            return


#
# Call the service pyscript/jupyter_kernel_start.  We can't immediately
# exit since Jupyter thinks the kernel has stopped.  We sit in the
# middle of the heartbeat loop so we know when the kernel is stopped.
#
async def kernel_run(config_filename, verbose):
    """Start a new pyscript kernel."""
    port_names = ["hb_port", "stdin_port", "shell_port", "iopub_port", "control_port"]
    hass_url = HASS_URL.rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + HASS_TOKEN,
    }

    with open(config_filename, "r") as fp:
        config = json.load(fp)

    if verbose >= 1:
        print(f"{SCRIPT_NAME}: got jupyter client config={config}")

    #
    # The kernel generates its own port numbers since it might be on another host,
    # so we delete the client ports.  Also, it needs the name of a state variable to
    # report the port numbers it uses.  We add a random prefix to avoid collisions.
    #
    kernel_config = config.copy()
    for port_name in port_names:
        del kernel_config[port_name]
    kernel_config["state_var"] = "pyscript.jupyter_ports_" + secrets.token_hex(5)
    kernel_config["ip"] = HASS_HOST

    #
    # Call the pyscript/jupyter_kernel_start service to tell pyscript to start
    # a Jupyter session.
    #
    url = hass_url + "/api/services/pyscript/jupyter_kernel_start"
    if verbose >= 2:
        print(f"{SCRIPT_NAME}: about to do service call post {url}")
    result = do_request(url, headers, data=json.dumps(kernel_config))
    if verbose >= 1:
        print(f"{SCRIPT_NAME}: service call put {url} returned {result.status_code}")

    #
    # When pyscript starts a Jupyter session it will start servers to listen for
    # connections on 5 tcp ports, and it randomly generates unused port numbers.
    # We need to find out the port numbers so we can connect.  This is a hack,
    # but the current way we get them is to check a state variable that pyscript
    # sets with a json string containing the port numbers.  We need to poll, since
    # we don't know how long it will take.
    #
    while True:
        url = hass_url + "/api/states/" + kernel_config["state_var"]
        if verbose >= 2:
            print(f"{SCRIPT_NAME}: about to do state get {url}")
        result = do_request(url, headers)
        if result.status_code == 200:
            result_json = result.json()
            if "state" in result_json:
                port_nums = json.loads(result_json["state"])
                if verbose >= 1:
                    print(
                        f"{SCRIPT_NAME}: state variable get {url} returned {port_nums}"
                    )
                break
            if verbose >= 2:
                print(
                    f"{SCRIPT_NAME}: state get {url} got result.text={result.text}; retrying"
                )
        elif verbose >= 2:
            print(
                f"{SCRIPT_NAME}: state get {url} got result.status {result.status_code}; retrying"
            )
        await asyncio.sleep(0.5)

    #
    # We act as a tcp relay on all the links between the Jupyter client and pyscript kernel.
    # There are five types of connections, and each Jupyter client might connect to each
    # of them multiple times.
    #
    status_q = asyncio.Queue(0)
    relay_ports = {}
    for port_name in port_names:
        relay_ports[port_name] = RelayPort(
            port_name,
            port_nums[port_name],
            config["ip"],
            config[port_name],
            verbose=verbose,
        )
        await relay_ports[port_name].client_server_start(status_q)

    #
    # Keep track of which tasks have started or stopped, or request an exit
    #
    tasks = set()
    task_cnt_max = 0
    while True:
        status = await status_q.get()
        if status[0] == "task_start":
            tasks.add(status[1])
            task_cnt_max = max(len(tasks), task_cnt_max)
        elif status[0] == "task_end":
            tasks.discard(status[1])
            #
            # if no more relaying is going on (ie, all the ports are closed), and we
            # were doing some before (at least 3 connections), then exit
            #
            if len(tasks) == 0 and task_cnt_max >= 10:
                exit_status = 0
                break
        elif status[0] == "exit":
            exit_status = status[1]
            break

    #
    # Shut everything down and exit
    #
    for port in relay_ports.values():
        await port.client_server_stop()
    for task in tasks:
        try:
            task.cancel()
            await task
        except asyncio.CancelledError:
            pass
    sys.exit(exit_status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config_file", type=str, help="json kernel config file generated by Jupyter"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="increase output verbosity (repeat up to 4x)",
    )
    args = parser.parse_args()

    asyncio.run(kernel_run(args.config_file, args.verbose if args.verbose is not None else 0))
