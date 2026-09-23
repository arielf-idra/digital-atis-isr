"""Per-station configuration.

Each station points at the most direct source we know of: the raw Icecast
audio stream. The AOPA Israel radio page (https://www.aopa.org.il/radio) is
where these URLs were found, but we do not depend on it at runtime.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Station:
    icao: str
    name: str
    spoken_name: str  # how the airport is named on the recording
    stream_url: str
    frequency: str
    runways: tuple[str, ...]
    elevation_ft: int
    # Extra words that help the speech model with local vocabulary.
    vocabulary: tuple[str, ...] = field(default_factory=tuple)


STATIONS: dict[str, Station] = {
    "LLHA": Station(
        icao="LLHA",
        name="Haifa",
        spoken_name="Haifa",
        stream_url="https://llha.yarintw.com/ATIS.mp3",
        frequency="135.400",
        runways=("15", "33"),  # re-designated from 16/34 in 2024
        elevation_ft=28,
        vocabulary=("Haifa clearance", "Haifa tower", "Pluto", "Carmel", "Acre"),
    ),
}
