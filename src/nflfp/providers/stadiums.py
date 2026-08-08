"""Stadium coordinates, keyed by nflverse ``stadium_id``.

Why this is code and not a table
--------------------------------
A forecast needs a latitude and longitude; nflverse's schedule gives a
``stadium_id`` and a *name*. The name is unusable as a key — the same venue
appears as "Ravens Stadium", "M&T Bank Stadium" and several sponsor names across
seasons, and ``raw_schedules`` holds 111 distinct name strings for 62 distinct
ids. The id is stable, so it is the join key.

The coordinates themselves are static physical facts about ~30 buildings. They
do not need a migration, a refresh job, or an upstream provider; putting them in
a table would add operational surface for data that changes when a stadium is
built. Keeping them here makes them reviewable in a diff and testable without a
database.

Roof handling
-------------
``raw_schedules.roof`` is ``dome``, ``closed``, ``outdoors``, or empty. Empty
means retractable-with-unknown-state, which is genuinely unknown before kickoff
— so those venues are marked :attr:`Stadium.retractable` and *do* get a
forecast, flagged so the model can treat them as uncertain rather than assuming
either extreme.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stadium:
    """A venue's fixed physical properties."""

    stadium_id: str
    name: str
    latitude: float
    longitude: float
    timezone: str
    #: True for fixed roofs and permanently-indoor venues: weather is irrelevant.
    indoor: bool = False
    #: True for retractable roofs, where the state is unknown before kickoff.
    retractable: bool = False

    @property
    def weather_relevant(self) -> bool:
        """Whether fetching a forecast for this venue is worth the request.

        Retractable roofs count: the roof is often open in September and shut in
        December, and the model is better served by a real forecast plus an
        "uncertain" flag than by a fabricated neutral one.
        """
        return not self.indoor


#: Every venue hosting a game in the current schedule, plus recent
#: international and relocated sites. A missing id degrades gracefully — see
#: :func:`lookup`.
STADIUMS: dict[str, Stadium] = {
    s.stadium_id: s
    for s in (
        # ---- outdoor -----------------------------------------------------
        Stadium("BAL00", "M&T Bank Stadium", 39.2780, -76.6227, "America/New_York"),
        Stadium("BOS00", "Gillette Stadium", 42.0909, -71.2643, "America/New_York"),
        Stadium("BUF00", "Highmark Stadium", 42.7738, -78.7870, "America/New_York"),
        Stadium("CAR00", "Bank of America Stadium", 35.2258, -80.8528, "America/New_York"),
        Stadium("CHI98", "Soldier Field", 41.8623, -87.6167, "America/Chicago"),
        Stadium("CIN00", "Paycor Stadium", 39.0955, -84.5160, "America/New_York"),
        Stadium("CLE00", "Huntington Bank Field", 41.5061, -81.6995, "America/New_York"),
        Stadium("DEN00", "Empower Field at Mile High", 39.7439, -105.0201, "America/Denver"),
        Stadium("GNB00", "Lambeau Field", 44.5013, -88.0622, "America/Chicago"),
        Stadium("JAX00", "EverBank Stadium", 30.3239, -81.6373, "America/New_York"),
        Stadium("KAN00", "GEHA Field at Arrowhead Stadium", 39.0489, -94.4839, "America/Chicago"),
        Stadium("MIA00", "Hard Rock Stadium", 25.9580, -80.2389, "America/New_York"),
        Stadium("NAS00", "Nissan Stadium", 36.1665, -86.7713, "America/Chicago"),
        Stadium("NYC01", "MetLife Stadium", 40.8135, -74.0745, "America/New_York"),
        Stadium("PHI00", "Lincoln Financial Field", 39.9008, -75.1675, "America/New_York"),
        Stadium("PIT00", "Acrisure Stadium", 40.4468, -80.0158, "America/New_York"),
        Stadium("SEA00", "Lumen Field", 47.5952, -122.3316, "America/Los_Angeles"),
        Stadium("SFO01", "Levi's Stadium", 37.4033, -121.9694, "America/Los_Angeles"),
        Stadium("TAM00", "Raymond James Stadium", 27.9759, -82.5033, "America/New_York"),
        Stadium("WAS00", "Northwest Stadium", 38.9077, -76.8645, "America/New_York"),
        # ---- fixed roof / permanently indoor ------------------------------
        Stadium("DET00", "Ford Field", 42.3400, -83.0456, "America/Detroit", indoor=True),
        Stadium("LAX01", "SoFi Stadium", 33.9535, -118.3392, "America/Los_Angeles", indoor=True),
        Stadium("MIN01", "U.S. Bank Stadium", 44.9738, -93.2578, "America/Chicago", indoor=True),
        Stadium("NOR00", "Caesars Superdome", 29.9511, -90.0812, "America/Chicago", indoor=True),
        Stadium("VEG00", "Allegiant Stadium", 36.0909, -115.1833, "America/Los_Angeles", indoor=True),
        # ---- retractable: roof state unknown before kickoff ----------------
        Stadium("ATL97", "Mercedes-Benz Stadium", 33.7554, -84.4009, "America/New_York", retractable=True),
        Stadium("DAL00", "AT&T Stadium", 32.7473, -97.0945, "America/Chicago", retractable=True),
        Stadium("HOU00", "NRG Stadium", 29.6847, -95.4107, "America/Chicago", retractable=True),
        Stadium("IND00", "Lucas Oil Stadium", 39.7601, -86.1639, "America/Indiana/Indianapolis", retractable=True),
        Stadium("PHO00", "State Farm Stadium", 33.5276, -112.2626, "America/Phoenix", retractable=True),
        # ---- international and recent relocations -------------------------
        Stadium("LON00", "Wembley Stadium", 51.5560, -0.2795, "Europe/London"),
        Stadium("LON02", "Tottenham Hotspur Stadium", 51.6043, -0.0665, "Europe/London"),
        Stadium("GER00", "Allianz Arena", 48.2188, 11.6247, "Europe/Berlin"),
        Stadium("FRA00", "Deutsche Bank Park", 50.0686, 8.6455, "Europe/Berlin"),
        Stadium("SAO00", "Arena Corinthians", -23.5453, -46.4742, "America/Sao_Paulo"),
        Stadium("MEX00", "Estadio Azteca", 19.3029, -99.1505, "America/Mexico_City"),
        Stadium("LAX99", "Los Angeles Memorial Coliseum", 34.0141, -118.2879, "America/Los_Angeles"),
        Stadium("LAX97", "Dignity Health Sports Park", 33.8644, -118.2611, "America/Los_Angeles"),
        Stadium("OAK00", "Oakland Coliseum", 37.7516, -122.2005, "America/Los_Angeles"),
    )
}


def lookup(stadium_id: str | None) -> Stadium | None:
    """Return the stadium for an id, or ``None`` if it is unknown.

    Unknown is a normal outcome, not an error: nflverse adds venues for
    international games, and a missing forecast for one game is much better than
    a failed ingest for all of them. Callers log and skip.
    """
    if not stadium_id:
        return None
    return STADIUMS.get(stadium_id.strip().upper())
