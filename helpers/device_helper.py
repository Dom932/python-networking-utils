import getpass
import logging
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from netmiko import ConnectHandler, NetMikoAuthenticationException, NetMikoTimeoutException


class ConnectionException(Exception):
    """
    Unable to connect to device
    """
    pass

class DeviceHelper:
    """
    Helper class for connection related tasks
    """

    _logger = logging.getLogger(__name__)

    @staticmethod
    def get_credentials():
        """
        Method to guide the user through building a credential set which can be used to provide
        credentials to connect_to_device() method

        :return: list - a list containing credential sets (dictionary)
        """

        credential_set = []

        valid_input = {"yes": True, "y": True, "ye": True, "no": False, "n": False}

        while True:

            username = input("Please enter a username: ")
            password = getpass.getpass()

            credential = {"username": username, "password": password}

            while True:
                secret = input("Do you need a secret? [yes/no]: ").lower()
                if secret in valid_input:
                    if valid_input[secret]:
                        secret = getpass.getpass(prompt="Please enter a secret: ")
                        credential["secret"] = secret
                        break
                    else:
                        break

            credential_set.append(credential)

            while True:

                additional_credentials = input("Do you need to provide additional credential? [yes/no]: ").lower()

                if additional_credentials in valid_input:

                    if not valid_input[additional_credentials]:
                        return credential_set
                    else:
                        break

    @staticmethod
    def backup_config(config, location, hostname):
        """
        Write a config to backup

        :param config: config to write to file
        :type config: str
        :param location: Directory to save config to
        :param hostname:

        """
        path = Path(location)

        if path.is_dir():

            dt = datetime.now()
            dt = dt.strptime(format="%Y-%m-%d_%H-%m")
            filename = f"{hostname}_{dt}.txt"
            path = path / filename

            with path.open(mode="w") as file:
                file.writelines(config)
        else:
            raise ValueError(f"Location is not a directory - {location}")

    @staticmethod
    def get_cisco_ios_version(sh_ver):
        """
        Gets Cisco IOS version from sh ver output
        :param sh_ver: show version output from device
        :type sh_ver: str
        :return: Cisco IOS version
        """

        rexp = r"Cisco IOS Software, .* Version ?(.*)"
        output = re.search(rexp, sh_ver)

        if output:
            return output.group(1)
        else:
            return "Unable to determine IOS version"

    @staticmethod
    def ping(host, ping_count=4):
        """
        Check if a device responds to pings
        :param host: host address or FQDN to ping
        :type host: str
        :param ping_count: Number of pings to send. Default is 4
        :type ping_count: int
        :return: bool if the device responds to pings
        """

        if sys.platform is "windows":
            param = f"-n {ping_count}"
        else:
            param = f"-c {ping_count}"

        command = f"ping {param} {host}".split()
        sub = subprocess.Popen(command)
        sub.wait()
        result = sub.poll()

        # if result = 0 then it was successful
        if result == 0:
            return True
        else:
            return False

    @classmethod
    def connect_to_device(cls, ipaddr, credentials, enable_mode=False, device_type='autodetect', timeout=None):
        """
        Helper method to connect to a device using netmiko.
        This method takes a set of possible credentials and attempts to connect to the device using them.
        if device type is set then it will attempt to connect using that device type, if not autodetect
        will be used.

        Example:

            cred = [
                {"username":"user", "password":"pass", "secret":"secretpassword"},
                {"username":"user2", "password":"pass2", "secret":"secretpassword2"}
            ]

            device_type = ["cisco_ios","cisco_asa"]

            connection - connect_to_device("182.169.0.1", cred, device_type=device_type)

        :param credentials: list of credentials containing in a dictionary.
                             [ {"username":"user", "password":"pass", "secret":"secretpassword"} ]
        :type credentials: list
        :param ipaddr: IP Address of device to connect connect to
        :type ipaddr: str
        :param enable_mode: if enable mode is to be entered after connecting
        :type enable_mode: bool
        :param device_type: list of device type to atempt to connect to. Default is AutoDetect
        :type device_type: list
        :param timeout: timeout for connection
        :type timeout: int

        :return: netmiko.ConnectHandler

        :Raises ConnectionException: If unable to connect to device
        """

        # verify if that credentials is not empty
        if credentials:

            cls._logger.info(f"{ipaddr} - Attempting to connect")

            # Start populating device dictionary to pass to netmiko
            device = {
                "ip": ipaddr
            }

            # if timeout is set, add it to the parameters for netmiko
            if timeout:
                device["timeout"] = timeout

            # convert credentials to a list if its just a dictionary
            if isinstance(credentials, dict):
                credentials = [credentials]

            # convert device_type to a list if its not a list
            if not isinstance(credentials, list):
                device_type = [device_type]

            try:
                for c in credentials:

                    # set username / password / secret
                    if "username" in c:
                        device["username"] = c["username"]

                    if "password" in c:
                        device["password"] = c["password"]

                    if "secret" in c:
                        device["secret"] = c["secret"]
                    else:
                        # if no secret then remove it
                        device.pop("secret", None)

                    for d in device_type:

                        try:
                            cls._logger.debug(f"{ipaddr} - Attempting to connect using "
                                              f"device type: {d}")

                            device['device_type'] = d

                            connection = ConnectHandler(**device)

                            if enable_mode:
                                connection.enable()

                            cls._logger.info(f"{ipaddr} - Connection established")
                            return connection

                        except NetMikoAuthenticationException:
                            # Ignore except - unable to connect based on current User/pass type combo
                            # Move onto next set
                            cls._logger.debug(f"{ipaddr} - Current username/password incorrect")
                            pass
                        except NetMikoTimeoutException as e:
                            # unable to connect to device
                            cls._logger.info(f"{ipaddr} - Connection timeout")
                            raise e

                # If this point is reached no connection was established
                cls._logger.error(f"{ipaddr} - Unable to connect to device")
                raise ConnectionException("Unable to connect to device")

            except NetMikoTimeoutException:
                raise ConnectionException("Connection to device timed out")
        else:
            cls._logger.error("No credentials provided")
            raise ConnectionException("No Credentials provided")
