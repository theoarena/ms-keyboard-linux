# Microsoft Keyboard

Give the My Favorites keys on your Wireless Keyboard 2000 something to do.

[What the app does](#what-the-app-does) • [Who it's for](#who-its-for) • [Use the app](#use-the-app) • [Install](#install)

## What the app does

On Windows, Mouse and Keyboard Center assigns the star and the five numbered favorite keys. On Linux, those keys do nothing. **Microsoft Keyboard** is the app that assigns them.

Typing, the pointer, and the volume keys already work. This app is for the favorites only.

Open it from your app grid. Pick a key, choose what it should do, and apply. The key works right away, and it keeps working after you sign in again.

## Who it's for

You use a Microsoft Wireless Keyboard 2000 on a Linux desktop, such as GNOME or Zorin, and you want those six keys to open an app, run a command, or trigger a shortcut.

## Use the app

The window is titled **Microsoft Keyboard**, with the subtitle **My Favorites**.

1. Pick a key: the star, or **1** through **5**.
2. Under **Action**, choose what that key does.
3. Select **Apply**.

You can set each key differently. Apply replaces the previous choice for that key.

| Action | What you get |
| --- | --- |
| Open app | The key opens an app you already have. Choose **1**, then **Open app**, then **Firefox**. Apply. Press **1** and Firefox opens. |
| System shortcut | The key sends a function key from **F13** to **F24**, so your desktop can record it. Choose **2**, then **System shortcut**, then **F15**. Apply. In Settings → Keyboard → Shortcuts, press the physical **2** key and bind it to Lock screen. |
| Command | The key runs a command you type. Choose the star, then **Command**, and enter `firefox --private-window`. Apply. The star opens a private window. |
| Nothing | The key stays quiet. Choose the key, then **Nothing**, and apply. |

**Restart Mapper**, in the header, reloads your keys without changing what you saved. Use it when a key does not respond.

> [!NOTE]
> The app starts your keys when you sign in. Leave Startup Applications alone. A second copy there runs each favorite twice.

## Install

You do this once. After that, open **Microsoft Keyboard** from your apps.

```bash
git clone https://github.com/theoarena/ms-keyboard-linux.git
cd ms-keyboard-linux
sudo python3 mskb.py install
```

Plug in the keyboard’s USB receiver before you apply a key.

On Ubuntu or Zorin, install the window toolkit if the app does not open:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```
