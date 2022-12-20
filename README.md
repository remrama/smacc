# Sleep Manipulation And Communication Clickything

A clickable interface for running sleep-related experiments.

* Trigger audio cues
* Collect dream reports
* Trigger EEG portcodes
* Save a detailed event log
* and more!

## Installation

### Get Python

Download either [Anaconda](https://www.anaconda.com/products/distribution) or [Miniconda](https://docs.conda.io/en/main/miniconda.html#latest-miniconda-installer-links). I prefer Miniconda, which is a much smaller install. If you're only using Python for SMACC, just get Miniconda.

### Get SMACC

1. Open the `Powershell` app on your PC **with Admin privileges** (Right-click to open and select `Run as administrator`).
2. Create a new conda environment, so that our installation is isolated from the rest of your system. Also we need to make sure we use Python 3.8. Type `conda create -n smacc python=3.8` and hit `Enter`.
3. Activate the environment you just created. Type `conda activate smacc` and hit `Enter`.
4. Install SMACC! Type `pip install 'smacc[port_triggers]'` and hit `Enter`. If you do _not_ plan to use port triggers, use only `pip install smacc` instead.
5. Generate some sound files to use for cueing. You can add your own, but this is just to get started and make sure everything works. Type `python -m smacc generate_cues` and hit `Enter`. That creates a simple beep cue. Now to make a pink-noise file for masking cues, Type `python -m smacc generate_noise` and hit `Enter`.
6. If planning to use parallel port, download _InpOut32_. Type `python -m smacc download_inpout` and hit `Enter`.

## Usage

### Optional setup

**These steps must be done _before_ running SMACC.**

SMACC will create a folder in your home directory, and then 3 folders in within that. It will look like this.
```
Users/<username>/smacc_data/cues  # <-- Any .wav file in here is made available as a cue to play with SMACC
Users/<username>/smacc_data/logs  # <-- Data .log files are saved here.
Users/<username>/smacc_data/noise # <-- The pink noise file is saved here.
```

If you don't want to use the default `~/smacc_data` folder, you can change this by setting a new environment variable called `SMACC_DATA_DIRECTORY` equal to whatever directory you want to use. SMACC will create it and all the subfolders (if not already present).

* Place any sound files in the `~/smacc_data/cues` folder (_must be **.wav** files!_).

There is a `Record Dream Report` button that will start to record from whatever external recording device is selected from the SMACC menubar. There is also an option to have it pop open a website URL. I use this to open up a dream report survey I have set up on Qualtrics. If you want it to open something, update the `SURVEY_URL` variable in `config.py`.

### Run SMACC

```bash
# Make sure the conda environment is active.
conda activate smacc

# Run SMACC.
python -m smacc
```

* Test the setup by trying to play some cues.
* If planning to record dreams, choose sound device for recording audio from the menubar (`Audio > Input device > [choose device]`).
