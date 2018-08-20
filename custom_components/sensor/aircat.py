"""
Support for AirCat air sensor.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.aircat/
"""

import asyncio
import logging
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_NAME, CONF_DEVICES, CONF_SENSORS, TEMP_CELSIUS)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import config_validation as cv

_LOGGER = logging.getLogger(__name__)

SENSOR_PM25 = 'value'
SENSOR_HCHO = 'hcho'
SENSOR_TEMPERATURE = 'temperature'
SENSOR_HUMIDITY = 'humidity'

DEFAULT_NAME = 'AirCat'
DEFAULT_SENSORS = [SENSOR_PM25, SENSOR_HCHO,
                   SENSOR_TEMPERATURE, SENSOR_HUMIDITY]

SENSOR_MAP = {
    SENSOR_PM25: ('PM2.5', 'μg/m³', 'blur'),
    SENSOR_HCHO: ('HCHO', 'mg/m³', 'biohazard'),
    SENSOR_TEMPERATURE: ('Temperature', TEMP_CELSIUS, 'thermometer'),
    SENSOR_HUMIDITY: ('Humidity', '%', 'water-percent')
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_DEVICES, default=['']):
        vol.All(cv.ensure_list, vol.Length(min=1)),
    vol.Optional(CONF_SENSORS, default=DEFAULT_SENSORS):
        vol.All(cv.ensure_list, vol.Length(min=1), [vol.In(SENSOR_MAP)]),
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the AirCat sensor."""
    name = config[CONF_NAME]
    devices = config[CONF_DEVICES]
    sensors = config[CONF_SENSORS]

    aircat = AirCatData(len(sensors))

    result = []
    for index in range(len(devices)):
        for sensor_type in sensors:
            result.append(AirCatSensor(aircat,
                name + str(index + 1) if index else name,
                devices[index], sensor_type))
    add_devices(result, True)


class AirCatSensor(Entity):
    """Implementation of a AirCat sensor."""

    def __init__(self, aircat, name, mac, sensor_type):
        """Initialize the AirCat sensor."""
        sensor_name, unit, icon = SENSOR_MAP[sensor_type]
        self._name = name + ' ' + sensor_name
        self._mac = mac
        self._sensor_type = sensor_type
        self._unit = unit
        self._icon = 'mdi:' + icon
        self._aircat = aircat

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return self._icon

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return self._unit

    @property
    def available(self):
        """Return if the sensor data are available."""
        return self.attributes is not None

    @property
    def state(self):
        """Return the state of the device."""
        attributes = self.attributes
        if attributes is None:
            return None
        state = float(attributes[self._sensor_type])
        return state/1000 if self._sensor_type == SENSOR_HCHO else round(state)

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attributes if self._sensor_type == SENSOR_PM25 else None

    @property
    def attributes(self):
        """Return the attributes of the device."""
        if self._mac:
            return self._aircat.devs.get(self._mac)
        for mac in self._aircat.devs:
            return self._aircat.devs[mac]
        return None

    async def async_update(self):
        """Update state."""
        #_LOGGER.debug("Begin update %s: %s", self._mac, self._sensor_type)
        await self._aircat.async_update()
        #_LOGGER.debug("Ended update %s: %s", self._mac, self._sensor_type)

    def shutdown(self, event):
        """Signal shutdown."""
        #_LOGGER.debug('Shutdown')
        self._aircat.shutdown()

import re
import json
import socket
import select
TIMEOUT=0.5
class AirCatData():
    """Class for handling the data retrieval."""

    def __init__(self, interval):
        """Initialize the data object."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(TIMEOUT)
        self._socket.setblocking(0)
        self._socket.bind(('', 9000))
        self._socket.listen(5)
        self._rlist = [self._socket]
        self._times = 0
        self._interval = interval
        self.devs = {}

    def shutdown(self):
        """Shutdown."""
        if self._socket  is not None:
            #_LOGGER.debug("Socket shutdown")
            self._socket.close()
            self._socket = None

    async def async_update(self):
        self._times += 1
        if self._times % self._interval != 1:
            return

        _LOGGER.debug('Begin update %d', self._times)
        rfd,wfd,efd = select.select(self._rlist, [], [], TIMEOUT)
        for fd in rfd:
            try:
                if fd is self._socket:
                    conn, addr = self._socket.accept()
                    _LOGGER.debug('Connected %s', addr)
                    self._rlist.append(conn)
                    conn.settimeout(TIMEOUT)
                else:
                    self.handle(fd)
            except:
                import traceback
                _LOGGER.error('Exception: %s', traceback.format_exc())
        _LOGGER.debug('Ended update %d', self._times)

    def handle(self, conn):
        data = conn.recv(1024) # If connection is closed, recv() will result a timeout exception and receive '' next time, so we can purge connection list
        if not data:
            _LOGGER.error('Closed %s', conn)
            self._rlist.remove(conn)
            conn.close()
            return

        if len(data) < 34: # 23+5+6
            _LOGGER.error('Received Invalid %s', data)
            return

        mac = data[17:23].hex()
        jsonStr = re.findall(r"(\{.*?\})", str(data), re.M)
        count = len(jsonStr)
        if count > 0:
            status = json.loads(jsonStr[count - 1])
            self.devs[mac] = status
            _LOGGER.debug('Received %s: %s', mac, status)
        else:
            _LOGGER.debug('Received %s: %s',  mac, data)

        response = data[:23] + b'\x00\x18\x00\x00\x02{"type":5,"status":1}\xff#END#'
        #_LOGGER.debug('Response %s', response)
        conn.sendall(response)