# EFVM Ticket Monitor

A lightweight Python tool to monitor ticket availability for the EFVM (Vale) passenger train.

## Features

* Monitor one-way or round-trip journeys
* Choose any station along the Vitória a Minas railway
* Filter by Economy, Executive, or both classes
* Support for multiple passengers
* Automatic browser login: opens the official Vale login page and closes automatically once authenticated
* Background monitoring: searches run quietly without open windows on your desktop
* Audio alert when available tickets are detected
* Privacy-focused: credentials and tokens are kept in volatile memory only (never written to disk)
* Interactive CLI: press `V` to step back and edit choices

## Requirements

* Python 3.8+
* `playwright`
* Google Chrome or Microsoft Edge (pre-installed on Windows)

Install dependencies:

```bash
pip install playwright
```

*(Optional)* If you do not have Chrome or Edge installed:

```bash
playwright install chromium
```

## Usage

```bash
python efvmTicketSearcher.py
```

1. A browser window will open to the official Vale portal.
2. Sign in with your account. Once completed, the window **closes automatically**.
3. Follow the interactive steps in the terminal to configure your trip.
   * Press `V` at any prompt to return to the previous step.
   * Press `Ctrl+C` anytime to pause or stop monitoring.

## Disclaimer

This project is for personal and educational use only. It is not affiliated with or endorsed by Vale S.A.

Author: Bernardo Costa — [@bernardocst](https://github.com/bernardocst)