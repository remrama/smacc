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

1. Open the `Powershell` app on your PC (or `Terminal` if Mac).
2. Create a new conda environment, so that our installation is isolated from the rest of your system. Also we need to make sure we use Python 3.8. Type `conda create -n smacc python=3.8` and hit `Enter`.
3. Activate the environment you just created. Type `conda activate smacc` and hit `Enter`.
4. Install SMACC! Type `pip install smacc` and hit `Enter`.
5. Generate some sound files to use for cueing. You can add your own, but this is just to get started and make sure everything works. Type `python -m smacc generate_cues` and hit `Enter`. That creates a simple beep cue. Now to make a pink-noise file for masking cues, Type `python -m smacc generate_noise` and hit `Enter`.
6. If planning to use parallel port, download _InpOut32_. Type `python -m smacc download_inpout` and hit `Enter`.

## Usage

### Before opening SMACC

* Place any sound files in the `stimuli` folder (**must be .wav files!**).
* Optional: Insert dream report questionnaire link in `config.json`.

### Open SMACC

```bash
python -m smacc
```

### Check recording device

* Test the setup by trying to play some cues.
* If planning to record dreams, choose sound device for recording audio from the Menu Bar (`Audio > Output device > [choose device]`).
