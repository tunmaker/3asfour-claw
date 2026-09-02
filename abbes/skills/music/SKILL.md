---
name: music
description: "Play music and Qur'an from the household Jellyfin library on the Pi speaker, via the jellyfin tools."
metadata:
  {
    "openclaw":
      {
        "emoji": "🎵",
      },
  }
---

# Music & audio playback

The household's audio (music, Qur'an recitations) lives on Jellyfin. Play it on
the Pi speaker with the `jellyfin` MCP tools — never exec:

1. `jellyfin_music` / `jellyfin_browse` — find the track, album, artist, or
   sura the person asked for.
2. `jellyfin_sessions` — the target is always the session named **Abbes Pi**.
   Other sessions (a phone, a browser) belong to people, not to you.
3. `jellyfin_play` — start it on the Abbes Pi session.
4. `jellyfin_playback_control` — pause, resume, stop, next, previous, volume.

**Always target Abbes Pi and only Abbes Pi.** Never pause, stop, or change
what is playing on any other session — those are other people's devices.

The Pi speaker is shared with your own voice. If you need to speak while music
plays, the person hears both at once; that is expected. Stopping the music is a
deliberate request, not something you do to talk.

This plays from the household's own library. It has no purchasing power and
reaches no outside service.
