# EFVM Ticket Monitor

A simple Python tool that monitors ticket availability for the EFVM (Vale) passenger train.

## Features

* Monitor one-way or round-trip trips
* Choose origin and destination
* Select Economy, Executive, or both classes
* Monitor multiple passengers
* Automatic availability checks
* Sound alert when tickets are found
* Edit information before starting the monitor
* Press `V` to go back during data entry

## Requirements

* Python 3.x
* `requests`

Install the dependency:

```bash
pip install requests
```

## Usage

Run:

```bash
python efvmTicketSearcher.py
```

Follow the prompts to select your trip information.

Press `V` to go back and correct previous information.

Press `Ctrl+C` to stop the monitor.

## Disclaimer

This project is for personal use and educational purposes. It is not affiliated with or endorsed by Vale!
By Bernardo Costa — [@bernardocst](https://github.com/bernardocst)
