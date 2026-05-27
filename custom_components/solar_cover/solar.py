"""Solar engine -- sun position and daily curve using astral.

No HA imports permitted. Uses hass.config values passed in at construction time.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TypedDict

from astral import Observer
from astral.sun import azimuth as astral_azimuth
from astral.sun import elevation as astral_elevation


class SunSample(TypedDict):
    time: str
    azimuth: float
    elevation: float


class SolarEngine:
    """Computes solar position for a fixed geographic location."""

    def __init__(self, lat: float, lon: float, elev: float) -> None:
        self._observer = Observer(latitude=lat, longitude=lon, elevation=elev)

    def sun_position(self, dt: datetime) -> tuple[float, float]:
        """Return (azimuth_deg, elevation_deg) for the given UTC datetime."""
        az = astral_azimuth(self._observer, dt)
        el = astral_elevation(self._observer, dt)
        return az, el

    def position_curve(self, date_: date) -> list[SunSample]:
        """Return 288 five-minute samples for the given date (UTC midnight to midnight).

        Samples cover one full UTC day at 5-minute intervals.
        """
        start = datetime(date_.year, date_.month, date_.day, tzinfo=UTC)
        samples: list[SunSample] = []
        for i in range(288):
            dt = start + timedelta(minutes=i * 5)
            az, el = self.sun_position(dt)
            samples.append(SunSample(time=dt.isoformat(), azimuth=az, elevation=el))
        return samples

    def hourly_curve(self, date_: date) -> list[SunSample]:
        """Return 24 hourly samples for the given date.

        Used for position_curve entity attribute.
        """
        start = datetime(date_.year, date_.month, date_.day, tzinfo=UTC)
        samples: list[SunSample] = []
        for i in range(24):
            dt = start + timedelta(hours=i)
            az, el = self.sun_position(dt)
            samples.append(SunSample(time=dt.isoformat(), azimuth=az, elevation=el))
        return samples

    def fov_window(
        self,
        azimuth_deg: float,
        fov_left: float,
        fov_right: float,
        date_: date,
    ) -> tuple[datetime | None, datetime | None]:
        """Return (entry_time, exit_time) when sun enters/exits the FOV today.

        Returns (None, None) if the sun never enters the FOV on this date.
        Entry and exit times are UTC datetimes.
        """
        samples = self.position_curve(date_)
        start = datetime(date_.year, date_.month, date_.day, tzinfo=UTC)
        entry: datetime | None = None
        exit_: datetime | None = None
        in_fov = False

        for i, sample in enumerate(samples):
            gamma = _gamma(azimuth_deg, sample["azimuth"])
            currently_in = (
                sample["elevation"] > 0 and _in_fov(gamma, fov_left, fov_right)
            )
            dt = start + timedelta(minutes=i * 5)

            if currently_in and not in_fov:
                entry = dt
            elif not currently_in and in_fov:
                exit_ = dt

            in_fov = currently_in

        return entry, exit_


def _gamma(win_azimuth: float, sol_azimuth: float) -> float:
    """Compute surface solar azimuth angle in degrees.

    Positive = sun to the left when facing the window.
    Negative = sun to the right.
    Range: (-180, 180].
    """
    return (win_azimuth - sol_azimuth + 180) % 360 - 180


def _in_fov(gamma: float, fov_left: float, fov_right: float) -> bool:
    """Return True if gamma is within the field of view."""
    return gamma < fov_left and gamma > -fov_right
