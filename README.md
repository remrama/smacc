# Sleep Manipulation And Communication Clickything

A clickable interface for running sleep-related experiments.

* Trigger audio cues
* Collect dream reports
* Trigger EEG portcodes
* Save a detailed event log
* and more!

## Installation

To install SMACC, go to the [releases page](https://github.com/remrama/smacc/releases), click the _Assets_ dropdown for the latest release, and download the _SMACC.exe_ file. Once downloaded, double-clicking this file will run SMACC.

Note that for some features, you will need to open SMACC with Administrator privileges (Right-click to open and select `Run as administrator`).

## Optional setup

* If you don't want to use the default `~/smacc_data` folder, you can change this by setting a new environment variable called `SMACC_DATA_DIRECTORY` equal to whatever directory you want to use. SMACC will create it and all the subfolders (if not already present).

* Place any sound files in the `~/smacc_data/cues` folder (_must be **.wav** files!_).

* There is a `Record Dream Report` button that will start to record from whatever external recording device is selected from the SMACC menubar. There is also an option to have it pop open a website URL. I use this to open up a dream report survey I have set up on Qualtrics. If you want it to open something, update the `SURVEY_URL` variable in `config.py`. If planning to record dreams, choose sound device for recording audio from the menubar (`Audio > Input device > [choose device]`).
