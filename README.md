This integration allows to connect an Energy OWL CM160 on a homeassistant instant and retrieve the electrical current measurement from it.

![image](https://github.com/user-attachments/assets/75d97f4f-463f-4380-8232-92ce58faa015)


How to install
==============

* Connect the CM160 to your HomeAssistant machine and take note of the port.

Note: if you are using a virtual machine, make sure you bridge the USB device from the host to the HA VM.
Port can be discovered by examining System Devices in Windows under COM ports, or by listing /dev under Linux. 
Typical names are COMxx (Windows) or /dev/ttyUSB0 (Linux).
For windows, driver may be required for COM port to appear. Install the software for Energy OWL website if needed.

* Install HACS into home assistant
* Open HACS page in Home Assistant, add a custom package source: https://github.com/PBrunot/energy_owl_hacs
* Search for OWL and install the package from HACS

How to use
==========

* You will need to specify the port path (e.g. /dev/ttyUSB0 or COM4) during integration configuration.
* Allow for a few minutes before the sensor with CM160 current is updated.

Reason is the CM160 first historical data, then sends realtime data. Sending the historical data takes a while.

* Look for entity CM160 - Current 

![image](https://github.com/user-attachments/assets/20e1dcac-2248-4dd1-9a46-9dbcfda59633)

* Data is updated every 15s. To convert into instantaneous power in kW, you need to multiply current by the average voltage in your home and divide by 1000.
* To convert the instantaneous power to energy counter, insert a helper to integrate the instantaneous power into kWh. This counter can then be used normally for the Energy dashboard.
