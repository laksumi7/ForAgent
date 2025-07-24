"""
web_interface.py
================

This module defines a simple web interface for interacting with the trading
application. It uses FastAPI to serve HTML pages and handle form submissions.
The interface provides the following functionality:

* Display the current mode (virtual or real), account information and a list
  of implemented features.
* Switch between virtual and real trading modes using a password‑protected form.
* Reset the virtual trading log.
* Stop trading, which forces a switch back to virtual mode and clears the log.

The HTML templates are located in the ``templates`` directory and are
rendered with Jinja2. Extending the interface with additional pages is as
simple as adding new templates and corresponding route handlers.
"""

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from trading_mode import TradingMode

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# A single TradingMode instance is shared across requests. If multiple
# processes are spawned then each will have its own instance. The instance
# reads configuration on construction and can be reloaded via the switch
# handler below when toggling modes.
tm = TradingMode()

# Define a list of features to present on the main page. This can be
# extended in the future as more functionality is added.
FEATURES = [
    "실거래/가상모드 전환",            # switch between real and virtual mode
    "로그 리셋 (가상모드)",           # reset log when in virtual mode
    "자동 재시작 기능",               # auto restart functionality implemented in auto_restart.py
    "정지 버튼을 통한 매매 중단",     # stop trading via a button
]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the home page showing account info and available actions."""
    info = tm.get_account_info()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "features": FEATURES,
            "account_info": info,
            "virtual": tm.virtual,
        },
    )


@app.post("/switch")
async def switch_mode(password: str = Form(...)) -> RedirectResponse:
    """Switch between virtual and real trading modes.

    A simple password check guards this endpoint. In a real system this
    password should be stored securely (for example, as an environment
    variable) and hashed instead of being hard‑coded.
    """
    # Replace this with your own authentication mechanism. The password
    # should be kept outside of source control.
    if password != "password":
        # Deny switch on wrong password; silently redirect back to index.
        return RedirectResponse("/", status_code=303)

    # Toggle virtual/real flag. When switching to real mode instantiate
    # a fresh TradingMode so that API credentials and coins list are reloaded.
    tm.virtual = not tm.virtual
    if tm.virtual:
        tm.log("Switched to virtual mode")
    else:
        # Reload config and Upbit connection
        tm.__init__()
        tm.log("Switched to real mode")

    return RedirectResponse("/", status_code=303)


@app.post("/reset")
async def reset_log() -> RedirectResponse:
    """Reset the log file. Only has an effect in virtual mode."""
    try:
        tm.reset_log()
    except RuntimeError:
        # Ignore attempts to reset while in real mode. In a production
        # application this might return an error message instead.
        pass
    return RedirectResponse("/", status_code=303)


@app.post("/stop")
async def stop_trading() -> RedirectResponse:
    """Stop all trading activity.

    This handler forces the application back into virtual mode and clears
    the log. It provides a quick way to safely halt real trading without
    needing a password. Use this endpoint when emergency intervention is
    required.
    """
    if not tm.virtual:
        tm.virtual = True
        tm.log("Trading stopped; switching to virtual mode")
    try:
        tm.reset_log()
    except RuntimeError:
        # If we switched from real to virtual then reset_log will succeed.
        pass
    return RedirectResponse("/", status_code=303)
