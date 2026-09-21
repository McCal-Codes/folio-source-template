# A Folio source

A template for publishing tweaks, themes and layouts for [Folio](https://github.com/McCal-Codes/folio). Put as many
packages in it as you like — one source holds up to 5,000 — push, and GitHub Pages serves a signed source that anyone
can add to their phone.

There are two example packages here so you can see the shape of one: **Midnight**, a theme, and **Quiet Hours**, a
tweak bundle. Delete them once yours work.

## Using it

1. **Use this template** to make your own repository, then clone it.
2. **Make a key.** It never goes in the repository:

   ```bash
   openssl ecparam -name prime256v1 -genkey -noout -out folio-source.pem
   ```

   Keep that file somewhere safe — a password manager is fine. If you lose it, everyone who added your source has to
   confirm a new key before they get another update.

3. **Add it as a secret.** In the repository: *Settings › Secrets and variables › Actions › New repository secret*,
   named `FOLIO_SOURCE_KEY`, with the whole PEM file pasted in, `-----BEGIN` line and all.
4. **Turn on Pages.** *Settings › Pages › Build and deployment › Source: GitHub Actions.*
5. **Edit `source.json`** — your source's name, its description and where people should report problems.
6. **Write a package.** Copy one of the folders in `packages/`, change `id`, `name` and `author` in its
   `manifest.json`, and put its icon in `assets/icons/`.
7. **Build it yourself before pushing:**

   ```bash
   python3 tools/build.py --key folio-source.pem
   ```

8. **Push.** The Action builds, signs and publishes. Your source is then
   `https://<you>.github.io/<repository>/`, which is what people paste into Folio under *Market › Sources › Add*.

The first time someone adds it, Folio shows them your key's fingerprint and remembers it. After that a source signed
with a different key stops working until they agree to the change, so the key matters more than the repository does.

## Listing an app

Some things have to be apps of their own: Android will only take a keyboard as its own app, for instance. A package
whose `manifest.json` has `"kind": ["externalApp"]` isn't packed. Its `via` list says where people can get it (Play,
F-Droid or Obtainium), and an `app.json` beside the manifest lets Folio install the APK itself, for anyone who has
turned that on:

```json
{ "url": "https://github.com/you/your-app/releases/download/v1.0.0/YourApp-1.0.0.apk",
  "sha256": "…", "size": 1234567 }
```

Take the checksum and size from the release, never type them. Folio refuses an APK whose bytes don't match, and
Android asks before installing anything, but nothing checks the app itself: your source is what vouches for it.

## What gets built

`tools/build.py` turns this folder into `_site/`, which is the source as a phone sees it:

```
_site/index.json          the list, generated from your packages so it can't disagree with them
_site/entry.json          the signed pointer to the list: its sha256, its size, and when it expires
_site/entry.json.sig      the signature, over entry.json's exact bytes
_site/key.pub             your public key, so a phone can pin it
_site/packages/*.foliopkg one zip per package
_site/assets/             the pictures your packages name
```

The build then runs the validator over what it produced, and fails if anything is wrong. You can run that yourself
against a folder, a single package or a `.foliopkg`:

```bash
python3 tools/folio-pkg.py validate _site
python3 tools/folio-pkg.py validate packages/midnight
```

## What a package may contain

Data, and nothing that runs: JSON and pictures. A theme carries `theme.json`, a bundle carries `tweaks.json` naming
tweaks Folio already has, a layout carries `layout.json`. That is the whole reason a Folio source is safe to add
without reading the code — there is no code. The full format is in Folio's
[SDK documentation](https://github.com/McCal-Codes/folio/tree/main/docs/sdk).

`schema/v1/` is a copy of Folio's schemas so this repository can check itself with nothing installed. Refresh it from
the Folio repository when the format moves on.

## Keeping a package honest

- **Credit anything you were inspired by**, and don't include GPL code.
- **Name every permission** your package uses; the privacy label people see is built from that list.
- **Pictures are downloaded before anything is installed**, so keep them small — the validator warns past 1 MB.
- **Revoking a package:** add its id to `revoked.json` and push. Phones that already have it will turn it off.

## Licence

The template is MIT. Your packages are yours; say what they are in each `manifest.json`.
