__all__ = ["AndorNeo"]

import asyncio
import numpy as np
from time import sleep

from yaqd_core import IsDaemon, IsSensor, HasMeasureTrigger, HasMapping
from typing import Dict, Any, List, Union
from . import atcore 
from . import features
from . import _andor_sdk3

ATCore = atcore.ATCore
ATCoreException = atcore.ATCoreException


class AndorNeo(_andor_sdk3.AndorSDK3):
    _kind = "andor-neo"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)

        # implement config, state features
        self.features["spurious_noise_filter"].set(self._config["spurious_noise_filter"])
        self.features["static_blemish_correction"].set(self._config["static_blemish_correction"])
        self.features["electronic_shuttering_mode"].set(self._config["electronic_shuttering_mode"])
        self.features["simple_preamp_gain_control"].set(self._config["simple_preamp_gain_control"])
        self.features["exposure_time"].set(self._config["exposure_time"])
        # aoi currently in config, so only need to run on startup
        self._set_aoi()
        self._set_temperature()

    def _set_aoi(self):
        aoi_keys = ["aoi_binning", "aoi_width", "aoi_left", "aoi_height", "aoi_top"]
        binning, width, left, height, top = [
            self._config[k] for k in aoi_keys
        ]
        binning = int(binning[0])  # equal xy binning, so only need 1 index

        # check if aoi is within sensor limits
        max_width = self.features["sensor_width"].get()
        max_height = self.features["sensor_height"].get()

        # handle defaults (maximum sizes)
        if left is None:
            left = 1
        if top is None:
            top = 1
        if width is None:
            width = max_width - left + 1
        if height is None:
            height = max_height - top + 1
        width //= binning
        height //= binning

        self.logger.debug(f"{max_width}, {max_height}, {binning}, {width}, {height}, {top}")
        w_extent = width * binning + (left-1)
        h_extent = height * binning  + (top-1)
        if w_extent > max_width:
            raise ValueError(f"height extends over {w_extent} pixels, max is {max_width}")
        if h_extent > max_height:
            raise ValueError(f"height extends over {h_extent} pixels, max is {max_height}")

        self.features["aoi_binning"].set(f"{binning}x{binning}")
        self.features["aoi_width"].set(width)
        self.features["aoi_left"].set(left)
        self.features["aoi_height"].set(height)
        self.features["aoi_top"].set(top)

        # apply shape, mapping
        self._channel_shapes = {
            "image": (self.features["aoi_height"].get(), self.features["aoi_width"].get())
        }
        x_ai = np.arange(left, left + width * binning, binning)[None, :]
        y_ai = np.arange(top, top + height * binning, binning)[:, None]
        
        x_index = x_ai.__array_interface__
        x_index["data"] = x_ai.tobytes()
        y_index = y_ai.__array_interface__
        y_index["data"] = y_ai.tobytes()
        
        self._mappings = {
            "x_index": x_index,
            "y_index": y_index
        }

        for k in ["aoi_height", "aoi_width", "aoi_top", "aoi_left", "aoi_binning"]:
            self.logger.debug(f"{k}: {self.features[k].get()}")

    def _set_temperature(self):
        # possible_temps = self.features["temperature_control"].options()
        sensor_cooling = self._config["sensor_cooling"]
        self.features["sensor_cooling"].set(sensor_cooling)
        if sensor_cooling:
            set_temp = self.features["temperature_control"].get()
            self.logger.info(f"Sensor is cooling.  Target temp is {set_temp} C.")
            self._loop.run_in_executor(None, self._check_temp_stabilized)
        else:
            sensor_temp = self.features["sensor_temperature"].get()
            self.logger.info(f"Sensor is not cooled.  Current temp is {sensor_temp} C.")

        status = self.features["temperature_status"].get()

    def _check_temp_stabilized(self):
        set_temp = self.features["temperature_control"].get()
        sensor_temp = self.features["sensor_temperature"].get()
        diff = float(set_temp) - sensor_temp
        while abs(diff) > 1.:
            self.logger.info(
                f"Sensor is cooling.  Target: {set_temp} C.  Current: {sensor_temp:0.2f} C."
            )
            sleep(5)
            set_temp = self.features["temperature_control"].get()
            sensor_temp = self.features["sensor_temperature"].get()
            diff = float(set_temp) - sensor_temp
        self.logger.info("Sensor temp is stabilized.")

    def get_sensor_info(self):
        return self.sensor_info

    def get_feature_names(self) -> List[str]:
        return [v.sdk_name for v in self.features.values()]

    def get_feature_value(self, k:str) -> Union[int, bool, float, str]:
        feature = self.features[k]
        return feature.get()

    def get_feature_options(self, k:str) -> List[str]:  # -> List[Union[str, float, int]]:
        feature = self.features[k]
        # if isinstance(feature, features.SDKEnum):
        return feature.options()
        # elif isinstance(feature, features.SDKFloat) or isinstance(feature, features.SDKInt):
        #     return [feature.min(), feature.max()]
        # else:
        #     raise ValueError(f"feature {feature} is of type {type(feature)}, not `SDKEnum`.")

    def close(self):
        self.sdk3.close(self.hndl)
