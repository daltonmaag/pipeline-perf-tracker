# UFO Performance Tracker

A tracker for performance improvements across the UFO libraries inspired by
arewefastyet.com

Tested on Ubuntu on WSL2. Should work on Linux and macOS, not windows (because
it uses /usr/bin/time to measure time... to be improved!)

To setup a fresh Ubuntu:

```bash
sudo apt install python3-pip
pip3 install poetry
```

To run this script:

```bash
poetry install
poetry run python runner.py
```

The results of the runs are stored both in `results/results.json` and embedded
into `results/index.html`.
