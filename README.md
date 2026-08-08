### [HwGDReqs](https://hwgdreqs.github.io/)

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
* Twitch Priority System: Subs/VIPs/Mods get priority queue positions
* Twitch Restrictions: Subs-only, VIP-only, Followers-only mode
* Twitch Ban Integration: Ban users directly from the app + delete their levels
* YouTube Chat with yt-dlp/pytchat: Full YouTube live chat monitoring
* Queue Popout Window: OBS-capturable standalone window with scaling
* Statistics Dashboard: Today/always stats, most active requesters, etc.
* Update Checker + Auto-Updater: Self-updating on Windows with bat script
* Level History Tab: Shows removed levels with click-to-copy
* Full Logging System: Logs to file AND console with toggle
* Console Log Toggle: print_full_log_to_console setting
* Network API Hosting: Can host API on local network with random port
* Auto-clearing Status Bar: Messages disappear after 5s
* Drag-to-Reorder Queue: Click and hold for 1s then drag
* Context Menu: Right-click levels for quick actions (move up/down, copy, delete, blacklist)
* Bulk Actions: Delete all from requester/author, blacklist+delete, ban+delete+blacklist
* !whereami Command: Tells users their position in queue
* Cooldown System: Per-requester request cooldown
* Requester Level Count Tracking: Max levels per requester per session
* Platform-Specific Chat Windows: Separate Twitch/YouTube chat viewers
* "Allow Any Level" Mode: Adds unlisted levels as bare IDs with ⚠️
* Queue Popout Scaling: OBS-friendly scaling from 30-300%
* Level History with Difficulty Icons: Shows removed levels with icons
* Login Flow with Platform Selection: Twitch, YouTube, or Both
* Channel Moderator Scope: For banning users
* Chat Edit Scope: For !queue and !whereami commands
* Statistics Tracking: Per-day and all-time stats
* PFP in Info Tab: Your profile picture in settings
* YouTube Refresh Button: Manual refresh when stream starts
* Blacklist Timestamps: Tracks when things were blacklisted
* Priority Levels: Levels can be marked priority and inserted at front

what the fuck did i do

Site: https://hwgdreqs.github.io

made by MalikHw47
