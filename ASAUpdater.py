#!/usr/bin/env python3

"""
Script to update multiple Cisco ASA OS and ASDM images, without the need of a FTP, TFTP, etc server.

The script will read a CSV which contains a list of IP addresses and update each ASA or ASDM image.
The CSV file must contain a column titled "IP Addresses" with all device IP addresses listed under it.

The new image file will be uploaded to each device by SCP. If SCP is not enabled on the device, this
script will enable SCP temporally and will disable SCP once the file upload has completed.

The script will prompt you to enter a set of credentials used to connect to your devices. You can
provide multiple credentials if required for different devices.

You can optionally reboot the device if required - ASA image updates require a reboot, while ASDM do
not. Following a reboot the script will wait 5 mins and perform a ping check to verify if it is
responding. If the device does not respond to ICMP, then the script will mark the device as no
responsive following a reboot. Please be careful when using the reboot command.

Please review the script before usage and test before use in production systems.
Please use this script at your own risk.

Author: Dom932
URL: https://github.com/Dom932

Requirements:
            Python 3.6+
            netmiko 2.1.1+
Usage:

    Example Usage of required inputs:
        >python3 ASAUpdater.py -i <input CSV file> -o <output CSV file> -it <image type> -il <image location>
        >python3 ASAUpdater.py -i devices.csv -o report.csv -it asdm -il asdm-741.bin

    Complete list of parameters and documentation use:
        >python3 ASAUpdate.py --help

"""


import argparse
import csv
import time
import logging
import sys
from pathlib import Path
from netmiko import FileTransfer
from helpers import DeviceHelper, ConnectionException
from helpers import ThreadingHelper

_logger = logging.getLogger(__name__)


class Device:
    """
    Device Class
    """

    def __init__(self, ip_address):
        self.ip_address = ip_address
        self.name = ""
        self.connected = False
        self.successfully_rebooted = False
        self.file_uploaded = False
        self.error = ""
        self.credentials = None
        self.config_backed_up = False


