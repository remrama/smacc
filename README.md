# Sleep Manipulation And Communication Clickything

A clickable interface for running sleep-related experiments.

* Trigger audio cues
* Collect dream reports
* Trigger EEG portcods
* Save a detailed event log
* and more!


## Installation

```bash
# Install SMACC
pip install smacc

# Use SMACC to generate some wav files for cueing.
python -m smacc.generate_cues
python -m smacc.generate_noise  # noise to mask the cues

# If planning to use parallel port, download InpOut32
python -m smacc.download_inpout
```


## Usage

### Before opening SMACC

* Place any sound files in the `stimuli` folder (**must be .wav files!**).
* Optional: Insert dream report questionnaire link in `config.json`.


### Open SMACC

```bash
python -m smacc.run
```

### Check recording device.

* From the Menu bar, choose sound device for playing audio (`Audio > Input device > [choose device]`)
* From the Menu bar, choose sound device for recording dreams (`Audio > Output device > [choose device]`)

