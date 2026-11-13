# MAX! Cube Manager app repository

This repository contains the Home Assistant app in [`max_cube_manager/`](./max_cube_manager/).

## Install in Home Assistant

1. Open **Settings > Apps**, open the menu, and choose **Repositories**.
2. Add `https://github.com/LechStaniszewski/eq3-server`.
3. Check for updates, then install **MAX! Cube Manager** from this repository.
4. Configure the MAX! Cube address before starting the app.

See the app's [documentation](./max_cube_manager/DOCS.md) for setup details.

## Install the Home Assistant integration with HACS

Install HACS first, then add this repository as a custom integration:

1. In HACS, open **Integrations** and choose **Custom repositories** from the menu.
2. Add `https://github.com/LechStaniszewski/eq3-server` with category **Integration**.
3. Install **MAX! Cube Manager** and restart Home Assistant.
4. Add **MAX! Cube Manager** under **Settings > Devices & services**. Use
   `max_cube_manager` as the app hostname unless the app has a different slug.

After this one-time setup, HACS can provide integration updates. See the app's
[documentation](./max_cube_manager/DOCS.md) for manual installation and entity
behavior.
