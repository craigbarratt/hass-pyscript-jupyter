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
import configparser
import json
import secrets
import sys
import traceback
from asyncio.streams import StreamReader, StreamWriter
from pathlib import Path
from typing import Any

import aiohttp
import aiohttp_socks as proxy
from aiohttp import ClientResponse
from aiohttp.typedefs import StrOrURL

#
# Our program name we print when --verbose is used
#
this_file = Path(__file__).resolve()
SCRIPT_NAME = this_file.name

CONFIG_NAME = "pyscript.conf"
CONFIG_DEFAULTS = {
    "hass_host": "localhost",
    "hass_url": "http://${hass_host}:8123",
    "hass_token": "",
    "hass_proxy": "",
}
CONFIG_SETTINGS = {}


def load_config() -> None:
    """Read the Home Assistant connection settings from the config file"""
    global CONFIG_SETTINGS

    parser_conf = configparser.ConfigParser(
        defaults=CONFIG_DEFAULTS,
        interpolation=configparser.ExtendedInterpolation(),
        empty_lines_in_values=False,
        converters={"unquoted": lambda x: x.strip("'\"") if x else None},
    )

    try:
        parser_conf.read_file(Path(this_file.parent, CONFIG_NAME).open())
        hass_conf = parser_conf["homeassistant"]
    except KeyError:
        print(f"{SCRIPT_NAME}: missing section 'homeassistant' in config file")
        sys.exit(1)
    except Exception as err:
        print(f"{SCRIPT_NAME}: unable to load config file ({err})")
        sys.exit(1)

    CONFIG_SETTINGS = {opt: hass_conf.getunquoted(opt) for opt in CONFIG_DEFAULTS}


class RelayPort:
    """Define the RelayPort class, that does full-duplex forwarding between TCP endpoints."""

    def __init__(
        self,
        name: str,
        kernel_port: int,
        client_host: str,
        client_port: int,
        verbose: int = 0,
    ):
        """Initialize a relay port."""
        self.name = name
        self.client_host = client_host
        self.client_port = client_port
        self.kernel_host = CONFIG_SETTINGS["hass_host"]
        self.kernel_port = kernel_port
        self.verbose = verbose

        self.client2kernel_task = None
        self.kernel2client_task = None
        self.kernel_connect_task = None
        self.client_server = None
        self.kernel_reader = None
        self.kernel_writer = None

    async def client_server_start(self, status_q: asyncio.Queue):
        """Start a server that listens for client connections."""

        async def client_connected(reader: StreamReader, writer: StreamWriter) -> None:
            try:
                my_exit_q = asyncio.Queue(0)
                client_reader = reader
                client_writer = writer
                await status_q.put(["task_start", asyncio.current_task()])

                if CONFIG_SETTINGS["hass_proxy"] is not None:
                    if self.verbose >= 3:
                        print(
                            f"{SCRIPT_NAME}: {self.name} connected to jupyter client; now trying pyscript kernel"
                            f" via proxy {CONFIG_SETTINGS['hass_proxy']} at {self.kernel_host}:{self.kernel_port}"
                        )
                    kernel_reader, kernel_writer = await proxy.open_connection(
                        proxy_url=CONFIG_SETTINGS["hass_proxy"],
                        host=self.kernel_host,
                        port=self.kernel_port,
                    )
                else:
                    if self.verbose >= 3:
                        print(
                            f"{SCRIPT_NAME}: {self.name} connected to jupyter client; now trying pyscript kernel"
                            f" at {self.kernel_host}:{self.kernel_port}"
                        )
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
                    print(
                        f"{SCRIPT_NAME}: {self.name} shutting down connections (exit_status={exit_status})"
                    )
                for task in [client2kernel_task, kernel2client_task]:
                    try:
                        task.cancel()
                        await task
                    except asyncio.CancelledError:
                        pass
                for sock in [client_writer, kernel_writer]:
                    sock.close()
                for task in [
                    asyncio.current_task(),
                    client2kernel_task,
                    kernel2client_task,
                ]:
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

    async def client_server_stop(self) -> None:
        """Stop the server waiting for client connections."""
        if self.client_server:
            self.client_server.close()
            self.client_server = None

    async def forward_data_task(
        self,
        dir_str: str,
        reader: StreamReader,
        writer: StreamWriter,
        exit_q: asyncio.Queue,
        exit_status: int,
    ):
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
async def kernel_run(config_filename: str, verbose: int) -> None:
    """Start a new pyscript kernel."""
    port_names = ["hb_port", "stdin_port", "shell_port", "iopub_port", "control_port"]
    hass_host = CONFIG_SETTINGS["hass_host"]
    hass_url = CONFIG_SETTINGS["hass_url"].rstrip("/")
    hass_proxy = CONFIG_SETTINGS["hass_proxy"]

    connector = proxy.ProxyConnector.from_url(hass_proxy) if hass_proxy else None
    headers = {
        "Authorization": f'Bearer {CONFIG_SETTINGS["hass_token"]}',
    }
    session = aiohttp.ClientSession(
        connector=connector, headers=headers, raise_for_status=True
    )

    async def do_request(
        url: StrOrURL, data: Any = None, json: Any = None, **kwargs: Any
    ) -> ClientResponse:
        """Do a GET or POST with the given URL."""
        try:
            method = "POST" if data or json else "GET"
            return await session.request(
                method=method, url=url, data=data, json=json, **kwargs
            )
        except aiohttp.ClientConnectorError as err:
            print(
                f"{SCRIPT_NAME}: unable to connect to host {err.host}:{err.port} ({err.strerror})"
            )
            sys.exit(1)
        except aiohttp.ClientResponseError as err:
            print(
                f"{SCRIPT_NAME}: request failed with {err.status}: {err.message} (url={err.request_info.url})"
            )
            sys.exit(1)
        except Exception as err:
            print(f"{SCRIPT_NAME}: got error {err} (url={url})")
            sys.exit(1)

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
    kernel_config["ip"] = hass_host

    #
    # Call the pyscript/jupyter_kernel_start service to tell pyscript to start
    # a Jupyter session.
    #
    url = hass_url + "/api/services/pyscript/jupyter_kernel_start"
    if verbose >= 2:
        print(f"{SCRIPT_NAME}: about to do service call post {url}")
    result = await do_request(url, json=kernel_config)
    if verbose >= 1:
        print(f"{SCRIPT_NAME}: service call put {url} returned {result.status}")

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
        result = await do_request(url)
        if result.status == 200:
            result_json = await result.json()
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
                f"{SCRIPT_NAME}: state get {url} got result.status {result.status}; retrying"
            )
        await asyncio.sleep(0.5)

    # not needed any further
    await session.close()

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


def main() -> None:
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

    load_config()

    asyncio.run(kernel_run(args.config_file, args.verbose if args.verbose else 0))


if __name__ == "__main__":
    main()
