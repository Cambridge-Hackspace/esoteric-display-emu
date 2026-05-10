# Esoteric Display Emulator (`esoteric-display-emu`)

This project serves as a snap-in replacement for any of the physical esoteric
displays we'll have in the Hackspace. Should make it easier to test your
software from the safety and comfort of your bathtub, tree fort, zipline
harness, or other mobile workstation.

In general, rendering software for the esoteric displays should use the
[esoteric display manager](https://github.com/Cambridge-Hackspace/esoteric-display-mgr)
instead of implementing DDP/UDP directly. But you can simply point the display
manager to this emulator and have a working test environment.

You should be able to run this in a terminal emulator. This design choice was
implemented because I like to practice being an old codger that shakes their
fist at new-fangled technologies like "GUIs". I prefer my graphics to be
entirely displayed on things not designed to display images, like
[traffic lights](https://github.com/Cambridge-Hackspace/traffic-light-display).

## Licensing

Copyright (c) 2026 Cambridge Hackspace.
Released under the [MIT License](https://mit-license.org/license.txt).

## Installation

You need [cargo](https://doc.rust-lang.org/cargo/getting-started/installation.html).
Simply execute `cargo build --release` and the artifact will drop magically
at `target/release/esoteric-display-emu`.

## Execution

Run the project using the following:

```sh
target/release/esoteric-display-emu \ # or wherever your binary lives
    --width <width> \                 # the number of columns on your esoteric display
    --height <height> \               # the number of rows on on your esoteric display
    --bind <ip:port> \                # the ip and port that you'd like to listen on
    --clock <fps>                     # the refresh rate of your esoteric display
```

Once the program opens, you can quit with `CTRL + C` or by hitting `q`.
If your terminal is too small for the image, you can use the arrow keys to pan.

## Image Dispatch

We're using [DDP](http://www.3waylabs.com/ddp/) to accept images, but we're
certainly not utilizing it to its fullest extent. DDP uses a 10-byte header:

| Byte Range | Description                                                                                                      |
|-----------:|:-----------------------------------------------------------------------------------------------------------------|
|          0 | This is mostly metadata. The emulator ignores most of it -- the `PUSH` flag is assumed. In general, use `0x41`.                                 |
|          1 | Part of this is the sequence number, which is ignored here. In general, use `0x00`.                              |
|          2 | Data type. We use this, see "data type" below.                                                                   |
|          3 | This is ignored and references the output device. Use `0x01` (default).                                          |
|        4-7 | Data offset in bytes, MSB first--this is used, and is helpful for issuing PATCH directives.                      |
|        8-9 | Data length in bytes, MSB first--this is used for sure, but anything that extends past the display is truncated. |

### Data Types

Byte 2 (0-indexed) is particularly important here. The DDP documentation notes
that it ought to be set to `0` if not used or undefined, in which case this
emulator assumes grayscale, 8 bits per pixel. The flags for this byte are
`C R TTT SSS`:

| Flag | Description                                                                                                                                                     |
|:-----|:----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| C    | 0 for standard types, and 1 otherwise (ignored, but in general use `0b0`).                                                                                      |
| R    | This is reserved by the protocol, so it's always `0b0`.                                                                                                         |
| TTT  | This is the data type: `0b000` (undefined), `0b001` (RGB), `0b010` (HSL), `0b011` (RGBW), or `0b100` (grayscale).                                               |
| SSS  | Size in bits per channel: `0b000` (undefined), `0b001` (1 bit), `0b010` (4 bits), `0b011` (8 bits), `0b100` (16 bits), `0b101` (24 bits), or `0b110` (32 bits). |

Important: If the `SSS` flag is set to `0b001` or `0b010` (1 or 4 bits,
respectively), then that entire byte will be padded for the whole channel! This
seems to be standard operating procedure for similar displays in the field to
save on microcontroller cycles, at the cost of cheap bandwidth.

## Arbitrary Data

After the header, an arbitrary amount of data can be specified. One can imagine
that there might be security concerns regarding this. The data should conform
to the specification set in the header.
