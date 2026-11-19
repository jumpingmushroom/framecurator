# Home Assistant

The Frame Curator integration shows the current photo as an image entity and adds controls for each display.

## Install

1. In HACS, open the menu and select **Custom repositories**.
2. Add `https://github.com/jumpingmushroom/framecurator` with the type **Integration**.
3. Install **Frame Curator** and restart Home Assistant.
4. Go to **Settings** > **Devices & services** > **Add integration** and select **Frame Curator**.
5. Fill in the fields, then repeat for each display:

   | Field | Description |
   |---|---|
   | Name | Display name, for example `Wallpanel`. Home Assistant turns it into a slug for the `device` value: lowercase, with spaces and other characters replaced by `-`, up to 32 characters. For example, `Living Room` becomes `living-room`. Allowed `device` characters are `a-z`, `0-9`, `_` and `-`. You can have up to 16 displays. |
   | URL | API address, for example `http://192.0.2.10:8099`. |
   | Token | The `FRAME_TOKEN` value. |
   | Width, Height | The display's size in pixels, 320 to 4096. For example, 1920 and 1200. |

Each display has its own current photo, mode, repeat history and image size. The curated pool and blocked photos are shared.

## Entities

Each display creates the following entities.

- An image entity named after the display, for example `image.wallpanel`, with the attributes `date`, `years_ago`, `place`, `people`, `mode` and `bucket`.
- A **Caption** sensor, for example `Tønsberg, Norway · 3 Oct 2026`, or `… · 3 years ago` for a memory.
- Diagnostic sensors for date, place, people, years ago, next change and why shown.
- Buttons: **Skip**, **Previous**, **Never show this** (tags the photo `frame/block` in Immich), **Undo never show** (restores the last photo that display blocked), **More like this** and **Less like this** (recorded for later tuning).
- Switches: **Pause**, **Favorite** (the Immich favorite flag) and **Pick** (membership of the picks album).
- A **Rotation interval** number, in minutes, per display.
- A **Mode** select: mixed, recent, picks, memories, favorites, person, album, place.
- **Person**, **Album** and **Place** selects. Choosing one also switches the display to that mode. They show curated photos only. If nothing matches, the display falls back to the whole pool.
- Config entities for the per-display **mix** (percent weights for on this day, favorites and picks, recent, and whole library) and **repeat window**, and for the **minimum vision score**, which all displays and the curator share.
- **Re-evaluate**: applies the minimum score again to photos that the curator decided by score alone. It needs no Ollama. It leaves photos whose tags you changed by hand and blocked photos alone. It fires `framecurator_reevaluated` with the counts and whether the changes held (`settled`).

The `framecurator_photo_changed` event fires whenever the photo changes. It carries the caption fields and the display name in `device`.

## Show the photo on a dashboard

```yaml
type: picture-entity
entity: image.wallpanel
show_name: false
show_state: false
```

## Automation examples

Turn the display's screen off at night. Replace `switch.wallpanel_screen` with your screen entity:

```yaml
automation:
  - alias: Wallpanel screen off at night
    triggers:
      - trigger: time
        at: "23:00:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.wallpanel_screen
```

Pause the photo rotation when nobody is home. Replace `switch.wallpanel_pause` with the **Pause** switch of your display:

```yaml
automation:
  - alias: Pause frame when nobody is home
    triggers:
      - trigger: state
        entity_id: zone.home
        to: "0"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.wallpanel_pause
  - alias: Resume frame when someone arrives
    triggers:
      - trigger: numeric_state
        entity_id: zone.home
        above: 0
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.wallpanel_pause
```
