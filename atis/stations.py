"""Per-station configuration.

Audio stations point at the most direct source we know of: the raw Icecast
stream (found via https://www.aopa.org.il/radio; we don't depend on that page
at runtime).

Text stations have no public audio stream. Their D-ATIS text comes from
atis.guru, which republishes the data-link ATIS that aircraft request over
ACARS. It only updates when an aircraft happens to request it, so it can be
hours or days old.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Station:
    icao: str
    name: str
    frequency: str
    runways: tuple[str, ...]
    elevation_ft: int
    source: str = "audio"          # "audio" (our transcription) or "text" (published D-ATIS)
    stream_url: str | None = None  # audio stations
    page_url: str | None = None    # text stations
    spoken_name: str = ""          # how the airport is named on the recording
    # Extra words that help the speech model with local vocabulary.
    vocabulary: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source_url(self) -> str:
        return self.stream_url or self.page_url or ""


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
    "LLBG": Station(
        icao="LLBG",
        name="Ben Gurion",
        source="text",
        page_url="https://atis.guru/atis/LLBG",
        frequency="D-ATIS",
        runways=("03", "21", "08", "26", "12", "30"),
        elevation_ft=135,
    ),
    "LLER": Station(
        icao="LLER",
        name="Ramon",
        source="text",
        page_url="https://atis.guru/atis/LLER",
        frequency="D-ATIS",
        runways=("01", "19"),
        elevation_ft=288,
    ),
}