def upgrade_asa(device, image_type, image_location, dest_drive="disk0:", reboot=False,
                backup_config=False, backup_location=None):
    """
    Method to upgrade a Cisco ASA OS version or ASDM Version

    :param device: Device to upgrade
    :type device: Device
    :param image_type: Image file to be uploaded - ASDM or ASA
    :type image_type: str
    :param image_location: location of the source image file on local computer
    :type image_location: str
    :param dest_drive: destination drive that the image file will be uploaded. Default: "Disk0:"
    :type dest_drive: str
    :param reboot: indicates if a reboot is required
    :type reboot: bool
    :param backup_config: indicates if a config backup is required
    :type backup_config: bool
    :param backup_location: location to save backups
    :type backup_location: str
    :return: Device with updated attributes
    """

    try:

        connection = DeviceHelper.connect_to_device(ipaddr=device.ip_address, credentials=device.credentials,
                                                    enable_mode=True, device_type=["cisco_asa"])

        device.connected = True

        prompt = connection.find_prompt()

        device.name = prompt[0:(len(prompt) - 1)]

        # Backup config
        if backup_config:
            _logger.info(f"{device.ip_address} - Starting Config Backup")

            config = connection.send_command("sh run")
            DeviceHelper.backup_config(config, backup_location, device.name)

            _logger.info(f"{device.ip_address} - Completed Config")

        image_file_name = Path(image_location).name

        # Check if scp is enabled
        output = connection.send_command("sh run | i ssh scopy enable")

        if output.lower() is "ssh copy enable":
            _logger.debug(f"{device.ip_address} - SCP enabled")
            scp_enabled = True
        else:
            _logger.debug(f"{device.ip_address} - SCP not enabled. Enabling")
            scp_enabled = False
            # enable SCP
            connection.send_config_set(["ssh scopy enable"])

        with FileTransfer(connection, source_file=image_location, dest_file=image_file_name,
                          file_system=dest_drive) as scp:
            _logger.debug(f"{device.ip_address} - Starting to copy image to device")
            # check if there is free space
            if scp.verify_space_available():
                # Transfer file
                scp.transfer_file()

                # verify file
                if not scp.verify_file():
                    device.error = "File transfer verifier failed"
                    _logger.info(f"{device.ip_address} - file verifier failed")
                else:
                    device.file_uploaded = True
                    _logger.info(f"{device.ip_address} - Not enough space to image")

            else:
                device.error = "Not enough space to upload file"

        # disable scp if it was not enabled originally
        if not scp_enabled:
            connection.send_config_set(["no ssh scopy enable"])
            _logger.debug(f"{device.ip_address} - Disabling SCP")

        # if file was uploaded set it as the new image
        if device.file_uploaded:

            asa_file_path = f"{dest_drive}/{image_file_name}"

            if image_type.lower() == "asa":
                config = f"boot system {asa_file_path}"
                _logger.debug(f"{device.ip_address} - setting ASA boot image to : {asa_file_path}")
                connection.send_config_set([config])
            elif image_type.lower() == "asdm":
                config = f"asdm image {asa_file_path}"
                _logger.debug(f"{device.ip_address} - setting ASDM image to : {asa_file_path}")
                connection.send_config_set([config])

            # save config
            _logger.debug(f"{device.ip_address} - Saving Config")
            connection.save_config()

            # reboot if set
            if reboot:
                _logger.info(f"{device.ip_address} - Rebooting device")
                connection.send_confg_set(["reboot"])
                connection.send_confg_set(["y"])

                # wait 5 mins to and check
                time.sleep(300)

                device.successfully_rebooted = DeviceHelper.ping(device.ip_address)

                if device.successfully_rebooted:
                    _logger.info(f"{device.ip_address} - Device Rebooted")
                else:
                    _logger.warning(f"{device.ip_address} - Device not rebooted")
                return device

    except ConnectionException as e:
        device.connected = False
        _logger.error(f"{device.ip_address} - Connection Exception")
        _logger.error(f"{e}")
        return device
    except ValueError as e:
        device.connected = False
        _logger.error(f"{device.ip_address} - Value Error")
        _logger.error(f"{e}")
        return device


def read_csv(input_file):
    """
    Read a CSV file with an 'IP Address' column  creating a list of devices objects
    :param input_file: csv file location
    :type input_file: str
    :return list: list of devices based on CSV
    """

    devices = []

    # Read CSV file and write each row to a Device object
    with Path(input_file).open(mode="r") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            device = Device(ip_address=row["IP Address"])
            devices.append(device)

    return devices


def write_csv(output_file, devices):
    """
    Write each device to CSV
    :param output_file: location where to save CSV file
    :type output_file: str
    :param devices: list of device objects
    :type devices: list
    """

    with Path(output_file).open(mode="w") as csvfile:
        wr = csv.writer(csvfile, dialect="excel")
        wr.writerow(["Name", "IP Address", "Connected", "SuccessfullyRebooted", "Error"])

        for device in devices:
            row = [device.name, device.ip_address, device.connected, device.successfully_rebooted, device.error]
            wr.writerow(row)


