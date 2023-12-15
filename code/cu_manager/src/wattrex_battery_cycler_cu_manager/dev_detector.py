#!/usr/bin/python3
'''
This file contains the class that will detected the different devices connected to the cycler.
'''

#######################        MANDATORY IMPORTS         #######################
from __future__ import annotations
from typing import List, Dict, Tuple

#######################         GENERIC IMPORTS          #######################
from os import listdir
from time import sleep, time
from serial import PARITY_ODD

#######################      SYSTEM ABSTRACTION IMPORTS  #######################
from system_logger_tool import Logger, SysLogLoggerC, sys_log_logger_get_module_logger
if __name__ == '__main__':
    cycler_logger = SysLogLoggerC(file_log_levels='./devops/scpi/log_config.yaml', output_sub_folder='detector')
log: Logger = sys_log_logger_get_module_logger(__name__)
from bitarray.util import ba2int, int2ba

#######################       THIRD PARTY IMPORTS        #######################
from can_sniffer import DrvCanCmdDataC, DrvCanFilterC, DrvCanCmdTypeE, DrvCanMessageC
from scpi_sniffer import DrvScpiCmdDataC, DrvScpiCmdTypeE, DrvScpiSerialConfC
from wattrex_battery_cycler_datatypes.comm_data import CommDataDeviceC
from system_shared_tool import SysShdIpcChanC

#######################          MODULE IMPORTS          #######################

######################             CONSTANTS              ######################
# from .context import (DEFAULT_TX_CAN_NAME, DEFAULT_TX_SCPI_NAME, DEFAULT_RX_CAN_NAME,
#                     DEFAULT_RX_SCPI_NAME, DEFAULT_DETECT_TIMEOUT)
from context import (DEFAULT_TX_CAN_NAME, DEFAULT_TX_SCPI_NAME, DEFAULT_RX_CAN_NAME,
                    DEFAULT_RX_SCPI_NAME, DEFAULT_DETECT_TIMEOUT)
DEV_PATH = '/dev/wattrex/'
SCPI_QUEUE_PREFIX = 'DET_'

#######################              CLASS               #######################
all_devices = {
    'EPC': (0x13, 0x80), # Range of can ids for the registered EPCs (0x80 excluded, max value 0x7F)
    'EA': {}, # Dict with info from the ea devices registered
    'RS': {} # Dict with info from the rs devices registered
}

