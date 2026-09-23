# Digital ATIS – Israel

Listens to broadcast ATIS audio and publishes it as text.

**Live:** https://arielf-idra.github.io/digital-atis-isr/

## Disclaimer

**UNOFFICIAL — NOT FOR OPERATIONAL USE.**

- This is an automatic speech-to-text transcription of a publicly streamed ATIS
  broadcast. It **can be wrong, incomplete, late or unavailable** at any time,
  without notice.
- It is **not** provided, approved or endorsed by the Israel Airports Authority,
  any air navigation service provider, airport, or the owners of the audio stream.
- It must **not** be used for flight planning, navigation, or any decision affecting
  safety. **Always obtain the official ATIS on frequency** (and official weather)
  before flight.
- Provided "as is", without warranty of any kind. Use entirely at your own risk.
  The authors accept no liability for any use of this information.

The same notice is included in every data response as the `disclaimer` field. Apps
that use the data must show it to their users.

## Stations

| ICAO | Airport | ATIS freq | Source stream |
|------|---------|-----------|---------------|
| LLHA | Haifa   | 135.400   | `https://llha.yarintw.com/ATIS.mp3` |

The stream URLs were found on the [AOPA Israel radio page](https://www.aopa.org.il/radio).
At runtime we connect straight to the raw Icecast stream and don't depend on any
web page.

## How it works

1. **Record** about 130 s of the stream with `ffmpeg`. That covers 2–3 plays of the ATIS loop.
2. **Split into loops** at the long pause between plays. Each complete loop is transcribed on its own.
3. **Transcribe** with [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
   (`small.en`, CPU). An example ATIS in the prompt steers it toward aviation phrasing.
4. **Parse** each transcript into fields: letter, time, runway, circuit, wind, visibility,
   clouds, temperature, dew point, QNH. A value is rejected if it is implausible,
   such as an unknown runway, QNH outside 940–1060 or a dew point above the temperature.
5. **Vote** across the loops. The page marks each field by how its loops compared:

   | Mark | Meaning |
   |------|---------|
   | ✓ confirmed | every loop that read it agrees |
   | ✓ majority | most loops agree |
   | ⚠ heard once | only one loop read it; not confirmed |
   | ✕ unclear | the loops disagree; left blank instead of guessed |

6. **Letter check.** The letter is said at the start and end of every repetition.
   Each mention is scored against all 26 code words ("information Alpha" …
   "information Zulu") by how well each one fits the audio, and the scores are
   added up across all mentions. This catches accent mishearings such as
   "dual yet" for Juliet, and the letter is confirmed only when every mention agrees.
7. **METAR cross-check.** Values are compared with the official METAR from
   [aviationweather.gov](https://aviationweather.gov/data/api/), preferring the
   report whose time matches the ATIS "valid from" time. **The ATIS always takes
   priority**: the METAR never replaces an ATIS value. A disagreement is shown to
   the user as a warning next to the value, e.g. "METAR says 30".
8. **Publish** `data/<ICAO>/latest.json`, `history.json` and `latest.mp3` to the
   `gh-pages` branch. The audio clip lets anyone check the text by ear.

If the stream is down, the last good ATIS stays on the page with an **offline** banner.
The page shows, live, how long ago the ATIS was heard and when it was issued, and
warns when the data is more than 15 minutes old.

## Using the data in other apps

Anyone can read the data over HTTPS. It is served with `Access-Control-Allow-Origin: *`,
so browser apps can call it directly.

| What | URL |
|------|-----|
| Current ATIS | `https://raw.githubusercontent.com/arielf-idra/digital-atis-isr/gh-pages/data/LLHA/latest.json` |
| Recent ATIS list | `https://raw.githubusercontent.com/arielf-idra/digital-atis-isr/gh-pages/data/LLHA/history.json` |
| Audio of the current ATIS | `https://raw.githubusercontent.com/arielf-idra/digital-atis-isr/gh-pages/data/LLHA/latest.mp3` |

Replace `LLHA` with any supported ICAO code. A new check is published about every
3 minutes; GitHub may cache the file for up to 5 more minutes.

**How old is it?** The file is static, so it can't know when you read it. Use the
`timing` block and your own clock:

```json
"timing": {
  "heard_at": "2026-09-23T09:33:07Z",        // end of the recording this data is based on
  "first_heard_at": "2026-09-23T09:32:15Z",  // when this letter/issue was first heard
  "atis_issued_at": "2026-09-23T08:50:00Z",  // the ATIS "valid from" time
  "atis_age_min_when_heard": 43,
  "published_at": "2026-09-23T09:33:49Z",
  "check_interval_min": 3,
  "stale_after": "2026-09-23T09:48:07Z"      // treat as out of date after this
}
```

- Minutes since last heard = `now − heard_at`
- Age of the ATIS = `now − atis_issued_at`
- If `now > stale_after`, the service has stopped updating: don't show the data as current.

`latest.json`, trimmed:

```json
{
  "station": {"icao": "LLHA", "name": "Haifa", "frequency": "135.400"},
  "disclaimer": "UNOFFICIAL - NOT FOR OPERATIONAL USE. ...",
  "checked_at": "2026-09-23T06:44:10Z",
  "first_seen": "2026-09-23T06:40:02Z",
  "timing": { ... },
  "status": "ok",
  "quality": "good",
  "letter": "F",
  "text": "Haifa airport information Foxtrot. ... QNH 1015 millibars. ...",
  "fields": {
    "runway": {"value": "33", "status": "confirmed", "votes": 2, "of": 2},
    "wind":   {"value": "VRB/3kt", "status": "confirmed", "votes": 2, "of": 2},
    "qnh":    {"value": 1015, "status": "confirmed", "votes": 2, "of": 2}
  }
}
```

- `status`: `ok`, `unreadable` (a recording was made but couldn't be read), or `offline` (no stream; the previous ATIS is kept).
- `quality`: `good` (letter confirmed, no conflicts), `partial` or `poor`.
- `fields.<name>.status`: `confirmed`, `majority`, `single` (heard once) or `conflict` (`value` is `null`).
- Fields: `letter`, `time`, `runway`, `circuit`, `wind`, `visibility`, `clouds`, `temperature`, `dewpoint`, `qnh`.
- `metar`: the cross-check: `raw`, `time`, `matched` (whether this is the METAR the ATIS was built from),
  `checks.<field>` = `{"metar": value, "agree": true|false|null}`, and `differs` (list of fields).
- `fields.letter.method` is `acoustic` with a `confidence` (0–1) when the letter was scored from the audio.

## Broadcasts that fail to decode

Every ATIS must give **runway, wind, temperature and QNH**. If any of them can't
be read, the system:

- shows a red "Could not read the …" banner on the page and lists the fields in
  `missing_required` in the JSON;
- keeps the recording and all transcripts in
  [`gh-pages/data/<ICAO>/failed/`](https://github.com/arielf-idra/digital-atis-isr/tree/gh-pages/data/LLHA/failed)
  (the last 100);
- opens a [GitHub issue labelled `decode-failure`](https://github.com/arielf-idra/digital-atis-isr/issues?q=label%3Adecode-failure)
  with the missing fields, every repetition's transcript, the METAR and a link to
  the recording. Each broadcast (letter + issue time) is reported once.

GitHub emails the repository owner about new issues. Review them to find phrases
the decoder should learn, and add the transcripts as test fixtures.

## Running on GitHub

The [ATIS workflow](.github/workflows/atis.yml) runs on GitHub Actions. Each run
listens for about 50 minutes. It records 3 minutes at a time, and while one
recording is being processed the next is already recording, so a fresh result is
published about every 3 minutes. At the end, each run starts the next one itself
(`workflow_dispatch`). A 15-minute schedule restarts the chain if it ever breaks. Results go to the
`gh-pages` branch as one commit that is amended each time, so audio doesn't build
up in git history. The web page (`index.html` on `main`) reads from there.

## Running locally

```sh
pip install -r requirements.txt      # also needs ffmpeg on PATH
python -m atis LLHA                  # one capture into ./data
python -m http.server                # then open http://localhost:8000
pytest -q
```

## Adding a station

Add an entry to [`atis/stations.py`](atis/stations.py) with its stream URL and runways,
and add it to `STATIONS` in [`index.html`](index.html) and to `--stations`
in the workflow.