def main(input_csv, output_csv, image_type, image_location, dest_drive, credentials, reboot=False,
         backup_config=False, backup_location=None, worker_threads=4):
    """
    Main run method
    :param input_csv: Location of CSV file to read
    :type input_csv: str
    :param output_csv: Location where to wrtie output
    :type output_csv: str
    :param image_type: Type of image to be uploaded - asa or asdm
    :type image_type: str
    :param image_location: location of the image file been uploaded on your local machine
    :type image_location: str
    :param dest_drive: destination drive on the device to upload image to
    :type dest_drive: str
    :param reboot: (optional) if the device should be rebooted after setting the image. A
    SA code requires a reboot to take afect.
    Default is False
    :type reboot:bool
    :param credentials: a list of credentials to use
    :type credentials: list
    :param backup_config: (optional) if the config should be backed up before upgrade. Default is False
    :type backup_config: bool
    :param backup_location: (optional) location folder to save backup config
    :type backup_location: str
    :param worker_threads: (optional) Number of worker threads. Default is 4
    :type worker_threads: int
    :return:
    """

    # create list of devices
    device_list = read_csv(input_csv)

    _logger.info(f"Starting ASA upgrades on:{len(device_list)}")
    _logger.info(f"-Worker Threads: {worker_threads}")
    _logger.info(f"-Image Type: {image_type}")
    _logger.info(f"-Image Location: {image_location}")
    _logger.info(f"-Dest Drive: {dest_drive}")
    _logger.info(f"-Reboot: {reboot}")
    _logger.info(f"-Backup Config: {backup_config}")
    _logger.info(f"-Backup Location: {backup_location}")

    # Populate credentials
    for d in device_list:
        d.credentials = credentials

    args = {
        "image_type": image_type,
        "image_location": image_location,
        "reboot": reboot,
        "dest_drive": dest_drive,
        "backup_config": backup_config,
        "backup_location": backup_location,
    }

    # create threading helper
    _logger.debug("Starting Threads")
    th = ThreadingHelper(worker_func=upgrade_asa, num_of_workers=worker_threads, worker_func_args=args)
    result = th.run(device_list)

    write_csv(output_csv, result)


if __name__ == "__main__":

    parse = argparse.ArgumentParser()
    parse.add_argument("-i","--inputcsv", type=str, required=True,
                       help="<Required> Location of source CSV file")
    parse.add_argument("-o", "outputcsv", type=str, required=True,
                       help="<Required> Location of output CSV file")
    parse.add_argument("-it", "imagetype", type=str, choices=["asa", "asdm", "ASA", "ASDM"], required=True,
                       help="<Required> Type of image been loaded - ASA or ASDM")
    parse.add_argument("-il", "imagelocation", type=str, required=True,
                       help="<Required> Location of image file to upload")
    parse.add_argument("-d", "--destdrive", type=str, default="disk0:",
                       help="Location drive where image file is to be saved. Default is disk0:")
    parse.add_argument("-r", "--reboot", action="store_true",
                       help="Set if the ASA should be rebooted after uploading")
    parse.add_argument("-b", "--backupconfig", action="store_true",
                       help="Set config should be backed up. --backuplocation is required if set")
    parse.add_argument("-bl", "--backuplocation", type=str,
                       help="Backup location not set")
    parse.add_argument("-w", "--workerthreads", type=int, default=4,
                       help="Number of worker threads to use. Default is 4")
    parse.add_argument("-lv","--logginglevel", type=str, choices=["critical", "error", "warning", "info", "debug", "notset"],
                       default="info",
                       help="Logging level, Default is info")
    parse.add_argument("-lf", "--loggingtofile", action="store_true",
                       help="Set if logging should be saved to the file")

    parse_args = parse.parse_args()

    # if backup location is set, backup location needs to be set
    if parse_args.backupconfig and not parse_args.backuplocation:
        print("--backupconfig is set but no --backuplocation set")
    else:

        credentials_ = DeviceHelper.get_credentials()

        logging_mapper = {
            "critical": logging.CRITICAL,
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG,
            "notset": logging.NOTSET
        }

        _logger.setLevel(logging_mapper[parse_args.logginglevel])
        formatter = logging.Formatter("%(asctime)s - %(threadName)s -  %(name)s - %(levelname)s - %(message)s")

        if parse_args.loggingtofile:
            fh = logging.FileHandler("BugChecker.log")
            fh.setFormatter(formatter)
            _logger.addHandler(fh)

        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        _logger.addHandler(sh)

        main(input_csv=parse_args.inputcsv, output_csv=parse_args.outputcsv, image_type=parse_args.imagetype,
             image_location=parse_args.imagelocation, dest_drive=parse_args.destdrive, reboot=parse_args.reboot,
             credentials=credentials_, backup_config=parse_args.backupconfig,
             backup_location=parse_args.backuplocation, worker_threads=parse_args.workerthreads)
