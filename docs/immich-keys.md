# Immich API keys

Frame Curator uses two Immich API keys with the smallest permissions each job needs. If one key leaks, the other job's permissions stay out of reach. The curator key can tag photos but cannot change favorites or albums. The frame key serves photos and handles the buttons.

## Create the keys

1. In Immich, go to **Account Settings** > **API Keys**.
2. Create a key named `framecurator-curator` with these permissions:
   `asset.read`, `asset.view`, `album.read`, `person.read`, `face.read`, `tag.read`, `tag.create`, `tag.asset`.
3. Create a key named `framecurator-frame` with these permissions:
   `asset.read`, `asset.view`, `album.read`, `person.read`, `face.read`, `tag.read`, `tag.create`, `tag.asset`, `asset.update` (Favorite), `albumAsset.create` and `albumAsset.delete` (Pick).
   If you set `frame.image_size: fullsize`, also add `asset.download`.
4. Put the keys in `.env` as `IMMICH_CURATOR_KEY` and `IMMICH_FRAME_KEY`.
5. In Immich, create an empty album named **Frame - Picks**. Frame Curator never creates it. To use another name, set `picks_album` in `config.yaml`.

Neither key needs admin permissions.
