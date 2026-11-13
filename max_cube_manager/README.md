# MAX! Cube Manager

Manage MAX! Cube thermostats, rooms, and schedules through a local web
interface or a Home Assistant app.

## Home Assistant

This folder is a Home Assistant app. It uses ingress, so the interface is
available inside Home Assistant without exposing an unauthenticated port.

Install this repository from Home Assistant's **Settings > Apps > Repositories**
page, or copy this app folder into Home Assistant's `local_apps` directory for
local testing.
Before starting the app, set **MAX! Cube address** in its configuration to the
Cube's IPv4 address or host name. The app uses bridged networking, so it does
not rely on LAN UDP broadcast discovery. The default Cube TCP port is `62910`.
See [DOCS.md](./DOCS.md) for setup and troubleshooting.

## Local web interface

From the repository root, run:

```sh
python3 -m max_cube_manager.max_web
```

The server binds to `127.0.0.1:8765` and discovers the Cube automatically.
Use `--cube-host` to select a Cube explicitly.

The command-line interface can also be run with:

```sh
python3 -m max_cube_manager.max --discover
```

Run the tests from the repository root with:

```sh
python3 -m unittest -v max_cube_manager.test_maxcube max_cube_manager.test_max_web max_cube_manager.test_home_assistant
```
