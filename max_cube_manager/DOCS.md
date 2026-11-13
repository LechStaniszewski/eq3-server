# MAX! Cube Manager

The app provides the MAX! Cube Manager web interface inside Home Assistant.
Home Assistant ingress handles authentication; the app does not open a port on
the host or require a separate login.

## Setup

1. Copy this project folder into Home Assistant's `local_apps` folder, for
   example as `local_apps/max_cube_manager`.
2. Set **MAX! Cube address** to the Cube's IPv4 address or host name in the app
   configuration. The app uses the bridged network and does not rely on UDP
   broadcast discovery.
3. Keep **MAX! Cube port** at `62910` unless the Cube uses a different port.
4. Optionally enable **Debug logging** to include HTTP request metadata and
   MAX! Cube operation timings and error details in the app log.
5. Save the configuration, start the app, and open its web interface.

Restart the app after changing its configuration.

Debug logging does not include request bodies or raw Cube packets.

## Features

- View thermostats grouped by room.
- Rename rooms and thermostats, and move thermostats between rooms.
- View and edit each thermostat's weekly schedule.
- View current and target temperatures and adjust a room's target.

Radiator valves may not report a measured current temperature. In that case the
interface displays **Not reported**.

## Troubleshooting

- Confirm the Cube address is correct and reachable from the Home Assistant
  host.
- Check the app's log for Cube connection errors.
- If the page cannot reach the app API, the status beside the title now shows
  the HTTP status or request error.
- The app accepts web traffic only from Home Assistant's Supervisor ingress
  proxy. It intentionally does not expose a standalone network port.
