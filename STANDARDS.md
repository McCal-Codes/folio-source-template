# Standards for Folio packages

Folio has a set of [standards](https://github.com/McCal-Codes/folio/tree/main/docs/standards) for how the app itself
is built. Most of them are about Kotlin code a package never touches. This page is the part that applies to you: what
a theme, tweak bundle or layout has to do to feel like it belongs in Folio.

Rule IDs in brackets point to the matching rule in Folio's standards, if you want the longer reasoning.

## Everything here is data

- **Only JSON and pictures.** No DEX, JAR, native code or anything else that runs ([PRV-13]). The validator refuses
  it, and Folio never loads it.
- **Tweak bundles only name tweaks Folio already has.** A bundle can't add behaviour; it switches on and sets what's
  there. If you need something Folio can't do, open an issue on Folio describing it.
- **Declare every permission** your package uses in `permissions`, and no more. The privacy label people see before
  installing is built from that list ([PRV-4], [PRV-5]).

## Look like Folio

- **Start from iOS.** Folio is iOS-styled. A theme should read as an iOS appearance (glass, grouped lists, calm colour)
  rather than a Material one ([DES-1]).
- **Use Apple's patterns, not Apple's artwork.** No SF Symbols, Apple fonts, wallpapers or screenshots ([DES-2]).
- **Keep the accent for what matters.** If a theme tints everything, badges and active Focus modes stop standing out
  ([DES-12]).
- **Red means destructive.** Don't use it as a theme's main colour for buttons that aren't ([DES-13]).

## Readable for everyone

- **Contrast:** text at least 4.5:1 against what it sits on, icons and large text at least 3:1. Check your theme over
  a white wallpaper and a black one ([A11Y-9]).
- **Don't rely on colour alone** to show a state ([A11Y-10]).
- **Glass has a solid fallback.** People who turn on Reduce Transparency or high contrast get Folio's solid surfaces
  instead of your glass values. That's intended; don't design a theme that only works as glass ([A11Y-11]).
- **Write descriptions people can translate.** Keep the text in `depiction.json`'s markdown blocks plain, and add other
  languages as keys when you can.

## Every screen

- **Say which screens you support** in `screens` (`cover`, `inner`), and only list the ones you tried.
- **A layout package must fit.** Folio lays out by window size, not by phone model, so a layout has to work on the
  cover screen, the inner screen, both orientations, and a half-open hinge ([ADP-5], [ADP-7]).
- **Screenshots are real.** Every picture in your depiction is a real capture of your package in Folio. Don't mock up
  a result it can't produce. Check screenshots for notifications, contacts and account names before you publish.

## Test before you publish

1. `python3 tools/build.py --key folio-source.pem` (it validates what it builds).
2. Install the built `.foliopkg` on a phone or emulator and try it folded and unfolded, light and dark, with a bright
   and a dark wallpaper.
3. Turn animations off (Developer options › Animator duration scale › Off) and check it still looks right.
4. Uninstall it and check Folio goes back to how it was.

## Made with AI

AI-made packages are welcome, and they're labelled ([AI-6], [AI-7]):

- **Start `description` with "AI-assisted (tool name)."** For example: `"AI-assisted (Claude). Deep blue glass and
  square icons."` Say it again in your depiction.
- **Keep the label** when you update, fork or republish a package someone else made with AI.
- **A person is responsible.** Whoever publishes it has tried it on a device and stands behind it.
- Folio's manifest will get its own field for this. Until then, the first words of `description` are the label, and a
  source or the Community listing may remove an unlabelled AI-made package.

This is different from Folio's app code, where outside AI agents may only test for and fix bugs. See
[AI contributions](https://github.com/McCal-Codes/folio/blob/main/docs/standards/ai-contributions.md).

## Credit and licence

- Credit anything you were inspired by, and don't include GPL material.
- Say what your package's licence is in `license`.

[PRV-4]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/privacy-permissions.md
[PRV-5]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/privacy-permissions.md
[PRV-13]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/privacy-permissions.md
[DES-1]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/design.md
[DES-2]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/design.md
[DES-12]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/design.md
[DES-13]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/design.md
[A11Y-9]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/accessibility.md
[A11Y-10]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/accessibility.md
[A11Y-11]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/accessibility.md
[ADP-5]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/adaptive-layout.md
[ADP-7]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/adaptive-layout.md
[AI-6]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/ai-contributions.md
[AI-7]: https://github.com/McCal-Codes/folio/blob/main/docs/standards/ai-contributions.md