class DetectorC:
    '''
    Classmethod to handle DetectorCectorC .
    '''
    def __init__(self, cu_id : int):
        self.__cu_id = cu_id
        self.det_bms: List[CommDataDeviceC] = []
        self.det_epc: List[CommDataDeviceC] = []
        self.det_ea: List[CommDataDeviceC] = []
        self.det_rs: List[CommDataDeviceC] = []
        self.det_flow: List[CommDataDeviceC] = []
        self.found_scpi_devs: Dict[str, Dict[str, bool]] = {
            ## The bool indicates if the device has responded
            ## Example: 'source': {'EA_1': False, 'EA_2': False},
            'source': {},
            'load': {},
            'bk': {},
            'flow': {},
        }
        self.__reqs_flow: bool = False
        self.__reqs_sources: bool = False
        self.__reqs_rs: bool = False
        self.__reqs_epc: bool = False
        ## Create the queues for CAN messages # TODO: Uncomment when can is working
        self.__tx_can: SysShdIpcChanC = SysShdIpcChanC(name= DEFAULT_TX_CAN_NAME)
        # self.__rx_can: SysShdIpcChanC = SysShdIpcChanC(name= DEFAULT_RX_CAN_NAME,
        #                                                 max_message_size= 400)
        ## Create the queues for SCPI messages
        self.__tx_scpi: SysShdIpcChanC = SysShdIpcChanC(name= DEFAULT_TX_SCPI_NAME)
        self.__rx_scpi : Dict[str, SysShdIpcChanC] = {}

    def process_detection(self) -> None:
        '''
        Process detection of connected devices using CAN and SCPI.
        '''
        ## Reset detected devices lists
        self.__reset_detected()
        self.__find_scpi_devs()
        log.critical(f"Found scpi devs: {self.found_scpi_devs}")
        ## Add filter to the can bus to receive all messages # TODO: Uncomment when can is working
        # self.__tx_can.send_data(DrvCanCmdDataC(data_type= DrvCanCmdTypeE.ADD_FILTER,
        #                                 payload= DrvCanFilterC(addr= 0x000, mask= 0x000,
        #                                                         chan_name=DEFAULT_RX_CAN_NAME)))
        ## Request detections
        # self.detect_epc()
        self.detect_sources()
        log.info(f"START DETECT DEVICES LOOP")
        initial_time = time()
        while (initial_time + DEFAULT_DETECT_TIMEOUT) > time():
            ## TODO: Uncomment when can is working
            # msg_can : DrvCanMessageC = self.__rx_can.receive_data_unblocking()
            # if msg_can is not None:
            #     if 0x100 <= msg_can.addr <= 0x120:
            #         self.detect_bms(msg_can)
            #     elif 0x130 <= msg_can.addr <= 0x7FF:
            #         self.detect_epc(msg_can)
            #     else:
            #         log.error(f"Unknown device with can id {msg_can.addr}")

            self.detect_sources()
            # while not self.__rx_scpi.is_empty():
            #     msg: DrvScpiCmdDataC = self.__rx_scpi.receive_data()
            #     # TODO: Add detection of ea, rs and flow
            #     if msg.data_type == DrvScpiCmdTypeE.MESSAGE:
            #         pass
            #         #self.detect_epc(msg)

        ## TODO: Uncomment when can is working
        # self.__tx_can.send_data(DrvCanCmdDataC(data_type= DrvCanCmdTypeE.REMOVE_FILTER,
        #                                 payload= DrvCanFilterC(addr= 0x000, mask= 0x000,
        #                                                         chan_name=DEFAULT_RX_CAN_NAME)))
        self.__tx_can.terminate()
        # self.__rx_can.terminate()

    def __reset_detected(self) -> None:
        '''
        Reset the detection of connected devices.
        '''
        self.det_bms.clear()
        self.det_epc.clear()
        self.det_ea.clear()
        self.det_rs.clear()
        self.det_flow.clear()
        for dev_dict in self.found_scpi_devs:
            self.found_scpi_devs[dev_dict].clear()
        self.__reqs_flow = False
        self.__reqs_sources = False
        self.__reqs_rs = False
        self.__reqs_epc = False

    def __find_scpi_devs(self) -> None:
        '''
        Find the scpi devices connected to the computational unit.
        '''
        for dev_dir in self.found_scpi_devs:
            listdir_result: List[str] = []
            try:
                listdir_result = listdir(DEV_PATH+dev_dir)
            except FileNotFoundError:
                log.info(f"Path {DEV_PATH+dev_dir} not found")
                continue
            for element in listdir_result:
                self.found_scpi_devs[dev_dir][element] = False

    def detect_bms(self, msg: DrvCanMessageC):
        '''
        Detect the bms connected to the cycler.
        '''
        if int(msg.addr) not in [dev.serial_number for dev in self.det_bms]:
            dev_data = CommDataDeviceC(cu_id=self.__cu_id, comp_dev_id= 0, serial_number= msg.addr,
                                    link_name= str(msg.addr - 0x100))
            self.det_bms.append(dev_data)

    def detect_epc(self, msg: DrvCanMessageC|None = None) -> None:
        '''
        Detect the bms connected to the cycler.

        Returns:
            List[CyclerDataDeviceC]: List of bms devices.
        '''
        if not self.__reqs_epc:
            ## Request info for all the epcs listed
            for can_id in range(all_devices['EPC'][0], all_devices['EPC'][1]):
                ## The id send is the union of the device can id and type of the message to send
                id_msg = can_id<<4 | 1
                data_msg = 0x0
                msg = DrvCanMessageC(addr= id_msg, size= 1, payload = data_msg)
                self.__tx_can.send_data(DrvCanCmdDataC(data_type=DrvCanCmdTypeE.MESSAGE,
                                                         payload=msg))
            self.__reqs_epc = True
        elif msg is not None:
            can_id, serial_number = self.__parse_epc_msg(msg)
            if can_id not in [int(dev.link_name) for dev in self.det_epc]:
                dev_data = CommDataDeviceC(cu_id=self.__cu_id,
                                           comp_dev_id= 0,
                                           serial_number=serial_number,
                                           link_name= can_id)
                self.det_epc.append(dev_data)

    def detect_sources(self):
        '''
        Detect the sources connected to the cycler.
        '''
        if not self.__reqs_sources:
            ## Create a queue for each SCPI connected device
            for source_name in self.found_scpi_devs['source']:
                self.__rx_scpi[source_name] = SysShdIpcChanC(name= SCPI_QUEUE_PREFIX+source_name,
                                                        max_message_size=400)
                self.__tx_scpi.send_data(DrvScpiCmdDataC(
                                                data_type=DrvScpiCmdTypeE.ADD_DEV,
                                                port=DEV_PATH+'source/'+source_name,
                                                rx_chan_name=SCPI_QUEUE_PREFIX+source_name,
                                                payload=DrvScpiSerialConfC(
                                                        port=DEV_PATH+'source/'+source_name,
                                                        separator='\n', timeout = 0.8,
                                                        write_timeout = 0.8, parity = PARITY_ODD,
                                                        baudrate = 9600)
                                                )
                                        )
                ## Request info for the source
                if source_name.startswith('EA'):
                    self.__tx_scpi.send_data(DrvScpiCmdDataC(data_type=DrvScpiCmdTypeE.WRITE_READ,
                                                            port=DEV_PATH+'source/'+source_name,
                                                            payload=":*IDN?"))
            self.__reqs_sources = True
        else:
            for source_name in self.found_scpi_devs['source']:
                if not self.found_scpi_devs['source'][source_name]:
                    ## Try to read its queue for response
                    msg_source: DrvScpiCmdDataC|None = \
                                            self.__rx_scpi[source_name].receive_data_unblocking()
                    if msg_source is not None:
                        if source_name.startswith('EA'):
                            try:
                                ea_serial_number = msg_source.payload[0].split(', ')[2]
                                ea_model = msg_source.payload[0].split(', ')[1].replace(' ', '_')
                            except Exception as exc:
                                log.error(f"Error parsing EA response: {exc} | Response received (__dict__): {msg_source.__dict__}")
                            else:
                                log.critical(f"EA found: {msg_source.__dict__}")
                                self.det_ea.append(CommDataDeviceC(cu_id=self.__cu_id,
                                                                    comp_dev_id= 0,
                                                                    serial_number=ea_serial_number,
                                                                    link_name=source_name))

                        self.found_scpi_devs['source'][source_name] = True
                        self.__tx_scpi.send_data(DrvScpiCmdDataC(
                                                data_type=DrvScpiCmdTypeE.DEL_DEV,
                                                port=DEV_PATH+'source/'+source_name,
                                                )
                                        )



    def detect_flow(self, msg: DrvScpiCmdDataC):
        '''
        Detect the flow connected to the cycler.
        '''
        pass

    def __parse_epc_msg(self, msg: DrvCanMessageC) -> Tuple[int, str]:
        msg_bits = int2ba(int.from_bytes(msg.payload,'little'),length=64, endian='little')
        # The first 6 bits correspond to the can id
        can_id = ba2int(msg_bits[:6])
        log.info(f"Device ID: {can_id}")
        # The next 5 bits correspond to the fw version
        fw_ver = ba2int(msg_bits[6:11])
        log.info(f"Device fw version: {fw_ver}")
        # The next 13 bits correspond to the hw version
        hw_ver = msg_bits[11:24]
        log.info(f"Device hw version: {ba2int(hw_ver)}")
        # The last bits correspond to the serial number
        serial_number = str(ba2int(msg_bits[24:32]))
        return can_id, serial_number
