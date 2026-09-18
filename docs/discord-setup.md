# Discord setup

## Do I need to do anything?

No. VNPresence ships with its own Discord application ("a Visual Novel"). Install,
add a game, press Play. This page is only for people who want their own.

The one Discord setting that matters:

**User Settings → Activity Privacy → "Share your detected activities with
others"** must be **on**. If it is off, nothing you do here will show anything.

## Why the top line says "Playing a Visual Novel"

Discord builds the activity header from the **name of the application** the
presence is sent from. That name lives in the Discord developer portal and
cannot be set per update - the payload has no field for it. Every Rich Presence
tool has this constraint.

So the layout VNPresence produces is:

```
Playing a Visual Novel        <- the application's name (fixed)
Steins;Gate                   <- details  (the game, most prominent line we control)
Reading                       <- state
01:24:07 elapsed              <- timestamps
[ View on VNDB ]               <- button
```

## Making your own application

Do this if you want the header to read something else, or one application per
game.

1. Go to <https://discord.com/developers/applications> and sign in.
2. **New Application**. The name you type is exactly what appears after
   *Playing*, so name it `Visual Novel`, or `Steins;Gate`, or whatever you want.
3. Accept the developer terms, then open the application.
4. On **General Information**, copy the **Application ID** (a long number).
5. Put it in your config:

```yaml
# %APPDATA%\VNPresence\config.yaml
client_id: "123456789012345678"
```

Or for one game only:

```yaml
# %APPDATA%\VNPresence\games\steins-gate.yaml
title: Steins;Gate
client_id: "123456789012345678"
```

Check it with:

```bash
vnpresence doctor
```

## Do I need to upload images?

No. Discord's *Rich Presence → Art Assets* page exists for apps that ship a fixed
set of images, and it caps out at 300 per application. VNPresence instead sends
the VNDB cover URL directly, which Discord fetches and displays - so a new game
needs no upload, and there is no 300-game ceiling.

If you do want an uploaded asset (for example a custom small icon), upload it
under *Rich Presence → Art Assets*, then use its key:

```yaml
# config.yaml
small_image: my_icon_key
```

Both forms work: a key for an uploaded asset, or a public `https://` URL.

## One application per game

Possible, and the only way to get the game's name on the header line - at the
price of creating an application for every title by hand:

1. Create an application named exactly like the game.
2. Put its id in that game's profile as `client_id`.

VNPresence connects to whichever application the running game specifies.

## Nothing shows up

| Check | How |
|---|---|
| Discord **desktop** app running? | The browser client has no local RPC socket |
| Activity sharing on? | Settings → Activity Privacy |
| Right account? | The presence goes to whichever account the desktop app is signed into |
| Application id correct? | `vnpresence doctor` reports the connection |
| Looking at your own profile? | Buttons are not rendered for yourself - ask a friend |
| Game actually detected? | `vnpresence play <game> -v` prints the tracked process |
