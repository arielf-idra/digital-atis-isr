# Digital ATIS – Israel

Listens to broadcast ATIS audio and publishes it as text.

**Live:** https://arielf-idra.github.io/digital-atis-isr/

> ⚠️ **Not for operational use.** This is an unofficial, automatic speech-to-text
> transcription. It can be wrong, late or offline. Always listen to the official
> ATIS on frequency.

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

6. **Publish** `data/<ICAO>/latest.json`, `history.json` and `latest.mp3`. The audio
   clip lets anyone check the text by ear.

If the stream is down, the last good ATIS stays on the page with an **offline** banner.
The page also warns when the data is more than 20 minutes old.

## Running on GitHub

The [ATIS workflow](.github/workflows/atis.yml) runs on GitHub Actions. Each job
checks the stream about every 4 minutes for 50 minutes, and a concurrency group
queues the next job, so jobs follow each other without a gap. Results go to the
`gh-pages` branch as one commit that is amended each time, so audio doesn't build
up in git history.

One-time setup: **Settings → Pages → Deploy from branch → `gh-pages` / root**.

## Running locally

```sh
pip install -r requirements.txt      # also needs ffmpeg on PATH
python -m atis LLHA --out site/data  # one capture
python -m http.server -d site        # then open http://localhost:8000
pytest -q
```

## Adding a station

Add an entry to [`atis/stations.py`](atis/stations.py) with its stream URL and runways,
and add it to `STATIONS` in [`site/index.html`](site/index.html) and to `--stations`
in the workflow.
