### HwGDReqs

a GD level requests app for streamers



### Features:

* Twitch Chat Monitoring: Listens for level IDs in Twitch chat (Device flow login)
* YouTube Chat Monitoring: Listens for level IDs in YouTube live chat (no login, just username)
* Thumbnails: using \[Level Thumbnails](https://levelthumbs.prevter.me/) API to see kevel thumbs on the app
* Queue Management to viewers: Add, remove, and replace levels (only to same requester)
* Blacklist System: Block levels, authors, or requesters
* Difficulty Filtering: Filter allowed difficulties
* Length Filtering: Filter allowed level lengths
* No Disliked Levels: Option to block disliked levels
* Requester Limits: Max levels per requester
* Level History: Track removed levels
* Thumbnail Caching: Cache level thumbnails
* API Server: HTTP API for external control (for anyone who wants to make a Geode Integration mod, please tell me tho)
* Chat Commands: `!del id` to delete a level and `!replace oldid newid` to replace (for the requester who sent the level)
* Level Fetching: Uses GDBrowser API for level data
* Platform Icons: Shows Twitch/YouTube icon per level
* Settings UI: Full settings dialog for all options
* Persistent Storage: Saves queue, blacklists, and settings



